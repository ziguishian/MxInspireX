from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromptService:
    def __init__(self, store) -> None:
        self.store = store

    def create_template(self, *, project_id: str, payload: dict) -> dict:
        name = str(payload.get("name", "")).strip()
        body = str(payload.get("templateBody", ""))
        if not name or not body.strip():
            raise ValueError("Prompt 模板名称和内容不能为空")
        template_id = str(uuid4())
        with self.store._connect() as connection:
            connection.execute("INSERT INTO prompt_templates (id, project_id, name, template_body, variables_schema, tags_json) VALUES (?, ?, ?, ?, ?, ?)", (template_id, project_id, name, body, json.dumps(payload.get("variablesSchema") or {}, ensure_ascii=False), json.dumps(payload.get("tags") or [], ensure_ascii=False)))
        return self.get_template(template_id)

    def list_templates(self, project_id: str) -> list[dict]:
        with self.store._connect() as connection:
            rows = connection.execute("SELECT * FROM prompt_templates WHERE project_id = ? ORDER BY name", (project_id,)).fetchall()
        return [self.get_template(row["id"]) for row in rows]

    def get_template(self, template_id: str) -> dict:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM prompt_templates WHERE id = ?", (template_id,)).fetchone()
            versions = connection.execute("SELECT * FROM prompt_versions WHERE prompt_template_id = ? ORDER BY version DESC", (template_id,)).fetchall()
        if row is None:
            raise ValueError("Prompt 模板不存在")
        template = self._template_row(row)
        template["versions"] = [{"id": item["id"], "version": item["version"], "contentHash": item["content_hash"], "createdAt": item["created_at"]} for item in versions]
        return template

    def create_version(self, *, template_id: str, content: str | None = None) -> dict:
        template = self.get_template(template_id)
        version_content = content if content is not None else template["templateBody"]
        if not version_content.strip():
            raise ValueError("Prompt 内容不能为空")
        with self.store._connect() as connection:
            latest = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM prompt_versions WHERE prompt_template_id = ?", (template_id,)).fetchone()["version"]
            version = int(latest) + 1
            version_id = str(uuid4())
            digest = hashlib.sha256(version_content.encode("utf-8")).hexdigest()
            created_at = now_iso()
            connection.execute("INSERT INTO prompt_versions (id, prompt_template_id, version, content_hash, created_at) VALUES (?, ?, ?, ?, ?)", (version_id, template_id, version, digest, created_at))
            connection.execute("UPDATE prompt_templates SET template_body = ? WHERE id = ?", (version_content, template_id))
        return {"id": version_id, "promptTemplateId": template_id, "version": version, "content": version_content, "contentHash": digest, "createdAt": created_at}

    @staticmethod
    def _template_row(row) -> dict:
        return {"id": row["id"], "projectId": row["project_id"], "name": row["name"], "templateBody": row["template_body"], "variablesSchema": json.loads(row["variables_schema"] or "{}"), "tags": json.loads(row["tags_json"] or "[]")}
