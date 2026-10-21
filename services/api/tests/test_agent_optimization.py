import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from test_delivery_contract import workspace, task
from app.design_tools import DesignToolRegistry
from app.delivery import DeliveryService
from app.model_catalog import ModelCatalog
from app.model_config import ModelPrice
from app.budget import BudgetService
from app.schedules import ScheduleService
from app.task_policy import delivery_contract, delivery_requirements, execution_flow
from app.media_editing import run_media


def registry(workspace):
    store,project,assets,canvas=workspace
    return DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)


def image_asset(workspace):
    data=io.BytesIO();Image.new('RGBA',(128,96),(20,160,50,120)).save(data,format='PNG')
    return workspace[2].add_bytes(project_id=workspace[1],kind='image',filename='source.png',content=data.getvalue())


def test_background_queue_claims_all_projects_and_recovers_expired_leases(workspace):
    store,project,assets,canvas=workspace
    task(store,project,context={'deliveryVerification':True})
    one=canvas.create_node(project,kind='html',title='未打开的项目',data={'html':'<h1>等待</h1>'},task_id='task')
    service=DeliveryService(store)
    jobs=service.claim_previews();assert jobs[0]['nodeId']==one['id']
    assert service.claim_previews()==[]
    with store._connect() as db:db.execute('UPDATE delivery_leases SET expires=0')
    assert service.claim_previews()[0]['fingerprint']==jobs[0]['fingerprint']
    service.record_check(project,one['id'],jobs[0]['fingerprint'],{'passed':True})
    assert service.claim_previews()==[]


def test_contract_checks_count_size_format_and_alpha(workspace):
    store,project,assets,canvas=workspace
    brief='生成 3 张透明背景海报，128×96 PNG'
    contract=delivery_contract(brief);assert contract[0]['count']==3
    task(store,project,context={'userMessage':brief})
    for _ in range(2): canvas.ensure_asset_node(project,image_asset(workspace),task_id='task')
    service=DeliveryService(store);result=service.inspect_task(project,'task')
    assert any('数量不足' in issue for issue in result['issues'])
    # A reused identical asset ID is one deliverable, never counted twice.
    assert result['contract'][0]['transparent']
    assert all(item['imageInfo']['width']==128 for item in result['artifacts'])


def test_version_restore_preserves_other_nodes_and_survives_restart(workspace):
    store,project,assets,canvas=workspace;task(store,project)
    tools=registry(workspace)
    node=tools.execute(project_id=project,task_id='task',name='canvas_create_html',arguments={'html':'<h1>第一版</h1>'})['node']
    version=canvas.versions(project,node['id'])[0]['id']
    other=canvas.create_node(project,kind='text',title='保留',data={'text':'其他节点'})
    canvas.update_node(project,node['id'],{'data':{'html':'<h1>第二版</h1>','extra':'应删除'}})
    tools=registry(workspace)
    result=tools.execute(project_id=project,task_id='task',name='canvas_restore_node',arguments={'node_id':node['id'],'version_id':version})
    assert result['node']['data']['html']=='<h1>第一版</h1>' and 'extra' not in result['node']['data']
    assert next(n for n in canvas.load(project)['nodes'] if n['id']==other['id'])==other


@pytest.mark.parametrize('format',['html','pdf','pptx','zip'])
def test_export_real_canvas_without_report_agent(workspace,format):
    store,project,assets,canvas=workspace;task(store,project)
    tools=registry(workspace)
    text=canvas.create_node(project,kind='text',title='设计方案',data={'text':'实际设计说明，保留引用图片。'},task_id='task')
    image=canvas.ensure_asset_node(project,image_asset(workspace),task_id='task')
    result=tools.execute(project_id=project,task_id='task',name='export_deliverable',arguments={'format':format,'title':'交付','node_ids':[text['id'],image['id']]})
    path=Path(assets.get_asset(project_id=project,asset_id=result['assetId'])['absolutePath']);assert path.stat().st_size>100
    if format=='pdf':
        from pypdf import PdfReader
        assert len(PdfReader(path).pages)==2
    elif format=='pptx':
        from pptx import Presentation
        assert len(Presentation(path).slides)==2
    elif format=='zip':
        with zipfile.ZipFile(path) as archive: assert 'manifest.json' in archive.namelist() and any(n.startswith('assets/') for n in archive.namelist())
    assert result['node']['data']['downloadable']


