import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.conversation_memory import ConversationMemoryService
from app.design_planning import planning_guide, VisualDirection
from app.reference_workflow import ReferenceWorkflow
from test_design_execution import BRIEF, env, finish

ROOT = Path(__file__).resolve().parents[1]


def gift_plan():
    names = ['礼盒外盒', '礼盒内装陈列', '杭州主题纸雕笔记本', '玉石发热中药枕', '迷你茶叶陶罐', '大漆玳瑁主人杯', '茶罐丝绸套']
    ids = ['box', 'display', 'notebook', 'pillow', 'tea', 'cup', 'silk']
    return {'goal':'杭州首届历史经典产业博览会七项礼盒视觉提案',
        'visualDirection':{'audience':'经博会政府礼赠嘉宾', 'theme':'和光同尘赴自在、历史经典与秋桂',
            'coreConcept':'以秋桂的轻盈联系杭州传统工艺，七件同属一个礼赠系统',
            'visualHierarchy':['主题文字优先，桂花纹样辅助，器物质感为主体'], 'formLanguage':['桂花疏密有序，几何边框克制'],
            'materialProcess':['纸雕层次、釉面反射、大漆纹理、玉石通透、丝绸光泽分别表达'],
            'colorRelationships':['创意六色：桂金、漆红、湖青、黛蓝、陶褐、米白；主次分明'],
            'compositionLighting':['暖白背景，柔和侧光，单品留白'], 'avoid':['未知尺寸角标','医疗功效宣传'],
            'evidence':[{'source':'user','use':'遵循指定五件礼品、主题与预算'}]},
        'preserve':['和光同尘赴自在、历史经典标签、秋桂时令', '预算13–15万元，100套以内', '创意六色不冒充官方色值'],
        'deliverables':[{'id':'gift-'+id, 'title':title, 'kind':'image', 'representation':'concept', 'acceptance':title+'独立成图，主题与系列色彩一致',
            'imageSpec':{'subjectStructure':title+'清晰可辨', 'formProportion':'主体占画面约三分之二',
                'materialConstruction':'纸材呈现细腻纤维；陶瓷、大漆、玉石和丝绸分别呈现真实材质特征',
                'compositionFraming':'暖白背景单品陈列，保留呼吸留白', 'lightSurface':'柔和侧光表现材质肌理',
                'avoid':['未知尺寸角标', '擅自宣称医疗功效']}} for id,title in zip(ids,names)],
        'coverage':[{'area':a['id'],'status':'included','detail':'按用户明确范围组织设计'} for a in planning_guide('comprehensive')['areas']],
        'deferred':['工程尺寸、工艺报价与正式色值待确认'], 'openQuestions':[], 'research':'按已有用户资料原创，不虚构外部事实'}


def continued_gift(env):
    store, project, _, tools, enqueue, call = env
    first=enqueue(BRIEF)
    finish(store,first,{'clarification':{'questions':[{'id':'qty','question':'预计制作多少套？'}]}})
    second=enqueue('根据以下补充信息继续原设计任务。数量100套以内；整套七项礼盒视觉提案。',
        clarificationTaskId=first, clarificationAnswers=[{'questionId':'qty','value':'100套以内','skipped':False}])
    saved=call(second,'design_plan',plan=gift_plan())
    assert saved['status']=='ready',saved
    import io
    from PIL import Image
    workflow = ReferenceWorkflow(store, tools.asset_store)
    image = io.BytesIO()
    Image.new('RGB', (64, 64), 'green').save(image, format='PNG')
    reference = workflow.library.add(image.getvalue(), 'reference.png')
    card=workflow.present(project,second,[reference])
    finish(store,second,{'referenceSelection':card})
    third=enqueue('跳过参考，继续原设计任务。',referenceSelection={'id':card['id'],'action':'skip'})
    current=tools._task_input(project,third)
    assert current['designPlan']==saved['plan']
    assert current['designPlan']['scopeId']==second
    assert current['designBatch']['intent']=='resume' and current['designBatch']['status']=='ready'
    assert current['designBatch']['itemIds']==[d['id'] for d in saved['plan']['deliverables']]
    assert current['designState']['decisions']['quantity']['value']=='100套以内'
    return third,saved['plan']


