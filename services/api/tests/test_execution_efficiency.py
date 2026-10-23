import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.parametrize('brief,count', [
    ('制作一张横版领养海报：保留第一张图的小狗身份与外观，沿用第二张海报的暖色插画风格和完整文案。必须结合这两张参考，只生成一张。', 1),
    ('参考两张图片生成一张海报', 1),
    ('把三张照片合成一张海报', 1),
    ('使用两张参考图，生成三张海报', 3),
    ('生成两张海报，第二张海报沿用第一张图的角色', 2),
    ('制作12张海报', 12),
    ('请生成这三张海报', 3),
])
def test_reference_quantities_and_ordinals_are_not_deliverable_counts(brief, count):
    from app.task_policy import delivery_contract
    assert next(item for item in delivery_contract(brief) if item['kind'] == 'image')['count'] == count

from app.task_policy import execution_flow, single_delivery_target
from app.delivery import DeliveryService
from app.conversation_memory import ConversationMemoryService
from app.task_inspection import performance_summary
from app.model_router import RouteTrace
from test_design_execution import env, finish

ROOT = Path(__file__).resolve().parents[1]


def clarified_bag(env, original='生成这个茶饮的外包装刀版图', answer='外带纸袋，按常见规格先做概念刀版'):
    source = env[4](original)
    finish(env[0], source, {'clarification': {'questions': [{'id': 'packaging', 'question': '包装类型和尺寸？'}]}})
    return env[4](answer, clarificationTaskId=source,
                  clarificationAnswers=[{'questionId': 'packaging', 'value': answer}])


def test_clarification_inherits_single_image_contract_without_repeating_quantity(env):
    task = clarified_bag(env)
    data = env[3]._task_input(env[1], task)
    assert data['continuation']
    assert data['singleDeliveryTarget'] == {'kind': 'image', 'count': 1, 'nodeId': None}


@pytest.mark.parametrize('brief', ['为这个肥皂盒设计一个包装', '设计一款落地灯', '换成更温润的造型', '设计两个包装'])
def test_unresolved_design_scope_requires_inventory_before_generation(env, brief):
    task = env[4](brief)
    data = env[3]._task_input(env[1], task)
    data['referenceWorkflow'] = {'status': 'skipped'}
    with env[0]._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task))
    result = env[5](task, 'generate_image', prompt='视觉概念')
    assert result['status'] == 'planning_required'
    assert result['submitted'] is False
    assert not env[3].canvas_store.load(env[1])['nodes']


@pytest.mark.parametrize('brief', ['为包装设计一个网站', '设计一个包装网站', '设计一个包装文案',
    '解释如何设计一个包装', '不需要设计一个包装', '设计一个包装 CAD 结构件'])
def test_packaging_mentions_do_not_invent_image_delivery(brief):
    from app.task_policy import delivery_contract
    assert not any(item['kind'] == 'image' for item in delivery_contract(brief))


def test_multiple_packaging_concepts_keep_quantity():
    from app.task_policy import delivery_contract
    brief = '设计两个包装'
    contract = delivery_contract(brief)
    assert contract == []  # Unknown nouns require an explicit inventory, never a guessed count.
    assert single_delivery_target(brief, {'deliveryContract': contract}) is None


@pytest.mark.parametrize('original,answer', [
    ('生成两张海报', '绿色'),
    ('生成一张海报和一张文字卡', '绿色'),
    ('生成一张海报', '生成一张海报并导出 ZIP'),
])
def test_clarification_does_not_short_circuit_additional_deliveries(env, original, answer):
    task = clarified_bag(env, original, answer)
    assert not env[3]._task_input(env[1], task).get('singleDeliveryTarget')


