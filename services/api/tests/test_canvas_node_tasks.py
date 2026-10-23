import json

import pytest

from app.agent_sessions import AgentSessionStore
from app.canvas import CanvasStore
from app.conversation_context import ConversationContext
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


@pytest.fixture
def node_runtime(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='node-tasks', slug='node-tasks', brief='', budget_minor=None,
                                               currency='CNY', root_path=str(tmp_path / 'node-tasks')))
    canvas = CanvasStore(store)
    runtime = TaskRuntime(store)
    monkeypatch.setattr(runtime, '_start_worker', lambda *args: False)
    return store, project['id'], canvas, runtime


def node_input(project_id, node_id, *, references=(), kind='image'):
    return {
        'taskSurface': 'canvas_node', 'canvasNodeId': node_id,
        'canvasParams': {'kind': kind, 'canvasNodeId': node_id, 'reference_node_ids': list(references)},
        'referencedNodes': [{'id': identity, 'projectId': project_id} for identity in references],
        'referencedAssets': [], 'referencedFiles': [],
    }


def test_node_tasks_are_isolated_and_different_nodes_can_queue_together(node_runtime):
    store, project_id, canvas, runtime = node_runtime
    first = canvas.create_node(project_id, kind='image', title='A')
    second = canvas.create_node(project_id, kind='image', title='B')
    task_a = runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='生成 A',
                             input_data=node_input(project_id, first['id']), run_async=True)
    task_b = runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='生成 B',
                             input_data=node_input(project_id, second['id']), run_async=True)
    assert task_a['taskSurface'] == task_b['taskSurface'] == 'canvas_node'
    assert {task_a['canvasNodeId'], task_b['canvasNodeId']} == {first['id'], second['id']}
    with pytest.raises(ValueError, match='正在执行'):
        runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='重复生成 A',
                        input_data=node_input(project_id, first['id']), run_async=True)
    assert ConversationContext(store)._rows(project_id, task_b['id']) == []
    session = AgentSessionStore(store).dispatch(project_id, task_a['id'], {'action': 'get', 'stage': 'design'})
    assert session['sessionId'] == f"project:{project_id}:node:{first['id']}:task:{task_a['id']}"


def test_node_task_rejects_filled_target_and_self_reference_before_insert(node_runtime):
    store, project_id, canvas, runtime = node_runtime
    filled = canvas.create_node(project_id, kind='text', title='filled', data={'text': 'existing'})
    with pytest.raises(ValueError, match='self_reference_not_allowed'):
        runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='覆盖',
                        input_data={**node_input(project_id, filled['id']), 'canvasParams': {'kind': 'text', 'canvasNodeId': filled['id']}},
                        run_async=True)
    blank = canvas.create_node(project_id, kind='image', title='blank')
    with pytest.raises(ValueError, match='self_reference_not_allowed'):
        runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='自引用',
                        input_data=node_input(project_id, blank['id'], references=[blank['id']]), run_async=True)
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0


def test_linked_image_ordinals_do_not_create_multiple_deliveries(node_runtime):
    store, project_id, canvas, runtime = node_runtime
    first = canvas.create_node(project_id, kind='text', title='first', data={'text': 'first source'})
    second = canvas.create_node(project_id, kind='text', title='second', data={'text': 'second source'})
    target = canvas.create_node(project_id, kind='image', title='output')
    inputs = node_input(project_id, target['id'], references=[first['id'], second['id']])
    args = dict(project_id=project_id, agent_key='design', workflow_step='design',
                brief='生成一张海报，保留第一张图的角色，沿用第二张海报风格。只生成一张。',
                input_data=inputs, run_async=True, request_id='linked-once')
    task = runtime.enqueue(**args)
    assert runtime.enqueue(**args)['id'] == task['id']
    with store._connect() as db:
        saved = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task['id'],)).fetchone()[0])
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
    assert saved['deliveryContract'] == [{'kind': 'image', 'count': 1, 'transparent': False}]
    assert saved['canvasParams']['reference_node_ids'] == [first['id'], second['id']]


@pytest.mark.parametrize('kind,brief', [
    ('text','实际查看当前图片，写一句中文描述。只保存一个文字节点，不生成图片。'),
    ('image','结合两张图片和文字节点生成一张海报'),
    ('video','根据图片制作视频，并保留图片中的文字'),
    ('audio','将视频中的文字文案生成语音'),
    ('html','用图片和文案制作网页'),
    ('cad','根据图片制作 CAD 模型'),
])
def test_node_delivery_type_does_not_infer_outputs_from_upstream_media(node_runtime, kind, brief):
    store, project_id, canvas, runtime = node_runtime
    node = canvas.create_node(project_id, kind=kind, title=kind)
    task = runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief=brief,
                           input_data=node_input(project_id, node['id'], kind=kind), run_async=True)
    with store._connect() as db:
        context = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task['id'],)).fetchone()[0])
    assert [(item['kind'],item['count']) for item in context['deliveryContract']] == [(kind,1)]


