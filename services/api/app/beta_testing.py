"""Local beta feedback and a deliberately scoped, redacted support bundle."""
from __future__ import annotations

import csv
import io
import json
import logging
import platform
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ready_output(node, task_id):
    data = node.get('data') or {}
    asset = data.get('asset') or {}
    belongs = (node.get('meta') or {}).get('taskId') == task_id or (asset.get('metadata') or {}).get('taskId') == task_id
    return bool(belongs and data.get('kind') != 'upload' and not any(data.get(k) for k in ('generating', 'draft', 'error'))
                and (asset.get('id') or any(data.get(k) for k in ('assetId', 'text', 'html', 'src'))))


def redact(value):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if re.search(r'(?i)api.?key|authorization|password|secret|access.?token|refresh.?token|cookie', k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r'data:[^\s,]+(?:;base64)?,[^\s"<>]+', '[MEDIA OMITTED]', value)
    value = re.sub(r'(?i)\bBearer\s+[^\s"\',;]+', 'Bearer [REDACTED]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value)
    value = re.sub(r'(?i)((?:api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token|cookie)["\']?\s*[:=]\s*["\']?)[^\s"\',;}]+', r'\1[REDACTED]', value)
    # Signed URLs, query strings and URL credentials are not useful for support.
    value = re.sub(r'(https?://)[^/\s@]+@', r'\1[REDACTED]@', value)
    value = re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]*', r'\1?[REDACTED]', value)
    value = value.replace(str(Path.home()), '[HOME]')
    return value[:24000] + ('\n[TRUNCATED]' if len(value) > 24000 else '')


class RedactedLogFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['shown', 'dismissed', 'rated']
    rating: int | None = Field(default=None, ge=1, le=5, strict=True)
    actor: str = Field(default='', max_length=80)

    @model_validator(mode='after')
    def score_required(self):
        if self.action == 'rated' and self.rating is None:
            raise ValueError('请选择 1–5 星')
        if self.action != 'rated' and self.rating is not None:
            raise ValueError('该操作不接受评分')
        return self


class UsageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event: Literal['app_open', 'page_view', 'artifact_view', 'artifact_export', 'message_copy', 'message_edit']
    page: str = Field(default='', max_length=40)
    projectId: str | None = Field(default=None, max_length=80)
    taskId: str | None = Field(default=None, max_length=80)
    actor: str = Field(default='', max_length=80)


