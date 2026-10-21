import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.delivery import DeliveryService
from app.design_runtime import DesignRuntimeError
from app.design_tools import DesignToolRegistry
from app.execution_store import ExecutionStore
from app.main import new_project
from app.model_catalog import ModelCatalog
from app.model_router import ModelRouter, RoutedDesignRuntime, evaluate_result
from app.agent_contracts import AgentResult
from app.providers.registry import ProviderRegistry
from app.storage import ProjectStore
from app.task_policy import delivery_requirements, execution_flow
from app.task_runtime import TASK_SCHEMA, TaskRuntime
from app.video import VideoJobService


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='交付回归', slug='delivery', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path/'delivery')))['id']
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
    return store, project, AssetStore(store), CanvasStore(store)


def task(store, project, *, context=None, output=None):
    with store._connect() as db:
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,output_json,created_at,updated_at) VALUES (?,?,'design','design','running',?,?,'now','now')", ('task',project,json.dumps(context or {}),json.dumps(output) if output else None))


@pytest.mark.parametrize('brief,kind,flow', [('画一只小狗的照片','image','design'), ('生成一个网页','html','design'), ('制作一段配音','audio','design'), ('请生成一段视频','video','design'), ('你好',None,'direct'), ('如何生成照片',None,'direct'), ('调研竞品并生成网页','html','research_design')])
def test_intent_is_independent_of_model_and_wording(brief,kind,flow):
    assert delivery_requirements(brief)==([kind] if kind else [])
    assert execution_flow(brief)==flow


def test_empty_or_failed_review_is_not_success():
    assert evaluate_result(AgentResult(status='succeeded',structured_data={'answer':'ok','review':{'passed':False}})) is None
    assert evaluate_result(AgentResult(status='succeeded',structured_data={'answer':''}))
    assert evaluate_result(AgentResult(status='succeeded',structured_data={'answer':'只是答复'}),['html'])


def test_html_delivery_needs_current_browser_check(workspace):
    store,project,assets,canvas=workspace
    task(store,project,context={'userMessage':'生成网页','deliveryVerification':True})
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    node=tools.execute(project_id=project,task_id='task',name='canvas_create_html',arguments={'html':'<h1>页面</h1>'})['node']
    delivery=DeliveryService(store,assets,canvas)
    pending=delivery.inspect_task(project,'task')
    assert pending['pendingPreview']==[node['id']] and not pending['passed']
    delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':True,'errors':[]})
    passed=delivery.inspect_task(project,'task')
    assert passed['passed'] and passed['artifact_refs'][0]['entity_type']=='canvas_node'
    canvas.update_node(project,node['id'],{'data':{'html':'<h1>新版</h1>'}})
    assert not delivery.inspect_task(project,'task')['passed']
    with pytest.raises(ValueError,match='内容已变化'):
        delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':True})


@pytest.mark.parametrize('name', ['canvas_create_html', 'canvas_create_text', 'canvas_update_node', 'canvas_link_nodes'])
def test_saved_canvas_operation_recovers_after_receipt_write_interruption(workspace, name):
    store,project,assets,canvas=workspace
    task(store,project)
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    first=canvas.create_node(project,kind='text',title='源',data={'text':'源'})
    second=canvas.create_node(project,kind='text',title='目标',data={'text':'目标'})
    args={'canvas_create_html':{'html':'<h1>已保存</h1>'},
          'canvas_create_text':{'text':'已保存'},
          'canvas_update_node':{'node_id':first['id'],'patch':{'data':{'text':'已更新'}}},
          'canvas_link_nodes':{'source_node_id':first['id'],'target_node_id':second['id']}}[name]
    with patch.object(tools.executions,'complete',side_effect=OSError('回执写入前中断')):
        with pytest.raises(OSError):
            tools.execute(project_id=project,task_id='task',name=name,arguments=args)
    before=canvas.load(project)
    recovered=tools.execute(project_id=project,task_id='task',name=name,arguments=args)
    assert recovered['status']=='succeeded'
    assert canvas.load(project)==before
    assert recovered.get('node',recovered.get('edge'))['meta']['taskId']=='task'