def test_single_image_receipt_survives_prompt_and_deliverable_id_changes(env):
    task = clarified_bag(env)
    executions = env[3].executions
    fingerprint, previous = executions.claim(task, 'generate_image', {'prompt': 'first'})
    assert previous is None
    result = {'status': 'succeeded', 'assetId': 'asset', 'node': {'id': 'node', 'data': {'assetId': 'asset'}}}
    executions.complete(task, fingerprint, result)
    from app.execution_store import ExecutionStore
    restarted = ExecutionStore(env[0])
    reused, previous = restarted.claim(task, 'generate_image', {'prompt': 'rewritten', 'deliverable_ids': ['bag-dieline']})
    assert reused == fingerprint and previous == result


@pytest.mark.parametrize('extra', [{'executionPolicyVersion': 1}])
def test_single_image_receipt_guard_preserves_plans_and_legacy_tasks(env, extra):
    task = clarified_bag(env)
    data = env[3]._task_input(env[1], task)
    data.update(extra)
    with env[0]._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task))
    executions = env[3].executions
    fingerprint, _ = executions.claim(task, 'generate_image', {'prompt': 'first'})
    executions.complete(task, fingerprint, {'status': 'succeeded', 'assetId': 'asset', 'node': {'id': 'node'}})
    next_fingerprint, previous = executions.claim(task, 'generate_image', {'prompt': 'second'})
    assert next_fingerprint != fingerprint and previous is None


def test_single_image_unconfirmed_request_cannot_be_reissued(env):
    task = clarified_bag(env)
    executions = env[3].executions
    executions.claim(task, 'generate_image', {'prompt': 'first'})
    with pytest.raises(RuntimeError, match='尚未确认|结果未知'):
        executions.claim(task, 'generate_image', {'prompt': 'rewritten', 'deliverable_ids': ['bag-dieline']})


@pytest.mark.parametrize('recovered',[False,True])
def test_real_runtime_entry_recognizes_empty_checkpoint(env,tmp_path,recovered):
    from types import SimpleNamespace
    from app.design_runtime import DesignRuntime
    from test_conversation_memory import picture
    store,project,_,tools,enqueue,_=env
    task=enqueue('生成一张海报')
    asset=picture(store,project=project,source='input-reference')
    data=tools._task_input(project,task)
    data['referencedAssets']=[{'id':asset['id']}]
    data['referenceWorkflow']={'status':'provided'}
    with store._connect() as db: db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(data),task))
    worker=tmp_path/'observe.mjs'
    worker.write_text("import fs from 'node:fs'; const p=JSON.parse(fs.readFileSync(0,'utf8')); console.log(JSON.stringify({type:'result',result:{status:'succeeded',structured_data:{mode:p.memory.analysisMode || null},provenance:{modelRequestCount:0}}}));",encoding='utf-8')
    registry=SimpleNamespace(credentials=SimpleNamespace(get=lambda _:'fixture'),billing=None,catalog=None,list=lambda:[])
    runtime=DesignRuntime(registry,worker_path=worker,runtime_root=tmp_path/'runs')
    runtime.executions=tools.executions
    if recovered: runtime.executions.save(task,{'responseCount':1})
    result=runtime.run(project_id=project,task_id=task,agent_key='design',workflow_step='design',brief='生成一张海报',
        constraints=data,retrieved_context=[],research_sources=[],prior_outputs=[],
        attachments=[{'assetId':asset['id'],'mime':'image/png','data':base64.b64encode(Path(asset['absolutePath']).read_bytes()).decode()}],
        provider_ref={'key':'fixture','model':'fixture','api':'chat_completions'})
    assert result.structured_data['mode']==(None if recovered else 'explicit_single_image')


@pytest.mark.parametrize('brief,independent', [
    ('不需要调研，生成一张海报', False), ('生成一张海报，参考最新趋势', False),
    ('联网核实这一个参数后生成一张海报', False), ('请输出一份竞品调研报告', True),
    ('先单独研究竞品，再设计海报', True), ('Please write a competitive research report', True),
    ('引用：“先独立调研”，生成一张海报', False), ('之前已经完成调研报告；现在生成一张海报', False),
    ('不用单独研究，直接做一张图', False), ('> 先研究竞品\n生成一张海报', False),
])
def test_research_routes_only_explicit_current_requests(brief, independent):
    assert (execution_flow(brief, {'executionPolicyVersion':2}) == 'research_design') == independent
    # Existing checkpoints retain their prior routing contract.
    assert execution_flow('不需要调研，生成一张海报') == 'research_design'


