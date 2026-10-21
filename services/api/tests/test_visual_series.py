import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.delivery import DeliveryService
from app.design_planning import save_design_plan
from app.design_tools import DesignToolRegistry
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA


def plan():
    return {'goal':'同版式六款角色卡，只替换名称和配色','preserve':['固定所有信息区位置和留白'],
            'deliverables':[{'id':f'role-{i}','title':f'角色卡{i}','kind':'image','acceptance':'角色名和配色正确、排版与母版一致'} for i in range(6)],
            'visualSeries':[{'id':'roles','masterId':'role-0','memberIds':[f'role-{i}' for i in range(6)],'size':'1024x1536',
                             'lockedLayout':['Logo 位于 x=15% y=12%，宽70%','标题框 y=42%，底部文字基线 y=90%，装饰固定右下角'],
                             'variableFields':['角色名称及英文译名','角色配色']}],
            'coverage':[],'deferred':[],'openQuestions':[],'research':'已有品牌参考足够'}


def analysis(asset_ids):
    return {'images':[{'asset_id':identity,'mode':'identity','visual_prompt':'绿色竖版卡片，固定信息区域和留白',
                      'use':'沿用已确认的卡片版式','preserve':'固定信息区的位置和比例'} for identity in asset_ids],
            'synthesis':'按角色内容替换名称和配色，保留套系排版关系'}


@pytest.fixture
def setup(tmp_path):
    store=ProjectStore(str(tmp_path))
    project=store.create_project(new_project(name='套系测试',slug='series',brief='',budget_minor=None,currency='CNY',root_path=str(tmp_path/'series')))['id']
    assets,canvas=AssetStore(store),CanvasStore(store)
    buffer=BytesIO();Image.new('RGB',(1024,1536),'#a8b980').save(buffer,format='PNG');content=buffer.getvalue()
    reference=assets.add_bytes(project_id=project,kind='image',filename='brand.png',content=content)
    reference=assets.get_asset(project_id=project,asset_id=reference['id'])
    inputs={'userMessage':'设计六款角色卡，同一排版，只变名称和配色','deliveryVerification':True,'referencedAssets':[{'id':reference['id']}]}
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES ('task',?,'design','design','running',?,'now','now')",(project,json.dumps(inputs)))
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        return content
    provider=SimpleNamespace(generate=generate,last_response={})
    registry=SimpleNamespace(image=lambda *a,**kw:provider)
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas,provider_registry=registry)
    def run(id, **extra):
        return tools.execute(project_id=project,task_id='task',name='generate_image',arguments={
            'prompt':'角色和颜色替换','output_mode':'create','source_asset_ids':[reference['id']],'deliverable_ids':[id],
            'model':'gpt-image-2.5-sunburst','params':{'size':'auto'},'reference_analysis':analysis([reference['id']]),**extra})
    return store,project,assets,canvas,reference,calls,run


