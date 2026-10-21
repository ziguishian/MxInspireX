import base64
import io
import json
import urllib.error
import http.client
from types import SimpleNamespace

import pytest
from PIL import Image

from app.design_tools import DesignToolRegistry, DesignToolError
from app.model_catalog import ModelCatalog
from app.model_config import DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL
from app.providers.http import OpenAICompatibleImageProvider, ProviderError
from app.providers.image_request import image_request_started
from app.providers.openrouter_image import OpenRouterImageProvider
from test_canvas_interactions import workspace


def image_bytes():
    output=io.BytesIO();Image.new('RGB',(16,16),'blue').save(output,format='PNG');return output.getvalue()


class Response:
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.body).encode()


def registry(workspace,adapter):
    _,store,canvas,assets=workspace
    return DesignToolRegistry(store,canvas_store=canvas,asset_store=assets,provider_registry=SimpleNamespace(image=lambda *a,**k:adapter))


@pytest.mark.parametrize('api',['images','chat_completions','gemini'])
@pytest.mark.parametrize('failure',[http.client.IncompleteRead(b'private partial image',5312), ConnectionResetError('secret'), TimeoutError('secret')])
def test_partial_image_response_is_unconfirmed_and_cannot_be_recharged(workspace,monkeypatch,api,failure):
    project,store,canvas,_=workspace
    adapter=OpenAICompatibleImageProvider('https://fixture.invalid/v1','fixture','fixture',SimpleNamespace(get=lambda _:'fixture-key'),api=api)
    calls=[]
    class BrokenResponse(Response):
        def read(self):raise failure
    def dispatch(*a,**k):calls.append(a);return BrokenResponse({})
    monkeypatch.setattr('urllib.request.urlopen',dispatch)
    tools=registry(workspace,adapter)
    args={'prompt':'七项礼盒的茶叶陶罐'}
    with pytest.raises(ProviderError) as error:tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    assert error.value.error_code=='image_result_unconfirmed'
    assert error.value.stop_tool and not error.value.response_received
    assert 'secret' not in str(error.value) and 'private' not in str(error.value)
    node=canvas.load(project)['nodes'][0]
    assert node['data']['status']=='生成结果待确认' and not node['data']['generating']
    assert tools.executions.result_status('task','generate_image',args)=={'state':'unconfirmed'}
    for retry in (args,{'prompt':'换个说法重新生成'}):
        with pytest.raises(DesignToolError,match='尚未确认|待核对'):tools.execute(project_id=project,task_id='task',name='generate_image',arguments=retry)
    assert len(calls)==1 and len(canvas.load(project)['nodes'])==1


