"""Versions observed by an Agent, independent of canvas layout and preview state."""
import contextvars
import hashlib
import json

active_task = contextvars.ContextVar('canvas_context_task', default=None)
TRANSIENT = {'previewValidation', 'deliveryReview', 'generating', 'error', 'status', 'job', 'draft',
             'generationPreviewTaskId', 'generationPreviewCallId', 'generationPreviewCreated', 'generationPreviewOriginalStatus'}


def fingerprint(node):
    data = {k:v for k,v in node.get('data',{}).items() if k not in TRANSIENT}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def observe(store, project_id, task_id, nodes, *, initial=False):
    if not task_id: return
    with store._connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS agent_node_versions(project_id TEXT,task_id TEXT,node_id TEXT,fingerprint TEXT,PRIMARY KEY(project_id,task_id,node_id))')
        for node in nodes:
            db.execute(f'INSERT OR {"IGNORE" if initial else "REPLACE"} INTO agent_node_versions VALUES(?,?,?,?)',(project_id,task_id,node['id'],fingerprint(node)))


def check(store, project_id, task_id, node):
    if not task_id: return
    observe(store,project_id,task_id,[],initial=True)
    with store._connect() as db:
        row=db.execute('SELECT fingerprint FROM agent_node_versions WHERE project_id=? AND task_id=? AND node_id=?',(project_id,task_id,node['id'])).fetchone()
    if row and row[0] != fingerprint(node):
        raise ValueError('节点内容已在读取后改变，已阻止覆盖；请重新读取该节点并基于最新内容修改。')