def test_video_backfill_retry_preserves_original_node_and_waits_for_review(workspace):
    store,project,assets,canvas=workspace
    node=canvas.create_node(project,kind='video',title='视频',task_id='task',data={'generating':True})
    calls=[]
    def retrieve(**kwargs): calls.append(kwargs); return {'status':'completed','content':b'video'}
    videos=VideoJobService(store,SimpleNamespace(video=lambda *a,**k:SimpleNamespace(retrieve=retrieve)),assets,canvas)
    job=videos.create(project,provider='openrouter',model='video',status='pending',job_id='upstream',prompt='video',source_asset_id=None,metadata={'taskId':'task','canvasNodeId':node['id']})
    task(store,project,context={'userMessage':'生成视频','deliveryVerification':True},output={'structured_data':{'answer':'提交成功'},'provenance':{'pendingMedia':[job['id']],'awaitingDelivery':True}})
    with patch.object(canvas,'ensure_asset_node',side_effect=OSError('暂时不能写入画布')):
        videos.tick()
    with store._connect() as db: assert db.execute("SELECT status FROM tasks WHERE id='task'").fetchone()[0]=='running'
    assert videos.get(project,job['id'])['outputAssetId']
    record=videos.get(project,job['id'])
    videos.update(project,job['id'],metadata={**record['metadata'],'nextPollAt':0})
    videos.tick()
    assert len(calls)==1 and len(canvas.load(project)['nodes'])==1
    completed=canvas.load(project)['nodes'][0]
    assert completed['id']==node['id'] and not completed['data']['generating']
    resumed=[]; videos.resume_delivery=lambda task_id:resumed.append(task_id)
    videos.settle_tasks(); assert not resumed
    delivery=DeliveryService(store,assets,canvas)
    delivery.record_check(project,node['id'],delivery.fingerprint(completed),{'passed':True,'errors':[],'duration':1,'frames':['data:image/jpeg;base64,ZnJhbWU=']})
    videos.settle_tasks(); assert not resumed
    result = TaskRuntime(store).get_task(project,'task')
    assert result['status'] == 'succeeded'
    assert result['output']['structured_data']['deliveryStatus'] == 'passed'
    assert 'review' not in result['output']['structured_data']


def test_media_preview_timeout_retries_then_recovers_without_generation(workspace):
    store,project,assets,canvas=workspace
    node=canvas.create_node(project,kind='video',title='视频',task_id='task')
    asset=assets.add_bytes(project_id=project,kind='video',filename='saved.mp4',content=b'saved-video')
    canvas.update_node(project,node['id'],{'data':{'assetId':asset['id']}})
    node=canvas.load(project)['nodes'][0]
    task(store,project,context={'userMessage':'生成视频','deliveryVerification':True},output={'structured_data':{'answer':'生成中'},'provenance':{'awaitingDelivery':True}})
    delivery=DeliveryService(store,assets,canvas)
    videos=VideoJobService(store,SimpleNamespace(),assets,canvas)
    assert len(delivery.claim_previews())==1
    for attempt in range(1,4):
        check=delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':False,'errors':['媒体预览检查超时：读取首帧'],'code':'media_timeout'})
        assert check['attempts']==attempt
        report=delivery.inspect_task(project,'task')
        if attempt<3:
            assert report['pendingPreview']==[node['id']] and not report['issues']
            videos.settle_tasks()
            with store._connect() as db: assert db.execute("SELECT status FROM tasks WHERE id='task'").fetchone()[0]=='running'
            assert delivery.claim_previews()==[]
            with patch('app.delivery.time.time',return_value=check['retryAfter']+1):
                assert len(delivery.claim_previews())==1
        else:
            assert not report['pendingPreview'] and report['issues']
            assert delivery.claim_previews()==[]
    videos.settle_tasks()
    runtime=TaskRuntime(store)
    failed=runtime.get_task(project,'task')
    assert failed['status']=='succeeded'
    assert failed['output']['structured_data']['deliveryStatus']=='needs_review'
    assert '产物已保存' in failed['trace'][-1]['message']
    with patch.object(runtime,'_start_worker',side_effect=AssertionError('must not rerun generation')):
        retried=runtime.retry(project,'task')
    assert retried['status']=='running' and retried['error'] is None
    assert delivery.inspect_task(project,'task')['pendingPreview']==[node['id']]
    assert len(delivery.claim_previews())==1
    delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':True,'errors':[],'duration':5,'frames':['data:image/jpeg;base64,ZnJhbWU=']})
    reviews=[];videos.resume_delivery=lambda task_id:reviews.append(task_id)
    videos.settle_tasks()
    assert reviews == []
    assert runtime.get_task(project,'task')['output']['structured_data']['deliveryStatus'] == 'passed'
    assert len(assets.list_assets(project))==1 and len(canvas.load(project)['nodes'])==1


