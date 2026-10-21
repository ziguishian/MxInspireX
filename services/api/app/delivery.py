"""Inspect actual task artifacts and persist browser checks against content hashes."""
from __future__ import annotations

import hashlib
import json
import time
import copy
from pathlib import Path

from .assets import AssetStore
from .canvas import CanvasStore
from .task_policy import delivery_requirements
from .html_assets import resolve_html_assets
from .delivery_findings import finding, unique_findings

DELIVERY_PROBE_VERSION = 2


class DeliveryService:
    def __init__(self, store, assets=None, canvas=None):
        self.store = store
        self.assets = assets or AssetStore(store)
        self.canvas = canvas or CanvasStore(store)
        with store._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS delivery_checks (project_id TEXT, node_id TEXT, fingerprint TEXT, result_json TEXT, PRIMARY KEY(project_id,node_id))")
            db.execute("CREATE TABLE IF NOT EXISTS delivery_leases (project_id TEXT, node_id TEXT, fingerprint TEXT, expires REAL, PRIMARY KEY(project_id,node_id))")

    def claim_previews(self, limit=2):
        """Workspace-wide queue, independent of the currently visible project."""
        with self.store._connect() as db:
            tasks = db.execute("""SELECT id,project_id,input_json FROM tasks WHERE status='running'
                OR (status IN ('failed','succeeded') AND json_extract(output_json,'$.structured_data.deliveryStatus')='pending')
                ORDER BY updated_at""").fetchall()
        claimed = []
        for task in tasks:
            if not json.loads(task['input_json'] or '{}').get('deliveryVerification'):
                continue
            for node in self.canvas.load(task['project_id'])['nodes']:
                data = node.get('data', {})
                if node.get('meta', {}).get('taskId') != task['id'] or data.get('generating') or data.get('kind') not in {'html','audio','video','cad'}:
                    continue
                check = self.check(task['project_id'], node)
                if data.get('kind') != 'html' and not data.get('assetId'):
                    continue
                if check and (not self.preview_pending(check) or check.get('retryAfter', 0) > time.time()):
                    continue
                fingerprint = self.fingerprint(node)
                with self.store._connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    previous = db.execute('SELECT fingerprint,expires FROM delivery_leases WHERE project_id=? AND node_id=?', (task['project_id'],node['id'])).fetchone()
                    if previous and previous['fingerprint'] == fingerprint and previous['expires'] > time.time():
                        continue
                    db.execute('INSERT OR REPLACE INTO delivery_leases VALUES (?,?,?,?)', (task['project_id'],node['id'],fingerprint,time.time()+120))
                claimed.append({'projectId': task['project_id'], 'nodeId': node['id'], 'fingerprint': fingerprint, 'kind': data['kind'], 'html': resolve_html_assets(data), 'assetId': data.get('previewAssetId') if data['kind']=='cad' else data.get('assetId')})
                if len(claimed) >= limit:
                    return claimed
        return claimed

    @staticmethod
    def fingerprint(node):
        data = node.get("data", {})
        source = resolve_html_assets(data) if data.get("kind") == "html" else (data.get("text") or data.get("summary") or "") if data.get("kind") == "text" else data.get("assetId", "")
        return hashlib.sha256(str(source).encode()).hexdigest()

    def check(self, project_id, node):
        with self.store._connect() as db:
            row = db.execute("SELECT result_json FROM delivery_checks WHERE project_id=? AND node_id=? AND fingerprint=?", (project_id, node["id"], self.fingerprint(node))).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def preview_pending(check):
        return not check or (not check.get('passed') and check.get('retryable') and check.get('attempts', 0) < 3)

    def requeue_failed_media(self, project_id, task_id, refs=None):
        """Recheck existing files only; never resubmit a generation job."""
        report = self.inspect_task(project_id, task_id, refs)
        failed = [a for a in report['artifacts'] if a['kind'] in {'video', 'audio'} and a['ready'] and a.get('preview') and not a['preview'].get('passed')]
        preview_errors = {e for a in failed for e in a['preview'].get('errors', [])}
        if not failed or report['pendingMedia'] or any(issue not in preview_errors for issue in report['issues']):
            return False
        with self.store._connect() as db:
            for item in failed:
                db.execute('DELETE FROM delivery_checks WHERE project_id=? AND node_id=? AND fingerprint=?', (project_id, item['nodeId'], item['fingerprint']))
                db.execute('DELETE FROM delivery_leases WHERE project_id=? AND node_id=?', (project_id, item['nodeId']))
        return True

    def record_check(self, project_id, node_id, fingerprint, result):
        node = next((n for n in self.canvas.load(project_id)["nodes"] if n["id"] == node_id), None)
        if not node or fingerprint != self.fingerprint(node):
            raise ValueError("节点内容已变化，请重新验收")
        if not isinstance(result, dict) or not isinstance(result.get("passed"), bool):
            raise ValueError("验收结果缺少 passed")
        if not isinstance(result.get("errors", []), list):
            raise ValueError("验收错误列表格式无效")
        frames = result.get("frames", [])
        if not isinstance(frames, list) or len(frames) > 3 or any(not isinstance(f, str) or not f.startswith("data:image/jpeg;base64,") or len(f) > 600000 for f in frames):
            raise ValueError("视频验收帧无效")
        if result["passed"] and node["data"].get("kind") in {"audio", "video"}:
            import math
            duration = result.get("duration")
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                raise ValueError("媒体验收缺少有效时长")
            if node["data"]["kind"] == "video" and not frames:
                raise ValueError("视频验收缺少实际抽帧")
        if result['passed'] and node['data'].get('kind') == 'cad' and len(frames) != 3:
            raise ValueError('CAD 预览验收需要三个实际模型视图')
        clean = {"passed": result["passed"] and not result.get("errors"), "errors": [str(e)[:300] for e in result.get("errors", [])][:12], "frames": frames,
                 "duration": result.get("duration"), "buttonsTested": result.get("buttonsTested", 0), "method": "browser-preview"}
        previous = self.check(project_id, node) or {}
        clean.update(code=str(result.get('code') or '')[:60], attempts=previous.get('attempts', 0) + 1)
        clean['retryable'] = not clean['passed'] and clean['code'] in {'media_timeout', 'media_transport'}
        if self.preview_pending(clean):
            clean['retryAfter'] = time.time() + 2 * clean['attempts']
        with self.store._connect() as db:
            db.execute("INSERT OR REPLACE INTO delivery_checks VALUES (?,?,?,?)", (project_id, node_id, fingerprint, json.dumps(clean, ensure_ascii=False)))
            db.execute('DELETE FROM delivery_leases WHERE project_id=? AND node_id=? AND fingerprint=?', (project_id, node_id, fingerprint))
        return {k: v for k, v in clean.items() if k != "frames"}

    def inspect(self, project_id, task_id, refs=None, required=None, require_preview=False, contract=None):
        board = self.canvas.load(project_id)
        refs = refs or []
        wanted_nodes = {r["entity_id"] for r in refs if r.get("entity_type") == "canvas_node"}
        wanted_assets = {r["entity_id"] for r in refs if r.get("entity_type") == "asset"}
        nodes = [n for n in board["nodes"] if n["id"] in wanted_nodes or n.get("meta", {}).get("taskId") == task_id or n.get("data", {}).get("assetId") in wanted_assets]
        unconfirmed_kinds = {n.get('data', {}).get('kind') for n in nodes if n.get('data', {}).get('status') == '生成结果待确认'}
        issues, pending, manifest, artifact_refs, available = [], [], [], [], set()
        findings = []

        def issue(message, code, node_id=None, *, kind='problem', next_action=None):
            issues.append(message)
            findings.append(finding(kind, code, message, node_id=node_id, next_action=next_action))
        content_checks = []
        with self.store._connect() as db:
            jobs = db.execute("SELECT id,status,output_asset_id,metadata_json FROM video_jobs WHERE project_id=?", (project_id,)).fetchall()
        jobs = [j for j in jobs if json.loads(j["metadata_json"] or "{}").get("taskId") == task_id]
        pending_media = [j["id"] for j in jobs if not j["output_asset_id"] and j["status"] not in {"failed", "cancelled", "expired"}]
        for j in jobs:
            if j["status"] in {"failed", "cancelled", "expired"} and not j["output_asset_id"]:
                issue("视频生成失败或已过期", 'video_generation_failed')
        if pending_media:
            available.add("video")
        for node in nodes:
            data = node.get("data", {})
            kind = data.get("kind", "text")
            asset = self.assets.get_asset(project_id=project_id, asset_id=data["assetId"]) if data.get("assetId") else None
            item = {"nodeId": node["id"], "kind": kind, "title": data.get("title", ""), "fingerprint": self.fingerprint(node), "ready": False}
            if isinstance(data.get('productionNotes'), list):
                item['productionNotes'] = [str(note)[:300] for note in data['productionNotes'] if str(note).strip()][:8]
            unconfirmed = data.get('status') == '生成结果待确认'
            if unconfirmed:
                issue(f"{item['title'] or kind} 的生成请求未取得可确认结果，可能已计费。", 'generation_unconfirmed', node['id'], kind='generation_unconfirmed')
            artifact_refs.append({"entity_type": "canvas_node", "entity_id": node["id"], "label": item["title"]})
            if asset:
                artifact_refs.append({'entity_type':'asset','entity_id':asset['id'],'label':item['title']})
                item.update(assetId=asset['id'],mime=asset['mime'])
                layout = (asset.get('metadata', {}).get('referenceSnapshot') or {}).get('visualSeries')
                if layout: item['visualSeries'] = layout
                if not Path(asset['absolutePath']).is_file(): issue(f"{item['title']} 引用的文件已丢失", 'file_missing', node['id'])
            elif data.get('assetId'):
                issue(f"{item['title']} 引用的资产不存在", 'asset_missing', node['id'])
            if kind in {"text", "html"}:
                value = data.get("html") if kind == "html" else data.get("text") or data.get("summary")
                if not str(value or "").strip():
                    issue(f"{item['title'] or kind} 节点没有内容", 'content_empty', node['id'])
                else:
                    item["ready"] = True
            elif asset:
                path = Path(asset["absolutePath"])
                item.update(assetId=asset["id"], mime=asset["mime"])
                artifact_refs.append({"entity_type": "asset", "entity_id": asset["id"], "label": item["title"]})
                if not path.is_file() or not path.stat().st_size:
                    issue(f"{item['title'] or kind} 文件缺失或为空", 'file_empty', node['id'])
                else:
                    item["ready"] = True
                    if kind == 'cad':
                        try:
                            from .cad import cad_manifest
                            cad = cad_manifest(self.assets, project_id, asset['id'])
                            item['geometry'] = cad['checks']
                            item['ready'] = bool(cad['checks'].get('valid') and cad['checks'].get('stepRoundTrip'))
                            if not item['ready']: issue('CAD 实体检查未通过', 'cad_invalid', node['id'])
                        except (ValueError, OSError, KeyError) as error:
                            item['ready'] = False
                            issue(f'CAD 文件检查失败：{error}', 'cad_check_unavailable', node['id'], kind='unverified')
                    if kind == "image" and asset["mime"] != "image/svg+xml":
                        from .image_output import inspect_image_output
                        image = inspect_image_output(path.read_bytes(), transparent_requested=asset.get("metadata", {}).get("params", {}).get("background") == "transparent")
                        item['imageInfo'] = image
                        if not image.get("verified") or image.get("warning"):
                            issue(image.get("warning") or "图像无法解码", 'image_invalid', node['id'])
                            item["ready"] = False
            elif kind == "video" and pending_media:
                item["pending"] = True
            elif not unconfirmed:
                issue(f"{item['title'] or kind} 节点缺少实际资产", 'asset_missing', node['id'])
            if item["ready"]:
                available.add(kind)
                if require_preview and kind in {"html", "video", "audio", "cad"}:
                    check = self.check(project_id, node)
                    item["preview"] = {k: v for k, v in (check or {}).items() if k != "frames"}
                    if self.preview_pending(check):
                        pending.append(node["id"])
                    elif not check["passed"]:
                        for message in check['errors'] or [f"{kind} 预览验收失败"]:
                            unavailable = check.get('code') in {'media_timeout', 'media_transport'}
                            issue(message, check.get('code') or 'preview_failed', node['id'], kind='unverified' if unavailable else 'problem',
                                  next_action='重新检查已有文件的预览或播放，无需重新生成。')
            manifest.append(item)
        for requirement in contract or []:
            kind = requirement['kind']
            matching = [item for item in manifest if item['kind'] == kind and item['ready']]
            waiting = len(pending_media) if kind == 'video' else 0
            if len(matching) + waiting < requirement.get('count', 1):
                # Preserve the contract failure while preventing a suggestion
                # to resubmit an unknown charged request as a missing item.
                issue(f"{kind} 数量不足：要求 {requirement.get('count',1)}，已保存 {len(matching)}", 'count_mismatch',
                      kind='generation_unconfirmed' if kind in unconfirmed_kinds else 'problem',
                      next_action=None if kind in unconfirmed_kinds else '查看交付清单，在对话中明确要求补齐缺项。')
        for kind in set(required or []) - available:
            issue(f"缺少必需产物：{kind}", 'artifact_missing', kind='generation_unconfirmed' if kind in unconfirmed_kinds else 'problem',
                  next_action=None if kind in unconfirmed_kinds else '查看交付清单，在对话中明确要求补齐缺项。')
        unique_refs = {(r["entity_type"], r["entity_id"]): r for r in artifact_refs}
        technical_issues = [message for message in issues if message not in {c['message'] for c in content_checks}]
        return {"passed": not issues and not pending and not pending_media, "issues": list(dict.fromkeys(issues)), "pendingPreview": pending,
                "technicalCheck":{"passed":not technical_issues and not pending and not pending_media,"issues":technical_issues},"contentChecks":content_checks,
                "pendingMedia": pending_media, "artifacts": manifest, "artifact_refs": list(unique_refs.values()), "artifactKinds": sorted(available),'contract':contract or [],
                'findings': unique_findings(findings)}

    def _inspection_key(self, project_id, task_id, refs):
        """Cheap version checks; image decoding and content validation are cached."""
        with self.store._connect() as db:
            row = db.execute('SELECT input_json FROM tasks WHERE project_id=? AND id=?', (project_id, task_id)).fetchone()
            context = json.loads(row[0]) if row else {}
            if context.get('executionPolicyVersion', 0) < 2:
                return None
            checks = [tuple(r) for r in db.execute('SELECT node_id,fingerprint,result_json FROM delivery_checks WHERE project_id=? ORDER BY node_id', (project_id,))]
            jobs = [tuple(r) for r in db.execute('SELECT id,status,output_asset_id FROM video_jobs WHERE project_id=? ORDER BY id', (project_id,))]
            updates = [tuple(r) for r in db.execute('SELECT revision,text FROM task_updates WHERE task_id=? ORDER BY revision', (task_id,))] if db.execute("SELECT 1 FROM sqlite_master WHERE name='task_updates'").fetchone() else []
        context.pop('deliveryProgress', None)
        if context.get('designBatch'):
            for field in ('currentProgress', 'cumulativeProgress'):
                context['designBatch'].pop(field, None)
        nodes = self.canvas.load(project_id)['nodes']
        files = []
        for asset_id in sorted({n.get('data', {}).get('assetId') for n in nodes} - {None, ''}):
            asset = self.assets.get_asset(project_id=project_id, asset_id=asset_id)
            path = Path(asset['absolutePath']) if asset else None
            try:
                stat = path.stat() if path else None
            except OSError:
                stat = None
            files.append([asset, [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns] if stat else None])
        return hashlib.sha256(json.dumps([context, refs or [], nodes, files, checks, jobs, updates], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def inspect_task(self, project_id, task_id, refs=None):
        key = self._inspection_key(project_id, task_id, refs)
        cache = getattr(self.store, '_delivery_inspections', None)
        if cache is None:
            cache = self.store._delivery_inspections = {}
        scope = (project_id, task_id)
        saved = cache.get(scope)
        if key and saved and saved[0] == key:
            return copy.deepcopy(saved[1])
        report = self._inspect_task(project_id, task_id, refs)
        if key:
            report['inspectionVersion'] = key
        # Pending previews, unknown media and failures are always checked again.
        if key and report['passed'] and not report.get('pendingPreview') and not report.get('pendingMedia') and key == self._inspection_key(project_id, task_id, refs):
            if len(cache) >= 32:
                cache.pop(next(iter(cache)))
            cache[scope] = (key, copy.deepcopy(report))
        else:
            cache.pop(scope, None)
        return report

    def _inspect_task(self, project_id, task_id, refs=None):
        with self.store._connect() as db:
            row = db.execute("SELECT input_json FROM tasks WHERE project_id=? AND id=?", (project_id, task_id)).fetchone()
        from .task_policy import normalize_delivery_context
        context = normalize_delivery_context(json.loads(row[0]) if row else {})
        plan = context.get('designPlan') or {}
        nodes = self.canvas.load(project_id)['nodes']
        refs = list(refs or [])
        if plan.get('scopeId'):
            item_ids = {d['id'] for d in plan.get('deliverables', [])}
            refs += [{'entity_type': 'canvas_node', 'entity_id': n['id']} for n in nodes if
                     n.get('data', {}).get('deliveryBinding', {}).get('scopeId') == plan['scopeId'] and
                     item_ids.intersection(n['data']['deliveryBinding'].get('itemIds', []))]
        required = delivery_requirements(context.get("userMessage", ""), context)
        from .task_policy import delivery_contract
        batch = context.get('designBatch')
        cumulative = None
        if batch and set(batch['itemIds']) != {d['id'] for d in plan.get('deliverables', [])}:
            cumulative = self.inspect(project_id, task_id, refs, [], False, [])
            refs = [{'entity_type': 'canvas_node', 'entity_id': n['id']} for n in nodes
                    if n.get('data', {}).get('deliveryBinding', {}).get('scopeId') == plan.get('scopeId') and
                    set(batch['itemIds']).intersection(n['data']['deliveryBinding'].get('itemIds', []))]
        report = self.inspect(project_id, task_id, refs, required, bool(context.get("deliveryVerification")), delivery_contract(context.get('userMessage',''),context))
        report['cumulativeArtifacts'] = (cumulative or report)['artifacts']
        report['designPlan'] = plan
        snapshots={s['id']:s for s in (context.get('conversationMemory') or {}).get('referenceSnapshots',[])}
        for node in nodes:
            if node['id'] in {a['nodeId'] for a in report['artifacts']}:
                snap=node.get('data',{}).get('referenceSnapshot')
                if snap:snapshots[snap['id']]=snap
        report['referenceSnapshots']=list(snapshots.values())
        from .design_batches import with_evidence, set_progress
        report['deliverables'] = with_evidence(context, report['cumulativeArtifacts'], nodes)
        set_progress(context, report['deliverables'])
        report['designBatch'] = context.get('designBatch')
        checks = []
        if (context.get('designPlanning') or {}).get('required') and not plan:
            checks.append({'category':'content','status':'unverified','message':'尚未明确本轮设计范围和交付清单'})
        if plan:
            if batch and batch['status'] == 'needs_plan':
                checks.append({'category':'content','status':'unverified','message':'本批执行清单尚未登记，请先保存 design_plan 再生成'})
            if not plan.get('ready'):
                checks.append({'category':'content','status':'unverified','message':'设计计划仍有未确定的关键问题'})
            for item in context['designBatch']['currentProgress'] if batch else report['deliverables']:
                if item['status'] in {'pending', 'blocked'}:
                    checks.append({'category':'content','status':'unverified','message':f"设计计划待交付：{item['title']}（{item['kind']}）" + ('，等待：' + '、'.join(item['blockingFields']) if item['status'] == 'blocked' else ''),'planItemId':item['id']})
        if checks:
            report['contentChecks'].extend(checks)
            report['issues'] = list(dict.fromkeys([*report['issues'], *(check['message'] for check in checks)]))
            for check in checks:
                report['findings'].append(finding('unverified', 'plan_incomplete', check['message'], plan_item_id=check.get('planItemId'),
                    next_action='补充必要资料或确认本轮交付清单后继续；已完成产物会保留。'))
            report['passed'] = False
        return report