def run(env, task, api, mode, recovery=None):
    store, project, _, tools, _, _ = env
    # Exercise legacy malformed-plan recovery; policy-v2 hides ready plan tools
    # and is covered separately by test_execution_efficiency.py.
    constraints={**tools._task_input(project,task),'executionFlow':'design','agentCollaboration':True,'executionPolicyVersion':1}
    # An analyzed empty selection is saved locally for this fixture; the
    # production selection/reference preflight itself is not bypassed.
    memory=ConversationMemoryService(store)
    if recovery is None:
        memory.update(project,task,{'expected_revision':memory.read(project,task)['revision'],'changes':[],'selected_ids':[]},'fixture-select')
    payload={'apiKey':'fixture','model':'fixture','api':api,'baseUrl':'http://gift-fixture.invalid/v1',
        'maxOutputTokens':4096,
        'modelCapabilities':{'contextLength':128000},'persistentSessions':True,'recovery':recovery or {},'memory':memory.runtime(project,task),
        'toolGateway':{'baseUrl':'http://gift-fixture.invalid','projectId':project,'taskId':task},
        'context':{'projectId':project,'taskId':task,'brief':constraints['userMessage'],'constraints':constraints}}
    if mode.startswith('durable'):
        payload['executionStateVersion']=1
        payload['modelCapabilities']['strictTools']=True
        payload['toolGateway']['supportsAsyncImageJobs']=mode=='durable'
    if mode == 'upload_failed':
        payload['executionStateVersion']=1
    environment={**os.environ,'PYTHONPATH':str(ROOT),'FIXTURE_PYTHON':sys.executable,'FIXTURE_WORKSPACE':str(store.workspace_root),
        'FIXTURE_PROJECT':project,'FIXTURE_GIFT_MODE':mode,'FIXTURE_GIFT_PLAN':json.dumps(gift_plan(),ensure_ascii=False)}
    worker=os.environ.get('AICS_TEST_WORKER') or str(ROOT/'app/openai_agent_worker.mjs')
    try:
        process=subprocess.run([shutil.which('node'),'--import',(ROOT/'tests/fixtures/gift_plan_transport.mjs').resolve().as_uri(),worker],
            input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,env=environment,timeout=60)
    except subprocess.TimeoutExpired as error:
        (store.workspace_root/'worker-timeout.log').write_bytes((error.stdout or b'')+(error.stderr or b''))
        raise
    events=[json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    if process.returncode:
        errors = [{k: v for k, v in event.items() if k != 'recovery'} for event in events if event.get('type') == 'error']
        print(json.dumps(errors, ensure_ascii=False))
    return process,events


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_recorded_gift_failure_normalizes_labels_reuses_plan_and_dispatches_seven_images(env,api):
    task=env[4](BRIEF+'，本轮七张独立概念图片，100套，预算13–15万元。无需寻找外部参考，直接生成并审查。')
    process,events=run(env,task,api,'recorded_failure')
    assert process.returncode==0,process.stderr+process.stdout[-6000:]
    checkpoint=[e['recovery'] for e in events if e['type']=='checkpoint'][-1]
    assert checkpoint['responseCount']==5
    output=next(e['result'] for e in events if e['type']=='result')
    assert 'review' not in output['structured_data']
    plan=env[3]._task_input(env[1],task)['designPlan']
    assert plan['revision']==1
    assert [a['area'] for a in plan['coverage']]==['objectives','concept','system','visuals','delivery']
    recorded=json.loads((ROOT/'tests/fixtures/gift_failed_call_shapes.json').read_text(encoding='utf-8'))
    # Repeated malformed rewrites cannot silently change any accepted design.
    assert plan['goal']==recorded['labeledPlan']['plan']['goal']
    assert [d['imageSpec'] for d in plan['deliverables']]==[
        {**d['imageSpec'],'variationAxis':None} for d in recorded['labeledPlan']['plan']['deliverables']]
    assert len((env[0].workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines())==7
    nodes=env[3].canvas_store.load(env[1])['nodes']
    assert {tuple(n['data']['deliveryBinding']['itemIds']) for n in nodes if n.get('data',{}).get('assetId')}=={(d['id'],) for d in plan['deliverables']}
    assert sum(e.get('message')=='调用工具：delivery_snapshot' for e in events)==0
    assert not any(t['name']=='generate_batch' and t['output'].get('status')=='invalid_arguments' for t in checkpoint['toolOutputs'])


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_fresh_seven_item_task_has_room_for_detailed_plan_and_inherits_visual_direction(env,api):
    task=env[4](BRIEF+'。总预算13–15万元，制作100套。先完成概念视觉，具体尺寸、报价和正式色值后续确认。'
        '本轮七项，每项一张独立图片：1.礼盒外盒；2.开盒内装陈列；3.杭州纸雕笔记本；4.玉石发热中药枕；'
        '5.迷你茶叶陶罐；6.大漆玳瑁主人杯；7.茶罐丝绸套。无需寻找外部参考，直接生成并审查。')
    process,events=run(env,task,api,'long_plan')
    assert process.returncode==0,process.stderr+process.stdout[-4000:]
    assert [e['recovery'] for e in events if e['type']=='checkpoint'][-1]['responseCount']==4, process.stderr + process.stdout[-4000:]
    context=env[3]._task_input(env[1],task)
    saved=context['designPlan']
    assert context['referenceWorkflow']['status']=='skipped'
    assert saved['visualDirection']==VisualDirection.model_validate(context['designState']['brief']['visualDirection']).model_dump()
    assert len(saved['deliverables'])==7 and saved['revision']==1
    assert len((env[0].workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines())==7
    assert 'review' not in next(e['result'] for e in events if e['type']=='result')['structured_data']


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_seven_gift_items_resume_without_plan_rewrite_or_review(env,api):
    store, project, _, tools, _, _ = env
    task, plan=continued_gift(env)
    process,events=run(env,task,api,'resume')
    assert process.returncode==0,process.stderr+process.stdout[-5000:]
    result=next(e['result'] for e in events if e['type']=='result')
    assert 'review' not in result['structured_data']
    assert tools._task_input(project,task)['designPlan']==plan
    calls=[json.loads(line) for line in (store.workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(calls)==7 and len({c['prompt'] for c in calls})==7
    assert [e['recovery'] for e in events if e['type']=='checkpoint'][-1]['responseCount']==4
    assert sum(e.get('message')=='调用工具：delivery_snapshot' for e in events)==0
    # Re-observing or replaying the same generated items uses saved assets.
    nodes=tools.canvas_store.load(project)['nodes']
    assert len([n for n in nodes if n.get('data',{}).get('assetId')])==7
    assert {tuple(n['data']['deliveryBinding']['itemIds']) for n in nodes if n.get('data',{}).get('assetId')}=={(d['id'],) for d in plan['deliverables']}
    with store._connect() as db:
        receipts=db.execute("SELECT args,output FROM tool_receipts WHERE task_id=? AND name='generate_image'",(task,)).fetchall()
    assert len(receipts)==7
    with patch('app.providers.local.LocalImageProvider.generate',side_effect=AssertionError('saved images must never be charged again')):
        for receipt in receipts:
            replay=tools.execute(project_id=project,task_id=task,name='generate_image',arguments=json.loads(receipt['args']))
            assert replay['assetId']==json.loads(receipt['output'])['assetId']


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_upload_failure_is_not_reported_as_saved_or_successful(env,api):
    task=env[4](BRIEF)
    process,events=run(env,task,api,'upload_failed')
    assert process.returncode==0,process.stderr+process.stdout[-6000:]
    result=next(e['result'] for e in events if e['type']=='result')
    assert result['status']=='failed'
    assert '尚未提交生成请求' in result['structured_data']['answer']
    assert '作品已保存' not in result['structured_data']['answer']
    assert not result['artifact_refs']
    assert not (env[0].workspace_root/'provider-calls.jsonl').exists()


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_prerequisite_repair_does_not_count_old_failure_on_successful_turns(env,api):
    task=env[4](BRIEF)
    process,events=run(env,task,api,'prerequisite_recovery')
    assert process.returncode==0,process.stderr+process.stdout[-6000:]
    checkpoint=[e['recovery'] for e in events if e['type']=='checkpoint'][-1]
    assert checkpoint['responseCount']==5
    assert checkpoint['recoveryAttempts']['design']['total']==1
    assert len([t for t in checkpoint['toolOutputs'] if t['name']=='generate_image' and t['output'].get('status')=='succeeded'])==7


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('mode',['schema_stalled','json_stalled','design_spec_stalled'])
def test_invalid_arguments_stop_durably_without_paid_calls(env,api,mode):
    task=env[4]('生成一张海报，跳过参考' if mode == 'design_spec_stalled' else BRIEF)
    process,events=run(env,task,api,mode)
    assert process.returncode!=0
    error=next(e for e in reversed(events) if e['type']=='error')
    assert error['kind']=='tool',error
    assert error['submitted'] is False
    assert error['billingCertainty']=='not_applicable'
    assert error['recovery']['recoveryAttempts']['design']['total']==2
    assert error['recovery']['responseCount']==3
    if mode == 'design_spec_stalled':
        failures = [e for e in events if e.get('phase') == 'error' and '工具失败：generate_image' in e.get('message', '')]
        assert len(failures) == 3
        assert not any('工具完成：generate_image' in e.get('message', '') for e in events)
        assert all(t['output']['submitted'] is False for t in error['recovery']['toolOutputs'] if t['name'] == 'generate_image')
    assert not (env[0].workspace_root/'provider-calls.jsonl').exists()
    again,more=run(env,task,api,mode,recovery=error['recovery'])
    assert again.returncode!=0
    assert [e for e in more if e['type']=='error'][-1]['recovery']['responseCount']==3
    assert not (env[0].workspace_root/'provider-calls.jsonl').exists()


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_six_saved_images_two_late_results_one_unknown_charge_and_plan_reuse_finish_without_review(env,api):
    task,plan=continued_gift(env)
    process,events=run(env,task,api,'partial_late')
    assert process.returncode==0,process.stderr+process.stdout[-8000:]
    checkpoint=[e['recovery'] for e in events if e['type']=='checkpoint'][-1]
    assert checkpoint['responseCount']==2, process.stderr + json.dumps([(t['name'],t.get('args',{}).get('deliverable_ids'),t['output'].get('status'),t['output'].get('batchContext',{}).get('batch',{}).get('itemIds')) for t in checkpoint['toolOutputs']],ensure_ascii=False)
    assert not [e for e in events if e.get('phase')=='recovery_attempt']
    batch=next(t['output'] for t in checkpoint['toolOutputs'] if t['name']=='generate_batch')
    assert sum(r['status']=='succeeded' for r in batch['results'])==6
    assert next(r for r in batch['results'] if r['deliverable_ids']==['gift-tea'])['status']=='generation_unconfirmed'
    result=next(e['result'] for e in events if e['type']=='result')
    assert len([r for r in result['artifact_refs'] if r['entity_type']=='asset'])==6
    assert 'review' not in result['structured_data']
    assert result['structured_data']['deliveryStatus']=='needs_review'
    assert sum(e.get('message')=='调用工具：delivery_snapshot' for e in events)==0
    assert env[3]._task_input(env[1],task)['designPlan']==plan
    assert len((env[0].workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines())==7
    nodes=env[3].canvas_store.load(env[1])['nodes']
    assert len(nodes)==7 and sum(bool(n['data'].get('assetId')) for n in nodes)==6
    with env[0]._connect() as db:
        receipts=db.execute("SELECT status,args,output FROM tool_receipts WHERE task_id=? AND name='generate_image'",(task,)).fetchall()
    assert sum(r['status']=='running' for r in receipts)==1
    with patch('app.providers.local.LocalImageProvider.generate',side_effect=AssertionError('no duplicate charge')):
        for receipt in receipts:
            if receipt['status']=='completed':
                replay=env[3].execute(project_id=env[1],task_id=task,name='generate_image',arguments=json.loads(receipt['args']))
                assert replay['assetId']==json.loads(receipt['output'])['assetId']


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_misplaced_research_and_empty_plan_read_are_locally_normalized(env,api):
    task=env[4](BRIEF+'，跳过参考直接生成')
    process,events=run(env,task,api,'envelope')
    assert process.returncode==0,process.stderr+process.stdout[-5000:]
    assert not [e for e in events if e.get('phase')=='recovery_attempt']
    plan=env[3]._task_input(env[1],task)['designPlan']
    assert plan['revision']==1 and plan['research']==gift_plan()['research']
    assert len((env[0].workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines())==7


def test_explicit_plan_correction_keeps_validation_and_acceptance_boundaries(env):
    task,plan=continued_gift(env)
    call=env[-1]
    changed=copy.deepcopy(gift_plan());changed['deliverables'][0]['imageSpec']['lightSurface']='柔和左侧主光，保留纸材纤维'
    corrected=call(task,'design_plan',plan=changed,change_reason='明确侧光方向以增强纸材表现，保持原验收条件')
    assert corrected['status']=='ready',corrected
    assert corrected['plan']['deliverables'][0]['imageSpec']['lightSurface'].startswith('柔和左侧')
    changed['deliverables'][0]['acceptance']='随意生成'
    assert call(task,'design_plan',plan=changed,change_reason='修改验收')['status']=='invalid'
    assert env[3]._task_input(env[1],task)['designPlan']['deliverables'][0]['acceptance']==plan['deliverables'][0]['acceptance']


@pytest.mark.parametrize('message',['继续原设计任务','请接着当前方案','继续原设计任务，但预算改成10万元'])
def test_plain_continuation_reuses_plan_but_changed_requirements_do_not(env,message):
    store,project,_,tools,enqueue,call=env
    first=enqueue(BRIEF)
    original=call(first,'design_plan',plan=gift_plan())['plan']
    finish(store,first,{'answer':'原计划已保存'})
    second=enqueue(message)
    saved=tools._task_input(project,second)
    if '改成' in message:
        assert saved.get('planAccepted') is False
        assert not saved.get('designPlan')
    else:
        assert saved['designPlan']==original
        assert saved['designBatch']['intent']=='resume'


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('mode',['durable','durable_partial'])
def test_durable_gift_finishes_from_receipts_without_plan_rewrite_or_extra_summary_round(env,api,mode):
    if mode=='durable_partial':
        task,original=continued_gift(env)
    else:
        task=env[4](BRIEF+'。七项各一张独立概念图，跳过参考，直接生成并审查。')
        original=None
    process,events=run(env,task,api,mode)
    assert process.returncode==0,process.stderr+process.stdout[-9000:]
    checkpoint=[e['recovery'] for e in events if e['type']=='checkpoint'][-1]
    assert checkpoint['responseCount']==(1 if original else 3)
    assert not [e for e in events if e.get('phase')=='recovery_attempt']
    assert sum(e.get('message')=='调用工具：delivery_snapshot' for e in events)==0
    result=next(e['result'] for e in events if e['type']=='result')
    expected=6 if original else 7
    assert len([r for r in result['artifact_refs'] if r['entity_type']=='asset'])==expected
    assert 'review' not in result['structured_data']
    if original:
        assert result['structured_data']['deliveryStatus']=='needs_review'
        assert env[3]._task_input(env[1],task)['designPlan']==original
    assert len((env[0].workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines())==7
