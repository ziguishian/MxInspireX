from __future__ import annotations

import json
import threading
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from .canvas_layout import nearest_open_position, next_output_position


class CanvasConflict(ValueError):
    pass


def _locked(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return guarded


class CanvasStore:
    """Persist a project canvas as a small, provider-neutral document.

    The Agent only works with this document contract. The renderer can map the
    nodes and edges to Vue Flow, tldraw, or another canvas implementation
    without exposing DOM details to the runtime.
    """

    _shared_lock = threading.RLock()

    def __init__(self, store) -> None:
        self.store = store
        self._lock = self._shared_lock
        with store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS canvas_versions (id TEXT PRIMARY KEY, project_id TEXT, node_id TEXT, content_json TEXT, created_at TEXT, UNIQUE(project_id,node_id,content_json))')

    def _path(self, project_id: str) -> Path:
        project = self.store.get_project(project_id)
        if project is None:
            raise ValueError("项目不存在")
        root = Path(str(project["rootPath"])).resolve()
        return root / "canvas" / "board.json"

    @staticmethod
    def _has_explicit_position(position: dict[str, Any] | None) -> bool:
        if not isinstance(position, dict):
            return False
        from math import isfinite
        return all(isinstance(position.get(axis), (int, float)) and not isinstance(position.get(axis), bool)
                   and isfinite(position[axis]) for axis in ('x', 'y'))

    @staticmethod
    def _reflow_automatic_nodes(document: dict[str, Any]) -> None:
        """Keep generated nodes clear when their real content changes size.

        Explicitly placed nodes belong to the user and are never moved. Nodes
        created by an Agent without coordinates carry ``autoPositioned`` and
        are reflowed in creation order whenever an image, video or text grows
        beyond its initial placeholder footprint.
        """
        raw_nodes = document.get('nodes') if isinstance(document.get('nodes'), list) else []
        nodes = [node for node in raw_nodes if isinstance(node, dict) and isinstance(node.get('position'), dict)]
        automatic = [node for node in nodes if (node.get('data') or {}).get('autoPositioned') is True]
        if not automatic:
            return
        fixed = [node for node in nodes if node not in automatic]
        def order_key(node: dict[str, Any]) -> tuple[float, str]:
            value = (node.get('data') or {}).get('autoLayoutOrder')
            return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float('inf'), str(node.get('id') or ''))
        def coordinate(value: Any, fallback: float) -> float:
            from math import isfinite
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else fallback
        occupied = list(fixed)
        for node in sorted(automatic, key=order_key):
            current = node.get('position') or {}
            node['position'] = nearest_open_position(occupied, node, {
                'x': coordinate(current.get('x'), 40),
                'y': coordinate(current.get('y'), 40),
            })
            occupied.append(node)

    def load(self, project_id: str) -> dict[str, Any]:
        path = self._path(project_id)
        if not path.is_file():
            return {"schemaVersion": "langju-canvas-v1", "nodes": [], "edges": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
        return {
            "schemaVersion": str(payload.get("schemaVersion") or "langju-canvas-v1"),
            "nodes": nodes,
            "edges": edges,
            "hiddenAssetIds": payload.get("hiddenAssetIds", []),
        }

    @_locked
    def save(self, project_id: str, document: dict[str, Any]) -> dict[str, Any]:
        path = self._path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            "schemaVersion": str(document.get("schemaVersion") or "langju-canvas-v1"),
            "nodes": document.get("nodes") if isinstance(document.get("nodes"), list) else [],
            "edges": document.get("edges") if isinstance(document.get("edges"), list) else [],
            "hiddenAssetIds": document.get("hiddenAssetIds", []),
        }
        # Persist both sides of edits, including user edits, without restoring
        # task tables or unrelated project state when one node is rolled back.
        from datetime import datetime, timezone
        versions = self.load(project_id)['nodes'] + normalized['nodes']
        with self.store._connect() as db:
            for node in versions:
                clean = {k: v for k,v in node.items() if k != 'deliveryProbe'}
                clean['data'] = {k:v for k,v in clean.get('data',{}).items() if k != 'previewValidation'}
                db.execute('INSERT OR IGNORE INTO canvas_versions VALUES (?,?,?,?,?)', (str(uuid4()),project_id,node['id'],json.dumps(clean,ensure_ascii=False,sort_keys=True),datetime.now(timezone.utc).isoformat()))
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return normalized

    def versions(self, project_id, node_id):
        with self.store._connect() as db:
            rows = db.execute('SELECT id,created_at,content_json FROM canvas_versions WHERE project_id=? AND node_id=? ORDER BY created_at DESC LIMIT 100', (project_id,node_id)).fetchall()
        return [{'id':row['id'],'createdAt':row['created_at'],'title':json.loads(row['content_json']).get('data',{}).get('title','')} for row in rows]

    def version(self, project_id, node_id, version_id):
        with self.store._connect() as db:
            row = db.execute('SELECT content_json FROM canvas_versions WHERE project_id=? AND node_id=? AND id=?', (project_id,node_id,version_id)).fetchone()
        if not row: raise ValueError('节点版本不存在或不属于当前项目')
        return json.loads(row[0])

    @_locked
    def create_node(
        self,
        project_id: str,
        *,
        kind: str,
        title: str,
        summary: str = "",
        asset_id: str | None = None,
        position: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
        execution_receipt: str | None = None,
    ) -> dict[str, Any]:
        document = self.load(project_id)
        node_id = str(uuid4())
        node_data = {
            "kind": str(kind or "text"),
            "previewSizingVersion": 2,
            "title": str(title or "未命名节点"),
            "summary": str(summary or ""),
            "status": "已生成",
        }
        if asset_id:
            node_data["assetId"] = asset_id
        if isinstance(data, dict):
            node_data.update(data)
        automatic = not self._has_explicit_position(position)
        if automatic:
            existing_orders = [
                item.get('data', {}).get('autoLayoutOrder')
                for item in document['nodes']
                if isinstance(item, dict) and isinstance(item.get('data'), dict)
                and isinstance(item['data'].get('autoLayoutOrder'), (int, float))
                and not isinstance(item['data'].get('autoLayoutOrder'), bool)
            ]
            node_data['autoPositioned'] = True
            node_data['autoLayoutOrder'] = (max(existing_orders) if existing_orders else 0) + 1
        else:
            node_data['autoPositioned'] = False
        automatic_position = next_output_position(document["nodes"], {'data': node_data})
        node = {
            "id": node_id,
            "type": "creative",
            "position": {
                "x": float((position or {}).get("x", automatic_position["x"])),
                "y": float((position or {}).get("y", automatic_position["y"])),
            },
            "data": node_data,
            "meta": {"createdBy": "design-agent", "taskId": task_id, **({"executionReceipt": execution_receipt} if execution_receipt else {})},
        }
        document["nodes"].append(node)
        self._reflow_automatic_nodes(document)
        self.save(project_id, document)
        return node

    @_locked
    def ensure_asset_node(self, project_id: str, asset: dict[str, Any], *, title: str | None = None,
                          summary: str | None = None, position: dict[str, Any] | None = None,
                          task_id: str | None = None, data: dict[str, Any] | None = None,
                          target_node_id: str | None = None, execution_receipt: str | None = None) -> dict[str, Any]:
        """Persist each generated asset once, including repeated tool calls/recovery."""
        mime_kind = str(asset.get("mime") or "").split("/")[0]
        asset_kind = mime_kind if mime_kind in {"image", "video", "audio"} else asset.get("kind", "image")
        if target_node_id:
            return self.update_node(project_id, target_node_id, {"data": {
                "kind": asset_kind,
                "assetId": asset["id"], "asset": {k: v for k, v in asset.items() if k != "absolutePath"},
                "generating": False, "draft": False, "error": "", "status": "已生成", **(data or {}),
            }, "meta": {"createdBy": "design-agent", "taskId": task_id, **({"executionReceipt": execution_receipt} if execution_receipt else {})}})
        for node in self.load(project_id)["nodes"]:
            if str(node.get("data", {}).get("assetId")) == str(asset["id"]):
                patch: dict[str, Any] = {"data": {}}
                if title:
                    patch["data"]["title"] = title
                if summary is not None:
                    patch["data"]["summary"] = summary
                if isinstance(data, dict):
                    patch["data"].update(data)
                if position:
                    patch["position"] = position
                if task_id:
                    patch["meta"] = {**node.get("meta", {}), "taskId": task_id}
                    if execution_receipt:
                        patch["meta"]["executionReceipt"] = execution_receipt
                return self.update_node(project_id, node["id"], patch) if position or patch["data"] or task_id else node
        kind = str(asset.get("kind") or "image")
        mime_kind = str(asset.get("mime") or "").split("/")[0]
        if mime_kind in {"image", "video", "audio"}:
            kind = mime_kind
        labels = {"image": "生成图像", "video": "生成视频", "audio": "生成音频", "3d": "生成模型"}
        node_data = {"asset": {key: value for key, value in asset.items() if key != "absolutePath"}}
        if isinstance(data, dict):
            node_data.update(data)
        return self.create_node(project_id, kind=kind, title=title or labels.get(kind, "生成内容"),
                                summary=summary or "", asset_id=asset["id"], position=position,
                                data=node_data,
                                task_id=task_id, execution_receipt=execution_receipt)

    @_locked
    def apply_changes(self, project_id: str, changes: dict[str, Any], *, agent_edit=False) -> dict[str, Any]:
        """Apply only changed objects, preserving concurrent Agent outputs."""
        doc = self.load(project_id)
        remove_nodes = set(changes.get("removeNodeIds", []))
        remove_edges = set(changes.get("removeEdgeIds", []))
        locked = self.active_node_ids(project_id, doc)
        touched = remove_nodes | {node.get('id') for node in changes.get('upsertNodes', [])}
        for edge in doc['edges'] + changes.get('upsertEdges', []):
            if edge.get('id') in remove_edges or edge in changes.get('upsertEdges', []):
                touched.update([edge.get('source'), edge.get('target')])
        if touched & locked and not agent_edit:
            raise CanvasConflict('这个节点正被当前任务使用，请等待完成或停止任务后再编辑。其他节点可以继续操作。')
        for collection, field in [('nodes', 'expectedNodes'), ('edges', 'expectedEdges')]:
            current = {item['id']: item for item in doc[collection]}
            for item_id, expected in changes.get(field, {}).items():
                actual = current.get(item_id)
                if expected is None:
                    conflict = actual is not None
                else:
                    conflict = actual is None or any(actual.get(key) != value for key, value in expected.items() if key not in {'type', 'deliveryProbe', 'animated'})
                if conflict:
                    raise CanvasConflict('节点或连线已被更新，已保留最新内容。请重新选择后操作。')
        hidden = set(doc.get("hiddenAssetIds", []))
        for node in doc["nodes"]:
            if node["id"] in remove_nodes and node.get("data", {}).get("assetId"):
                hidden.add(node["data"]["assetId"])
        nodes = {n["id"]: n for n in doc["nodes"] if n["id"] not in remove_nodes}
        for node in changes.get("upsertNodes", []):
            if not isinstance(node, dict) or not node.get("id"):
                raise ValueError("节点缺少 ID")
            merged = {**nodes.get(node["id"], {}), **node}
            if not isinstance(merged.get("position"), dict):
                raise ValueError("节点缺少位置")
            nodes[node["id"]] = merged
            hidden.discard(merged.get("data", {}).get("assetId"))
        edges = {e["id"]: e for e in doc["edges"] if e["id"] not in remove_edges and e["source"] not in remove_nodes and e["target"] not in remove_nodes}
        for edge in changes.get("upsertEdges", []):
            edge = {**edges.get(edge["id"], {}), **edge}
            if edge.get("source") not in nodes or edge.get("target") not in nodes:
                raise ValueError("连接的节点不存在")
            edges[edge["id"]] = edge
        updated = {**doc, "nodes": list(nodes.values()), "edges": list(edges.values()), "hiddenAssetIds": list(hidden)}
        self._reflow_automatic_nodes(updated)
        result = self.save(project_id, updated)
        return {**result, 'lockedNodeIds': sorted(self.active_node_ids(project_id, result))}

    def active_node_ids(self, project_id, document=None):
        from .conversation_context import _object
        with self.store._connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
                return set()
            rows = db.execute("SELECT id,input_json FROM tasks WHERE project_id=? AND status IN ('queued','running')", (project_id,)).fetchall()
        tasks = {row['id'] for row in rows}
        locked, assets = set(), set()
        with self.store._connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='cad_builds'").fetchone():
                locked.update(row[0] for row in db.execute("SELECT node_id FROM cad_builds WHERE project_id=? AND status IN ('queued','running') AND node_id IS NOT NULL",(project_id,)))
        for row in rows:
            data = _object(row['input_json'])
            target = (data.get('canvasParams') or {}).get('canvasNodeId')
            if target: locked.add(target)
            locked.update(item.get('id') or item.get('nodeId') for item in data.get('referencedNodes', []) if isinstance(item, dict))
            assets.update(item.get('id') or item.get('assetId') for item in data.get('referencedAssets', []) if isinstance(item, dict))
        for node in (document or self.load(project_id))['nodes']:
            if node.get('meta', {}).get('taskId') in tasks or node.get('data', {}).get('assetId') in assets - {None}:
                locked.add(node['id'])
        return locked - {None}

    @_locked
    def update_node(self, project_id: str, node_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        document = self.load(project_id)
        for node in document["nodes"]:
            if not isinstance(node, dict) or str(node.get("id")) != str(node_id):
                continue
            from .node_context import active_task, check, observe
            check(self.store, project_id, active_task.get(), node)
            if isinstance(patch.get("position"), dict):
                current_position = node.get("position") if isinstance(node.get("position"), dict) else {}
                node["position"] = {**current_position, **patch["position"]}
            if isinstance(patch.get("data"), dict):
                current_data = node.get("data") if isinstance(node.get("data"), dict) else {}
                node["data"] = {**current_data, **patch["data"]}
            for key, value in patch.items():
                if key not in {"position", "data"}:
                    node[key] = value
            self._reflow_automatic_nodes(document)
            self.save(project_id, document)
            observe(self.store, project_id, active_task.get(), [node])
            return node
        raise ValueError("画布节点不存在")

    @_locked
    def link_nodes(
        self,
        project_id: str,
        *,
        source_node_id: str,
        target_node_id: str,
        label: str | None = None,
        source_handle: str | None = None,
        target_handle: str | None = None,
        task_id: str | None = None,
        execution_receipt: str | None = None,
    ) -> dict[str, Any]:
        if str(source_node_id) == str(target_node_id):
            raise ValueError("不允许将节点连接到自己")
        document = self.load(project_id)
        node_ids = {str(node.get("id")) for node in document["nodes"] if isinstance(node, dict)}
        if str(source_node_id) not in node_ids or str(target_node_id) not in node_ids:
            raise ValueError("关系两端的画布节点不存在")
        edge_id = str(uuid4())
        edge = {
            "id": edge_id,
            **({"meta": {"taskId": task_id, "executionReceipt": execution_receipt}} if execution_receipt else {}),
            "source": str(source_node_id),
            "target": str(target_node_id),
            "animated": True,
        }
        if label:
            edge["label"] = str(label)
        if source_handle:
            edge["sourceHandle"] = str(source_handle)
        if target_handle:
            edge["targetHandle"] = str(target_handle)
        document["edges"].append(edge)
        self.save(project_id, document)
        return edge