@pytest.mark.parametrize('memory_enabled',[False,True])
def test_master_then_five_variants_share_actual_input_and_size_without_extra_outputs(setup,memory_enabled):
    store,project,assets,canvas,reference,calls,run=setup
    value=plan()
    for item in value['deliverables'][1:]:
        item['inputs']=[{'source':'deliverable','id':'role-0','role':'layout','purpose':'采用本轮先完成的版式'}]
    saved=save_design_plan(store,project,'task',value)['plan']
    if memory_enabled:
        from app.conversation_memory import ConversationMemoryService
        with store._connect() as db:
            data=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0]);data['memoryProtocol']=1
            db.execute("UPDATE tasks SET input_json=? WHERE id='task'",(json.dumps(data),))
        memory=ConversationMemoryService(store)
        memory.update(project,'task',{'expected_revision':memory.read(project,'task')['revision'],
                      'changes':[{'key':'asset:'+reference['id'],'assetId':reference['id'],'category':'asset','content':'品牌参考图','status':'observed','role':'input','source':{'taskId':'task'}}],
                      'selected_ids':['asset:'+reference['id']],
                      'references':[{'deliverable_id':'*','memory_ids':['asset:'+reference['id']]}]},'reference-choice')
    assert not saved['deliverables'][0]['dependsOn']
    assert all(item['dependsOn']==['role-0'] for item in saved['deliverables'][1:])
    assert run('role-1')['status']=='dependency_required'
    assert not calls
    master=run('role-0')
    assert calls[0]['size']=='672x1008' and 'aspectRatio' not in calls[0]
    master_path=assets.get_asset(project_id=project,asset_id=master['assetId'])['absolutePath']
    for i in range(1,6):
        analyzed=analysis([master['assetId'],reference['id']])
        variant=run(f'role-{i}',reference_analysis=analyzed)
        sent=calls[-1]
        assert sent['source_asset_paths'][0]==master_path
        assert Path(sent['source_asset_paths'][1]).name.endswith('brand.png')
        assert sent['size']=='672x1008' and 'aspectRatio' not in sent
        assert '底部文字基线 y=90%' in sent['prompt']
        assert '套系共同版式约束' not in sent['prompt'] and '接口参数' not in sent['prompt']
        snapshot=variant['asset']['metadata']['referenceSnapshot']
        assert snapshot['references'][0]['role']=='layout_master'
        assert {r['assetId'] for r in snapshot['references']}=={master['assetId'],reference['id']}
        assert run(f'role-{i}',reference_analysis=analyzed)['assetId']==variant['assetId']
    assert len(calls)==6 and len(canvas.load(project)['nodes'])==6
    report=DeliveryService(store,assets,canvas).inspect_task(project,'task')
    variants=[a for a in report['artifacts'] if a['assetId']!=master['assetId']]
    assert all(a['visualSeries']['masterAssetId']==master['assetId'] for a in variants)


def test_existing_template_allows_every_member_to_start_without_a_new_master(setup):
    store,project,assets,canvas,reference,calls,run=setup
    value=plan();value['visualSeries'][0].pop('masterId')
    value['visualSeries'][0]['masterAssetId']=reference['id']
    for item in value['deliverables']:
        item['inputs']=[{'source':'asset','id':reference['id'],'role':'layout','purpose':'共同复用用户已给定的版式'}]
    saved=save_design_plan(store,project,'task',value)['plan']
    assert all(not item['dependsOn'] for item in saved['deliverables'])
    for i in reversed(range(6)):
        result=run(f'role-{i}',source_asset_ids=[])
        assert result['status']=='succeeded'
        snapshot=result['asset']['metadata']['referenceSnapshot']
        assert snapshot['visualSeries']['masterAssetId']==reference['id']
        assert snapshot['inputBindings'][0]['source']=='asset'
        assert calls[-1]['source_asset_paths']==[reference['absolutePath']]
        assert run(f'role-{i}',source_asset_ids=[])['assetId']==result['assetId']
    assert len(calls)==len(canvas.load(project)['nodes'])==6


def test_legacy_plan_memory_key_resolves_during_generation_preflight(setup):
    store,project,_,_,reference,_,_=setup
    value=plan();value.pop('visualSeries')
    value['deliverables']=value['deliverables'][:1]
    value['deliverables'][0]['inputs']=[{'source':'asset','id':reference['id'],'role':'reference','purpose':'沿用品牌图'}]
    save_design_plan(store,project,'task',value)
    with store._connect() as db:
        data=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0])
        data['designPlan']['deliverables'][0]['inputs'][0]['id']='expo-key-visual-input'
        data['conversationMemory']={'selected':[{'id':'memory-visual-id','key':'expo-key-visual-input','assetId':reference['id']}]}
        db.execute("UPDATE tasks SET input_json=? WHERE id='task'",(json.dumps(data),))
    tools=DesignToolRegistry(store,asset_store=AssetStore(store),canvas_store=CanvasStore(store),provider_registry=SimpleNamespace(image=lambda *a,**kw:SimpleNamespace(api='images')))
    checked=tools.execute(project_id=project,task_id='task',name='generation_reference_check',arguments={'operations':[{
        'tool':'generate_image','arguments':{'prompt':'延展物料','deliverable_ids':['role-0'],'output_mode':'create'}
    }]})
    assert checked['status']=='ready',checked


