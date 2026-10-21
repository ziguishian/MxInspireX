import base64
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image
from app.main import new_project
from app.storage import ProjectStore
from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry
from app.execution_store import ExecutionStore
from app.task_runtime import TASK_SCHEMA
from app.video import VideoJobService
from app.providers.openrouter_video import OpenRouterVideoProvider
from app.providers.http import OpenAICompatibleSpeechProvider
from app.agent_contracts import AgentResult
from app.model_catalog import ModelCatalog
from app.model_router import RoutedDesignRuntime
from app.providers.registry import ProviderRegistry


def test_completed_media_read_projection_clears_stale_waiting_text_only():
    from app.delivery_findings import annotate_delivery
    answer = '视频请求已受理，正在等待生成结果。\n产物仍在生成或加载中，保存完成后更新结果。\n作品已生成并保存到右侧画布。'
    data = {'answer': answer, 'delivery': {'artifacts':[{'ready':True}]}}
    annotate_delivery(data)
    assert data['answer'] == '作品已生成并保存到右侧画布。'
    pending = {'answer':answer,'delivery':{'pendingMedia':['job']}}
    annotate_delivery(pending)
    assert pending['answer'] == answer
    data['answer'] = '本轮生成已结束，作品已保存到右侧画布。\n作品已生成并保存到右侧画布。'
    annotate_delivery(data)
    assert data['answer'] == '本轮生成已结束，作品已保存到右侧画布。'


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='功能验证', slug='flow', brief='网页设计', budget_minor=None, currency='CNY', root_path=str(tmp_path/'flow')))
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
    return store, project['id'], AssetStore(store), CanvasStore(store)


