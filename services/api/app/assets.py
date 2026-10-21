from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4


ASSET_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  path_relative TEXT NOT NULL,
  mime TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_project_kind ON assets(project_id, kind, created_at DESC);
"""


class AssetStore:
    def __init__(self, store) -> None:
        self.store = store
        with store._connect() as connection:
            connection.executescript(ASSET_SCHEMA)

    def add_bytes(self, *, project_id: str, kind: str, filename: str, content: bytes, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if project is None:
            raise ValueError("项目不存在")
        safe_name = Path(filename).name or f"asset-{uuid4().hex}"
        folder = {"image": "assets/generated", "video": "assets/video", "3d": "assets/3d", "cad": "assets/cad", "document": "assets/documents"}.get(kind, "assets/originals")
        relative = f"{folder}/{uuid4().hex}-{safe_name}"
        absolute = Path(project["rootPath"]) / relative
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        asset = {"id": str(uuid4()), "projectId": project_id, "kind": kind, "pathRelative": relative, "mime": mimetypes.guess_type(safe_name)[0] or "application/octet-stream", "byteSize": len(content), "sha256": digest, "metadata": metadata or {}, "createdAt": now}
        with self.store._connect() as connection:
            connection.execute("INSERT INTO assets (id, project_id, kind, path_relative, mime, byte_size, sha256, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (asset["id"], project_id, kind, relative, asset["mime"], len(content), digest, __import__("json").dumps(asset["metadata"], ensure_ascii=False), now))
        return asset

    def list_assets(self, project_id: str) -> list[dict[str, Any]]:
        import json

        with self.store._connect() as connection:
            rows = connection.execute("SELECT * FROM assets WHERE project_id = ? AND COALESCE(json_extract(metadata_json,'$.cadHidden'),0)=0 AND COALESCE(json_extract(metadata_json,'$.systemHidden'),0)=0 AND COALESCE(json_extract(metadata_json,'$.cadRole'),'model')='model' ORDER BY created_at DESC", (project_id,)).fetchall()
        return [{"id": row["id"], "projectId": row["project_id"], "kind": row["kind"], "pathRelative": row["path_relative"], "mime": row["mime"], "byteSize": row["byte_size"], "sha256": row["sha256"], "metadata": json.loads(row["metadata_json"]), "createdAt": row["created_at"]} for row in rows]

    def get_asset(self, *, project_id: str, asset_id: str) -> dict[str, Any] | None:
        import json

        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM assets WHERE id = ? AND project_id = ?", (asset_id, project_id)).fetchone()
        if row is None:
            return None
        asset = {"id": row["id"], "projectId": row["project_id"], "kind": row["kind"], "pathRelative": row["path_relative"], "mime": row["mime"], "byteSize": row["byte_size"], "sha256": row["sha256"], "metadata": json.loads(row["metadata_json"]), "createdAt": row["created_at"]}
        asset["absolutePath"] = str(Path(self.store.get_project(project_id)["rootPath"]) / row["path_relative"])
        return asset

    def delete_asset(self, *, project_id: str, asset_id: str) -> dict[str, Any] | None:
        """Delete a project asset and clear records that point at it.

        Asset references are intentionally stored as plain IDs in a handful of
        derived tables rather than foreign keys. Clearing those references
        keeps previews, exports and future generation requests from pointing at
        a file that no longer exists.
        """
        asset = self.get_asset(project_id=project_id, asset_id=asset_id)
        if asset is None:
            return None
        if asset.get('metadata', {}).get('cadRole'):
            if asset['metadata']['cadRole'] != 'model':
                raise ValueError('CAD 关联文件不能单独删除，请操作整个模型')
            # Archive the library entry; retained versions still own this bundle.
            import json
            metadata = {**asset['metadata'], 'cadHidden': True}
            with self.store._connect() as connection:
                connection.execute('UPDATE assets SET metadata_json=? WHERE id=? AND project_id=?', (json.dumps(metadata,ensure_ascii=False),asset_id,project_id))
            return {key:value for key,value in asset.items() if key != 'absolutePath'}
        project = self.store.get_project(project_id)
        if project is None:
            return None
        root = Path(project["rootPath"]).expanduser().resolve()
        absolute = Path(asset["absolutePath"]).expanduser().resolve()
        if root == absolute or root not in absolute.parents:
            raise ValueError("资产文件不在项目目录内，拒绝删除")

        # Missing files are treated as already deleted; the catalog row is the
        # source of truth and can still be removed safely.
        if absolute.is_file():
            absolute.unlink()

        with self.store._connect() as connection:
            connection.execute("UPDATE generations SET asset_id = NULL WHERE project_id = ? AND asset_id = ?", (project_id, asset_id))
            connection.execute("UPDATE generations SET parent_asset_id = NULL WHERE project_id = ? AND parent_asset_id = ?", (project_id, asset_id))
            connection.execute("UPDATE video_jobs SET source_asset_id = NULL WHERE project_id = ? AND source_asset_id = ?", (project_id, asset_id))
            connection.execute("UPDATE video_jobs SET output_asset_id = NULL WHERE project_id = ? AND output_asset_id = ?", (project_id, asset_id))
            connection.execute("DELETE FROM assets WHERE id = ? AND project_id = ?", (asset_id, project_id))
        return {key: value for key, value in asset.items() if key != "absolutePath"}
