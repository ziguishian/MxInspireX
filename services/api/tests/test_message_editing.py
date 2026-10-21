import json

import pytest

from app.agent_sessions import AgentSessionStore
from app.conversation_context import ConversationContext
from app.conversation_memory import ConversationMemoryService
from app.execution_store import ExecutionStore
from app.task_runtime import TaskRuntime
from test_conversation_context import workspace, add_turn


def runtime_for(store):
    runtime = TaskRuntime(store)
    runtime._start_worker = lambda *_: True
    return runtime


def finish(store, task_id, answer='新的回复'):
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded',output_json=? WHERE id=?", (json.dumps({'structured_data': {'answer': answer}}), task_id))


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_edit_replaces_visible_turn_and_resets_execution_without_losing_artifacts(workspace, status):
    add_turn(workspace, 'original', '@1 旧要求', status=status, extra={'referencedFiles': [{'documentId': 'doc', 'index': 1, 'filename': '参考.txt', 'pathRelative': 'knowledge/reference.txt'}]})
    executions = ExecutionStore(workspace)
    executions.save('original', {'finalResult': {'answer': '旧回复'}, 'sessions': {'design': 'old checkpoint'}})
    receipt, _ = executions.claim('original', 'generate_text', {'prompt': 'old'})
    executions.complete('original', receipt, {'assetId': 'saved-artifact'})
    runtime = runtime_for(workspace)
    edited = runtime.edit('one', 'original', brief='@1 新要求', input_data={'referencedFiles': [{'documentId': 'doc', 'index': 1, 'filename': '参考.txt'}]})
    assert edited['conversationTurnId'] == 'original'
    assert edited['replacesTaskId'] == 'original'
    assert edited['status'] == 'queued' and edited['output'] is None and edited['error'] is None
    assert edited['userMessage'] == '@1 新要求'
    assert len(edited['trace']) == 1 and '消息已修改' in edited['trace'][0]['message']
    assert [t['id'] for t in runtime.list_tasks('one')] == [edited['id']]
    assert TaskRuntime(workspace).list_tasks('one')[0]['userMessage'] == '@1 新要求'
    assert executions.load(edited['id']) == {'toolOutputs': []}
    assert executions.load('original')['toolOutputs'][0]['output']['assetId'] == 'saved-artifact'
    with workspace._connect() as db:
        inputs = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (edited['id'],)).fetchone()[0])
        assert inputs['referencedFiles'][0]['pathRelative'] == 'knowledge/reference.txt'
        assert db.execute('SELECT superseded_by FROM tasks WHERE id="original"').fetchone()[0] == edited['id']


def test_repeated_edits_keep_order_and_context_excludes_old_and_future_messages(workspace):
    for task, message in [('before', '前面的要求'), ('original', '旧要求'), ('after', '后续消息')]:
        add_turn(workspace, task, message)
    runtime = runtime_for(workspace)
    edited = runtime.edit('one', 'original', brief='新要求')
    assert [t['userMessage'] for t in reversed(runtime.list_tasks('one'))] == ['前面的要求', '新要求', '后续消息']
    context = ConversationContext(workspace)
    assert [m['content'] for m in context.build('one', edited['id'])['messages'] if m['role'] == 'user'] == ['前面的要求']
    with pytest.raises(ValueError, match='已被修改'):
        runtime.edit('one', 'original', brief='重复提交')
    finish(workspace, edited['id'])
    latest = runtime.edit('one', edited['id'], brief='再次修改')
    assert latest['conversationTurnId'] == 'original'
    assert [t['userMessage'] for t in reversed(runtime.list_tasks('one'))] == ['前面的要求', '再次修改', '后续消息']
    finish(workspace, latest['id'])
    future = runtime.enqueue(project_id='one', agent_key='design', workflow_step='design', brief='请继续', run_async=True)
    texts = [m['content'] for m in context.build('one', future['id'])['messages'] if m['role'] == 'user']
    assert texts == ['前面的要求', '再次修改', '后续消息']


def test_edit_is_project_scoped_and_rejected_requests_preserve_original(workspace):
    add_turn(workspace, 'original', '原文')
    runtime = runtime_for(workspace)
    assert runtime.edit('two', 'original', brief='不属于本项目') is None
    for invalid in ['', '  ', None]:
        with pytest.raises(ValueError): runtime.edit('one', 'original', brief=invalid)
    add_turn(workspace, 'busy', '正在运行', status='running')
    with pytest.raises(ValueError, match='尚未结束'): runtime.edit('one', 'original', brief='新内容')
    assert runtime.get_task('one', 'original')['userMessage'] == '原文'
    assert len(runtime.list_tasks('one')) == 2


def test_edit_discards_old_sdk_history_and_memory_from_current_context(workspace):
    add_turn(workspace, 'before', '前面的要求')
    add_turn(workspace, 'original', '我想要蓝色')
    runtime = runtime_for(workspace)
    sessions = AgentSessionStore(workspace)
    acquired = sessions.dispatch('one', 'original', {'action': 'acquire'})
    sessions.dispatch('one', 'original', {'action': 'mutate', 'operationId': 'old', 'revision': acquired['revision'],
        'transaction': {'type': 'append_items', 'items': [{'type': 'message', 'role': 'user', 'content': '我想要蓝色'}]}})
    memory = ConversationMemoryService(workspace)
    memory.bootstrap('one', 'original')
    with workspace._connect() as db:
        memory._write(db, 'project:one', 'color', {'content': '蓝色', 'active': True, 'scope': 'conversation', 'source': {'taskId': 'original'}})
    edited = runtime.edit('one', 'original', brief='我想要红色')
    current = sessions.dispatch('one', edited['id'], {'action': 'get'})
    assert current['sessionId'] != acquired['sessionId']
    assert '蓝色' not in json.dumps(current, ensure_ascii=False)
    assert memory.read('one', edited['id'])['records'] == []
    finish(workspace, edited['id'])
    future = runtime.enqueue(project_id='one', agent_key='design', workflow_step='design', brief='继续', run_async=True)
    resumed = sessions.dispatch('one', future['id'], {'action': 'get'})
    text = json.dumps(resumed, ensure_ascii=False)
    assert '红色' in text and '蓝色' not in text


def test_legacy_resubmit_request_also_replaces_instead_of_appending(workspace):
    add_turn(workspace, 'original', '原文')
    runtime = runtime_for(workspace)
    edited = runtime.enqueue(project_id='one', agent_key='design', workflow_step='design', brief='修改后', input_data={'resubmittedTaskId': 'original'}, run_async=True)
    assert edited['replacesTaskId'] == 'original'
    assert len(runtime.list_tasks('one')) == 1


def test_http_edit_route_returns_updated_turn_and_rejects_foreign_task(workspace):
    from fastapi.testclient import TestClient
    from app.main import app, get_tasks
    add_turn(workspace, 'original', '原文')
    runtime = runtime_for(workspace)
    app.dependency_overrides[get_tasks] = lambda: runtime
    try:
        client = TestClient(app)
        response = client.patch('/api/projects/one/tasks/original', json={'brief': '修改后'})
        assert response.status_code == 200, response.text
        assert response.json()['userMessage'] == '修改后'
        assert client.patch('/api/projects/two/tasks/original', json={'brief': '越界'}).status_code == 404
        assert client.patch('/api/projects/one/tasks/original', json={'brief': '重复'}).status_code == 409
    finally:
        app.dependency_overrides.pop(get_tasks, None)