def test_runtime_recovery_continues_existing_review_without_resubmitting_video(workspace):
    store,project,assets,canvas=workspace
    context={'userMessage':'生成视频','deliveryVerification':True,'deliveryReviewOnly':True,'executionFlow':'delivery_review'}
    task(store,project,context=context)
    asset=assets.add_bytes(project_id=project,kind='video',filename='saved.mp4',content=b'video')
    node=canvas.create_node(project,kind='video',title='视频',task_id='task',data={'assetId':asset['id']})
    delivery=DeliveryService(store,assets,canvas)
    delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':True,'errors':[],'duration':10,'frames':['data:image/jpeg;base64,ZnJhbWU=']})
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='failed',error_json=? WHERE id='task'",(json.dumps({'message':'找不到 Node.js：/replaced/app'}),))
    runtime=TaskRuntime(store)
    with patch.object(runtime,'_start_worker',return_value=True) as start:
        result=runtime.retry(project,'task')
    start.assert_called_once_with('task','生成视频')
    assert result['status']=='queued'
    with store._connect() as db:
        assert json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0])==context
    assert len(assets.list_assets(project))==1 and len(canvas.load(project)['nodes'])==1
    assert delivery.inspect_task(project,'task')['passed']


@pytest.mark.parametrize('review_status', ['unavailable', 'timed_out', 'failed', 'passed'])
def test_explicit_retry_only_resumes_interrupted_review(workspace, review_status):
    store, project, assets, canvas = workspace
    context = {'userMessage': '创建文本节点', 'deliveryVerification': True}
    output = {'structured_data': {'deliveryStatus': 'needs_review', 'review': {'status': review_status, 'passed': False}}}
    task(store, project, context=context, output=output)
    node = canvas.create_node(project, kind='text', title='已保存文案', task_id='task', data={'text': '慢一刻，把早晨留给一杯好咖啡。'})
    saved = {'stages': {'design': '文案已保存'}, 'toolOutputs': [{'name': 'canvas_create_text', 'args': {}, 'output': {'node': node}}], 'finalResult': output}
    ExecutionStore(store).save('task', saved)
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded' WHERE id='task'")
    runtime = TaskRuntime(store)
    with patch.object(runtime, '_start_worker', return_value=True) as start:
        with pytest.raises(ValueError):
            runtime.retry(project, 'task')
        start.assert_not_called()
    assert [item['id'] for item in canvas.load(project)['nodes']] == [node['id']]


