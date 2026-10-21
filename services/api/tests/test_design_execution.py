import copy
import json
from pathlib import Path

import pytest

from app.assets import AssetStore
from app.design_state import read_state, record_decisions, continuation_request
from app.design_tools import DesignToolRegistry, DesignToolError
from app.design_planning import planning_guide
from app.main import new_project
from app.model_router import ModelRouter
from app.storage import ProjectStore
from app.task_policy import execution_flow, delivery_requirements
from app.task_runtime import TaskRuntime

BRIEF = '为即将在杭州举办首届历史经典产业博览会做一套政府伴手礼盒。外盒设计元素:历史经典标签+秋桂时令+和光同尘赴自在主题。礼盒色调用经博会六色，包含杭州主题纸雕笔记本、玉石发热中药枕、迷你茶叶陶罐、大漆玳瑁主人杯、茶罐丝绸套。预算13-15万'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect x="40" y="40" width="400" height="200" fill="none" stroke="black"/><text x="40" y="280">包装展开概念 · 尺寸待工程确认</text></svg>'


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='礼盒流程回归', slug='gift', brief=BRIEF, budget_minor=None, currency='CNY', root_path=str(tmp_path/'gift')))
    runtime = TaskRuntime(store)
    monkeypatch.setattr(runtime, '_start_worker', lambda *args: False)
    from app.providers.local import LocalImageProvider
    from types import SimpleNamespace
    tools = DesignToolRegistry(store, asset_store=AssetStore(store), provider_registry=SimpleNamespace(image=lambda *a, **kw: LocalImageProvider()))
    def enqueue(brief=BRIEF, **inputs):
        return runtime.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief=brief, input_data=inputs, run_async=True)['id']
    def call(task, name, **args): return tools.execute(project_id=project['id'], task_id=task, name=name, arguments=args)
    return store, project['id'], runtime, tools, enqueue, call


def plan():
    return {'goal': '完成杭州礼盒概念设计', 'preserve': ['五件内装', '13–15万元预算'],
            'deliverables': [{'id': 'outer', 'title': '外盒展开概念', 'kind': 'image', 'representation': 'raster', 'acceptance': '包含外盒展开面、折线及概念标注'},
                             {'id': 'inner', 'title': '内装编排', 'kind': 'image', 'acceptance': '五件指定内装分别可辨识'},
                             {'id': 'budget', 'title': '预算框架', 'kind': 'text', 'acceptance': '明确总预算及待核价项'}],
            'coverage': [{'area': a['id'], 'status': 'included', 'detail': '按礼盒需求覆盖'} for a in planning_guide('comprehensive')['areas']],
            'deferred': ['生产工程定稿待尺寸'], 'openQuestions': [], 'research': '暂不联网，使用用户资料'}


def finish(store, task, output):
    with store._connect() as db: db.execute("UPDATE tasks SET status='succeeded',output_json=? WHERE id=?", (json.dumps({'structured_data': output}), task))


def test_gift_intent_and_continuation_are_design_not_tagging(env):
    _, _, _, tools, enqueue, _ = env
    task = enqueue()
    assert tools._task_input(env[1], task)['designPlanning']['profile'] == 'comprehensive'
    assert execution_flow(BRIEF) == 'design'
    from app.model_catalog import ModelCatalog
    router = ModelRouter(ModelCatalog(env[0]), None)
    assert router.route(BRIEF, {}, {}).task_type == 'design'
    assert router.route('可以', {}, {'continuation': {'taskId': task}}).task_type == 'design'
    assert continuation_request('好的，你按照计划生成全部图像')
    assert continuation_request('好的')
    assert not continuation_request('换个需求，做一个海报')
    assert execution_flow('做完整的礼盒设计方案') == 'design'


