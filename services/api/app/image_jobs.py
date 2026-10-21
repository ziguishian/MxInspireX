"""Durable local image operations, independent of an HTTP request's lifetime.

Only the first submission starts execution. Recovery observes local receipts;
an orphaned operation never resubmits a possibly charged Provider request.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import HTTPException
from starlette.responses import JSONResponse

_LOCAL_REJECTIONS = {'task_update_pending', 'invalid_arguments', 'image_parameters_invalid',
    'planning_required', 'delivery_assignment_required', 'dependency_required', 'representation_required',
    'memory_required', 'reference_mismatch', 'reference_missing', 'reference_changed',
    'reference_analysis_required', 'reference_mode_mismatch', 'reference_selection_required', 'batch_scope_required'}


class ImageJobs:
    def __init__(self, store, executions, tool_name='generate_image'):
        self.store, self.executions = store, executions
        self.tool_name = tool_name
        self.table = {'generate_image':'image_operations','generate_audio':'audio_operations'}[tool_name]
        self._lock = threading.RLock()
        self._live = set()
        self.on_settled = None
        with store._connect() as db:
            db.execute(f'''CREATE TABLE IF NOT EXISTS {self.table} (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT NOT NULL,
                arguments TEXT NOT NULL, state TEXT NOT NULL, output TEXT, http_status INTEGER,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    def identity(self, project_id, task_id, arguments):
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        prefix = '' if self.tool_name == 'generate_image' else self.tool_name+'\n'
        return hashlib.sha256((prefix+project_id+'\n'+task_id+'\n'+encoded).encode()).hexdigest(), encoded

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def _task(self, project_id, task_id):
        with self.store._connect() as db:
            row = db.execute('SELECT status FROM tasks WHERE project_id=? AND id=?', (project_id, task_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        return row['status']

    def submit(self, project_id, task_id, arguments, execute):
        status = self._task(project_id, task_id)
        operation_id, encoded = self.identity(project_id, task_id, arguments)
        with self._lock:
            with self.store._connect() as db:
                row = db.execute(f'SELECT * FROM {self.table} WHERE id=?', (operation_id,)).fetchone()
                if row:
                    output = json.loads(row['output'] or '{}')
                    # A changed local prerequisite can make the same input
                    # valid. Release only proven pre-dispatch rejections.
                    safe = row['state'] == 'completed' and output.get('status') in _LOCAL_REJECTIONS
                    receipt = self.executions.result_status(task_id, self.tool_name, arguments) if safe else None
                    if status == 'running' and receipt and receipt['state'] in {'missing', 'rejected'}:
                        db.execute(f'DELETE FROM {self.table} WHERE id=?', (operation_id,))
                    else:
                        return self.read(project_id, task_id, operation_id)
                    # The same local operation is observed, never queued twice.
                if status != 'running':
                    raise HTTPException(status_code=409, detail='任务已结束，不能提交新的生成请求')
                db.execute(f'INSERT INTO {self.table} VALUES (?,?,?,?,?,?,?,?,?)',
                           (operation_id, project_id, task_id, encoded, 'running', None, None, self.now(), self.now()))
            self._live.add(operation_id)
            threading.Thread(target=self._run, args=(operation_id, project_id, task_id, execute), daemon=True,
                             name='image-operation-'+operation_id[:12]).start()
            return {'operationId': operation_id, 'state': 'running'}

    def _complete(self, operation_id, output, http_status=200):
        with self.store._connect() as db:
            db.execute(f"UPDATE {self.table} SET state='completed',output=?,http_status=?,updated_at=? WHERE id=?",
                       (json.dumps(output, ensure_ascii=False), http_status, self.now(), operation_id))

    def _run(self, operation_id, project_id, task_id, execute):
        try:
            if self._task(project_id, task_id) != 'running':
                self._complete(operation_id, {'tool': self.tool_name, 'status': 'cancelled', 'retryable': False})
                return
            result = execute()
            if isinstance(result, JSONResponse):
                self._complete(operation_id, json.loads(result.body), result.status_code)
            else:
                self._complete(operation_id, result)
        except HTTPException as error:
            self._complete(operation_id, {'detail': error.detail}, error.status_code)
        except Exception as error:
            # An unexpected local exception can occur after Provider dispatch.
            # Leave the durable operation open for receipt reconciliation.
            logging.getLogger(__name__).error('Image operation interrupted: operation=%s error_type=%s', operation_id, type(error).__name__)
        finally:
            with self._lock:
                self._live.discard(operation_id)
            if self.on_settled:
                try:
                    self.on_settled(project_id, task_id)
                except Exception as error:
                    logging.getLogger(__name__).error('Late image sync deferred: operation=%s error_type=%s', operation_id, type(error).__name__)

    def read_arguments(self, project_id, task_id, arguments):
        self._task(project_id, task_id)
        operation_id, _ = self.identity(project_id, task_id, arguments)
        try:
            return self.read(project_id, task_id, operation_id)
        except HTTPException as error:
            if error.status_code != 404: raise
            return self.executions.result_status(task_id, self.tool_name, arguments)

    def read(self, project_id, task_id, operation_id):
        status = self._task(project_id, task_id)
        with self._lock:
            with self.store._connect() as db:
                row = db.execute(f'SELECT * FROM {self.table} WHERE id=? AND project_id=? AND task_id=?',
                                 (operation_id, project_id, task_id)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail='生成任务不存在')
            base = {'operationId': operation_id}
            if status == 'cancelled': return {**base, 'state': 'cancelled'}
            if row['state'] == 'completed':
                output = json.loads(row['output'])
                if output.get('status') != 'succeeded':
                    receipt = self.executions.result_status(task_id, self.tool_name, json.loads(row['arguments']))
                    if receipt.get('state') == 'completed' and receipt.get('output', {}).get('assetId'):
                        self._complete(operation_id, receipt['output'])
                        return {**base, **receipt, 'httpStatus':200}
                return {**base, 'state': 'completed', 'output': output, 'httpStatus': row['http_status']}
            if operation_id in self._live:
                return {**base, 'state': 'running'}
            receipt = self.executions.result_status(task_id, self.tool_name, json.loads(row['arguments']))
            if receipt['state'] == 'completed':
                self._complete(operation_id, receipt['output'])
                return {**base, **receipt, 'httpStatus': 200}
            if receipt['state'] == 'running': return {**base, 'state': 'running'}
            return {**base, 'state': 'unconfirmed', 'retryable': False, 'billingCertainty': 'unknown'}
