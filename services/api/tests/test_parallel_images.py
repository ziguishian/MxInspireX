import copy
from io import BytesIO
from PIL import Image


def png_fixture():
    output = BytesIO()
    Image.new("RGB", (300, 200), "green").save(output, format="PNG")
    return output.getvalue()

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.assets import AssetStore
from app.design_tools import DesignToolRegistry, DesignToolError
from app.execution_store import ExecutionStore
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='独立图片', slug='images', brief='生成不同方向的图片', budget_minor=None, currency='CNY', root_path=str(tmp_path/'images')))
    runtime = TaskRuntime(store); runtime._start_worker = lambda *args: False
    task = runtime.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief='生成不同方向的图片。跳过参考', run_async=True)
    assets = AssetStore(store)
    from app.main import app
    from app.image_jobs import ImageJobs
    monkeypatch.setattr(app.state, 'image_jobs', ImageJobs(store, ExecutionStore(store)), raising=False)
    return store, project['id'], task['id'], assets


def test_async_video_receipt_owns_target_after_prompt_change_and_restart(setup):
    store, project, task, assets = setup
    journal = ExecutionStore(store)
    key, previous = journal.claim(task, 'generate_video', {'prompt': 'original'}, resources=['node:video'])
    assert previous is None
    output = {'status': 'processing', 'job': {'id': 'accepted', 'metadata': {'canvasNodeId': 'video'}}}
    journal.complete(task, key, output)
    # Legacy receipts have only canvasNodeId; new receipts also persist scope IDs.
    assert ExecutionStore(store).claim(task, 'generate_video', {'prompt': 'rewritten'}, resources=['node:video']) == (key, output)
    other, previous = journal.claim(task, 'generate_video', {'prompt': 'independent'}, resources=['node:other'])
    assert previous is None and other != key
    journal.reject(task, other)
    batch_key, _ = journal.claim(task, 'generate_video', {'prompt': 'batch'}, resources=['delivery:scope:item'])
    batch = {'status': 'processing', 'job': {'id': 'batch-job', 'metadata': {'executionResources': ['delivery:scope:item']}}}
    journal.complete(task, batch_key, batch)
    assert ExecutionStore(store).claim(task, 'generate_video', {'prompt': 'batch rewritten'}, resources=['delivery:scope:item']) == (batch_key, batch)
    assert ExecutionStore(store).claim('new-user-task', 'generate_video', {'prompt': 'new request'}, resources=['node:video'])[1] is None


def test_read_only_receipt_query_tracks_live_then_late_result_and_repairs_checkpoint(setup,monkeypatch):
    from app.main import app, get_tool_result
    from fastapi import HTTPException
    store,project,task,assets=setup
    journal=ExecutionStore(store)
    entered,finish=threading.Event(),threading.Event()
    calls=[]
    def generate(**args):
        calls.append(args);entered.set();assert finish.wait(10)
        return png_fixture()
    registry=DesignToolRegistry(store,asset_store=assets,provider_registry=SimpleNamespace(image=lambda *a,**kw:SimpleNamespace(generate=generate)))
    monkeypatch.setattr(app.state,'design_tools',registry,raising=False)
    runtime=TaskRuntime(store);runtime._start_worker=lambda *a:False
    monkeypatch.setattr(app.state,'tasks',runtime,raising=False)
    args={'prompt':'迟到的礼盒','provider':'local-placeholder'}
    query={'name':'generate_image','arguments':args}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(registry.execute,project_id=project,task_id=task,name='generate_image',arguments=args)
        assert entered.wait(10)
        try:
            assert get_tool_result(project,task,query,store)=={'state':'running'}
            with pytest.raises(HTTPException) as wrong:get_tool_result('another-project',task,query,store)
            assert wrong.value.status_code==404
            with pytest.raises(DesignToolError,match='尚未确认'):
                registry.execute(project_id=project,task_id=task,name='generate_image',arguments=args)
        finally:finish.set()
        result=future.result(timeout=10)
    observed=get_tool_result(project,task,query,store)
    assert observed['state']=='completed' and observed['output']['assetId']==result['assetId']
    assert len(calls)==1
    journal.save(task,{'toolOutputs':[
        {'name':'generate_image','args':args,'output':{'status':'generation_unconfirmed'}},
        {'name':'generate_batch','args':{'items':[{'tool':'generate_image','arguments':args}]},'output':{'results':[{'status':'failed','message':'fetch failed'}]}},
    ]})
    recovered=journal.load(task)['toolOutputs']
    assert recovered[0]['output']['assetId']==result['assetId']
    assert recovered[1]['output']['results'][0]['status']=='succeeded'
    assert recovered[1]['output']['results'][0]['assetId']==result['assetId']
    assert 'message' not in recovered[1]['output']['results'][0]
    assert get_tool_result(project,task,{'name':'generate_image','arguments':{'prompt':'never submitted'}},store)=={'state':'missing'}
    with store._connect() as db:assert db.execute('SELECT count(*) FROM tool_receipts WHERE task_id=?',(task,)).fetchone()[0]==1