@pytest.mark.parametrize('api', ['chat_completions', 'responses'])
def test_native_vision_research_design_without_review_or_repeated_calls(workspace, api):
    store, project, assets, canvas = workspace
    fixtures = Path(__file__).parent/'fixtures'
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'PYTHONPATH': str(root), 'FIXTURE_PYTHON': sys.executable, 'FIXTURE_TOOL_SCRIPT': str(fixtures/'agent_tool_fixture.py'), 'FIXTURE_WORKSPACE': str(store.workspace_root), 'FIXTURE_PROJECT': project}
    inspected_image = io.BytesIO()
    Image.new('RGB', (24, 24), '#236b78').save(inspected_image, format='PNG')
    inspected = assets.add_bytes(project_id=project, kind='image', filename='inspection.png', content=inspected_image.getvalue())
    env['FIXTURE_INSPECT_ASSET'] = inspected['id']
    env['FIXTURE_TASK'] = 'fixture-task'
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?, 'design','design','running',?, '2026-09-14','2026-09-14')",('fixture-task',project,json.dumps({'userMessage':'请生成可交互的网页并研究来源','allowExternalNetwork':True})))
    catalog=ModelCatalog(store)
    settings=catalog.settings().model_dump(mode='json')
    settings['prices'][catalog.price_key('openrouter','http://fixture.invalid/v1','fixture-model')]={'currency':'CNY','perRequest':.01}
    from app.model_config import ModelSettings
    catalog.save_settings(ModelSettings.model_validate(settings))
    payload = {'persistentSessions':True,'api': api, 'model': 'fixture-model', 'apiKey': 'fixture-secret', 'baseUrl': 'http://fixture.invalid/v1',
        'toolGateway': {'baseUrl': 'http://fixture.invalid', 'projectId': project,'taskId':'fixture-task'}, 'context': {'projectId': project, 'taskId': 'fixture-task', 'brief': '请生成可交互的网页并研究来源', 'attachments': [{'filename': 'image.png', 'mime': 'image/png', 'data': 'aW1hZ2U='}], 'constraints': {'allowExternalNetwork': True, 'executionFlow': 'research_design_review'}}}
    result = subprocess.run([shutil.which('node'), '--import', (fixtures/'collaboration_transport.mjs').resolve().as_uri(), str(root/'app/openai_agent_worker.mjs')], input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, env=env, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout[-12000:]
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    final = next(e['result'] for e in events if e['type']=='result')
    assert final['provenance']['stages'] == ['research','design']
    assert 'review' not in final['structured_data']
    assert final['structured_data']['sources'][0]['url'] == 'https://example.com/research'
    assert len(canvas.load(project)['nodes']) == 1
    assert '<button' not in canvas.load(project)['nodes'][0]['data']['html']
    checkpoint = [e for e in events if e['type']=='checkpoint'][-1]['recovery']
    assert checkpoint['sessions']['design']
    assert len([e for e in events if e['type']=='usage']) == 5
    # Simulate losing the final result after all stage checkpoints were saved.
    payload['recovery'] = checkpoint
    restored = subprocess.run([shutil.which('node'), '--import', (fixtures/'collaboration_transport.mjs').resolve().as_uri(), str(root/'app/openai_agent_worker.mjs')], input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, env={**env,'FIXTURE_NO_MODEL_CALLS':'1'}, timeout=60)
    assert restored.returncode == 0, restored.stdout[-3000:]
    resumed_events = [json.loads(line) for line in restored.stdout.splitlines() if line.startswith('{')]
    resumed = next(e['result'] for e in resumed_events if e['type']=='result')
    assert resumed['provenance']['modelRequestCount'] == 0
    assert 'review' not in resumed['structured_data']
    assert resumed['structured_data']['deliveryStatus'] == 'passed'
    assert not any(e['type']=='usage' for e in resumed_events)
    assert len(canvas.load(project)['nodes']) == 1


def test_tool_receipt_and_checkpoint_survive_restart(workspace):
    store, project, assets, canvas = workspace
    registry = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    args = {'html': '<h1>Persisted</h1>'}
    first = registry.execute(project_id=project, task_id='task', name='canvas_create_html', arguments=args)
    ExecutionStore(store).save('task', {'stages': {'research':'evidence'}, 'sessions': {'research':[]}})
    restarted = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    assert restarted.execute(project_id=project, task_id='task', name='canvas_create_html', arguments=args) == first
    assert len(canvas.load(project)['nodes']) == 1
    state = ExecutionStore(store).load('task')
    assert state['stages']['research'] == 'evidence' and state['toolOutputs'][0]['output']['node']['id'] == first['node']['id']
    journal = ExecutionStore(store)
    journal.claim('interrupted', 'generate_image', {'prompt':'paid request'})
    with pytest.raises(RuntimeError, match='阻止重复'):
        journal.claim('interrupted', 'generate_image', {'prompt':'paid request'})


def test_video_background_completion_recovery_and_no_duplicate_assets(workspace):
    store, project, assets, canvas = workspace
    target = canvas.create_node(project, kind='video', title='视频', data={'generating':True})
    calls = []
    def retrieve(**kwargs):
        calls.append(kwargs)
        return {'status':'completed', 'content':b'video-bytes', 'jobId':'upstream-job'}
    providers = SimpleNamespace(video=lambda *a, **kw: SimpleNamespace(retrieve=retrieve))
    service = VideoJobService(store, providers, assets, canvas)
    job = service.create(project, provider='openrouter', model='video', status='pending', job_id='upstream-job', prompt='文生视频', source_asset_id=None, metadata={'taskId':'task','canvasNodeId':target['id'],'source':'design-agent-tool'})
    output = {'structured_data': {'answer':'视频请求已受理，正在等待生成结果。\n产物仍在生成或加载中，保存完成后更新结果。'}, 'provenance': {'pendingMedia':[job['id']]}}
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,output_json,created_at,updated_at) VALUES (?,?, 'design','design','running',?,'now','now')", ('task',project,json.dumps(output)))
    # A fresh service finds pending jobs without an IP profile or source asset.
    service = VideoJobService(store, providers, assets, canvas)
    service.tick()
    service.refresh(project, job['id'])
    assert len(calls) == 1
    assert len(assets.list_assets(project)) == 1
    assert canvas.load(project)['nodes'][0]['data']['assetId']
    with store._connect() as db:
        row = db.execute("SELECT status,output_json FROM tasks WHERE id='task'").fetchone()
    assert row['status'] == 'succeeded'
    assert json.loads(row['output_json'])['provenance']['pendingMedia'] == []
    assert json.loads(row['output_json'])['structured_data']['answer'] == '作品已生成并保存到右侧画布。'