def test_clarification_answers_survive_several_turns_and_do_not_create_fake_image_requirement(env):
    store, project, runtime, tools, enqueue, call = env
    first = enqueue()
    questions = [{'id': 'qty', 'question': '预计制作多少套？'}, {'id': 'who', 'question': '主要赠送对象是哪一类？'}, {'id': 'vi', 'question': '经博会六色是否已有官方色值？'}]
    finish(store, first, {'clarification': {'questions': questions}})
    second = enqueue('根据以下补充信息继续原设计任务。', clarificationTaskId=first,
                     clarificationAnswers=[{'questionId': q['id'], 'value': v, 'skipped': False} for q, v in zip(questions, ['1000套以上', '国内外贵宾/领导', '暂未提供'])])
    assert read_state(store, project, second)['decisions']['quantity']['value'] == '1000套以上'
    assert tools._task_input(project, second)['deliveryContract'] == []
    budget_question = {'id': 'cost', 'question': '13–15万元预算是否包含采购、外盒、运输、税费和设计？'}
    finish(store, second, {'clarification': {'questions': [budget_question]}})
    third = enqueue('预算全部包含', clarificationTaskId=second, clarificationAnswers=[{'questionId': 'cost', 'value': '全部包含'}])
    state = read_state(store, project, third)
    assert state['decisions']['budget_scope']['value'] == '全部包含'
    assert state['decisions']['quantity']['value'] == '1000套以上'
    question_result = call(third, 'request_clarification', questions=questions)
    assert not question_result['awaitingUser'] and len(question_result['answered']) == 3
    assert delivery_requirements('根据补充信息继续原设计任务，六色、标志暂无规范', tools._task_input(project, third)) == []
    assert runtime.get_task(project, third)['designState']['decisions']['audience']['value'] == '国内外贵宾/领导'


def test_latest_explicit_decision_wins_and_model_assumptions_cannot_override_it(env):
    store, project, _, _, enqueue, call = env
    first = enqueue('数量为300套')
    assert call(first, 'design_state', decisions=[{'field': 'quantity', 'value': '300套', 'status': 'confirmed', 'quote': '数量为300套'}])['status'] == 'recorded'
    second = enqueue('数量改为500套')
    assert read_state(store, project, second)['decisions']['quantity']['value'] == '300套'
    assert call(second, 'design_state', decisions=[{'field': 'quantity', 'value': '500套', 'status': 'confirmed', 'quote': '数量改为500套'}])['status'] == 'recorded'
    assert call(second, 'design_state', decisions=[{'field': 'quantity', 'value': '100套', 'status': 'assumed'}])['status'] == 'invalid'
    assert call(second, 'design_state', decisions=[{'field': 'quantity', 'value': '300套', 'status': 'confirmed', 'quote': '数量为300套', 'sourceTaskId': first}])['status'] == 'invalid'
    assert read_state(store, project, second)['decisions']['quantity']['value'] == '500套'
    assert call(second, 'design_state', decisions=[{'field': 'budget', 'value': '20万元', 'status': 'confirmed', 'quote': '用户同意20万元'}])['status'] == 'invalid'


def test_each_deliverable_is_bound_and_saved_outputs_are_not_generated_again(env):
    store, project, runtime, tools, enqueue, call = env
    task = enqueue(BRIEF + '。跳过参考')
    assert call(task, 'design_plan', plan=plan())['status'] == 'ready'
    assert call(task, 'generate_image', prompt='全部图') ['status'] == 'delivery_assignment_required'
    first = call(task, 'generate_image', prompt='外盒概念', provider='local-placeholder', deliverable_ids=['outer'])
    assert first['asset']['mime'] == 'image/png'
    report = call(task, 'delivery_verify')
    assert [d['status'] for d in report['deliverables']] == ['passed', 'pending', 'pending']
    again = call(task, 'generate_image', prompt='修改外盒概念', provider='local-placeholder', deliverable_ids=['outer'])
    assert again['reused'] and again['node']['id'] == first['node']['id']
    assert len(tools.asset_store.list_assets(project)) == 1
    call(task, 'canvas_create_text', text='预算13–15万元，采购报价待确认', deliverable_ids=['budget'])
    finish(store, task, {'designPlan': tools._task_input(project, task)['designPlan']})
    continued = enqueue('好的，你按照计划生成全部图像')
    context = tools._task_input(project, continued)
    assert context['planAccepted'] and len(context['designPlan']['deliverables']) == 2
    rows = call(continued, 'delivery_verify')['deliverables']
    assert [d['status'] for d in rows] == ['passed', 'pending']
    reduced = plan(); reduced['deliverables'] = reduced['deliverables'][:1]
    assert call(continued, 'design_plan', plan=reduced)['status'] == 'plan_reused'
    assert call(continued, 'design_plan', plan=reduced, change_reason='移除未完成项')['status'] == 'invalid'
    assert runtime.get_task(project, continued)['deliveryProgress'][1]['status'] == 'pending'