def test_schedule_tools_are_idempotent_and_project_scoped(workspace):
    store,project,assets,canvas=workspace
    task(store,project,context={'userMessage':'每天九点提醒我','textProvider':{'key':'openrouter','baseUrl':'https://example.test/v1','model':'test'}})
    tools=registry(workspace);tools.schedule_service=ScheduleService(store,None,None)
    args={'schedules':[{'title':'提醒','prompt':'检查交付','mode':'reminder','timing':{'kind':'daily','timezone':'Asia/Shanghai','time':'09:00'}}]}
    one=tools.execute(project_id=project,task_id='task',name='schedule_create',arguments=args)
    two=tools.execute(project_id=project,task_id='task',name='schedule_create',arguments=args)
    assert one==two and len(tools.schedule_service.list())==1
    schedule=one['schedules'][0]
    result=tools.execute(project_id=project,task_id='task',name='schedule_update',arguments={'schedule_id':schedule['id'],'status':'paused'})
    assert result['schedule']['status']=='paused'


def test_budget_blocks_unknown_and_excess_and_settles_reservations(workspace):
    store,project,*_=workspace;task(store,project)
    catalog=ModelCatalog(store);settings=catalog.settings();settings.taskBudgetPoints=100
    settings.prices[catalog.price_key('openrouter','https://test','known')]=ModelPrice(currency='CNY',perRequest=.6)
    catalog.save_settings(settings);budget=BudgetService(store,catalog)
    with pytest.raises(Exception,match='缺少价格'): budget.reserve('task',provider='openrouter',base_url='https://test',model='unknown',kind='text')
    first=budget.reserve('task',provider='openrouter',base_url='https://test',model='known',kind='text')
    with pytest.raises(Exception,match='预算'): budget.reserve('task',provider='openrouter',base_url='https://test',model='known',kind='text')
    budget.settle('task',first['reservationId'],20)
    assert budget.reserve('task',provider='openrouter',base_url='https://test',model='known',kind='text')['estimatedPoints']==60


def test_video_budget_settles_after_async_completion_without_new_reservation(workspace):
    from types import SimpleNamespace
    from app.billing import BillingService, MeteredProvider, billing_scope
    store,project,*_=workspace;task(store,project)
    catalog=ModelCatalog(store);settings=catalog.settings();settings.taskBudgetPoints=100
    settings.prices[catalog.price_key('openrouter','https://test','video')]=ModelPrice(currency='CNY',perSecond=.1);catalog.save_settings(settings)
    adapter=SimpleNamespace(provider_key='openrouter',base_url='https://test',model='video',last_response={})
    adapter.generate=lambda **kwargs:{'jobId':'job','status':'running'}
    def retrieve(**kwargs):
        adapter.last_response={'duration':3}
        return {'jobId':'job','status':'succeeded'}
    adapter.retrieve=retrieve
    provider=MeteredProvider(adapter,BillingService(store,catalog),'video')
    with billing_scope(task_id='task',project_id=project):provider.generate(duration=8)
    with store._connect() as db: reservation=db.execute('SELECT points,status FROM budget_reservations').fetchone()
    assert tuple(reservation)==(80,'reserved')
    # Polling is permitted even when the task's remaining budget is exhausted.
    provider.retrieve(job_id='job')
    provider.retrieve(job_id='job')
    with store._connect() as db: reservations=db.execute('SELECT points,status FROM budget_reservations').fetchall()
    assert len(reservations)==1 and tuple(reservations[0])==(30,'settled')