def test_gateway_returns_unknown_generation_without_500_or_releasing_receipt(setup,monkeypatch):
    import http.client
    from app.main import app,execute_agent_tool,get_tool_result
    from app.providers.http import OpenAICompatibleImageProvider
    from starlette.requests import Request
    store,project,task,assets=setup
    adapter=OpenAICompatibleImageProvider('https://fixture.invalid/v1','fixture','fixture',SimpleNamespace(get=lambda _:'fixture-key'))
    def disconnected(*a,**k):raise http.client.IncompleteRead(b'partial',5312)
    monkeypatch.setattr('urllib.request.urlopen',disconnected)
    registry=DesignToolRegistry(store,asset_store=assets,provider_registry=SimpleNamespace(image=lambda *a,**kw:adapter))
    monkeypatch.setattr(app.state,'design_tools',registry,raising=False)
    monkeypatch.setattr(app.state,'tasks',TaskRuntime(store),raising=False)
    request=Request({'type':'http','headers':[(b'x-aics-task-id',task.encode())]})
    args={'prompt':'陶罐','provider':'local-placeholder'}
    result=execute_agent_tool(project,'generate_image',args,request,store)
    assert result['status']=='generation_unconfirmed' and result['retryable'] is False
    assert result['billingCertainty']=='unknown'
    assert get_tool_result(project,task,{'name':'generate_image','arguments':args},store)=={'state':'unconfirmed'}


@pytest.mark.parametrize('count', [1, 4, 7])
def test_real_registry_overlaps_images_and_preserves_assets_receipts_and_canvas(setup, count):
    store, project, task, assets = setup
    both_started = threading.Barrier(count)
    def generate(**kwargs):
        both_started.wait(timeout=5)  # Serial generation cannot pass this barrier.
        return png_fixture()
    registry = DesignToolRegistry(store, asset_store=assets, provider_registry=SimpleNamespace(image=lambda *a, **kw: SimpleNamespace(generate=generate)))
    registry.execute(project_id=project, task_id=task, name='design_plan', arguments={'plan': {
        'goal':'多个独立方向', 'research':'使用已确认的共同风格', 'deliverables': [
            {'id':f'image-{i}', 'title':f'方向 {i}', 'kind':'image', 'acceptance':'可独立查看'} for i in range(count)]}})
    args = [{'prompt': f'方向 {i}', 'provider':'local-placeholder', 'deliverable_ids':[f'image-{i}']} for i in range(count)]
    def run(arguments): return registry.execute(project_id=project, task_id=task, name='generate_image', arguments=arguments)
    with ThreadPoolExecutor(max_workers=count) as pool: results = list(pool.map(run, args))
    nodes = registry.canvas_store.load(project)['nodes']
    assert len(nodes) == len({r['assetId'] for r in results}) == count
    assert len({tuple(n['position'].values()) for n in nodes}) == count
    assert len(ExecutionStore(store).load(task)['toolOutputs']) == count
    assert all(item['status'] in {'ready', 'passed'} for item in registry.delivery_verify(project_id=project, task_id=task)['deliverables'])
    assert run(args[0])['assetId'] == results[0]['assetId']
    assert len(registry.canvas_store.load(project)['nodes']) == count


