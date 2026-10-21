"""SQLite storage adapter for the official Agents SDK Session interface.

The SDK owns message semantics. This module only stores opaque SDK items and
applies its atomic history transactions; external tool receipts stay separate.
"""
import hashlib
import json
import re

from .conversation_context import ConversationContext
from .session_blobs import SessionBlobs


class AgentSessionStore:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(sdk_sessions)')}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sdk_%'")}
            if {'storage_version', 'compaction_signature'} <= columns and {
                'sdk_sessions', 'sdk_session_operations', 'sdk_session_archive', 'sdk_session_raw', 'sdk_context_manifests', 'sdk_session_blobs',
            } <= tables:
                return
            db.executescript('''
              CREATE TABLE IF NOT EXISTS sdk_sessions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, items TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0, owner TEXT);
              CREATE TABLE IF NOT EXISTS sdk_session_operations (
                session_id TEXT, operation_id TEXT, digest TEXT NOT NULL,
                PRIMARY KEY(session_id, operation_id));
              CREATE TABLE IF NOT EXISTS sdk_session_archive (
                session_id TEXT, revision INTEGER, items TEXT NOT NULL,
                PRIMARY KEY(session_id, revision));
              CREATE TABLE IF NOT EXISTS sdk_session_raw (
                session_id TEXT PRIMARY KEY, items TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sdk_context_manifests (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sdk_session_blobs (
                project_id TEXT NOT NULL, id TEXT NOT NULL, body BLOB NOT NULL,
                PRIMARY KEY(project_id,id));
            ''')
            if 'compaction_signature' not in {r[1] for r in db.execute('PRAGMA table_info(sdk_sessions)')}:
                db.execute('ALTER TABLE sdk_sessions ADD COLUMN compaction_signature TEXT')
            if 'storage_version' not in {r[1] for r in db.execute('PRAGMA table_info(sdk_sessions)')}:
                db.execute('ALTER TABLE sdk_sessions ADD COLUMN storage_version INTEGER NOT NULL DEFAULT 0')

    def dispatch(self, project_id, task_id, payload):
        stage = str(payload.get('stage', 'design'))
        if not re.fullmatch(r'[a-z_0-9]{1,80}', stage):
            raise ValueError('无效的会话阶段')
        # Validate ownership even for read operations. Never accept a client session ID.
        with self.store._connect() as db:
            task = db.execute('SELECT status,input_json,superseded_by FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if not task or task['status'] == 'cancelled' or task['superseded_by']:
            raise ValueError('任务不存在、不属于此项目或已停止')
        task_input = json.loads(task['input_json'] or '{}')
        editing = bool(task_input.get('replacesTaskId'))
        node_id = str(task_input.get('canvasNodeId') or (task_input.get('canvasParams') or {}).get('canvasNodeId') or '')
        node_task = task_input.get('taskSurface') == 'canvas_node' and bool(node_id)
        session_id = (f'project:{project_id}:node:{node_id}:task:{task_id}' if stage == 'design' and node_task else
                      f'project:{project_id}' if stage == 'design' and not editing else
                      f'project:{project_id}:task:{task_id}:{stage}')
        action = payload.get('action', 'get')
        initial = []
        with self.store._connect() as db:
            existing = db.execute('SELECT storage_version FROM sdk_sessions WHERE id=?', (session_id,)).fetchone()
        if stage == 'design' and not existing and not node_task:
            # One-time import of available original history, without model calls.
            history = ConversationContext(self.store)
            for row in history._rows(project_id, task_id):
                turn = history._turn(row, include_artifacts=False)
                for role, key, part in [('user', 'user', 'input_text'), ('assistant', 'assistant', 'output_text')]:
                    if turn[key]:
                        initial.append({'type': 'message', 'role': role,
                                        **({'status': 'completed'} if role == 'assistant' else {}),
                                        'content': [{'type': part, 'text': turn[key]}]})
        # Migrate only the session being opened, atomically and losslessly.
        # Normal reads no longer acquire the workspace-wide SQLite write lock.
        if not existing or existing['storage_version'] == 0:
            with self.store._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                blobs = SessionBlobs(db, project_id)
                initial_json = json.dumps(blobs.pack(initial), ensure_ascii=False)
                db.execute('INSERT OR IGNORE INTO sdk_sessions(id,project_id,items,storage_version) VALUES(?,?,?,1)',
                           (session_id, project_id, initial_json))
                row = db.execute('SELECT items,storage_version FROM sdk_sessions WHERE id=?', (session_id,)).fetchone()
                db.execute('INSERT OR IGNORE INTO sdk_session_raw VALUES(?,?)', (session_id, row['items']))
                if row['storage_version'] == 0:
                    for table, column in [('sdk_sessions', 'id'), ('sdk_session_raw', 'session_id')]:
                        value = db.execute(f'SELECT items FROM {table} WHERE {column}=?', (session_id,)).fetchone()
                        db.execute(f'UPDATE {table} SET items=? WHERE {column}=?',
                                   (json.dumps(blobs.pack(json.loads(value[0])), ensure_ascii=False), session_id))
                    for archived in db.execute('SELECT revision,items FROM sdk_session_archive WHERE session_id=?', (session_id,)).fetchall():
                        db.execute('UPDATE sdk_session_archive SET items=? WHERE session_id=? AND revision=?',
                                   (json.dumps(blobs.pack(json.loads(archived['items'])), ensure_ascii=False), session_id, archived['revision']))
                    db.execute('UPDATE sdk_sessions SET storage_version=1 WHERE id=?', (session_id,))
        if action in {'get', 'archive'}:
            with self.store._connect() as db:
                db.execute('BEGIN')
                row = db.execute('SELECT revision,compaction_signature FROM sdk_sessions WHERE id=?', (session_id,)).fetchone()
                items = []
                if payload.get('limit') != 0:
                    table, column = ('sdk_session_raw', 'session_id') if action == 'archive' else ('sdk_sessions', 'id')
                    value = db.execute(f'SELECT items FROM {table} WHERE {column}=?', (session_id,)).fetchone()
                    items = json.loads(value[0])
                    if payload.get('limit') is not None:
                        items = items[-max(0, int(payload['limit'])):] if int(payload['limit']) > 0 else []
                    items = SessionBlobs(db, project_id).unpack(items)
                return {'sessionId':session_id, 'revision':row['revision'], 'items':items, 'compactionSignature':row['compaction_signature']}
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            blobs = SessionBlobs(db, project_id)
            row = db.execute('SELECT * FROM sdk_sessions WHERE id=?', (session_id,)).fetchone()
            items, revision = json.loads(row['items']), row['revision']
            db.execute('INSERT OR IGNORE INTO sdk_session_raw VALUES(?,?)',(session_id,row['items']))
            if action == 'acquire':
                if row['owner'] and row['owner'] != task_id:
                    owner = db.execute('SELECT status FROM tasks WHERE id=?', (row['owner'],)).fetchone()
                    if owner and owner['status'] == 'running':
                        raise ValueError('同一项目的主会话正在执行，请等待原任务完成')
                db.execute('UPDATE sdk_sessions SET owner=? WHERE id=?', (task_id, session_id))
            elif action == 'release':
                db.execute('UPDATE sdk_sessions SET owner=NULL WHERE id=? AND owner=?', (session_id, task_id))
            elif action == 'mutate':
                if row['owner'] != task_id:
                    raise ValueError('会话未取得写入锁')
                transaction = payload.get('transaction') or {}
                operation_id = str(payload.get('operationId') or '')
                if not operation_id:
                    raise ValueError('会话写入必须具有幂等操作 ID')
                encoded = json.dumps(transaction, sort_keys=True, ensure_ascii=False)
                digest = hashlib.sha256(encoded.encode()).hexdigest()
                old = db.execute('SELECT digest FROM sdk_session_operations WHERE session_id=? AND operation_id=?', (session_id, operation_id)).fetchone()
                if old:
                    if old['digest'] != digest:
                        raise ValueError('相同会话操作 ID 的内容发生变化')
                    return {'sessionId': session_id, 'revision': revision, 'replayed': True}
                if payload.get('revision') != revision:
                    raise ValueError('会话版本发生变化，请从检查点恢复')
                transaction = blobs.pack(transaction)
                kind = transaction.get('type')
                result = None
                if kind == 'append_items':
                    items += transaction['items']
                elif kind == 'replace_suffix':
                    suffix = transaction['expectedSuffix']
                    if suffix and items[-len(suffix):] != suffix:
                        raise ValueError('会话尾部与 SDK 检查点不匹配')
                    items = (items[:-len(suffix)] if suffix else items) + transaction['replacement']
                elif kind == 'replace':
                    items = transaction['items']
                elif kind == 'pop':
                    result = items.pop() if items else None
                elif kind == 'rewrite':
                    for mutation in transaction['mutations']:
                        if mutation['type'] != 'replace_function_call':
                            raise ValueError('不支持的 SDK 历史变更')
                        items = [mutation['replacement'] if i.get('type') == 'function_call' and i.get('callId') == mutation['callId'] else i for i in items]
                else:
                    raise ValueError('无效的 SDK 历史事务')
                if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
                    raise ValueError('无效的 SDK 会话记录')
                if kind in {'append_items', 'replace_suffix'}:
                    raw = json.loads(db.execute('SELECT items FROM sdk_session_raw WHERE session_id=?',(session_id,)).fetchone()[0])
                    if kind == 'append_items':
                        raw += transaction['items']
                    else:
                        suffix=transaction['expectedSuffix']
                        if not suffix or raw[-len(suffix):]==suffix:
                            raw=(raw[:-len(suffix)] if suffix else raw)+transaction['replacement']
                        else:
                            # A compacted replay boundary need not exist in the raw audit stream.
                            raw += [i for i in transaction['replacement'] if i.get('type')!='compaction']
                    db.execute('UPDATE sdk_session_raw SET items=? WHERE session_id=?',(json.dumps(raw,ensure_ascii=False),session_id))
                # Preserve uncompressed revisions before any destructive history operation.
                if kind != 'append_items':
                    db.execute('INSERT OR IGNORE INTO sdk_session_archive VALUES(?,?,?)', (session_id, revision, row['items']))
                if kind == 'replace' and not any(i.get('type') == 'compaction' for i in items):
                    db.execute('UPDATE sdk_session_raw SET items=? WHERE session_id=?',(json.dumps(items,ensure_ascii=False),session_id))
                if kind in {'pop','rewrite'}:
                    raw=json.loads(db.execute('SELECT items FROM sdk_session_raw WHERE session_id=?',(session_id,)).fetchone()[0])
                    if kind=='pop' and raw and raw[-1]==result: raw.pop()
                    if kind=='rewrite':
                        for mutation in transaction['mutations']:
                            raw=[mutation['replacement'] if i.get('type')=='function_call' and i.get('callId')==mutation['callId'] else i for i in raw]
                    db.execute('UPDATE sdk_session_raw SET items=? WHERE session_id=?',(json.dumps(raw,ensure_ascii=False),session_id))
                compaction_signature = row['compaction_signature']
                if kind == 'replace':
                    compaction_signature = transaction.get('compactionSignature') if any(i.get('type') == 'compaction' for i in items) else None
                    db.execute('UPDATE sdk_sessions SET compaction_signature=? WHERE id=?', (compaction_signature, session_id))
                revision += 1
                db.execute('UPDATE sdk_sessions SET items=?,revision=? WHERE id=?', (json.dumps(items, ensure_ascii=False), revision, session_id))
                db.execute('INSERT INTO sdk_session_operations VALUES(?,?,?)', (session_id, operation_id, digest))
                return {'sessionId': session_id, 'revision': revision, 'item': blobs.unpack(result), 'compactionSignature':compaction_signature}
            else:
                raise ValueError('无效的会话操作')
            limit = payload.get('limit')
            if limit is not None:
                items = items[-max(0, int(limit)):] if int(limit) > 0 else []
            return {'sessionId': session_id, 'revision': revision, 'items': blobs.unpack(items), 'compactionSignature':row['compaction_signature']}

    def manifest(self, task_id, manifest):
        # Diagnostic fields only; prompts, credentials and model reasoning are excluded.
        allowed = {'id', 'stage', 'sessionId', 'revision', 'inputChars', 'inputImages',
                   'selected', 'omitted', 'model', 'responseId', 'sequence', 'reason',
                   'memoryRevision', 'memoryIds', 'referenceSnapshots', 'evidenceIds', 'nodeIds', 'nodeVersions', 'checkpointVersion', 'toolSchemaChars', 'skillBindings', 'skillChars',
                   'estimatedInputTokens', 'localBeforeTokens', 'localAfterTokens', 'localCompacted', 'receiptCount', 'localBudgetExceeded'}
        value = {k: v for k, v in manifest.items() if k in allowed}
        with self.store._connect() as db:
            db.execute('INSERT OR REPLACE INTO sdk_context_manifests VALUES(?,?,?)',
                       (value['id'], task_id, json.dumps(value, ensure_ascii=False)))

    def record_cost(self, task_id, manifest_id, points, ledger_id):
        with self.store._connect() as db:
            row = db.execute('SELECT payload FROM sdk_context_manifests WHERE id=? AND task_id=?',(manifest_id,task_id)).fetchone()
            if row:
                value=json.loads(row[0]);value.update(actualPoints=points,ledgerId=ledger_id)
                db.execute('UPDATE sdk_context_manifests SET payload=? WHERE id=? AND task_id=?',(json.dumps(value,ensure_ascii=False),manifest_id,task_id))