@pytest.mark.parametrize('operation,params',[('crop',{'x':0,'y':0,'width':64,'height':64}),('resize',{'width':32,'height':24}),('extend',{'width':256,'height':192}),('convert',{'format':'webp'})])
def test_image_edit_preserves_source(workspace,operation,params):
    store,project,_,canvas=workspace;task(store,project);asset=image_asset(workspace)
    original_node=canvas.ensure_asset_node(project,asset)
    path=Path(workspace[2].get_asset(project_id=project,asset_id=asset['id'])['absolutePath'])
    original=path.read_bytes()
    result=registry(workspace).execute(project_id=project,task_id='task',name='image_edit',arguments={
        'asset_id':asset['id'],'operation':operation,'params':params,'canvas_node_id':original_node['id'],'output_mode':'edit'})
    with Image.open(workspace[2].get_asset(project_id=project,asset_id=result['assetId'])['absolutePath']) as output: assert output.width==params.get('width',128)
    assert path.read_bytes()==original
    board={node['id']:node for node in canvas.load(project)['nodes']}
    assert result['node']['id']!=original_node['id'] and board[original_node['id']]['data']['assetId']==asset['id']


def test_local_video_trim_concat_voiceover_subtitles(workspace,tmp_path):
    store,project,assets,canvas=workspace;task(store,project);tools=registry(workspace)
    run_media(['-f','lavfi','-i','color=c=red:s=64x64:r=24','-t','1','-c:v','libx264','-pix_fmt','yuv420p','video.mp4'],tmp_path)
    run_media(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','audio.wav'],tmp_path)
    video=assets.add_bytes(project_id=project,kind='video',filename='video.mp4',content=(tmp_path/'video.mp4').read_bytes())
    audio=assets.add_bytes(project_id=project,kind='audio',filename='audio.wav',content=(tmp_path/'audio.wav').read_bytes())
    for operation,ids,params in [('trim',[video['id']],{'start':.1,'duration':.5}),('concat',[video['id'],video['id']],{}),('voiceover',[video['id'],audio['id']],{}),('subtitles',[video['id']],{'cues':[{'start':0,'end':.8,'text':'字幕'}]})]:
        result=tools.execute(project_id=project,task_id='task',name='media_edit',arguments={'operation':operation,'asset_ids':ids,'params':params})
        path=assets.get_asset(project_id=project,asset_id=result['assetId'])['absolutePath']
        assert Path(path).stat().st_size>500
        run_media(['-i',path,'-f','null','-'],tmp_path)


@pytest.mark.parametrize('repair',[False,True])
@pytest.mark.parametrize('budget',[False,True])
def test_sdk_role_models_and_no_automatic_background_repair(workspace,monkeypatch,tmp_path,repair,budget):
    import sys,time
    from app.providers.registry import ProviderRegistry
    from app.task_runtime import TaskRuntime
    from app.model_config import EndpointModel
    from app.billing import BillingService
    from app.video import VideoJobService
    store,project,assets,canvas=workspace
    fixture=Path(__file__).parent/'fixtures';root=Path(__file__).resolve().parents[1]
    monkeypatch.delenv('AICS_TEST_MODE',raising=False)
    for key,value in {'NODE_OPTIONS':f'--import={(fixture / "optimization_transport.mjs").as_uri()}','PYTHONPATH':str(root),'FIXTURE_PYTHON':sys.executable,'FIXTURE_TOOL_SCRIPT':str(fixture/'agent_tool_fixture.py'),'FIXTURE_WORKSPACE':str(store.workspace_root),'FIXTURE_PROJECT':project,'FIXTURE_TASK':'opt-flow','FIXTURE_MODEL_LOG':str(tmp_path/'models.jsonl')}.items():monkeypatch.setenv(key,value)
    if repair:monkeypatch.setenv('FIXTURE_BROKEN_HTML','1')
    providers=ProviderRegistry();monkeypatch.setattr(providers.credentials,'get',lambda key:'test-only')
    catalog=ModelCatalog(store);providers.catalog=catalog;providers.billing=BillingService(store,catalog)
    catalog.save('openrouter','https://fixture.invalid/v1',{'models':['design-model','research-model','review-model']})
    settings=catalog.settings();settings.tiers['STANDARD'].primary=EndpointModel(provider='openrouter',baseUrl='https://fixture.invalid/v1',model='design-model',api='responses')
    settings.roles={role:EndpointModel(provider='openrouter',baseUrl='https://fixture.invalid/v1',model=f'{role}-model',api='responses') for role in ['research','review']}
    if budget:
        settings.taskBudgetPoints=100
        for model in ['design-model','research-model','review-model']:
            settings.prices[catalog.price_key('openrouter','https://fixture.invalid/v1',model)]=ModelPrice(currency='CNY',perRequest=.01)
    catalog.save_settings(settings)
    runtime=TaskRuntime(store,provider_registry=providers,asset_store=assets)
    result=runtime.enqueue(project_id=project,task_id='opt-flow',agent_key='design',workflow_step='design',brief='先单独研究竞品，再制作网页，跳过参考',input_data={'textProvider':{'key':'openrouter','baseUrl':'https://fixture.invalid/v1','model':'design-model','api':'responses'}})
    assert result['status']=='running',result
    node=canvas.load(project)['nodes'][0];delivery=DeliveryService(store)
    delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':not repair,'errors':['missingFunction is not defined'] if repair else []})
    videos=VideoJobService(store,providers,assets,canvas)
    videos.settle_tasks()
    for _ in range(150):
        result=runtime.get_task(project,'opt-flow')
        if result.get('output') and (result['status']!='running' or result['output']['provenance'].get('awaitingDelivery')):break
        time.sleep(.05)
    if repair:
        assert result['status']=='succeeded'
        assert result['output']['structured_data']['deliveryStatus']=='needs_review'
        assert 'missingFunction' in canvas.load(project)['nodes'][0]['data']['html']
        records=[json.loads(line) for line in (tmp_path/'models.jsonl').read_text().splitlines()]
        assert not any(row['model']=='review-model' for row in records)
        assert len(canvas.load(project)['nodes'])==1
        if budget:
            with store._connect() as db: reservations=db.execute('SELECT points,status FROM budget_reservations').fetchall()
            assert all(row['status']=='settled' and row['points']==1 for row in reservations)
        return
    assert result['status']=='succeeded',result
    records=[json.loads(line) for line in (tmp_path/'models.jsonl').read_text().splitlines()]
    assert {row['model'] for row in records}=={'design-model','research-model'}
    with providers.billing._connect() as db: billed=[json.loads(row[0])['model'] for row in db.execute('SELECT data_json FROM credit_ledger')]
    assert {'design-model','research-model'} <= set(billed)
    assert 'review-model' not in billed
    if budget:
        with store._connect() as db: reservations=db.execute('SELECT points,status FROM budget_reservations').fetchall()
        assert len(reservations)==len(billed)
        assert all(row['status']=='settled' and row['points']==1 for row in reservations)


def test_schedule_generation_is_deferred_but_due_run_requires_artifact():
    brief='每天九点研究最新趋势并生成一张海报'
    assert delivery_requirements(brief)==[]
    assert execution_flow(brief)=='direct'
    assert delivery_requirements(brief,{'scheduledTask':{'id':'due'}})==['image']
    assert execution_flow(brief,{'scheduledTask':{'id':'due'}})=='research_design'
    assert delivery_requirements('现在生成一张海报，之后每天九点提醒我')==['image']


def test_web_read_paginates_real_snapshot_and_checks_network(workspace):
    from app.research import ResearchStore
    store,project,*_=workspace;tools=registry(workspace)
    task(store,project,context={'allowExternalNetwork':True})
    body='<html><title>来源</title><p>'+('研究原文' * 5000)+'</p><script>不作为正文</script></html>'
    with patch('app.research.safe_source_uri',side_effect=lambda value:value),patch.object(ResearchStore,'_fetch',return_value=(body.encode(),'text/html')) as fetch:
        first=tools.execute(project_id=project,task_id='task',name='web_read',arguments={'url':'https://example.test/research'})
        second=tools.execute(project_id=project,task_id='task',name='web_read',arguments={'url':first['url'],'offset':first['nextOffset']})
        assert fetch.call_count==1 and len(first['text'])==12000
        assert second['sourceId']==first['sourceId'] and second['nextOffset'] is None
        assert '不作为正文' not in first['text']+second['text']
    with store._connect() as db:db.execute("UPDATE tasks SET input_json='{}' WHERE id='task'")
    with pytest.raises(ValueError,match='联网'):tools.execute(project_id=project,task_id='task',name='web_read',arguments={'url':'https://example.test/research'})


def test_transcription_uses_catalog_multipart_and_real_duration(workspace,tmp_path,monkeypatch):
    from app.providers.registry import ProviderRegistry
    from app.billing import BillingService
    store,project,assets,canvas=workspace
    task(store,project,context={'textProvider':{'key':'openai-compatible','baseUrl':'https://relay.test/v1','model':'chat-model'}})
    tools=registry(workspace);providers=ProviderRegistry();catalog=ModelCatalog(store)
    providers.catalog=catalog;providers.billing=BillingService(store,catalog);tools.provider_registry=providers
    monkeypatch.setattr(providers.credentials,'get',lambda key:'test-key')
    catalog.save('openai-compatible','https://relay.test/v1',{'models':['relay-whisper']})
    settings=catalog.settings();settings.taskBudgetPoints=100
    settings.prices[catalog.price_key('openai-compatible','https://relay.test/v1','relay-whisper')]=ModelPrice(currency='CNY',perSecond=.01);catalog.save_settings(settings)
    run_media(['-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','1','recording.wav'],tmp_path)
    asset=assets.add_bytes(project_id=project,kind='audio',filename='recording.wav',content=(tmp_path/'recording.wav').read_bytes())
    with patch('app.transcription.urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'text':'这是真实返回的转写'}).encode())) as call:
        args={'asset_id':asset['id']}
        result=tools.execute(project_id=project,task_id='task',name='transcribe_audio',arguments=args)
        assert tools.execute(project_id=project,task_id='task',name='transcribe_audio',arguments=args)==result
        assert call.call_count==1
        request=call.call_args.args[0]
        assert request.full_url=='https://relay.test/v1/audio/transcriptions'
        assert b'relay-whisper' in request.data and b'RIFF' in request.data
    assert result['text']=='这是真实返回的转写' and result['segments']==[]
    assert canvas.load(project)['nodes'][0]['data']['text']==result['text']
    with store._connect() as db: reservation=db.execute('SELECT points,status FROM budget_reservations').fetchone()
    assert reservation['status']=='settled' and reservation['points']==1


def test_inpaint_uses_user_image_endpoint_and_repair_cannot_generate(workspace):
    store,project,*_=workspace
    task(store,project,context={'mediaProvider':{'image':{'key':'openai-compatible','baseUrl':'https://relay.test/v1','model':'configured-image'}}})
    tools=registry(workspace);asset=image_asset(workspace)
    args={'asset_id':asset['id'],'operation':'inpaint','params':{'maskAssetId':asset['id'],'prompt':'修改颜色'}}
    with patch.object(tools,'generate_image',return_value={'status':'succeeded'}) as generate:
        tools.execute(project_id=project,task_id='task',name='image_edit',arguments=args)
        values=generate.call_args.kwargs
        assert values['provider']=='openai-compatible' and values['model']=='configured-image'
        assert values['params']['baseUrl']=='https://relay.test/v1'
    with store._connect() as db:db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps({'deliveryRepairOnly':True,'deliveryRepairNodes':['original']}),'task'))
    with pytest.raises(Exception,match='定向修复'):
        tools.execute(project_id=project,task_id='task',name='image_edit',arguments={**args,'operation':'resize'})


def test_export_html_content_and_skip_prior_downloads(workspace):
    from pptx import Presentation
    store,project,assets,canvas=workspace;task(store,project);tools=registry(workspace)
    canvas.create_node(project,kind='html',title='网页',data={'html':'<h1>Actual content</h1><p>Editable body</p><script>throw Error()</script>'})
    tools.execute(project_id=project,task_id='task',name='export_deliverable',arguments={'format':'html'})
    result=tools.execute(project_id=project,task_id='task',name='export_deliverable',arguments={'format':'pptx'})
    deck=Presentation(assets.get_asset(project_id=project,asset_id=result['assetId'])['absolutePath'])
    assert len(deck.slides)==1
    text='\n'.join(shape.text for shape in deck.slides[0].shapes if shape.has_text_frame)
    assert 'Editable body' in text and 'throw' not in text
