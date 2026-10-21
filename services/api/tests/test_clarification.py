import json

import pytest

from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='逐题补充', slug='clarification', brief='保持白鹭造型，设计海报', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'clarification')))
    tasks = TaskRuntime(store)
    monkeypatch.setattr(tasks, '_start_worker', lambda *args: False)
    return store, project, tasks


def enqueue(tasks, project_id, brief, input_data=None):
    return tasks.enqueue(project_id=project_id, agent_key='design', workflow_step='design', brief=brief, input_data=input_data or {}, run_async=True)


@pytest.mark.parametrize('brief',['介绍下自己','介绍一下自己','请介绍一下你自己','自我介绍一下','你能做什么？','你可以做什么？'])
def test_self_introduction_is_simple_conversation_but_attached_edits_are_not(brief):
    from app.task_policy import is_simple_conversation
    assert is_simple_conversation(brief)
    assert not is_simple_conversation(brief, {'referencedAssets':[{'id':'image'}]})
    assert not is_simple_conversation('介绍下自己的产品，并设计一个包装')


def test_clarification_continuation_preserves_original_references_and_node_contract(runtime):
    store, project, tasks = runtime
    original = {
        'referencedAssets': [{'id': 'white-crane', 'projectId': project['id']}],
        'referencedNodes': [{'id': 'poster-node', 'projectId': project['id']}],
        'referencedFiles': [{'filename': '品牌资料.pdf', 'pathRelative': 'knowledge/brand.pdf', 'projectId': project['id']}],
        'canvasParams': {'kind': 'image', 'canvasNodeId': 'poster-node', 'aspectRatio': '3:4'},
        'imageStyle': '宋韵',
        'textProvider': {'key': 'openai-compatible', 'model': 'old-model'},
    }
    source = enqueue(tasks, project['id'], '保持白鹭造型，设计一张海报', original)
    output = {'structured_data': {'clarification': {'questions': [{'id': 'audience', 'question': '主要面向谁？', 'options': ['亲子家庭']}]}}}
    with store._connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded', output_json=? WHERE id=?", (json.dumps(output), source['id']))
    reply = enqueue(tasks, project['id'], '主要面向谁？\n银发游客，保留舒适感', {
        'clarificationTaskId': source['id'],
        'referencedFiles': [{'filename': '不相关草稿.docx'}],
        'canvasParams': {}, 'imageStyle': '不相关的新草稿风格',
        'textProvider': {'key': 'openrouter', 'model': 'current-model'},
    })
    with store._connect() as connection:
        data = json.loads(connection.execute('SELECT input_json FROM tasks WHERE id=?', (reply['id'],)).fetchone()[0])
    for key in ('referencedAssets', 'referencedNodes', 'referencedFiles', 'canvasParams', 'imageStyle'):
        assert data[key] == original[key]
    assert data['deliveryContract'][0]['kind'] == 'image'
    assert data['userMessage'] == '主要面向谁？\n银发游客，保留舒适感'
    assert data['textProvider']['model'] == 'current-model'


@pytest.mark.parametrize('state,output', [('queued', {}), ('succeeded', {}), ('failed', {'structured_data': {'clarification': {'questions': [{}]}}})])
def test_clarification_cannot_resume_unfinished_or_non_question_task(runtime, state, output):
    store, project, tasks = runtime
    source = enqueue(tasks, project['id'], '原任务')
    with store._connect() as connection:
        connection.execute('UPDATE tasks SET status=?, output_json=? WHERE id=?', (state, json.dumps(output), source['id']))
    with pytest.raises(ValueError, match='提问不存在或尚未完成'):
        enqueue(tasks, project['id'], '补充', {'clarificationTaskId': source['id']})


def test_clarification_cannot_import_another_projects_task(runtime):
    store, project, tasks = runtime
    source = enqueue(tasks, project['id'], '原任务')
    with store._connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded', output_json=? WHERE id=?", (json.dumps({'structured_data': {'clarification': {'questions': [{}]}}}), source['id']))
    with pytest.raises(ValueError, match='提问不存在或尚未完成'):
        enqueue(tasks, 'another-project', '补充', {'clarificationTaskId': source['id']})


def test_skill_authoring_survives_clarification_without_generating_media(runtime):
    from app.task_policy import is_skill_management, is_skill_creation, execution_flow
    from app.design_tools import DesignToolRegistry, DesignToolError
    store, project, tasks = runtime
    source = enqueue(tasks, project['id'], '创建一个包装设计 Skill')
    with store._connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded', output_json=? WHERE id=?", (json.dumps({'structured_data': {'clarification': {'questions': [{'id': 'scope', 'question': '适用什么场景？', 'options': ['文旅包装']}]}}}), source['id']))
    reply = enqueue(tasks, project['id'], '文旅品牌全案，需要生成图片', {'clarificationTaskId': source['id']})
    with store._connect() as connection:
        data = json.loads(connection.execute('SELECT input_json FROM tasks WHERE id=?', (reply['id'],)).fetchone()[0])
    assert is_skill_management(data['userMessage'], data) and is_skill_creation(data['userMessage'], data)
    assert data['deliveryContract'] == []
    assert not data.get('designPlanning', {}).get('required')
    with pytest.raises(DesignToolError, match='只管理 Skill'):
        DesignToolRegistry(store).execute(project_id=project['id'], task_id=reply['id'], name='generate_image', arguments={'prompt': '不得调用'})
    unrelated = enqueue(tasks, project['id'], '制作一张图片', {'skillAuthoringIntent': 'create', 'skillCreationRequired': True})
    with store._connect() as connection:
        independent = json.loads(connection.execute('SELECT input_json FROM tasks WHERE id=?', (unrelated['id'],)).fetchone()[0])
    assert not is_skill_management(independent['userMessage'], independent)
