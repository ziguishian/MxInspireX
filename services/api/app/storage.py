from __future__ import annotations

import json
import os
import re
import sqlite3
import shutil
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  brief TEXT NOT NULL DEFAULT '',
  budget_minor INTEGER,
  currency TEXT NOT NULL DEFAULT 'CNY',
  status TEXT NOT NULL DEFAULT 'draft',
  root_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_settings (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  locale TEXT NOT NULL DEFAULT 'zh-CN',
  privacy_mode TEXT NOT NULL DEFAULT 'local-first',
  default_provider_refs TEXT NOT NULL DEFAULT '{}',
  style_presets_json TEXT NOT NULL DEFAULT '{}'
);


CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);


CREATE TABLE IF NOT EXISTS video_jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  job_id TEXT,
  prompt TEXT NOT NULL DEFAULT '',
  source_asset_id TEXT,
  output_asset_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_jobs_project ON video_jobs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS research_sources (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,
  uri TEXT,
  title TEXT NOT NULL,
  author TEXT,
  published_at TEXT,
  fetched_at TEXT,
  checksum TEXT,
  rights_status TEXT NOT NULL DEFAULT 'unknown',
  snapshot_path TEXT,
  preview_image_url TEXT
);
CREATE TABLE IF NOT EXISTS research_notes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_id TEXT,
  category TEXT NOT NULL,
  body_md TEXT NOT NULL,
  claims_json TEXT NOT NULL DEFAULT '[]',
  confidence REAL
);
CREATE TABLE IF NOT EXISTS prompt_templates (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  template_body TEXT NOT NULL,
  variables_schema TEXT NOT NULL DEFAULT '{}',
  tags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS prompt_versions (
  id TEXT PRIMARY KEY,
  prompt_template_id TEXT NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(prompt_template_id, version)
);
CREATE TABLE IF NOT EXISTS generations (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_run_id TEXT,
  prompt_version_id TEXT,
  provider TEXT NOT NULL,
  model TEXT,
  seed TEXT,
  params_json TEXT NOT NULL DEFAULT '{}',
  parent_asset_id TEXT,
  evaluation_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
  id TEXT PRIMARY KEY,
  generation_id TEXT NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
  evaluator_type TEXT NOT NULL,
  score_json TEXT NOT NULL DEFAULT '{}',
  feedback_md TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
"""


def slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return ascii_slug or "project"


class ProjectStore:
    def __init__(self, workspace_root: str | None = None) -> None:
        configured = workspace_root or os.environ.get("AICS_WORKSPACE_ROOT")
        self.workspace_root = Path(configured or Path.cwd() / "workspace-data").expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.workspace_root / "catalog.sqlite"
        self._initialize_catalog()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.catalog_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_catalog(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            project_columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
            for column, definition in {
                "title_mode": "TEXT NOT NULL DEFAULT 'legacy'",
                "title_generated_at": "TEXT",
                "title_attempt_turns": "INTEGER NOT NULL DEFAULT 0",
                "title_retry_after": "REAL NOT NULL DEFAULT 0",
            }.items():
                if column not in project_columns:
                    connection.execute(f"ALTER TABLE projects ADD COLUMN {column} {definition}")
            # Old intake titles were the first line of the brief, capped at 48
            # characters. Only migrate that recognizable default; custom names
            # remain manual. A later explicit rename always disables automation.
            for row in connection.execute("SELECT * FROM projects WHERE title_mode='legacy'").fetchall():
                first_line = row["brief"].strip().splitlines()[:1]
                default_names = {"未命名设计任务", "新对话"}
                if first_line:
                    default_names.add(first_line[0][:48])
                automatic = row["name"] in default_names
                connection.execute("UPDATE projects SET title_mode=?, name=? WHERE id=?",
                                   ("auto" if automatic else "manual", "新对话" if automatic else row["name"], row["id"]))
                manifest = Path(row["root_path"], "project.json")
                if automatic and manifest.is_file():
                    self._write_project_manifest(connection, row["id"])
            generation_columns = {row[1] for row in connection.execute("PRAGMA table_info(generations)").fetchall()}
            for column, definition in {
                "asset_id": "TEXT",
                "prompt_text": "TEXT NOT NULL DEFAULT ''",
                "negative_prompt": "TEXT NOT NULL DEFAULT ''",
                "parent_generation_id": "TEXT",
            }.items():
                if column not in generation_columns:
                    connection.execute(f"ALTER TABLE generations ADD COLUMN {column} {definition}")
            research_columns = {row[1] for row in connection.execute("PRAGMA table_info(research_sources)").fetchall()}
            if "preview_image_url" not in research_columns:
                connection.execute("ALTER TABLE research_sources ADD COLUMN preview_image_url TEXT")
            self._repair_project_roots(connection)

    def _repair_project_roots(self, connection: sqlite3.Connection) -> None:
        """Rebase project folders copied from another machine into this workspace.

        Older catalog snapshots stored absolute project roots. When the
        workspace is moved to another user or checkout, the catalog still
        loads but every asset content request points at the old machine. If a
        project with the same slug already exists below the configured
        workspace, it is safe to update the catalog and its project manifest
        to that local folder. Catalog-only imports can also recreate a managed
        project directory when its old workspace name and project slug match;
        this restores its metadata, not any missing asset files.
        """
        workspace = self.workspace_root.resolve()
        rows = connection.execute("SELECT * FROM projects").fetchall()
        for row in rows:
            stored_root = Path(str(row["root_path"] or "")).expanduser()
            if stored_root.exists():
                continue
            candidate = (workspace / stored_root.name).resolve()
            if candidate == workspace or workspace not in candidate.parents:
                continue
            if not candidate.exists():
                # Do not redirect arbitrary external folders or detached drives.
                if stored_root.parent.name != workspace.name or stored_root.name != row["slug"]:
                    continue
                candidate.mkdir(parents=True, exist_ok=True)
                payload = {**self._to_project(row), "rootPath": str(candidate)}
                (candidate / "project.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if not candidate.is_dir():
                continue
            connection.execute("UPDATE projects SET root_path = ? WHERE id = ?", (str(candidate), row["id"]))
            manifest = candidate / "project.json"
            if manifest.is_file():
                try:
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    payload["rootPath"] = str(candidate)
                    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    # The catalog row is authoritative; a malformed legacy
                    # manifest must not prevent the API from starting.
                    pass

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [self._to_project(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._to_project(row) if row else None

    def get_project_settings(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM project_settings WHERE project_id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        return {"projectId": row["project_id"], "locale": row["locale"], "privacyMode": row["privacy_mode"], "defaultProviderRefs": json.loads(row["default_provider_refs"] or "{}"), "stylePresets": json.loads(row["style_presets_json"] or "{}")}

    def update_project_settings(self, project_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_project_settings(project_id)
        if current is None:
            return None
        merged = {**current, **changes}
        if merged["privacyMode"] not in {"local-first", "local-only", "approved-network"}:
            raise ValueError("privacyMode 必须是 local-first/local-only/approved-network")
        with self._connect() as connection:
            connection.execute("UPDATE project_settings SET locale = ?, privacy_mode = ?, default_provider_refs = ?, style_presets_json = ? WHERE project_id = ?", (merged["locale"], merged["privacyMode"], json.dumps(merged["defaultProviderRefs"], ensure_ascii=False), json.dumps(merged["stylePresets"], ensure_ascii=False), project_id))
        return self.get_project_settings(project_id)

    def update_project(self, project_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                return None
            current = self._to_project(row)
            current.update({key: value for key, value in changes.items() if value is not None})
            current["currency"] = current["currency"].upper()
            current["updatedAt"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            if changes.get("name") is not None:
                current["name"] = current["name"].strip()
                current["titleMode"] = "manual"
            connection.execute("UPDATE projects SET name=?, brief=?, budget_minor=?, currency=?, updated_at=?, title_mode=? WHERE id=?", (current["name"], current["brief"], current["budgetMinor"], current["currency"], current["updatedAt"], current["titleMode"], project_id))
            self._write_project_manifest(connection, project_id)
        return current

    def _write_project_manifest(self, connection, project_id):
        row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row:
            project = self._to_project(row)
            Path(project["rootPath"], "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_generated_title(self, project_id: str, expected_name: str, title: str, turns: int) -> bool:
        """Commit only if no manual rename/deletion happened during inference."""
        timestamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        with self._connect() as connection:
            changed = connection.execute("""UPDATE projects SET name=?, title_generated_at=?, title_attempt_turns=?
                WHERE id=? AND name=? AND title_mode='auto' AND title_generated_at IS NULL""",
                (title, timestamp, turns, project_id, expected_name)).rowcount
            if changed:
                self._write_project_manifest(connection, project_id)
        # Naming is metadata, not new project activity: preserve updated_at/order.
        return bool(changed)

    def delete_project(self, project_id: str) -> dict[str, Any] | None:
        """Delete a project row and its project-owned files from this workspace."""
        project = self.get_project(project_id)
        if project is None:
            return None
        workspace = self.workspace_root.resolve()
        root = Path(project["rootPath"]).expanduser().resolve()
        # Refuse to remove anything outside a project directory below the
        # configured workspace, even if a corrupted row points elsewhere.
        if root == workspace or workspace not in root.parents:
            raise ValueError("项目目录不在当前工作区内，拒绝删除")
        with self._connect() as connection:
            # Several older project-owned tables predate the catalog foreign
            # keys. Remove their rows explicitly so deleting a project cannot
            # leave orphaned task, asset, document, or version records.
            table_names = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            if "knowledge_documents" in table_names:
                if "knowledge_chunks_fts" in table_names:
                    connection.execute(
                        """DELETE FROM knowledge_chunks_fts
                           WHERE chunk_id IN (
                             SELECT kc.id FROM knowledge_chunks kc
                             JOIN knowledge_documents kd ON kd.id = kc.document_id
                             WHERE kd.project_id = ?
                           )""",
                        (project_id,),
                    )
                connection.execute("DELETE FROM knowledge_documents WHERE project_id = ?", (project_id,))
            # Clear task-owned records before their task rows, including tables
            # that deliberately do not declare foreign keys.
            for table in sorted(table_names - {"projects", "tasks"}):
                quoted = '"' + table.replace('"', '""') + '"'
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info({quoted})")}
                if "project_id" in columns:
                    connection.execute(f"DELETE FROM {quoted} WHERE project_id = ?", (project_id,))
                elif "task_id" in columns and "tasks" in table_names:
                    connection.execute(f"DELETE FROM {quoted} WHERE task_id IN (SELECT id FROM tasks WHERE project_id = ?)", (project_id,))
            if "tasks" in table_names:
                connection.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        if root.exists():
            shutil.rmtree(root)
        return project


    def create_project(self, project: dict[str, Any]) -> dict[str, Any]:
        root = Path(project["rootPath"])
        root.mkdir(parents=True, exist_ok=True)
        for folder in ("assets/originals", "assets/generated", "assets/video", "assets/3d", "assets/cad", "assets/documents", "knowledge/parsed", "knowledge/indexes", "exports"):
            (root / folder).mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(
                """INSERT INTO projects (id, name, slug, brief, budget_minor, currency, status, root_path, created_at, updated_at, title_mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (project["id"], project["name"], project["slug"], project["brief"], project["budgetMinor"], project["currency"], project["status"], project["rootPath"], project["createdAt"], project["updatedAt"], project.get("titleMode", "manual")),
            )
            connection.execute(
                "INSERT INTO project_settings (project_id) VALUES (?)",
                (project["id"],),
            )

        (root / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
        return project

    @staticmethod
    def _to_project(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "name": row["name"], "slug": row["slug"], "brief": row["brief"],
            "budgetMinor": row["budget_minor"], "currency": row["currency"], "status": row["status"],
            "rootPath": row["root_path"], 
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            "titleMode": row["title_mode"], "titleGeneratedAt": row["title_generated_at"],
        }