@pytest.mark.parametrize('brief', ['生成两张海报', '生成一张海报并导出 ZIP', '生成一张海报，然后分析它', '设计一套海报', '生成一张海报，并写一段介绍', 'Create one poster and write a description'])
def test_uncertain_or_additional_work_never_gets_single_completion(env, brief):
    task = env[4](brief)
    assert not env[3]._task_input(env[1],task).get('singleDeliveryTarget')


@pytest.mark.parametrize('brief', [
    '生成一张海报，并保留产品外观，另外背景用暖色。',
    '生成一张海报，然后把标题放在上方，同时保留底部留白。',
    'Create one poster and keep the product shape, also use a warm background.',
    '请直接生成一张图片并放到画布，使用默认创意档 1K，不需要联网研究、额外方案或导出。生成后做一次质量审查。',
    '生成一张咖啡海报，文案「一套生活方案」。请直接制作，放到画布。',
])
def test_single_artifact_keeps_fast_path_with_save_and_review_instructions(env, brief):
    task = env[4](brief)
    assert env[3]._task_input(env[1], task)['singleDeliveryTarget']['kind'] == 'image'


def test_concept_image_is_not_a_proposal_document(env):
    task = env[4]('生成一张方形品牌 Logo 方案图，只生成一张图，不做应用展开。')
    assert env[3]._task_input(env[1], task)['singleDeliveryTarget']['kind'] == 'image'


def test_cad_adjacent_to_chinese_still_requires_real_artifact():
    from app.task_policy import delivery_contract
    assert delivery_contract('直接创建一个参数化CAD底座，提供STEP/STL文件。') == [
        {'kind':'cad','count':1,'transparent':False}]


def test_policy_is_server_owned_and_request_replay_preserves_it(env):
    store, project, runtime, tools, _, _ = env
    args = dict(project_id=project,agent_key='design',workflow_step='design',brief='生成一张海报',run_async=True,
                request_id='stable',input_data={'executionPolicyVersion':99,'singleDeliveryTarget':{'kind':'text','count':1}})
    task = runtime.enqueue(**args)['id']
    saved = tools._task_input(project,task)
    assert saved['executionPolicyVersion'] == 3
    assert saved['singleDeliveryTarget']['kind'] == 'image'
    assert runtime.enqueue(**args)['id'] == task
    with store._connect() as db:
        saved.pop('executionPolicyVersion')
        db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(saved),task))
    assert runtime.enqueue(**args)['id'] == task
    assert 'executionPolicyVersion' not in tools._task_input(project,task)


def test_performance_uses_actual_responses_not_outer_route_or_duplicate_events(env):
    store = env[0]
    task = {'id':'metrics','trace':[]}
    assert performance_summary(store,task)['sdkRequests'] is None
    trace = RouteTrace(store)
    trace.append('metrics',{'call_kind':'main_agent','submitted':True,'inputTokens':99999})
    response = {'call_kind':'sdk_response','inputTokens':123,'outputTokens':45}
    trace.append('metrics',response,record_id='sdk:metrics:one')
    trace.append('metrics',response,record_id='sdk:metrics:one')
    for status in ['submitted','succeeded']:
        trace.append('metrics',{'call_kind':'image_generation','fingerprint':'one-image','model':'fixture','submitted':True,'status':status})
    task['output'] = {'provenance':{'performance':{'sdkRequests':1,'completedResponses':1,'stageMs':{'design':20,'review':10},'firstArtifactMs':15,'coverage':'full'}}}
    summary = performance_summary(store,task)
    assert summary['sdkRequests'] == 1 and summary['imageRequests'] == 1
    assert summary['inputTokens'] == 123 and summary['outputTokens'] == 45
    assert 'reviewMs' not in summary and summary['firstArtifactMs'] == 15


