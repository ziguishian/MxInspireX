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


def node_input(project_id, node_id, *, references=()):
    return {
        'taskSurface': 'canvas_node', 'canvasNodeId': node_id,
        'canvasParams': {'kind': 'image', 'canvasNodeId': node_id, 'reference_node_ids': list(references)},
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