def test_visual_relationship_and_review_baseline_never_imply_execution_dependency(setup):
    store,project,assets,canvas,reference,calls,run=setup
    saved=save_design_plan(store,project,'task',plan())['plan']
    assert saved['visualSeries'][0]['masterId']=='role-0'
    assert all(not item['dependsOn'] for item in saved['deliverables'])
    result=run('role-5')
    assert result['status']=='succeeded' and len(calls)==1
    assert calls[0]['source_asset_paths']==[reference['absolutePath']]
    assert result['asset']['metadata']['referenceSnapshot']['visualSeries']=={'id':'roles','layoutSize':'1024x1536','aspectRatio':'2:3'}


def test_existing_template_can_scale_to_planned_output_dimensions(setup):
    store,project,assets,canvas,reference,calls,run=setup
    value=plan();value['visualSeries'][0]['size']='1536x1024'
    value['deliverables'][1]['inputs']=[{'source':'asset','id':reference['id'],'role':'layout','purpose':'沿用模板布局并按输出规格缩放'}]
    save_design_plan(store,project,'task',value)
    run('role-1')
    assert calls[0]['size']=='1008x672' and calls[0]['source_asset_paths']==[reference['absolutePath']]


def test_explicit_layout_input_cannot_be_silently_dropped_as_inspiration(setup):
    store,project,_,_,reference,calls,run=setup
    value=plan()
    value['deliverables'][0]['inputs']=[{'source':'asset','id':reference['id'],'role':'layout','purpose':'保持已确认版式'}]
    save_design_plan(store,project,'task',value)
    described=analysis([reference['id']])
    described['images'][0]['mode']='inspiration'
    rejected=run('role-0',reference_analysis=described)
    assert rejected['status']=='reference_analysis_required' and not calls
    assert run('role-0')['status']=='succeeded' and len(calls)==1


def test_composer_style_reference_does_not_become_a_layout_lock(setup):
    store,project,_,_,reference,calls,run=setup
    with store._connect() as db:
        data=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0])
        data['userMessage']='参考这张图的 IP 风格，设计一个新的男性角色'
        db.execute("UPDATE tasks SET input_json=? WHERE id='task'",(json.dumps(data),))
    value=plan();value.pop('visualSeries');value['deliverables']=value['deliverables'][:1]
    value['deliverables'][0]['inputs']=[{'source':'asset','id':reference['id'],'role':'layout','purpose':'作为角色风格参考'}]
    saved=save_design_plan(store,project,'task',value)['plan']
    assert saved['deliverables'][0]['inputs'][0]['role']=='reference'
    described=analysis([reference['id']])
    described['images'][0].update(mode='inspiration',preserve='',use='只借鉴角色风格，不复用原排版')
    result=run('role-0',reference_analysis=described)
    assert result['status']=='succeeded' and len(calls)==1
    assert not calls[0].get('source_asset_paths')


@pytest.mark.parametrize('change', ['missing-master','overlap','cycle','mixed-kind','size'])
def test_rejects_invalid_series_before_generation(setup,change):
    store,project,*_=setup
    value=plan()
    if change=='missing-master':value['visualSeries'][0]['masterId']='absent'
    if change=='overlap':value['visualSeries'].append({**value['visualSeries'][0],'id':'other'})
    if change=='cycle':
        value['deliverables'][0]['inputs']=[{'source':'deliverable','id':'role-1','purpose':'等待前置'}]
        value['deliverables'][1]['dependsOn']=['role-0']
    if change=='mixed-kind':value['deliverables'][1]['kind']='text'
    if change=='size':value['visualSeries'][0]['size']='auto'
    with pytest.raises(ValueError):save_design_plan(store,project,'task',value)


def test_does_not_create_series_dependencies_for_independent_designs(setup):
    store,project,*_=setup
    value=plan();value.pop('visualSeries')
    saved=save_design_plan(store,project,'task',value)['plan']
    assert all(not item['dependsOn'] for item in saved['deliverables'])