def test_phase_timings_deduplicate_attempts_and_preserve_unknown(env):
    store=env[0]
    trace=RouteTrace(store)
    task={'id':'timings','output':{'provenance':{'performance':{'contextPreparationMs':4}}}}
    trace.append('timings',{'call_kind':'runtime_timing','phase':'contextPreparationMs','latency_ms':8})
    for status in ('submitted','succeeded'):
        trace.append('timings',{'call_kind':'image_generation','fingerprint':'image','provider':'evolink','model':'fixture',
            'status':status,'submitted':True,'timingMs':{'referenceUploadMs':20,'providerWaitMs':100},'referenceUploadCacheHits':1})
    result=performance_summary(store,task)
    assert result['timingMs']['contextPreparationMs'] == 12
    assert result['timingMs']['referenceUploadMs'] == 20
    assert result['timingMs']['observedProcessingMs'] is None
    assert result['referenceUploadCacheHits'] == 1
    assert result['imageRequests'] == 1


@pytest.mark.parametrize('change', ['text','scope','reference','late','file','preview'])
def test_local_inspection_cache_reuses_only_unchanged_evidence(env, change):
    store, project, _, tools, enqueue, call = env
    task = enqueue('生成一张海报，不需要参考')
    ConversationMemoryService(store).prepare_empty_selection(project,task)
    result = call(task,'generate_image',prompt='简约蓝色海报')
    service = DeliveryService(store,tools.asset_store,tools.canvas_store)
    with patch.object(service,'_inspect_task',wraps=service._inspect_task) as inspect:
        first = service.inspect_task(project,task)
        assert first['passed'], first
        service.inspect_task(project,task)
        assert inspect.call_count == 1
        if change == 'text':
            tools.canvas_store.update_node(project,result['node']['id'],{'data':{'productionNotes':['新的制作要求']}})
        elif change in {'scope','reference'}:
            inputs = tools._task_input(project,task)
            inputs['userMessage' if change == 'scope' else 'referencedAssets'] = '生成两张海报' if change == 'scope' else [{'id':'new-reference'}]
            with store._connect() as db: db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(inputs),task))
        elif change == 'late':
            tools.canvas_store.create_node(project,kind='text',title='迟到产物',data={'text':'新增文字'},task_id=task)
        elif change == 'file':
            asset = tools.asset_store.get_asset(project_id=project,asset_id=result['assetId'])
            Path(asset['absolutePath']).write_bytes(b'corrupted')
        else:
            node = result['node']
            service.record_check(project,node['id'],service.fingerprint(node),{'passed':True,'errors':[]})
        second = service.inspect_task(project,task)
        assert inspect.call_count == 2
        assert second['inspectionVersion'] != first['inspectionVersion']