@pytest.mark.parametrize('api',['images','chat_completions','gemini','openrouter'])
def test_loading_starts_at_actual_image_dispatch(workspace,monkeypatch,api):
    project,_,canvas,_=workspace
    def credentials(_):
        assert canvas.load(project)['nodes']==[], 'no placeholder during credential/request validation'
        return 'fixture-key'
    adapter=(OpenRouterImageProvider if api=='openrouter' else OpenAICompatibleImageProvider)(
        base_url='https://fixture.invalid/v1',provider_key='fixture',model='fixture',credentials=SimpleNamespace(get=credentials),api=api)
    calls=[]
    def dispatch(request,**kwargs):
        calls.append(request)
        nodes=canvas.load(project)['nodes']
        assert len(nodes)==1 and nodes[0]['data']['generating']
        encoded=base64.b64encode(image_bytes()).decode()
        if api=='gemini':return Response({'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'image/png','data':encoded}}]}}]})
        if api=='chat_completions':return Response({'choices':[{'message':{'images':[{'image_url':{'url':'data:image/png;base64,'+encoded}}]}}]})
        return Response({'data':[{'b64_json':encoded}]})
    monkeypatch.setattr('urllib.request.urlopen',dispatch)
    result=registry(workspace,adapter).execute(project_id=project,task_id='task',name='generate_image',arguments={'prompt':'海报'})
    assert len(calls)==1
    assert result['node']['data']['generating'] is False and result['node']['data']['assetId']==result['assetId']
    assert len(canvas.load(project)['nodes'])==1


def test_local_adapter_rejection_does_not_create_loading_or_block_corrected_retry(workspace,monkeypatch):
    project,_,canvas,_=workspace
    adapter=OpenAICompatibleImageProvider('https://fixture.invalid/v1','fixture','fixture',SimpleNamespace(get=lambda _:None))
    calls=[];monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:calls.append(a))
    tools=registry(workspace,adapter)
    with pytest.raises(ProviderError,match='API Key'):
        tools.execute(project_id=project,task_id='task',name='generate_image',arguments={'prompt':'海报'})
    assert not canvas.load(project)['nodes'] and not calls
    with workspace[1]._connect() as db:
        assert db.execute("SELECT count(*) FROM tool_receipts WHERE task_id='task' AND status='running'").fetchone()[0]==0


@pytest.mark.parametrize('status', [401, 402, 403])
def test_provider_access_rejection_stops_changed_prompts_after_restart(workspace, monkeypatch, status):
    project, store, canvas, _ = workspace
    adapter = OpenAICompatibleImageProvider('https://fixture.invalid/v1', 'fixture', 'fixture', SimpleNamespace(get=lambda _: 'fixture-key'))
    tools = registry(workspace, adapter)
    calls = []
    def dispatch(request, **kwargs):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, status, 'access rejected', {}, io.BytesIO(b'{"error":{"message":"insufficient balance or permission"}}'))
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    args = {'prompt':'单一 Logo'}
    with pytest.raises(ProviderError) as error:
        tools.execute(project_id=project, task_id='task', name='generate_image', arguments=args)
    assert error.value.stop_tool and error.value.error_code == 'image_provider_access'
    receipt = tools.executions.completed_result('task', 'generate_image', args)
    assert receipt['stopTool'] and receipt['status'] == 'failed'
    restarted = registry(workspace, adapter)
    for changed in (args, {'prompt':'同一 Logo 换一种描述'}):
        with pytest.raises(DesignToolError) as retry:
            restarted.execute(project_id=project, task_id='task', name='generate_image', arguments=changed)
        assert retry.value.stop_tool and retry.value.error_code == 'image_provider_access'
    assert len(calls) == 1 and canvas.load(project)['nodes'] == []


def test_budget_rejection_precedes_loading_and_provider_dispatch(workspace,monkeypatch):
    from app.billing import MeteredProvider, billing_context
    project,store,canvas,_=workspace
    calls=[]
    def credential(_):calls.append('credential');return 'fixture-key'
    adapter=OpenAICompatibleImageProvider('https://fixture.invalid/v1','fixture','fixture',SimpleNamespace(get=credential))
    billing=SimpleNamespace(store=store,catalog=SimpleNamespace(settings=lambda:SimpleNamespace(taskBudgetPoints=0)))
    def reject(*a,**k):
        assert canvas.load(project)['nodes']==[]
        raise ProviderError('积分预算不足',status_code=402)
    monkeypatch.setattr('app.budget.BudgetService.reserve',reject)
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:calls.append('transport'))
    token=billing_context.set({'task_id':'task'})
    try:
        with pytest.raises(ProviderError,match='积分预算'):
            registry(workspace,MeteredProvider(adapter,billing,'image')).execute(project_id=project,task_id='task',name='generate_image',arguments={'prompt':'海报'})
    finally:billing_context.reset(token)
    assert not calls and canvas.load(project)['nodes']==[]