def test_accepted_series_cannot_lose_layout_contract(setup):
    store,project,*_=setup
    saved=save_design_plan(store,project,'task',plan())['plan']
    with store._connect() as db:
        data=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0]);data['planAccepted']=True
        db.execute("UPDATE tasks SET input_json=? WHERE id='task'",(json.dumps(data),))
    value=plan();value.pop('visualSeries')
    with pytest.raises(ValueError,match='套系'):save_design_plan(store,project,'task',value)
    assert save_design_plan(store,project,'task',plan())['plan']['revision']==saved['revision']


def test_changed_layout_contract_invalidates_delivery_inventory(setup):
    store,project,assets,canvas,*_=setup
    with store._connect() as db:
        context=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0])
        context['executionPolicyVersion']=2
        db.execute("UPDATE tasks SET input_json=? WHERE id='task'",(json.dumps(context),))
    save_design_plan(store,project,'task',plan())
    service=DeliveryService(store,assets,canvas)
    previous=service.inspect_task(project,'task')['inspectionVersion']
    revised=plan();revised['visualSeries'][0]['lockedLayout'][0]='Logo 固定在 x=20% y=10%，宽60%'
    save_design_plan(store,project,'task',revised)
    assert service.inspect_task(project,'task')['inspectionVersion']!=previous


@pytest.mark.parametrize('source_id',['absent','role-1'])
def test_input_dependencies_reject_unknown_and_self_references(setup,source_id):
    store,project,*_=setup
    value=plan();value['deliverables'][1]['inputs']=[{'source':'deliverable','id':source_id,'purpose':'使用前置内容'}]
    with pytest.raises(ValueError,match='dependsOn'):save_design_plan(store,project,'task',value)


def test_legacy_accepted_series_survives_optional_schema_fields(setup):
    store,project,*_=setup
    value=plan()
    for item in value['deliverables'][1:]:item['dependsOn']=['role-0']
    save_design_plan(store,project,'task',value)
    with store._connect() as db:
        data=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0])
        data['planAccepted']=True
        for group in data['designPlan']['visualSeries']:group.pop('masterAssetId')
        for item in data['designPlan']['deliverables']:item.pop('inputs')
        db.execute("UPDATE tasks SET input_json=? WHERE id='task'",(json.dumps(data),))
    saved=save_design_plan(store,project,'task',value)['plan']
    assert all(item['dependsOn']==['role-0'] for item in saved['deliverables'][1:])


@pytest.mark.parametrize('ratio', [None, '16:10', '8:5'])
def test_openrouter_series_keeps_nonstandard_layout_ratio_through_preflight_and_dispatch(setup, monkeypatch, ratio):
    import base64
    from app.providers.openrouter_image import OpenRouterImageProvider
    from test_image_dispatch import Response, image_bytes
    from test_gpt_image_25_parameters import SUNBURST_ROUTER_PARAMETERS
    store, project, assets, canvas, reference, _, _ = setup
    value = plan()
    value['visualSeries'][0].update(size='1600x1000', masterId=None)
    save_design_plan(store, project, 'task', value)
    provider = OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', 'openai/gpt-image-2.5-sunburst',
        SimpleNamespace(get=lambda _: 'fixture-key'), supported_parameters=SUNBURST_ROUTER_PARAMETERS, supports_streaming=True)
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas,
        provider_registry=SimpleNamespace(image=lambda *a, **kw: provider))
    calls = []
    def dispatch(request, **kwargs):
        payload = json.loads(request.data)
        calls.append(payload)
        assert payload['size'] == '1024x640' and payload['quality'] == 'low'
        assert 'aspect_ratio' not in payload and 'resolution' not in payload
        assert payload['stream'] is False and len(payload['input_references']) == 1
        return Response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    args = {'prompt': '保持船舶套系版式', 'output_mode': 'create', 'source_asset_ids': [reference['id']],
        'deliverable_ids': ['role-0'], 'provider': 'openrouter', 'model': provider.model, 'quality': 'final',
        'params': {'aspect_ratio': ratio} if ratio else {}, 'reference_analysis': analysis([reference['id']])}
    checked = tools.execute(project_id=project, task_id='task', name='generation_reference_check',
        arguments={'operations': [{'tool': 'generate_image', 'arguments': args}]})
    assert checked['status'] == 'ready', checked
    assert checked['imageRequests'][0]['params']['size'] == '1024x640'
    assert not calls
    result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments=args)
    replay = tools.execute(project_id=project, task_id='task', name='generate_image', arguments=args)
    assert result['status'] == 'succeeded' and replay['assetId'] == result['assetId'] and len(calls) == 1
    layout = result['asset']['metadata']['referenceSnapshot']['visualSeries']
    assert layout['layoutSize'] == '1600x1000' and layout['aspectRatio'] == '8:5'