def test_missing_dimensions_only_block_dependent_engineering_item(env):
    _, _, _, _, enqueue, call = env
    task = enqueue(BRIEF + '。跳过参考'); value = plan(); value['deliverables'][0]['blockingFields'] = ['dimensions']
    assert call(task, 'design_plan', plan=value)['status'] == 'ready'
    assert call(task, 'generate_image', prompt='外盒概念', provider='local-placeholder', deliverable_ids=['outer'])['status'] == 'dependency_required'
    assert call(task, 'canvas_create_text', text='先给出概念预算与材质建议', deliverable_ids=['budget']).get('node')
    assert call(task, 'delivery_verify')['deliverables'][0]['status'] == 'blocked'


def test_explicit_image_request_cannot_be_removed_from_plan(env):
    _, _, _, _, enqueue, call = env
    task = enqueue('生成两张礼盒效果图')
    value = plan(); value['deliverables'] = value['deliverables'][2:]
    assert call(task, 'design_plan', plan=value)['status'] == 'invalid'


def test_continue_preserves_explicit_image_count_and_changes_can_amend_plan(env):
    store, project, _, tools, enqueue, call = env
    task = enqueue('生成两张礼盒效果图')
    value = plan(); value['deliverables'] = value['deliverables'][:1]
    assert call(task, 'design_plan', plan=value)['status'] == 'invalid'
    value['deliverables'] = plan()['deliverables'][:2]
    assert call(task, 'design_plan', plan=value)['status'] == 'ready'
    finish(store, task, {})
    continued = enqueue('好的')
    inputs = tools._task_input(project, continued)
    assert inputs['planAccepted'] and inputs['deliveryContract'][0]['count'] == 2
    changed = enqueue('按计划把外盒展开图改为三视图')
    inputs = tools._task_input(project, changed)
    assert inputs['planBaseline'] and not inputs['planAccepted']


def test_known_missing_vi_does_not_block_the_entire_plan_or_confirm_bundled_questions(env):
    store, _, _, _, enqueue, call = env
    task = enqueue()
    questions = [{'id':'mixed','question':'制作数量多少套，预算是否包含全部成本？'}, {'id':'vi','question':'是否有经博会六色色值？'}]
    finish(store, task, {'clarification':{'questions':questions}})
    next_task = enqueue('300套，暂无官方色值', clarificationTaskId=task, clarificationAnswers=[{'questionId':'mixed','value':'300套'},{'questionId':'vi','value':'暂无官方色值'}])
    value = plan(); value['openQuestions'] = ['经博会六色是否已提供？']
    assert call(next_task, 'design_plan', plan=value)['status'] == 'ready'
    result = call(next_task, 'request_clarification', questions=[{'id':'cost','question':'预算是否包含运输和税费？'}])
    assert result['awaitingUser']


def test_review_reuse_requires_passed_scope_and_unchanged_content(env):
    store, project, _, tools, enqueue, call = env
    task = enqueue('生成预算文字节点')
    value = plan(); value['deliverables'] = value['deliverables'][2:]
    value['deferred'] = []  # This fixture has no next batch to register.
    call(task, 'design_plan', plan=value)
    node = call(task, 'canvas_create_text', text='预算13–15万元，采购待核价', deliverable_ids=['budget'])['node']
    report = call(task, 'delivery_verify')
    assert report['passed']
    review = {'passed':True, 'checks':[{'category':'content','status':'passed','artifactId':node['id'],'planItemId':'budget','message':'预算与待核价范围完整'}]}
    finish(store, task, {'delivery':report,'review':review,'deliveryStatus':'passed'})
    continued = enqueue('继续')
    assert 'reviewCache' not in call(continued, 'delivery_verify')
    # A positive generic review with an incomplete overall delivery is not reusable.
    report['passed'] = False
    finish(store, task, {'delivery':report,'review':review,'deliveryStatus':'needs_review'})
    assert 'reviewCache' not in call(continued, 'delivery_verify')
    report['passed'] = True
    finish(store, task, {'delivery':report,'review':review,'deliveryStatus':'passed'})
    tools.canvas_store.update_node(project, node['id'], {'data':{'text':'预算改为25万元'}})
    assert 'reviewCache' not in call(continued, 'delivery_verify')
    tools.canvas_store.update_node(project, node['id'], {'data':{'text':'预算13–15万元，采购待核价'}})
    call(continued, 'design_state', decisions=[{'field':'material','value':'建议使用纸浆托','status':'assumed'}])
    assert 'reviewCache' not in call(continued, 'delivery_verify')


def test_new_user_instructions_invalidate_review_scope_even_before_an_edit(env):
    from app.design_state import review_request
    context = {'userMessage':'继续','continuation':{'taskId':'old'},'designState':{'goal':'生成礼盒图'}}
    assert review_request(context) == '生成礼盒图'
    context['userMessage'] = '按计划把盒子改成红色'
    assert review_request(context) == context['userMessage']