def test_one_unknown_image_failure_keeps_other_success_without_resubmitting(setup, caplog):
    store, project, task, assets = setup
    both_started = threading.Barrier(2)
    def generate(**kwargs):
        both_started.wait(timeout=5)
        # Production image requests append shared safety/output constraints to
        # the user's prompt before provider dispatch. Match the original
        # request without assuming the provider payload is byte-for-byte equal.
        if kwargs['prompt'].startswith('lost response'):
            raise TimeoutError('provider response lost')
        return png_fixture()
    registry = DesignToolRegistry(store, asset_store=assets, provider_registry=SimpleNamespace(image=lambda *a, **kw: SimpleNamespace(generate=generate)))
    def run(prompt): return registry.execute(project_id=project, task_id=task, name='generate_image', arguments={'prompt':prompt,'provider':'local-placeholder'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        failed, successful = pool.submit(run, 'lost response'), pool.submit(run, 'saved')
        with pytest.raises(TimeoutError): failed.result(timeout=10)
        saved = successful.result(timeout=10)
    assert 'Design tool failed:' in caplog.text and 'provider response lost' in caplog.text
    assert run('saved')['assetId'] == saved['assetId']
    board = registry.canvas_store.load(project)['nodes']
    assert len(board) == 2 and sum(bool(n['data'].get('assetId')) for n in board) == 1
    with pytest.raises(DesignToolError, match='尚未确认'): run('try another prompt')


def test_receipts_allow_live_independent_generations_but_block_conflicts_and_unknown_results(setup):
    store, _, task, _ = setup
    journal = ExecutionStore(store)
    with journal.running_scope():
        first, _ = journal.claim(task, 'generate_image', {'prompt':'first'}, resources=['node:one'])
        with pytest.raises(RuntimeError, match='并发冲突'):
            journal.claim(task, 'generate_image', {'prompt':'overwrite'}, resources=['node:one'])
        second, _ = journal.claim(task, 'generate_image', {'prompt':'second'}, resources=['node:two'])
        for name in ['generate_image','generate_video','generate_audio','generate_3d','generate_text']:
            additional, _ = journal.claim(task, name, {'prompt':name})
            journal.complete(task, additional, {'status':'succeeded'})
        with pytest.raises(RuntimeError, match='阻止'):
            journal.claim(task, 'image_edit', {'operation':'inpaint'})
        journal.complete(task, second, {'status':'succeeded'})
    # An interrupted/lost response may not be treated as a concurrent live job.
    with journal.running_scope(), pytest.raises(RuntimeError, match='尚未确认'):
        ExecutionStore(store).claim(task, 'generate_image', {'prompt':'rewritten'})
    journal.reject(task, first)
    with journal.running_scope():
        for i in range(8): journal.claim(task, 'generate_image', {'prompt':f'new {i}'})


def test_dependencies_block_before_dispatch_and_unlock_after_real_output(setup):
    store, project, task, assets = setup
    registry = DesignToolRegistry(store, asset_store=assets)
    def call(name, **args): return registry.execute(project_id=project, task_id=task, name=name, arguments=args)
    plan = {'goal':'先定义文案，再生成海报', 'research':'使用用户提供的内容', 'deliverables':[
        {'id':'copy','title':'文案','kind':'text','acceptance':'文案完整'},
        {'id':'poster','title':'海报','kind':'image','acceptance':'使用前置文案','dependsOn':['copy']}]}
    assert call('design_plan', plan=plan)['status'] == 'ready'
    result = call('generate_image', prompt='海报', deliverable_ids=['poster'])
    assert result['status'] == 'dependency_required' and result['dependencies'][0]['id'] == 'copy'
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM tool_receipts WHERE name='generate_image'").fetchone()[0] == 0
    report = registry.delivery_verify(project_id=project, task_id=task)
    assert next(d for d in report['deliverables'] if d['id']=='poster')['status'] == 'blocked'
    call('canvas_create_text', text='已确认的真实文案', deliverable_ids=['copy'])
    report = registry.delivery_verify(project_id=project, task_id=task)
    assert next(d for d in report['deliverables'] if d['id']=='poster')['status'] == 'pending'
    # Past dependency validation; the unavailable provider is the next error.
    with pytest.raises(DesignToolError, match='图像工具尚未初始化'):
        call('generate_image', prompt='海报', deliverable_ids=['poster'])
    for deps in [['poster'], ['missing']]:
        invalid = copy.deepcopy(plan); invalid['deliverables'][1]['dependsOn'] = deps
        assert call('design_plan', plan=invalid, change_reason='明确调整生成依赖')['status'] == 'invalid'
    cycle = copy.deepcopy(plan); cycle['deliverables'][0]['dependsOn'] = ['poster']
    assert call('design_plan', plan=cycle, change_reason='明确调整生成依赖')['status'] == 'invalid'