def test_openrouter_video_protocol_and_reference_bytes(workspace):
    _, _, _, _ = workspace
    requests = []
    class Response(io.BytesIO):
        headers = {'Content-Type':'video/mp4'}
    def respond(request, **kwargs):
        requests.append(request)
        if '/content?' in request.full_url: return Response(b'video-bytes')
        body = {'id':'job', 'status':'pending' if request.data else 'completed', 'usage':{'cost':.25}}
        return Response(json.dumps(body).encode())
    provider = OpenRouterVideoProvider(provider_key='openrouter', credentials=SimpleNamespace(get=lambda _: 'secret'), endpoint='https://openrouter.ai/api/v1', model='bytedance/seedance-2.5')
    with patch('app.providers.openrouter_video.urllib.request.build_opener', return_value=SimpleNamespace(open=respond)):
        assert provider.generate(prompt='生成视频', duration=5, generate_audio=False)['jobId']=='job'
        result = provider.retrieve(job_id='job')
    assert requests[0].full_url.endswith('/videos')
    assert json.loads(requests[0].data)['generate_audio'] is False
    assert requests[1].full_url.endswith('/videos/job')
    assert result['content'] == b'video-bytes'
    assert provider.last_response['usage']['cost'] == .25


def test_openrouter_audio_stream_collects_audio_and_usage():
    events = [{'choices':[{'delta':{'audio':{'data':base64.b64encode(part).decode()}}}]} for part in [b'ID3', b'audio']]
    events.append({'choices':[], 'usage':{'cost':.1}})
    stream = io.BytesIO((''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n').encode())
    provider = OpenAICompatibleSpeechProvider('https://openrouter.ai/api/v1', 'openrouter', 'any-audio-output', SimpleNamespace(get=lambda _: 'secret'), api='chat_completions')
    with patch('app.providers.http.urllib.request.urlopen', return_value=stream) as call:
        assert provider.generate(text='你好') == b'ID3audio'
        assert json.loads(call.call_args.args[0].data)['stream'] is True
    assert provider.last_response['usage']['cost'] == .1


def test_explicit_text_or_html_node_model_overrides_global_auto(workspace):
    store, project, assets, canvas = workspace
    catalog = ModelCatalog(store)
    providers = ProviderRegistry(); providers.catalog = catalog
    calls=[]
    def run(**kwargs):
        calls.append(kwargs)
        return AgentResult(status='succeeded', structured_data={'answer':'ok'}, provenance={'artifactKinds':[kwargs['constraints']['canvasParams']['kind']]})
    runtime = RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store)
    for kind in ['text','html']:
        runtime.run(project_id=project, task_id=kind, brief='设计需求', provider_ref={'key':'openrouter','baseUrl':'https://relay.test/v1','model':'global'}, constraints={'modelRouting':{'mode':'auto'},'canvasParams':{'kind':kind,'model':'explicit'}})
    assert all(c['provider_ref']['model']=='explicit' for c in calls)


def test_media_wait_recovery_does_not_resubmit_an_agent(workspace):
    from app.task_runtime import TaskRuntime
    store, project, assets, canvas = workspace
    runtime = TaskRuntime(store, asset_store=assets, design_runtime=SimpleNamespace(run=lambda **_: pytest.fail('unexpected SDK call')))
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,output_json,created_at,updated_at) VALUES (?,?, 'design','design','running',?,'now','now')", ('media-wait',project,json.dumps({'provenance':{'pendingMedia':['existing-job']}})))
    with patch.object(runtime, '_start_worker', side_effect=AssertionError('resubmitted worker')):
        assert runtime.recover_pending() == 1
    assert runtime.get_task(project, 'media-wait')['status'] == 'running'


def test_failed_video_completes_task_with_visible_error(workspace):
    store, project, assets, canvas = workspace
    node = canvas.create_node(project, kind='video', title='视频', data={'generating': True})
    providers = SimpleNamespace(video=lambda *a, **kw: SimpleNamespace(retrieve=lambda **_: {'status':'failed', 'error':'生成失败详情'}))
    service = VideoJobService(store, providers, assets, canvas)
    job = service.create(project, provider='openrouter', model='video', status='pending', job_id='upstream', prompt='video', source_asset_id=None, metadata={'taskId':'failed-video', 'canvasNodeId':node['id']})
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,output_json,created_at,updated_at) VALUES (?,?, 'design','design','running',?,'now','now')", ('failed-video',project,json.dumps({'structured_data':{}, 'provenance':{'pendingMedia':[job['id']]}})))
    service.tick()
    with store._connect() as db:
        row = db.execute("SELECT status,error_json FROM tasks WHERE id='failed-video'").fetchone()
    assert row['status'] == 'failed' and json.loads(row['error_json'])['message']
    assert canvas.load(project)['nodes'][0]['data']['generating'] is False
    assert canvas.load(project)['nodes'][0]['data']['error'] == '生成失败详情'