def test_media_recheck_does_not_hide_other_delivery_failures(workspace):
    store,project,assets,canvas=workspace
    task(store,project,context={'userMessage':'生成视频','deliveryVerification':True})
    asset=assets.add_bytes(project_id=project,kind='video',filename='saved.mp4',content=b'video')
    node=canvas.create_node(project,kind='video',title='视频',task_id='task',data={'assetId':asset['id']})
    canvas.create_node(project,kind='image',title='缺少图像',task_id='task')
    delivery=DeliveryService(store,assets,canvas)
    delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':False,'errors':['媒体无法解码或检查超时']})
    assert not delivery.requeue_failed_media(project,'task')
    assert delivery.check(project,node)


def test_old_browser_workers_cannot_claim_or_overwrite_new_checks(workspace):
    from fastapi import HTTPException
    from app.main import claim_delivery_previews, save_delivery_check
    store,project,assets,canvas=workspace
    assert claim_delivery_previews(store)==[]
    assert claim_delivery_previews(store,{'probeVersion':1})==[]
    with pytest.raises(HTTPException) as error:
        save_delivery_check(project,'node',{'fingerprint':'old','result':{'passed':False}},store)
    assert error.value.status_code==409


def test_recovery_reconciles_saved_asset_without_repeating_provider(workspace):
    store,project,assets,canvas=workspace
    task(store, project)
    args={'prompt':'生成图片','provider':'openai-image'}
    journal=ExecutionStore(store)
    fingerprint,_=journal.claim('task','generate_image',args)
    node=canvas.create_node(project,kind='image',title='原节点',task_id='task',data={'generating':True})
    from io import BytesIO
    from PIL import Image
    raster = BytesIO()
    Image.new('RGB', (20, 20), 'green').save(raster, format='PNG')
    assets.add_bytes(project_id=project,kind='image',filename='recovered.png',content=raster.getvalue(),metadata={'taskId':'task','executionReceipt':fingerprint,'canvasNodeId':node['id']})
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas,provider_registry=SimpleNamespace(image=lambda *a,**k:pytest.fail('must not regenerate')))
    result=tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    assert result['node']['id']==node['id'] and result['assetId']
    assert len(canvas.load(project)['nodes'])==1
    journal.claim('unknown','generate_image',args)
    with pytest.raises(RuntimeError,match='阻止重复'):journal.claim('unknown','generate_image',args)


def test_bad_configuration_stops_without_expensive_escalation(workspace):
    store,project,assets,canvas=workspace
    catalog=ModelCatalog(store);providers=ProviderRegistry();providers.catalog=catalog
    ids=[v.primary.model for v in catalog.settings().tiers.values()]
    catalog.save('openrouter','https://relay.test/v1',{'models':ids,'modelCatalog':[]})
    calls=[]
    def fail(**kw):calls.append(kw);raise DesignRuntimeError('400 invalid parameter',kind='configuration')
    router=RoutedDesignRuntime(SimpleNamespace(run=fail),catalog,providers,store)
    with pytest.raises(DesignRuntimeError,match='400'):
        router.run(project_id=project,task_id='task',brief='你好',provider_ref={'key':'openrouter','baseUrl':'https://relay.test/v1','model':'gpt-5.6-terra'},constraints={})
    from app.model_config import DEFAULT_FAST_TEXT_MODEL
    assert len(calls)==1 and calls[0]['provider_ref']['model']==DEFAULT_FAST_TEXT_MODEL
    assert calls[0]['constraints']['executionFlow']=='direct'


def test_successful_conversation_does_not_advance_workflow(workspace, monkeypatch):
    monkeypatch.delenv('AICS_TEST_MODE', raising=False)
    store,project,assets,canvas=workspace
    runtime=TaskRuntime(store,asset_store=assets,design_runtime=SimpleNamespace(run=lambda **kw:AgentResult(status='succeeded',structured_data={'answer':'你好'})))
    response=runtime.enqueue(project_id=project,agent_key='design',workflow_step='design',brief='你好',input_data={'textProvider':{'key':'openrouter','model':'test'}})
    assert response['status']=='succeeded'
    with store._connect() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name IN ('workflows','workflow_steps')").fetchall() == []