@pytest.mark.parametrize('implicit_item',[False,True])
def test_declaring_an_input_does_not_bypass_reference_scope(setup,implicit_item):
    store,project,assets,canvas,reference,calls,run=setup
    unrelated=assets.add_bytes(project_id=project,kind='image',filename='unrelated.png',content=Path(reference['absolutePath']).read_bytes())
    value=plan();value.pop('visualSeries')
    if implicit_item:value['deliverables']=value['deliverables'][1:2]
    target=next(item for item in value['deliverables'] if item['id']=='role-1')
    target['inputs']=[{'source':'asset','id':unrelated['id'],'role':'layout','purpose':'模型误选无关资料'}]
    save_design_plan(store,project,'task',value)
    rejected = run('role-1',deliverable_ids=None if implicit_item else ['role-1'],source_asset_ids=[])
    assert rejected['status'] == 'reference_mismatch' and '本轮引用' in rejected['instruction']
    assert not calls


def test_image_consumes_saved_text_and_image_only_from_its_actual_dependencies(setup):
    store,project,assets,canvas,reference,calls,run=setup
    value=plan();value.pop('visualSeries')
    value['deliverables']=[{'id':'copy','title':'定稿文案','kind':'text','acceptance':'包含确认的活动标题'},
        value['deliverables'][0],value['deliverables'][1],value['deliverables'][2]]
    value['deliverables'][2]['inputs']=[{'source':'deliverable','id':'copy','role':'content','purpose':'使用实际定稿文案'},
                                      {'source':'deliverable','id':'role-0','role':'reference','purpose':'使用已完成的产品图'}]
    save_design_plan(store,project,'task',value)
    assert run('role-1')['status']=='dependency_required'
    registry=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    text=registry.execute(project_id=project,task_id='task',name='canvas_create_text',arguments={'title':'定稿','text':'海风设计展 · 九月相见\n内部执行步骤：保存资产并回传交付报告。','deliverable_ids':['copy'],'output_mode':'create'})
    assert run('role-1')['status']=='dependency_required'
    parent=run('role-0')
    described=analysis([parent['assetId'],reference['id']])
    # The parent is now visible and can be analyzed before composing the child.
    checker=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas,provider_registry=SimpleNamespace(image=lambda *a,**kw:SimpleNamespace(api='images')))
    checked=checker.execute(project_id=project,task_id='task',name='generation_reference_check',arguments={'operations':[{
        'tool':'generate_image','arguments':{'prompt':'融合产品与定稿文案','source_asset_ids':[reference['id']],
            'deliverable_ids':['role-1'],'model':'gpt-image-2.5-sunburst','output_mode':'create','reference_analysis':described}}]})
    assert checked['status']=='ready',checked
    assert checked['imageRequests'][0]['providerInputAssetIds']==[parent['assetId'],reference['id']]
    visual_prompt='蓝绿色产品海报，产品居中，上方标题“海风设计展 · 九月相见”，底部留白。'
    child=run('role-1',prompt=visual_prompt,reference_analysis=described)  # Unrelated role-2 is still absent.
    assert child['status']=='succeeded' and len(calls)==2
    assert '海风设计展 · 九月相见' in calls[-1]['prompt']
    assert '内部执行步骤' not in calls[-1]['prompt'] and '回传交付报告' not in calls[-1]['prompt']
    assert calls[-1]['source_asset_paths'][0]==assets.get_asset(project_id=project,asset_id=parent['assetId'])['absolutePath']
    records=child['asset']['metadata']['referenceSnapshot']['inputBindings']
    assert records[0]['nodeIds']==[text['node']['id']]
    assert run('role-1',prompt=visual_prompt,reference_analysis=described)['assetId']==child['assetId'] and len(calls)==2