class BetaTesting:
    def __init__(self, store, canvas):
        self.store, self.canvas = store, canvas
        self.handler = None
        with store._connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS beta_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS task_feedback (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL, rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                actor TEXT NOT NULL DEFAULT '', shown_at TEXT, dismissed_at TEXT,
                rated_at TEXT, updated_at TEXT NOT NULL, task_status TEXT, output_ids TEXT NOT NULL DEFAULT '[]');
              CREATE TABLE IF NOT EXISTS beta_usage (
                id TEXT PRIMARY KEY, event TEXT NOT NULL, page TEXT, project_id TEXT,
                task_id TEXT, actor TEXT, created_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS beta_usage_time ON beta_usage(created_at);
            ''')
            db.execute("INSERT OR IGNORE INTO beta_meta VALUES ('installationId', ?)", (str(uuid4()),))

    def start_logging(self):
        folder = self.store.workspace_root / 'logs'
        folder.mkdir(exist_ok=True)
        self.handler = RotatingFileHandler(folder / 'api.log', maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8')
        self.handler.setFormatter(RedactedLogFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        for name in ('', 'uvicorn.error'):
            logging.getLogger(name).addHandler(self.handler)

    def close(self):
        if self.handler:
            for name in ('', 'uvicorn.error'):
                logging.getLogger(name).removeHandler(self.handler)
            self.handler.close()

    def usage(self, payload):
        with self.store._connect() as db:
            db.execute('INSERT INTO beta_usage VALUES (?,?,?,?,?,?,?)', (str(uuid4()), payload.event, payload.page, payload.projectId, payload.taskId, payload.actor, now_iso()))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            db.execute('DELETE FROM beta_usage WHERE created_at < ?', (cutoff,))

    def feedback(self, project_id):
        with self.store._connect() as db:
            rows = db.execute('SELECT * FROM task_feedback WHERE project_id=?', (project_id,)).fetchall()
        return [self._feedback(row) for row in rows]

    @staticmethod
    def _feedback(row):
        return {'taskId': row['task_id'], 'rating': row['rating'], 'shownAt': row['shown_at'], 'dismissedAt': row['dismissed_at'], 'ratedAt': row['rated_at']}

    def save_feedback(self, project_id, task_id, payload):
        with self.store._connect() as db:
            task = db.execute('SELECT status FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
            if not task:
                raise HTTPException(404, '任务不存在')
            outputs = [n['id'] for n in self.canvas.load(project_id)['nodes'] if ready_output(n, task_id)]
            if not outputs:
                raise HTTPException(409, '产物尚未生成，请查看结果后再评价')
            now = now_iso()
            db.execute('INSERT OR IGNORE INTO task_feedback (task_id,project_id,updated_at) VALUES (?,?,?)', (task_id, project_id, now))
            if payload.action == 'rated':
                db.execute('UPDATE task_feedback SET rating=?,actor=?,rated_at=?,updated_at=?,task_status=?,output_ids=?,dismissed_at=NULL WHERE task_id=?',
                           (payload.rating, payload.actor, now, now, task['status'], json.dumps(outputs), task_id))
            elif payload.action == 'shown':
                db.execute('UPDATE task_feedback SET shown_at=COALESCE(shown_at,?),updated_at=? WHERE task_id=?', (now, now, task_id))
            else:
                db.execute('UPDATE task_feedback SET dismissed_at=?,updated_at=? WHERE task_id=?', (now, now, task_id))
            return self._feedback(db.execute('SELECT * FROM task_feedback WHERE task_id=?', (task_id,)).fetchone())

    def export(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with self.store._connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            installation = db.execute("SELECT value FROM beta_meta WHERE key='installationId'").fetchone()[0]
            rows = db.execute('SELECT t.*,p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE t.updated_at>=? ORDER BY t.created_at DESC LIMIT 500', (cutoff,)).fetchall()
            total_tasks = db.execute('SELECT count(*) FROM tasks WHERE updated_at>=?', (cutoff,)).fetchone()[0]
            feedback = [dict(r) for r in db.execute('SELECT * FROM task_feedback WHERE updated_at>=? ORDER BY updated_at', (cutoff,))]
            usage = [dict(r) for r in db.execute('SELECT * FROM beta_usage WHERE created_at>=? ORDER BY created_at DESC LIMIT 20000', (cutoff,))]
            task_ids = {r['id'] for r in rows}
            routes = []
            if 'model_call_trace' in tables:
                routes.extend(dict(r) for r in db.execute('SELECT r.* FROM model_call_trace r JOIN tasks t ON t.id=r.task_id WHERE t.updated_at>=? ORDER BY r.created_at DESC LIMIT 10000', (cutoff,)))
            if 'model_route_trace' in tables and len(routes) < 10000:
                routes.extend(dict(r) for r in db.execute('SELECT r.* FROM model_route_trace r JOIN tasks t ON t.id=r.task_id WHERE t.updated_at>=? ORDER BY r.rowid DESC LIMIT ?', (cutoff, 10000-len(routes))))
            routes = [{'taskId': r['task_id'], 'route': json.loads(r['data_json'])} for r in routes if r['task_id'] in task_ids]
        tasks = []
        for row in rows:
            inp, out = json.loads(row['input_json'] or '{}'), json.loads(row['output_json'] or '{}') or {}
            data = out.get('structured_data') or {}
            tasks.append({'taskId': row['id'], 'projectId': row['project_id'], 'project': row['project_name'], 'status': row['status'],
                          'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'prompt': inp.get('userMessage', ''),
                          'answer': data.get('answer') or data.get('reply') or data.get('finalOutput') or '',
                          'deliveryStatus': data.get('deliveryStatus'), 'provider': inp.get('textProvider'),
                          'scheduledTask': inp.get('scheduledTask'), 'trace': [{k: str(v)[:1000] for k,v in event.items() if k in {'id','phase','message','timestamp','createdAt','status'}} for event in json.loads(row['trace_json'] or '[]')[-200:] if isinstance(event,dict)],
                          'error': json.loads(row['error_json'] or 'null')})
        ratings = [r['rating'] for r in feedback if r['rating'] is not None]
        summary = {'schemaVersion': 1, 'appVersion': '0.1.0', 'buildChannel': 'beta', 'exportedAt': now_iso(), 'since': cutoff,
                   'installationId': installation, 'platform': platform.system(), 'platformVersion': platform.release(),
                   'tasks': len(tasks), 'totalTasksInRange': total_tasks, 'tasksTruncated': total_tasks > len(tasks), 'taskStatus': dict(Counter(t['status'] for t in tasks)), 'ratings': len(ratings),
                   'averageRating': round(sum(ratings) / len(ratings), 2) if ratings else None,
                   'ratingDistribution': {str(i): ratings.count(i) for i in range(1, 6)},
                   'usageEvents': dict(Counter(r['event'] for r in usage)), 'limits': {'tasks': 500, 'traceEntriesPerTask': 200, 'usageEvents': 20000}}
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('summary.json', json.dumps(redact(summary), ensure_ascii=False, indent=2))
            for name, items in [('tasks', tasks), ('feedback', feedback), ('usage', usage), ('model-routes', routes)]:
                archive.writestr(name + '.jsonl', '\n'.join(json.dumps(redact(item), ensure_ascii=False) for item in items))
            table = io.StringIO(newline='')
            writer = csv.writer(table)
            writer.writerow(['task_id', 'project_id', 'actor', 'rating', 'task_status', 'rated_at'])
            for item in feedback:
                values = [str(redact(item.get(k) or '')) for k in ('task_id','project_id','actor','rating','task_status','rated_at')]
                writer.writerow(["'" + v if v.startswith(('=', '+', '-', '@')) else v for v in values])
            archive.writestr('feedback.csv', '\ufeff' + table.getvalue())
            for name in ('api.log', 'api.log.1', 'api.log.2', 'desktop.log', 'desktop.log.1', 'desktop.log.2'):
                log = self.store.workspace_root / 'logs' / name
                if log.is_file() and not log.is_symlink() and log.resolve().is_relative_to(self.store.workspace_root):
                    with log.open('rb') as stream:
                        stream.seek(max(0, log.stat().st_size - 2 * 1024 * 1024))
                        content = stream.read().decode('utf-8', errors='replace')
                    archive.writestr('logs/' + name, '\n'.join(redact(line) for line in content.splitlines()))
            archive.writestr('README.txt', 'MxinspireX · 内部测试日志\n包含近 30 天的对话文本、执行过程、模型路由、使用记录和星级反馈，以及最近的运行日志。\nsummary.json 查看汇总；feedback.csv 可用表格软件打开；JSONL 每行一条记录。\n记录保存在本机，仅在用户手动导出后交付。导出不包含原始素材、完整数据库或凭据文件；已过滤常见密钥及带查询参数的链接。\n部分生成阶段的评分以 task_status=running 标记，output_ids 对应当时已有产物。\n')
        return output.getvalue()


router = APIRouter(prefix='/api/testing')


@router.post('/events')
def record_usage(payload: UsageInput, request: Request):
    request.app.state.testing.usage(payload)
    return {'ok': True}


@router.get('/projects/{project_id}/feedback')
def project_feedback(project_id: str, request: Request):
    return request.app.state.testing.feedback(project_id)


@router.post('/projects/{project_id}/tasks/{task_id}/feedback')
def task_feedback(project_id: str, task_id: str, payload: FeedbackInput, request: Request):
    return request.app.state.testing.save_feedback(project_id, task_id, payload)


@router.get('/export')
def export_testing_logs(request: Request):
    bundle = request.app.state.testing.export()
    filename = f'MxinspireX-beta-logs-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip'
    return Response(bundle, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})