def test_interrupted_agent_keeps_submitted_video_attached_to_task(workspace, monkeypatch):
    monkeypatch.delenv('AICS_TEST_MODE',raising=False)
    store,project,assets,canvas=workspace
    def interrupted(**kwargs):
        VideoJobService(store).create(project,provider='openrouter',model='video',status='pending',job_id='accepted',prompt='video',source_asset_id=None,metadata={'taskId':kwargs['task_id']})
        raise DesignRuntimeError('模型连接中断')
    runtime=TaskRuntime(store,asset_store=assets,design_runtime=SimpleNamespace(run=interrupted))
    response=runtime.enqueue(project_id=project,agent_key='design',workflow_step='design',brief='生成视频',input_data={'textProvider':{'key':'openrouter','model':'test'}})
    assert response['status']=='running' and response['output']['provenance']['pendingMedia']
    assert response['output']['provenance']['awaitingDelivery']


@pytest.mark.parametrize('review_passed',[True,False])
def test_real_sdk_finishes_html_without_another_model_call(workspace, monkeypatch, review_passed):
    import sys,time
    from pathlib import Path
    store,project,assets,canvas=workspace
    monkeypatch.delenv('AICS_TEST_MODE',raising=False)
    monkeypatch.setenv('AICS_PROVIDER_KEY_OPENROUTER','test-only-key')
    root=Path(__file__).resolve().parents[1]; fixtures=root/'tests/fixtures'
    for key,value in {'NODE_OPTIONS':f'--import={(fixtures/"delivery_transport.mjs").as_uri()}','FIXTURE_PYTHON':sys.executable,'FIXTURE_TOOL_SCRIPT':str(fixtures/'agent_tool_fixture.py'),'FIXTURE_WORKSPACE':str(store.workspace_root),'FIXTURE_PROJECT':project,'FIXTURE_TASK':'flow-task','PYTHONPATH':str(root)}.items():monkeypatch.setenv(key,value)
    providers=ProviderRegistry();providers.catalog=ModelCatalog(store)
    providers.catalog.save('openrouter','https://fixture.invalid/v1',{'models':['gpt-5.6-terra'],'modelCatalog':[]})
    runtime=TaskRuntime(store,provider_registry=providers,asset_store=assets)
    result=runtime.enqueue(project_id=project,task_id='flow-task',agent_key='design',workflow_step='design',brief='生成一个网页，跳过参考',input_data={'textProvider':{'key':'openrouter','baseUrl':'https://fixture.invalid/v1','model':'gpt-5.6-terra'},'modelRouting':{'mode':'manual'}})
    assert result['status']=='running' and result['output']['provenance']['awaitingDelivery']
    assert result['output']['artifact_refs'][0]['entity_type']=='canvas_node'
    # Empty memory is initialized locally; saving one artifact ends the main turn.
    assert result['output']['usage']['input_tokens']==10
    assert runtime.recover_pending()==1
    node=canvas.load(project)['nodes'][0]; delivery=DeliveryService(store,assets,canvas)
    delivery.record_check(project,node['id'],delivery.fingerprint(node),{'passed':True,'errors':[],'buttonsTested':1})
    monkeypatch.setenv('FIXTURE_REVIEW_ONLY','1')
    if not review_passed:monkeypatch.setenv('FIXTURE_REVIEW_FAIL','1')
    videos=VideoJobService(store,providers,assets,canvas)
    videos.settle_tasks()
    for _ in range(100):
        result=runtime.get_task(project,'flow-task')
        if result['status'] in ['succeeded','failed']:break
        time.sleep(.1)
    assert result['status']=='succeeded',result
    assert result['output']['structured_data']['deliveryStatus']=='passed'
    assert 'review' not in result['output']['structured_data']
    assert result['output']['usage']['input_tokens']==10
    assert len(canvas.load(project)['nodes'])==1
    assert result['output']['provenance']['stages']==['design']
