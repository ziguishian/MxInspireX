"""Durable SDK checkpoints and tool receipts, scoped to one user task."""
from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

_live_lock = threading.RLock()
_live_calls = {}
_running_scope = ContextVar('running_tool_scope', default=None)
_independent_generators = {'generate_image', 'generate_video', 'generate_audio', 'generate_3d','generate_cad', 'generate_text'}


class ExecutionStore:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                  task_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tool_receipts (
                  task_id TEXT NOT NULL, fingerprint TEXT NOT NULL, name TEXT NOT NULL,
                  args TEXT NOT NULL, status TEXT NOT NULL, output TEXT, updated_at TEXT NOT NULL,
                  PRIMARY KEY(task_id, fingerprint));
            """)

    def load(self, task_id):
        self.reconcile(task_id)
        with self.store._connect() as db:
            row = db.execute("SELECT payload FROM agent_checkpoints WHERE task_id=?", (task_id,)).fetchone()
            receipts = db.execute("SELECT name,args,output FROM tool_receipts WHERE task_id=? AND status='completed'", (task_id,)).fetchall()
        state = json.loads(row[0]) if row else {}
        # A tool receipt commits before the HTTP response; it survives loss of
        # the worker's subsequent checkpoint event.
        outputs = state.setdefault("toolOutputs", [])
        for item in receipts:
            args = json.loads(item["args"])
            output = json.loads(item['output'])
            if output.get('stopTool'):
                state.setdefault('blockedTools', {})[item['name']] = output
            existing = next((x for x in outputs if x['name'] == item['name'] and x.get('args') == args), None)
            if existing is not None:
                # The durable receipt supersedes a worker-side timeout. It
                # must not remain cached as a failure after a late completion.
                if existing.get('output', {}).get('status') != 'succeeded' or existing['output'].get('assetId') != output.get('assetId'):
                    existing['output'] = output
            else:
                outputs.append({"name": item["name"], "args": args, "output": output})
        for entry in outputs:
            if entry['name'] != 'generate_batch': continue
            operations = entry.get('args', {}).get('items', [])
            for result, operation in zip(entry.get('output', {}).get('results', []), operations):
                args = dict(operation.get('arguments', {}))
                if operation.get('deliverable_ids') and not args.get('deliverable_ids'):
                    args['deliverable_ids'] = operation['deliverable_ids']
                saved = next((x['output'] for x in outputs if x['name'] == operation.get('tool') and x.get('args') == args), None)
                if saved and saved.get('status') == 'succeeded':
                    result.update(status='succeeded', assetId=saved.get('assetId'), nodeId=(saved.get('node') or {}).get('id'))
                    for key in ('message', 'errorCode', 'stopTool', 'retryable'): result.pop(key, None)
        return state

    def save(self, task_id, state):
        with self.store._connect() as db:
            db.execute("INSERT OR REPLACE INTO agent_checkpoints VALUES (?,?,?)", (task_id, json.dumps(state, ensure_ascii=False), self.now()))

    @contextmanager
    def running_scope(self):
        scope = {'claimed': set()}
        token = _running_scope.set(scope)
        try:
            yield
        finally:
            # A lost HTTP/provider response is no longer a live parallel job.
            # Its durable running receipt still blocks replay after this scope.
            with _live_lock:
                for key in scope['claimed']: _live_calls.pop(key, None)
            _running_scope.reset(token)

    def _live_key(self, task_id, fingerprint):
        return str(self.store.catalog_path), task_id, fingerprint

    def completed_result(self, task_id, name, args):
        """Look up an exact successful/terminal replay before resolving live nodes."""
        self.reconcile(task_id)
        encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256((name + "\n" + encoded).encode()).hexdigest()
        with self.store._connect() as db:
            row = db.execute("SELECT output FROM tool_receipts WHERE task_id=? AND fingerprint=? AND status='completed'", (task_id, key)).fetchone()
        return json.loads(row[0]) if row else None

    def result_status(self, task_id, name, args):
        """Observe the original call only; never claim, reject or resubmit it."""
        encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        fingerprint = hashlib.sha256((name + '\n' + encoded).encode()).hexdigest()
        def read():
            with self.store._connect() as db:
                return db.execute('SELECT status,output FROM tool_receipts WHERE task_id=? AND fingerprint=?',
                                  (task_id, fingerprint)).fetchone()
        with _live_lock:
            live = self._live_key(task_id, fingerprint) in _live_calls
            row = read()
        if row and row['status'] == 'running' and not live:
            self.reconcile(task_id)
            row = read()
        if not row: return {'state': 'missing'}
        if row['status'] == 'completed': return {'state': 'completed', 'output': json.loads(row['output'])}
        return {'state': 'running' if live else 'unconfirmed' if row['status'] == 'running' else row['status']}

    def claim(self, task_id, name, args, *, resources=()):
        with _live_lock:
            fingerprint, previous = self._claim(task_id, name, args, resources)
            scope = _running_scope.get()
            if previous is None and scope is not None:
                key = self._live_key(task_id, fingerprint)
                _live_calls[key] = set(resources)
                scope['claimed'].add(key)
            return fingerprint, previous

    def _claim(self, task_id, name, args, resources):
        self.reconcile(task_id)
        encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256((name + "\n" + encoded).encode()).hexdigest()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,output FROM tool_receipts WHERE task_id=? AND fingerprint=?", (task_id, fingerprint)).fetchone()
            if row and row["status"] == "rejected":
                db.execute("DELETE FROM tool_receipts WHERE task_id=? AND fingerprint=?", (task_id, fingerprint))
                row = None
            if row and row['status']=='running' and name=='schedule_create':
                # ScheduleService uses the same request ID and checks the
                # already committed rows before creating anything.
                db.execute('DELETE FROM tool_receipts WHERE task_id=? AND fingerprint=?',(task_id,fingerprint))
                row=None
            if row:
                if row["status"] == "completed":
                    return fingerprint, json.loads(row["output"])
                raise RuntimeError(f"{name} 上次调用尚未确认结果，已阻止重复执行；请核对原任务和供应商记录后再发起新任务。")
            # A confirmed format failure is not an in-flight charge. Preserve
            # its cause on changed-argument retries and after worker restarts.
            stopped = db.execute("SELECT fingerprint,output FROM tool_receipts WHERE task_id=? AND name=? AND status='completed' AND json_extract(output,'$.stopTool')=1", (task_id, name)).fetchone()
            if stopped:
                return stopped['fingerprint'], json.loads(stopped['output'])
            if name == 'generate_video' and resources:
                # An async receipt is completed as soon as the provider accepts
                # it. Its pending job still owns the target, including after a
                # restart or a model rewriting the prompt in the same task.
                accepted = db.execute("SELECT fingerprint,output FROM tool_receipts WHERE task_id=? AND name='generate_video' AND status='completed' ORDER BY updated_at", (task_id,)).fetchall()
                for receipt in accepted:
                    result = json.loads(receipt['output'] or '{}')
                    job = result.get('job') or {}
                    meta = job.get('metadata') or {}
                    owned = set(meta.get('executionResources') or [])
                    if meta.get('canvasNodeId'):
                        owned.add(f"node:{meta['canvasNodeId']}")
                    if job.get('id') and owned.intersection(resources):
                        return receipt['fingerprint'], result
            if name == 'web_search':
                previous = db.execute("SELECT status,output FROM tool_receipts WHERE task_id=? AND name='web_search' AND status IN ('running','completed')", (task_id,)).fetchall()
                for search in previous:
                    if search['status'] == 'running':
                        raise RuntimeError('本轮搜索请求仍在执行或结果尚未确认，已阻止重复提交。')
                    result = json.loads(search['output'] or '{}')
                    if result.get('stopTool'):
                        raise RuntimeError(result.get('message') or '本轮搜索已停止，不重复提交。')
            if name.startswith("generate_") or name in {'image_edit','transcribe_audio'}:
                running = db.execute("SELECT name,fingerprint FROM tool_receipts WHERE task_id=? AND (name LIKE 'generate_%' OR name IN ('image_edit','transcribe_audio')) AND status='running'", (task_id,)).fetchall()
                scope = _running_scope.get()
                live_independent = name in _independent_generators and scope is not None and all(
                    row['name'] in _independent_generators and (key := self._live_key(task_id, row['fingerprint'])) in _live_calls
                    and not set(resources).intersection(_live_calls[key]) for row in running)
                if running and not live_independent:
                    raise RuntimeError("本轮有生成请求的结果尚未确认或存在并发冲突，已阻止通过改写提示词重复提交。请等待依赖请求；结果未知时先核对原任务。")
            db.execute("INSERT INTO tool_receipts VALUES (?,?,?,?,?,?,?)", (task_id, fingerprint, name, encoded, "running", None, self.now()))
        return fingerprint, None

    def reconcile(self, task_id):
        """Recover only locally recorded effects; never resubmit an unknown charge."""
        with self.store._connect() as db:
            rows = db.execute("SELECT * FROM tool_receipts WHERE task_id=? AND status='running' AND name!='web_search'", (task_id,)).fetchall()
            if not rows:
                return
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            trace_rows = []
            if 'model_route_trace' in tables:
                trace_rows.extend(db.execute("SELECT data_json FROM model_route_trace WHERE task_id=? ORDER BY rowid", (task_id,)).fetchall())
            if 'model_call_trace' in tables:
                trace_rows.extend(db.execute("SELECT data_json FROM model_call_trace WHERE task_id=? ORDER BY created_at,rowid", (task_id,)).fetchall())
            asset_rows = db.execute("SELECT id,project_id,metadata_json FROM assets").fetchall()
            job_rows = db.execute("SELECT id,project_id,metadata_json FROM video_jobs").fetchall()
            task = db.execute("SELECT project_id,status FROM tasks WHERE id=?", (task_id,)).fetchone()
        from .assets import AssetStore
        from .canvas import CanvasStore
        from .video import VideoJobService
        assets, canvas = AssetStore(self.store), CanvasStore(self.store)
        board = canvas.load(task["project_id"]) if task else {"nodes": [], "edges": []}
        latest_image_route = {}
        for item in trace_rows:
            try:
                event = json.loads(item['data_json'])
            except (TypeError, ValueError):
                continue
            if event.get('phase') == 'image_route' and event.get('fingerprint'):
                latest_image_route[event['fingerprint']] = event.get('status')
        for row in rows:
            if row['name'] == 'web_search': continue
            with _live_lock:
                if self._live_key(task_id, row['fingerprint']) in _live_calls: continue
            if row['name'] == 'generate_image' and latest_image_route.get(row['fingerprint']) == 'safe_rejected':
                # No candidate was left in flight. Release only the exact
                # receipt and remove its automatically created loading node.
                pending = [node['id'] for node in board['nodes']
                           if node.get('meta', {}).get('executionReceipt') == row['fingerprint']
                           and node.get('data', {}).get('generating')]
                if pending and task:
                    canvas.apply_changes(task['project_id'], {'removeNodeIds': pending}, agent_edit=True)
                    board = canvas.load(task['project_id'])
                self.reject(task_id, row['fingerprint'])
                continue
            # Canvas data and the receipt marker share one atomic file write.
            # A crash between that write and complete() must not create it twice.
            collection = "edges" if row["name"] == "canvas_link_nodes" else "nodes"
            local = next((item for item in board[collection]
                          if item.get("meta", {}).get("taskId") == task_id
                          and item.get("meta", {}).get("executionReceipt") == row["fingerprint"]), None)
            if local and row['name'] in {'generate_image','generate_audio'} and not local.get('data', {}).get('assetId'):
                # A loading/error placeholder proves only that dispatch began;
                # it is not a recoverable generated result.
                local = None
            if local:
                output = {"tool": row["name"], "status": "succeeded", "edge" if collection == "edges" else "node": local}
                if collection == "nodes":
                    output["outputKind"] = local.get("data", {}).get("kind")
                    if local.get("data", {}).get("assetId"):
                        output["assetId"] = local["data"]["assetId"]
                self.complete(task_id, row["fingerprint"], output)
                continue
            def matches(item):
                meta = json.loads(item["metadata_json"] or "{}")
                return meta.get("taskId") == task_id and meta.get("executionReceipt") == row["fingerprint"]
            saved = next((a for a in asset_rows if matches(a)), None)
            if row['name'] == 'generate_cad':
                # Reconcile a local build without executing the model again.
                if not task or task['status'] == 'cancelled':
                    self.complete(task_id,row['fingerprint'],{'status':'cancelled','error':'原任务已取消，不发布 CAD 构建'})
                    continue
                from .cad import cad_manifest
                with self.store._connect() as db:
                    build = db.execute("SELECT * FROM cad_builds WHERE task_id=? AND json_extract(payload,'$._receipt')=?",(task_id,row['fingerprint'])).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='cad_builds'").fetchone() else None
                if saved and build:
                    payload = json.loads(build['payload'])
                    try:
                        model = cad_manifest(assets,saved['project_id'],saved['id'])
                        target = payload.get('canvas_node_id')
                        current = next((n for n in canvas.load(saved['project_id'])['nodes'] if n['id']==target),None)
                        if target and (not current or current['data'].get('cadRevision')!=payload.get('base_revision')):
                            raise ValueError('模型已修改，恢复时保留当前版本')
                        asset = assets.get_asset(project_id=saved['project_id'],asset_id=saved['id'])
                        data = {'kind':'cad','cad':model,'cadRevision':model['revision'],'previewAssetId':model['files']['glb'],'thumbnailAssetId':model['files']['thumbnail'],'deliveryBinding':payload.get('_binding',{}),'title':model['title']}
                        node = canvas.ensure_asset_node(saved['project_id'],asset,task_id=task_id,target_node_id=target,data=data,execution_receipt=row['fingerprint'])
                        self.complete(task_id,row['fingerprint'],{'status':'succeeded','outputKind':'cad','node':node,'assetId':saved['id']})
                    except (ValueError,OSError) as error:
                        self.complete(task_id,row['fingerprint'],{'status':'failed','error':str(error)})
                elif build and build['status'] in {'succeeded','failed','cancelled'}:
                    self.complete(task_id,row['fingerprint'],json.loads(build['result']) if build['result'] else {'status':build['status'],'error':build['error']})
                continue
            job_row = next((j for j in job_rows if matches(j)), None)
            if not saved and not job_row:
                continue
            project_id = (saved or job_row)["project_id"]
            output = {"tool": row["name"], "status": "submitted"}
            meta = json.loads((saved or job_row)["metadata_json"] or "{}")
            target = meta.get("canvasNodeId")
            if not any(n["id"] == target for n in canvas.load(project_id)["nodes"]):
                target = None
            if job_row:
                job = VideoJobService(self.store).get(project_id, job_row["id"])
                output.update(job=job, status=job["status"])
                if not saved and job.get("outputAssetId"):
                    saved = {"id": job["outputAssetId"]}
            if saved:
                asset = assets.get_asset(project_id=project_id, asset_id=saved["id"])
                node = canvas.ensure_asset_node(project_id, asset, task_id=task_id, target_node_id=target)
                output.update(asset=asset, assetId=asset["id"], node=node, outputKind=asset["kind"], status="succeeded")
            elif target:
                canvas.update_node(project_id, target, {"data": {"job": output["job"], "generating": True, "error": "", "status": "生成中"}})
            self.complete(task_id, row["fingerprint"], output)

    def complete(self, task_id, fingerprint, output):
        with self.store._connect() as db:
            db.execute("UPDATE tool_receipts SET status='completed',output=?,updated_at=? WHERE task_id=? AND fingerprint=?", (json.dumps(output, ensure_ascii=False), self.now(), task_id, fingerprint))

    def reject(self, task_id, fingerprint):
        with self.store._connect() as db:
            db.execute("UPDATE tool_receipts SET status='rejected',updated_at=? WHERE task_id=? AND fingerprint=?", (self.now(), task_id, fingerprint))

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()