@pytest.mark.parametrize('mode', ['complete', 'clarify', 'unverified'])
def test_sdk_completes_missing_deliverables_in_execution_and_reports_honest_status(env, mode):
    import os
    import shutil
    import subprocess
    import sys
    store, project, _, tools, enqueue, _ = env
    task = enqueue('生成两张礼盒概念图')
    inputs = tools._task_input(project, task)
    value = plan(); value['deliverables'] = value['deliverables'][:2]
    value['deliverables'][1]['representation'] = 'raster'
    # This fixture intentionally finishes its second item in a later stage;
    # make its real dependency explicit instead of simulating serial independents.
    value['deliverables'][1]['dependsOn'] = [value['deliverables'][0]['id']]
    root = Path(__file__).resolve().parents[1]
    fixtures = Path(__file__).parent / 'fixtures'
    variables = {**os.environ,'PYTHONPATH':str(root),'FIXTURE_PYTHON':sys.executable,'FIXTURE_TOOL_SCRIPT':str(fixtures/'agent_tool_fixture.py'),
                 'FIXTURE_WORKSPACE':str(store.workspace_root),'FIXTURE_PROJECT':project,'FIXTURE_TASK':task,'FIXTURE_COMPLETION_MODE':mode,'FIXTURE_DESIGN_PLAN':json.dumps(value,ensure_ascii=False)}
    payload = {'api':'responses','apiKey':'test-fixture','model':'gpt-6-astra','baseUrl':'http://fixture.invalid/v1',
               'toolGateway':{'baseUrl':'http://fixture.invalid','projectId':project,'taskId':task},
               'context':{'projectId':project,'taskId':task,'brief':inputs['userMessage'],'constraints':{**inputs,'executionFlow':'design_review','allowExternalNetwork':False,'mediaProvider':{'image':{'key':'local-placeholder'}}}}}
    result = subprocess.run([shutil.which('node') or 'node','--import',(fixtures/'planned_delivery_transport.mjs').as_uri(),str(root/'app/openai_agent_worker.mjs')],input=json.dumps(payload),capture_output=True,text=True,env=variables,timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    final = next(json.loads(line)['result'] for line in result.stdout.splitlines() if line.startswith('{') and json.loads(line).get('type') == 'result')
    data = final['structured_data']
    assert len(tools.canvas_store.load(project)['nodes']) == (1 if mode == 'clarify' else 2)
    if mode == 'complete':
        assert data['deliveryStatus'] == 'passed'
        assert [d['status'] for d in data['delivery']['deliverables']] == ['passed','passed']
    elif mode == 'clarify':
        assert data['clarification']['awaitingUser']
        assert not data.get('review')
    else:
        assert data['deliveryStatus'] == 'passed'
        assert 'review' not in data
        assert not final.get('next_actions')


@pytest.mark.parametrize('svg', ['<svg><script>alert(1)</script></svg>', '<svg><image href="https://example.com/a.png"/></svg>', '<svg><rect onclick="alert(1)"/></svg>', '<!DOCTYPE svg [<!ENTITY x "danger">]><svg>&x;</svg>', '<svg><animateTransform attributeName="transform"/></svg>', '<svg xml:base="https://example.com/"><use href="#foreign"/></svg>'])
def test_vector_output_rejects_executable_or_remote_resources(env, svg):
    _, _, _, _, enqueue, call = env
    task = enqueue('画一个矩形')
    with pytest.raises(DesignToolError): call(task, 'canvas_create_svg', svg=svg)


def test_even_valid_vector_output_is_disabled(env):
    _, project, _, tools, enqueue, call = env
    with pytest.raises(DesignToolError, match='全局禁用'):
        call(enqueue('输出 SVG 矢量文件'), 'canvas_create_svg', svg=SVG)
    assert tools.asset_store.list_assets(project) == []


@pytest.mark.parametrize('answers', ['bad', [1]])
def test_malformed_structured_answers_are_rejected_without_losing_original_task(env, answers):
    store, _, _, _, enqueue, _ = env
    task = enqueue()
    finish(store, task, {'clarification':{'questions':[{'id':'qty','question':'多少套？'}]}})
    with pytest.raises(ValueError, match='结构化答案列表'):
        enqueue('继续', clarificationTaskId=task, clarificationAnswers=answers)