def test_conversation_history_ignores_node_tasks(node_runtime):
    store, project_id, canvas, runtime = node_runtime
    node = canvas.create_node(project_id, kind='image', title='node')
    runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='节点生成',
                    input_data=node_input(project_id, node['id']), run_async=True)
    conversation = runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='主对话',
                                   input_data={'taskSurface': 'conversation'}, run_async=True)
    assert ConversationContext(store).build(project_id, conversation['id'])['historyTurnCount'] == 0
    with store._connect() as db:
        saved = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (conversation['id'],)).fetchone()[0])
    assert saved['taskSurface'] == 'conversation'


@pytest.mark.parametrize('kind', ['image', 'video', 'audio', 'text', 'html', 'cad'])
def test_all_node_types_bind_before_worker_and_reuse_request(node_runtime, monkeypatch, kind):
    store, project_id, canvas, runtime = node_runtime
    node = canvas.create_node(project_id, kind=kind, title=kind)
    observed = []
    def worker(task_id, brief):
        data = next(n['data'] for n in canvas.load(project_id)['nodes'] if n['id'] == node['id'])
        assert data['taskId'] == task_id and data['generating']
        observed.append(task_id)
        # Simulate a worker completing before the POST response is returned.
        canvas.update_node(project_id, node['id'], {'data': {'generating': False, 'assetId': 'saved'}})
    monkeypatch.setattr(runtime, '_start_worker', worker)
    args = dict(project_id=project_id, agent_key='design', workflow_step='design', brief='生成',
                input_data=node_input(project_id, node['id'], kind=kind), run_async=True, request_id='stable')
    first = runtime.enqueue(**args)
    assert runtime.enqueue(**args)['id'] == first['id']
    assert observed == [first['id']]
    data = next(n['data'] for n in canvas.load(project_id)['nodes'] if n['id'] == node['id'])
    assert data['assetId'] == 'saved' and not data['generating']


@pytest.mark.parametrize('kind,requested', [('image', 'video'), ('text', 'image'), ('drawing', 'drawing'), ('3d', '3d')])
def test_reject_invalid_node_generation_type_before_enqueue(node_runtime, kind, requested):
    store, project_id, canvas, runtime = node_runtime
    node = canvas.create_node(project_id, kind=kind, title=kind)
    with pytest.raises(ValueError, match='类型'):
        runtime.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief='生成',
                        input_data=node_input(project_id, node['id'], kind=requested), run_async=True)
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0


def test_transaction_rechecks_request_key_before_rejecting_busy_node(node_runtime, monkeypatch):
    _, project_id, canvas, runtime = node_runtime
    node = canvas.create_node(project_id, kind='image', title='image')
    args = dict(project_id=project_id, agent_key='design', workflow_step='design', brief='生成',
                input_data=node_input(project_id, node['id']), run_async=True, request_id='same')
    first = runtime.enqueue(**args)
    # Simulate a request that passed the early lookup before another request committed.
    monkeypatch.setattr(runtime, '_request_task', lambda *args, **kwargs: None)
    assert runtime.enqueue(**args)['id'] == first['id']


def test_failed_node_retry_uses_new_references_without_replaying_old_request(node_runtime):
    store, project_id, canvas, runtime = node_runtime
    old = canvas.create_node(project_id, kind='text', title='old', data={'text':'old source'})
    new = canvas.create_node(project_id, kind='text', title='new', data={'text':'latest source'})
    target = canvas.create_node(project_id, kind='image', title='output')
    args = dict(project_id=project_id, agent_key='design', workflow_step='design', brief='生成',
                input_data=node_input(project_id, target['id'], references=[old['id']]),
                run_async=True, request_id='first-attempt')
    first = runtime.enqueue(**args)
    # A definite pre-provider failure, not an unknown charged request.
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='failed' WHERE id=?", (first['id'],))
    canvas.update_node(project_id, target['id'], {'data':{'generating':False,'error':'preflight failed'}})
    retry = {**args, 'request_id':'explicit-retry',
             'input_data':node_input(project_id, target['id'], references=[new['id']])}
    second = runtime.enqueue(**retry)
    assert second['id'] != first['id']
    assert runtime.enqueue(**retry)['id'] == second['id']
    assert runtime.enqueue(**args)['id'] == first['id']
    with store._connect() as db:
        rows = db.execute('SELECT id,input_json FROM tasks').fetchall()
    assert len(rows) == 2
    saved = {row['id']:json.loads(row['input_json']) for row in rows}
    assert saved[first['id']]['canvasParams']['reference_node_ids'] == [old['id']]
    assert saved[second['id']]['canvasParams']['reference_node_ids'] == [new['id']]
    current = {node['id']:node for node in canvas.load(project_id)['nodes']}
    assert current[old['id']]['data'] == old['data']
    assert current[new['id']]['data'] == new['data']
    assert current[target['id']]['data']['taskId'] == second['id']
