import json

import pytest

from app.design_planning import planning_profile, planning_guide
from app.design_tools import DesignToolRegistry
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime
from app.task_policy import execution_flow


@pytest.mark.parametrize('brief,profile', [
    ('设计一套文旅品牌视觉', 'brand'), ('为展厅做全案设计', 'comprehensive'),
    ('制作完整的博物馆设计方案', 'comprehensive'), ('Create a brand identity', 'brand'),
    ('品牌设计包含什么内容？', None), ('只修改品牌视觉里的 Logo 背景', None),
    ('把品牌标志的背景改为透明', None), ('生成一张白鹭图', None),
    ('每周提醒我检查品牌设计', None),
])
def test_planning_entry_keeps_focused_edits_and_questions_small(brief, profile):
    assert planning_profile(brief) == profile


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='设计规划', slug='planning', brief='设计一套品牌视觉', budget_minor=None, currency='CNY', root_path=str(tmp_path/'planning')))
    runtime = TaskRuntime(store)
    monkeypatch.setattr(runtime, '_start_worker', lambda *args: False)
    task = runtime.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief='设计一套品牌视觉。跳过参考', run_async=True)
    tools = DesignToolRegistry(store)
    return store, project, task, runtime, tools


def plan():
    return {'goal':'围绕白鹭角色建立文旅品牌视觉', 'preserve':['保留白鹭造型'],
        'deliverables':[
            {'id':'identity','title':'核心标志','kind':'image','acceptance':'保留白鹭形态，图形清晰'},
            {'id':'guide','title':'品牌使用手册','kind':'html','acceptance':'包含定位、标准色、字体层级、应用和使用边界'}],
        'coverage':[{'area':area['id'],'status':'included','detail':'纳入核心标志或使用手册'} for area in planning_guide('brand')['areas']],
        'deferred':['不制作视频和未经要求的包装'], 'openQuestions':[], 'research':'基础范围采用现有资料，无需新增联网搜索'}


def test_plan_required_before_any_generation_and_survives_restart(setup):
    store, project, task, runtime, tools = setup
    def call(name, **arguments): return tools.execute(project_id=project['id'],task_id=task['id'],name=name,arguments=arguments)
    blocked = call('generate_image', prompt='Logo')
    assert blocked['status'] == 'planning_required'
    assert tools.canvas_store.load(project['id'])['nodes'] == []
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tool_receipts').fetchone()[0] == 0
    incomplete = plan()
    incomplete['coverage'] = []
    assert call('design_plan', plan=incomplete)['status'] == 'invalid'
    waiting = plan()
    waiting['openQuestions'] = ['品牌名是什么？']
    assert call('design_plan', plan=waiting)['status'] == 'needs_clarification'
    assert call('canvas_create_text', text='不应提前生成')['status'] == 'planning_required'
    saved = call('design_plan', plan=plan())
    assert saved['status'] == 'ready'
    assert call('design_plan', plan=plan())['plan']['revision'] == saved['plan']['revision']
    restarted = DesignToolRegistry(store)
    assert restarted.execute(project_id=project['id'],task_id=task['id'],name='design_plan')['plan'] == saved['plan']
    generated = call('canvas_create_text', text='品牌定位说明')
    assert generated['node']['data']['text'] == '品牌定位说明'
    assert execution_flow('设计一套品牌视觉') == 'design'


def test_plan_resolves_selected_memory_key_to_backing_asset_id(setup):
    store, project, task, _, tools = setup
    with store._connect() as db:
        data = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task['id'],)).fetchone()[0])
        data['conversationMemory'] = {'selected': [{
            'id': 'memory-logo-id', 'key': 'expo-logo-input', 'assetId': 'actual-logo-asset'
        }]}
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task['id']))
    value = plan()
    value['deliverables'][0]['inputs'] = [{
        'source': 'asset', 'id': 'expo-logo-input', 'role': 'reference', 'purpose': '保留已选 Logo'
    }]
    saved = tools.execute(project_id=project['id'], task_id=task['id'], name='design_plan', arguments={'plan': value})
    assert saved['status'] == 'ready'
    assert saved['plan']['deliverables'][0]['inputs'][0]['id'] == 'actual-logo-asset'


@pytest.mark.parametrize(('message', 'expected_role'), [
    ('@asset:input-reference 参考这个 IP 形象风格，再设计一个男性角色', 'reference'),
    ('@asset:input-reference 按这张图保持相同版式，只替换角色', 'layout'),
])
def test_current_input_reference_only_becomes_layout_when_user_explicitly_requests_it(setup, message, expected_role):
    store, project, task, _, tools = setup
    with store._connect() as db:
        data = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task['id'],)).fetchone()[0])
        data.update(userMessage=message, referencedAssets=[{'id':'input-reference'}])
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task['id']))
    value = plan()
    value['deliverables'][0]['inputs'] = [{
        'source':'asset', 'id':'input-reference', 'role':'layout', 'purpose':'作为角色设计参考'
    }]
    saved = tools.execute(project_id=project['id'], task_id=task['id'], name='design_plan', arguments={'plan':value})
    assert saved['status'] == 'ready'
    assert saved['plan']['deliverables'][0]['inputs'][0]['role'] == expected_role


def test_delivery_receives_plan_and_flags_missing_formats_without_claiming_visual_pass(setup):
    store, project, task, runtime, tools = setup
    tools.execute(project_id=project['id'],task_id=task['id'],name='design_plan',arguments={'plan':plan()})
    tools.execute(project_id=project['id'],task_id=task['id'],name='canvas_create_text',arguments={'text':'只有一些说明'})
    report = tools.delivery_verify(project_id=project['id'],task_id=task['id'])
    assert report['designPlan']['goal'] == plan()['goal']
    assert report['passed'] is False
    assert any('核心标志' in issue for issue in report['issues'])
    assert any('品牌使用手册' in issue for issue in report['issues'])


def test_clarification_inherits_scope_but_not_unresolved_plan_or_old_task_actions(setup):
    store, project, task, runtime, tools = setup
    value = plan()
    value['openQuestions'] = ['品牌名是什么？']
    tools.execute(project_id=project['id'],task_id=task['id'],name='design_plan',arguments={'plan':value})
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded',output_json=? WHERE id=?",(json.dumps({'structured_data':{'clarification':{'questions':[{'question':'品牌名是什么？'}]}}}),task['id']))
    reply = runtime.enqueue(project_id=project['id'],agent_key='design',workflow_step='design',brief='品牌名是白鹭文旅',run_async=True,input_data={'clarificationTaskId':task['id']})
    context = tools._task_input(project['id'],reply['id'])
    assert context['designPlanning']['profile'] == 'brand'
    assert not context.get('designPlan')
    edit = runtime.enqueue(project_id=project['id'],agent_key='design',workflow_step='design',brief='只把品牌 Logo 的背景变透明',run_async=True)
    assert not tools._task_input(project['id'],edit['id']).get('designPlanning')
