"""Durable human steering, separate from mutable task/checkpoint snapshots."""
from .agent_contracts import utc_now

SCHEMA = '''CREATE TABLE IF NOT EXISTS task_updates (
 task_id TEXT NOT NULL, project_id TEXT NOT NULL, request_id TEXT NOT NULL,
 text TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, applied_at TEXT,
 PRIMARY KEY(task_id,request_id), UNIQUE(task_id,revision));'''

class TaskUpdates:
    def __init__(self, store): self.store = store

    @staticmethod
    def _item(row):
        return {'id': row['request_id'], 'text': row['text'], 'revision': row['revision'], 'createdAt': row['created_at'], 'appliedAt': row['applied_at']}

    def list(self, project_id, task_id):
        with self.store._connect() as db:
            if not db.execute('SELECT 1 FROM tasks WHERE project_id=? AND id=?', (project_id, task_id)).fetchone(): raise KeyError('任务不存在')
            rows = db.execute('SELECT * FROM task_updates WHERE project_id=? AND task_id=? ORDER BY revision', (project_id, task_id)).fetchall()
        return [self._item(row) for row in rows]

    def append(self, project_id, task_id, request_id, text):
        import json
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128: raise ValueError('补充要求缺少有效请求标识')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 12000: raise ValueError('补充要求应为 1–12000 字的文字')
        text = text.strip()
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,input_json FROM tasks WHERE project_id=? AND id=?', (project_id, task_id)).fetchone()
            if not row: raise KeyError('任务不存在')
            previous = db.execute('SELECT * FROM task_updates WHERE task_id=? AND request_id=?', (task_id,request_id)).fetchone()
            if previous:
                if previous['text'] != text: raise ValueError('相同请求标识的补充内容发生变化')
                return self._item(previous)
            if row['status'] not in ('queued', 'pending', 'running'): raise ValueError('当前任务已结束，补充未发送，请作为下一项提交')
            if json.loads(row['input_json']).get('taskSurface') == 'canvas_node': raise ValueError('请在项目对话任务中补充要求')
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM task_updates WHERE task_id=?', (task_id,)).fetchone()[0]
            created = utc_now()
            db.execute('INSERT INTO task_updates VALUES (?,?,?,?,?,?,NULL)', (task_id,project_id,request_id,text,revision,created))
            db.execute('UPDATE tasks SET updated_at=? WHERE id=?', (created,task_id))
            return {'id':request_id,'text':text,'revision':revision,'createdAt':created,'appliedAt':None}

    def acknowledge(self, project_id, task_id, revision):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM tasks WHERE project_id=? AND id=?', (project_id,task_id)).fetchone()
            if not row: raise KeyError('任务不存在')
            if row['status'] not in ('queued','pending','running'): return []
            db.execute('UPDATE task_updates SET applied_at=? WHERE project_id=? AND task_id=? AND revision<=? AND applied_at IS NULL', (utc_now(),project_id,task_id,revision))
        return self.list(project_id,task_id)

    def pending_after(self, project_id, task_id, revision):
        with self.store._connect() as db:
            return bool(db.execute('SELECT 1 FROM task_updates WHERE project_id=? AND task_id=? AND revision>? LIMIT 1', (project_id,task_id,revision)).fetchone())