def test_asset_inspection_returns_native_image_only_for_current_project(workspace):
    store, project, assets, canvas = workspace
    source = io.BytesIO()
    Image.new('RGBA', (20, 10), (35, 107, 120, 180)).save(source, format='PNG')
    asset = assets.add_bytes(project_id=project, kind='image', filename='picture.png', content=source.getvalue())
    registry = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    result = registry.execute(project_id=project, task_id=None, name='asset_inspect', arguments={'asset_id':asset['id']})
    assert result['image'].startswith('data:image/jpeg;base64,')
    assert result['visionPreview']['normalized'] is True
    assert result['visionPreview']['width'] == 20 and result['visionPreview']['height'] == 10
    assert 'absolutePath' not in result


def test_generate_text_uses_selected_model_and_persists_node(workspace):
    store, project, assets, canvas = workspace
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?, 'design','design','running',?,'now','now')", ('text-task',project,json.dumps({'textProvider':{'key':'openrouter','baseUrl':'https://relay.test/v1','model':'default'}})))
    calls=[]
    def text(key, **kwargs):
        calls.append((key,kwargs))
        return SimpleNamespace(complete=lambda **_: '真实模型输出')
    registry = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=SimpleNamespace(text=text))
    result = registry.execute(project_id=project, task_id='text-task', name='generate_text', arguments={'model':'selected','prompt':'文案'})
    assert calls[0][1]['model']=='selected'
    assert result['node']['data']['text']=='真实模型输出'


def test_generate_text_reuses_the_active_agent_endpoint_in_auto_mode(workspace):
    store, project, assets, canvas = workspace
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?, 'design','design','running',?,'now','now')", ('text-route-task',project,json.dumps({'textProvider':{'key':'openrouter','baseUrl':'https://ui-placeholder.test/v1','model':'ui-placeholder'}})))
    calls=[]
    def text(key, **kwargs):
        calls.append((key,kwargs))
        return SimpleNamespace(complete=lambda **_: '沿用主 Agent 端点')
    registry = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=SimpleNamespace(text=text))
    result = registry.execute(project_id=project, task_id='text-route-task', name='generate_text', arguments={
        'model':'agent-suggested-model', 'prompt':'文案',
        '_model_context':{'provider':'openai-compatible','baseUrl':'https://closeai.test/v1','model':'gpt-5.6-terra','api':'responses','tier':'STANDARD','routeSource':'automatic'},
    })
    assert calls == [('openai-compatible', {'base_url':'https://closeai.test/v1','model':'gpt-5.6-terra'})]
    assert result['node']['data']['text']=='沿用主 Agent 端点'


def test_video_download_does_not_forward_key_to_cdn():
    import urllib.error
    from email.message import Message
    provider = OpenRouterVideoProvider(provider_key='openrouter', credentials=SimpleNamespace(get=lambda _: 'secret'), endpoint='https://openrouter.ai/api/v1', model='video')
    headers = Message(); headers['Location']='https://cdn.example.com/signed-video.mp4'
    class Response(io.BytesIO):
        headers={'Content-Type':'video/mp4'}
    def redirect(request, **_):
        assert request.get_header('Authorization') == 'Bearer secret'
        raise urllib.error.HTTPError(request.full_url, 302, 'redirect', headers, None)
    with patch('app.providers.openrouter_video.urllib.request.build_opener', return_value=SimpleNamespace(open=redirect)), patch('app.providers.openrouter_video.urllib.request.urlopen', return_value=Response(b'video')) as download:
        assert provider._request('/videos/job/content?index=0', binary=True) == b'video'
        # The redirect request is a URL string, not the authenticated Request.
        assert download.call_args.args == ('https://cdn.example.com/signed-video.mp4',)


def test_validation_error_allows_correction_but_ambiguous_generation_blocks(workspace):
    store, project, assets, canvas = workspace
    journal = ExecutionStore(store)
    fingerprint, _ = journal.claim('request','generate_video',{'prompt':'original'})
    with pytest.raises(RuntimeError, match='改写提示词'):
        journal.claim('request','generate_video',{'prompt':'rewritten'})
    journal.reject('request', fingerprint)
    assert journal.claim('request','generate_video',{'prompt':'corrected'})[1] is None