@pytest.mark.parametrize('api', ['responses','chat_completions'])
@pytest.mark.parametrize('kind,mode', [('image','normal'),('image','packaging'),('image','clarification'),('text','normal'),('html','normal'),('image','steering'),('image','reference'),('image','planned'),('image','plan_creation'),('image','access_rejected'),('image','image_input'),('image','image_local'),('image','image_edit'),('image','image_multi'),('image','product_identity'),('image','selection_planned')])
def test_generation_finishes_without_review_or_wrap_up_call(env, api, kind, mode):
    store, project, _, tools, enqueue, _ = env
    brief = {'image':'生成一张海报，不需要参考', 'text':'创建一个文本节点', 'html':'创建一个 HTML 网页，不需要参考'}[kind]
    if mode == 'packaging':
        brief = '为这个肥皂盒设计一个包装'
    if mode == 'plan_creation':
        brief = '为咖啡品牌制作海报概念图，并把品牌应用清单作为文本节点保存在画布。本轮包含图像和文字两项交付，不需要参考。'
    if mode == 'product_identity':
        from test_product_identity import BRIEF
        brief = BRIEF
    if mode == 'clarification':
        brief = '外带纸袋，按常见规格先做概念刀版'
        task = clarified_bag(env, answer=brief)
    else:
        task = enqueue(brief)
    if mode == 'packaging':
        data = tools._task_input(project, task)
        data['referenceWorkflow'] = {'status': 'provided'}
        with store._connect() as db:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task))
    attachments = []
    asset = None
    if mode in {'image_input','image_local','image_edit','image_multi'}:
        from test_conversation_memory import picture
        asset = picture(store, project=project, source='input-reference')
        data = tools._task_input(project,task)
        data.update(memoryProtocol=1,referencedAssets=[{'id':asset['id'],'projectId':project}],referenceWorkflow={'status':'provided'})
        with store._connect() as db:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(data),task))
        attachments = [{'assetId':asset['id'],'projectId':project,'mime':'image/png',
                        'data':base64.b64encode(Path(asset['absolutePath']).read_bytes()).decode()}]
        if mode == 'image_edit':
            brief = '把这张图片的背景改成米色，生成一张图，保持主体不变'
            data['userMessage'] = brief
        if mode == 'image_multi':
            second = picture(store, name='second', project=project, source='input-reference')
            data['referencedAssets'].append({'id':second['id'],'projectId':project})
            attachments.append({'assetId':second['id'],'projectId':project,'mime':'image/png',
                'data':base64.b64encode(Path(second['absolutePath']).read_bytes()).decode()})
        with store._connect() as db:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(data),task))
    fixture_plan = {'goal':'一张海报和应用清单', 'research':'使用已有需求，无需研究',
        'preserve':[], 'coverage':[], 'deferred':[], 'openQuestions':[], 'deliverables':[
            {'id':'poster','title':'主海报','kind':'image','acceptance':'简约蓝色主题'},
            {'id':'list','title':'品牌应用清单','kind':'text','acceptance':'已交付、后续、选配分组'}],
        'currentItemIds':['poster','list']}
    if mode == 'packaging':
        fixture_plan['deliverables'] = fixture_plan['deliverables'][:1]
        fixture_plan['currentItemIds'] = ['poster']
        fixture_plan['goal'] = '为当前产品设计一个包装概念'
    if mode == 'product_identity':
        from test_mixed_delivery_scope import PLAN
        fixture_plan = PLAN
    if mode in {'planned','access_rejected','selection_planned'}:
        saved = tools.design_plan(project_id=project, task_id=task, plan=fixture_plan)
        assert saved['status'] == 'ready', saved
    constraints = tools._task_input(project,task)
    if mode == 'selection_planned':
        constraints['memoryProtocol']=1
        with store._connect() as db:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(constraints),task))
    if mode not in {'plan_creation','product_identity','packaging'}:
        assert constraints['singleDeliveryTarget']['kind'] == kind
    memory = ConversationMemoryService(store)
    memory.prepare_empty_selection(project,task)
    if mode in {'image_local','image_edit','image_multi'}:
        memory.prepare_single_image_selection(project,task,attachments,constraints)
    payload = {'apiKey':'fixture','model':'fixture','api':api,'baseUrl':'http://efficiency.invalid/v1','executionStateVersion':1,
        'memory':memory.runtime(project,task,images=True),
        'toolGateway':{'baseUrl':'http://efficiency.invalid','projectId':project,'taskId':task,'supportsTaskUpdates':mode=='steering'},
        'context':{'projectId':project,'taskId':task,'brief':brief,'attachments':attachments,'constraints':{**constraints,'executionFlow':'design_review'}}}
    environment = {**os.environ,'PYTHONPATH':str(ROOT),'FIXTURE_PYTHON':sys.executable,'FIXTURE_WORKSPACE':str(store.workspace_root),
        'FIXTURE_PROJECT':project,'FIXTURE_KIND':kind,'FIXTURE_MODE':mode,'FIXTURE_HTML_PREVIEW':'1','FIXTURE_PLAN':json.dumps(fixture_plan)}
    if asset:
        environment.update(FIXTURE_REFERENCE=asset['id'],FIXTURE_MEMORY_REVISION=str(payload['memory']['revision']))
    if mode == 'selection_planned': environment['FIXTURE_MEMORY_REVISION']=str(payload['memory']['revision'])
    if mode == 'image_multi': environment['FIXTURE_SECOND_REFERENCE'] = second['id']
    if mode == 'access_rejected':
        environment['FIXTURE_ACCESS_FAILURE'] = '1'
    process = subprocess.run([shutil.which('node'),'--import',(ROOT/'tests/fixtures/efficiency_transport.mjs').as_uri(),str(ROOT/'app/openai_agent_worker.mjs')],
        input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,env=environment,timeout=45)
    events = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    assert process.returncode == 0, process.stderr + process.stdout[-2500:]
    result = next(e['result'] for e in events if e['type']=='result')
    if mode == 'reference':
        assert result['provenance']['performance']['sdkRequests'] == 1
        assert result['structured_data']['referenceSelection']['status'] == 'pending'
        assert 'deliveryStatus' not in result['structured_data']
        assert not result['structured_data'].get('review')
        assert not tools.canvas_store.load(project)['nodes']
        return
    expected_calls = 3 if mode in {'product_identity','packaging'} else 2 if mode in {'steering','plan_creation','image_input','image_multi','selection_planned'} else 1
    assert result['provenance']['modelRequestCount'] == expected_calls, process.stderr
    assert result['provenance']['performance']['sdkRequests'] == expected_calls
    assert not result['provenance']['awaitingDelivery']
    assert 'review' not in result['structured_data']
    assert not any('review' in stage for stage in result['provenance']['stages'])
    assert not any(item['name'] == 'delivery_snapshot' for item in result['tool_outputs'])
    if mode in {'image_input','image_local','image_edit','image_multi'}:
        names = [item['name'] for item in result['tool_outputs']]
        assert names.count('conversation_memory_update') == (0 if mode in {'image_local','image_edit'} else 1)
        assert names.count('generate_image') == 1
        assert not {'design_plan','design_state','generate_batch','conversation_memory_read'}.intersection(names)
        assert not any(item['output'].get('status') == 'memory_required' for item in result['tool_outputs'])
    assert result['structured_data']['deliveryStatus'] == ('needs_review' if mode == 'access_rejected' else 'passed')
    if mode == 'normal':
        assert result['structured_data']['answer'] == '作品已保存到右侧画布。'
    assert len(tools.canvas_store.load(project)['nodes']) == (3 if mode == 'product_identity' else 2 if mode in {'planned','plan_creation','selection_planned'} else 1)
    if mode == 'selection_planned':
        assert not any(t['output'].get('status')=='memory_required' for t in result['tool_outputs'])
    assert not any(item['name']=='generate_text' for item in result['tool_outputs'])
    if mode == 'access_rejected':
        failures = [item for item in result['tool_outputs'] if item['name'] == 'generate_image']
        assert len(failures) == 1 and failures[0]['output']['stopTool']
        assert not (store.workspace_root/'provider-calls.jsonl').exists()
        return
    if kind == 'image':
        assert len((store.workspace_root/'provider-calls.jsonl').read_text().splitlines()) == (2 if mode == 'product_identity' else 1)
    if mode == 'product_identity':
        generated = [item['output'] for item in result['tool_outputs'] if item['name']=='generate_image']
        assert len(generated) == 2
        source, scene = generated
        snapshot = scene['asset']['metadata']['referenceSnapshot']
        assert snapshot['providerInputAssetIds'] == [source['assetId']]
        assert snapshot['inputBindings'][0]['role'] == 'identity'
        assert snapshot['analysis']['images'][0]['mode'] in {'identity','edit'}