@pytest.mark.parametrize('edit',[False,True])
def test_explicit_rejection_cleans_empty_attempt_and_retry_reuses_success_receipt(workspace,monkeypatch,edit):
    project,_,canvas,assets=workspace
    original=canvas.ensure_asset_node(project,assets.add_bytes(project_id=project,kind='image',filename='original.png',content=image_bytes())) if edit else None
    adapter=OpenAICompatibleImageProvider('https://fixture.invalid/v1','fixture','fixture',SimpleNamespace(get=lambda _:'fixture-key'))
    tools=registry(workspace,adapter);calls=[]
    def dispatch(request,**kwargs):
        calls.append(request)
        pending=[node for node in canvas.load(project)['nodes'] if node['data'].get('generating')]
        assert len(pending)==1
        if len(calls)==1:raise urllib.error.HTTPError(request.full_url,400,'invalid size',{},io.BytesIO(b'{"error":{"message":"invalid size"}}'))
        return Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})
    monkeypatch.setattr('urllib.request.urlopen',dispatch)
    args={'prompt':'海报','params':{'size':'1024x1024'}}
    if edit:
        args.update(canvas_node_id=original['id'],output_mode='edit')
        # Explicit target was selected by this task's node composer.
        monkeypatch.setattr(tools,'_task_input',lambda *a:{'canvasParams':{'canvasNodeId':original['id'],'kind':'image'}})
    with pytest.raises(ProviderError):tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    nodes=canvas.load(project)['nodes']
    if edit:
        assert len(nodes)==1 and nodes[0]['data']['assetId']==original['data']['assetId']
        assert not nodes[0]['data'].get('generating') and not nodes[0]['data'].get('error')
    else:assert nodes==[]
    result=tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    replay=tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    expected_nodes=2 if edit else 1
    assert len(calls)==2 and result['assetId']==replay['assetId'] and len(canvas.load(project)['nodes'])==expected_nodes
    if edit:
        board={node['id']:node for node in canvas.load(project)['nodes']}
        assert result['node']['id']!=original['id'] and board[original['id']]['data']['assetId']==original['data']['assetId']


def test_unconfirmed_dispatch_keeps_receipt_and_blocks_duplicate_charge(workspace,monkeypatch):
    project,_,canvas,_=workspace
    adapter=OpenAICompatibleImageProvider('https://fixture.invalid/v1','fixture','fixture',SimpleNamespace(get=lambda _:'fixture-key'))
    tools=registry(workspace,adapter);calls=[]
    def dispatch(*a,**k):calls.append(a);raise TimeoutError('timeout')
    monkeypatch.setattr('urllib.request.urlopen',dispatch)
    args={'prompt':'海报'}
    with pytest.raises(ProviderError):tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    with pytest.raises(DesignToolError,match='尚未确认'):tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    assert len(calls)==1
    assert len(canvas.load(project)['nodes'])==1 and not canvas.load(project)['nodes'][0]['data']['generating']


def test_safe_fallback_reuses_one_loading_node_and_records_route(workspace):
    project,store,canvas,assets=workspace
    catalog=ModelCatalog(store)
    base='https://relay.test/v1'
    catalog.save('openrouter',base,{'models':[DEFAULT_DRAFT_IMAGE_MODEL,DEFAULT_IMAGE_MODEL]})
    calls=[]
    class CandidateAdapter:
        reports_image_request_start=True
        api='images'
        supported_parameters=None
        last_response={}
        def __init__(self,model):self.model=model
        def generate(self,**_):
            calls.append((self.model,len(canvas.load(project)['nodes'])))
            image_request_started()
            if self.model==DEFAULT_DRAFT_IMAGE_MODEL:
                raise ProviderError('model not found',status_code=404)
            return image_bytes()
    providers=SimpleNamespace(catalog=catalog,image=lambda _key,**kwargs:CandidateAdapter(kwargs['model']))
    tools=DesignToolRegistry(store,canvas_store=canvas,asset_store=assets,provider_registry=providers)
    result=tools.execute(project_id=project,task_id='task',name='generate_image',arguments={
        'prompt':'概念探索','quality':'draft','provider':'openrouter','params':{'baseUrl':base},
    })
    assert calls==[(DEFAULT_DRAFT_IMAGE_MODEL,0),(DEFAULT_IMAGE_MODEL,1)]
    assert len(canvas.load(project)['nodes'])==1
    assert result['model']==DEFAULT_IMAGE_MODEL and result['imageRoute']['fallbackUsed'] is True
    assert result['asset']['metadata']['imageQuality']['model']==DEFAULT_IMAGE_MODEL
    assert result['asset']['metadata']['imageRoute']['finalModel']==DEFAULT_IMAGE_MODEL
    from app.model_router import RouteTrace
    events=RouteTrace(store).list('task')
    assert [event['status'] for event in events if event.get('model')==DEFAULT_DRAFT_IMAGE_MODEL][-2:]==['submitted','safe_rejected']
    assert [event['status'] for event in events if event.get('model')==DEFAULT_IMAGE_MODEL][-2:]==['submitted','succeeded']
