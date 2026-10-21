import base64
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.design_tools import DesignToolError
from app.model_config import DEFAULT_IMAGE_MODEL
from app.providers.http import ProviderError
from app.providers.openrouter_image import OpenRouterImageProvider
from app.providers.registry import ProviderRegistry
from test_image_dispatch import Response, image_bytes, registry, workspace


class StreamResponse(io.BytesIO):
    headers = {'Content-Type': 'text/event-stream; charset=utf-8'}

    def __init__(self, events, done=True):
        body = ': heartbeat\r\n\r\n' + ''.join(
            'data: ' + json.dumps(event) + '\r\n\r\n' for event in events)
        super().__init__((body + ('data: [DONE]\r\n\r\n' if done else '')).encode())


def adapter(stream=True):
    return OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', DEFAULT_IMAGE_MODEL,
                                   SimpleNamespace(get=lambda _: 'fixture-key'), supports_streaming=stream)


def complete_event():
    return {'type': 'image_generation.completed', 'b64_json': base64.b64encode(image_bytes()).decode(),
            'media_type': 'image/png', 'created': 1, 'usage': {'cost': 0.2, 'completion_tokens': 20}}


def test_streamed_creative_image_preserves_usage_and_ignores_previews(workspace, monkeypatch):
    project, _, canvas, _ = workspace
    provider = adapter()
    calls = []

    def dispatch(request, **kwargs):
        calls.append(json.loads(request.data))
        assert calls[-1]['stream'] is True
        assert calls[-1]['model'] == DEFAULT_IMAGE_MODEL and calls[-1]['quality'] == 'low'
        assert calls[-1]['resolution'] == '1K'
        # Model a response that needs longer than the old 180-second read limit.
        if kwargs['timeout'] <= 200:
            raise TimeoutError('high-quality edit not ready yet')
        return StreamResponse([{'type': 'image_generation.partial_image', 'b64_json': 'preview-only'}, complete_event()])

    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    tools = registry(workspace, provider)
    result = tools.execute(project_id=project, task_id='task', name='generate_image',
                           arguments={'prompt': '产品套系', 'provider': 'openrouter', 'model': DEFAULT_IMAGE_MODEL})
    assert len(calls) == 1 and len(canvas.load(project)['nodes']) == 1
    assert result['imageOutput']['verified'] and result['asset']['byteSize'] == len(image_bytes())
    assert provider.last_response['usage']['cost'] == 0.2
    assert provider.last_response['data'][0]['media_type'] == 'image/png'


@pytest.mark.parametrize('support', [True, False, None])
def test_registry_uses_only_saved_streaming_capability(support):
    providers = ProviderRegistry(SimpleNamespace(get=lambda _: 'fixture-key'))
    providers.catalog = SimpleNamespace(record=lambda *a: {'supports_streaming': support})
    assert providers.image('openrouter', model=DEFAULT_IMAGE_MODEL).supports_streaming is (support is True)


def test_json_response_to_stream_request_does_not_resubmit(monkeypatch):
    calls = []
    def dispatch(request, **kwargs):
        calls.append(json.loads(request.data))
        return Response({'data': [{'b64_json': complete_event()['b64_json']}], 'usage': {'cost': 0.2}})
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    assert adapter().generate(prompt='封面') == image_bytes()
    assert len(calls) == 1 and calls[0]['stream'] is True


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('multiple', [False, True])
def test_edit_disables_streaming_before_dispatch_and_preserves_inputs(tmp_path, monkeypatch, stream, multiple):
    sources = [tmp_path / 'original.png', tmp_path / 'second.png']
    for source in sources:
        source.write_bytes(image_bytes())
    calls = []
    provider = adapter(stream)

    def dispatch(request, **kwargs):
        payload = json.loads(request.data)
        calls.append(payload)
        # Reproduce the production service's exact rejection if this regresses.
        if payload['stream']:
            raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {}, io.BytesIO(
                b'{"error":{"message":"Streaming is not supported for image-to-image (edit) requests"}}'))
        return Response({'data': [{'b64_json': complete_event()['b64_json']}], 'usage': {'cost': 0.2}})

    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    paths = [str(source) for source in (sources if multiple else sources[:1])]
    assert provider.generate(prompt='只添加竹制底座，其余保持不变', source_asset_path=paths[0],
                             source_asset_paths=paths, quality='high', resolution='2K') == image_bytes()
    assert len(calls) == 1
    payload = calls[0]
    assert payload['stream'] is False
    assert payload['model'] == DEFAULT_IMAGE_MODEL and payload['quality'] == 'high' and payload['resolution'] == '2K'
    assert payload['prompt'].startswith('只添加竹制底座，其余保持不变')
    assert len(payload['input_references']) == len(paths)
    assert all(base64.b64decode(item['image_url']['url'].split(',', 1)[1]) == image_bytes()
               for item in payload['input_references'])
    assert provider.last_response['usage']['cost'] == 0.2


def test_gateway_stops_explicit_streaming_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': 'streaming boundary'}).json()['id']
        from test_conversation_context import add_turn
        add_turn(app.state.store, 'stream-task', '产品图', project=project, status='running')
        monkeypatch.setattr(app.state.providers, 'image', lambda *a, **k: adapter())
        calls = []
        def reject(request, **kwargs):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {}, io.BytesIO(
                b'{"error":{"message":"Streaming is not supported for image-to-image (edit) requests"}}'))
        monkeypatch.setattr('urllib.request.urlopen', reject)
        response = client.post(f'/api/projects/{project}/agent-tools/generate_image',
                               headers={'x-aics-task-id': 'stream-task'}, json={'prompt': '产品图'})
        assert response.status_code == 422
        result = response.json()
        assert result['errorCode'] == 'image_streaming_unsupported'
        assert result['stopTool'] and result['retryable'] is False
        assert '不表示原图不支持编辑' in result['detail']
        assert len(calls) == 1
        assert app.state.design_tools.canvas_store.load(project)['nodes'] == []


@pytest.mark.parametrize('failure', ['timeout', 'wrapped_timeout', 'disconnect', 'partial_only', 'malformed_stream'])
def test_unknown_result_keeps_receipt_and_blocks_changed_prompt(workspace, monkeypatch, failure):
    project, store, canvas, assets = workspace
    calls = []
    def dispatch(request, **kwargs):
        calls.append(request)
        if failure == 'timeout': raise TimeoutError('read timed out')
        if failure == 'wrapped_timeout': raise urllib.error.URLError(TimeoutError('read timed out'))
        if failure == 'disconnect': raise ConnectionResetError('disconnected')
        if failure == 'malformed_stream':
            response = StreamResponse([])
            response.write(b'data: {invalid json}\n\n')
            response.seek(0)
            return response
        return StreamResponse([{'type': 'image_generation.partial_image', 'b64_json': complete_event()['b64_json']}], done=False)
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    tools = registry(workspace, adapter())
    with pytest.raises(ProviderError) as failed:
        tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': '封面'})
    assert failed.value.stop_tool and not failed.value.response_received
    assert failed.value.error_code == ('image_response_timeout' if 'timeout' in failure else 'image_result_unconfirmed')
    assert '结果待确认' in str(failed.value)
    with store._connect() as db:
        assert db.execute("SELECT status FROM tool_receipts WHERE task_id='task'").fetchone()[0] == 'running'
    assert not assets.list_assets(project)
    node = canvas.load(project)['nodes'][0]
    assert not node['data']['generating'] and node['data']['status'] == '生成结果待确认'
    # Reconstruct the registry to exercise the persisted receipt, not memory.
    with pytest.raises(DesignToolError, match='尚未确认'):
        registry(workspace, adapter()).execute(project_id=project, task_id='task', name='generate_image',
                                               arguments={'prompt': '改写提示词再次提交'})
    assert len(calls) == 1


@pytest.mark.parametrize('stream_error', [False, True])
def test_completed_invalid_response_stops_without_retry(workspace, monkeypatch, stream_error):
    project, store, canvas, _ = workspace
    calls = []
    def dispatch(request, **kwargs):
        calls.append(request)
        return (StreamResponse([{'type': 'error', 'error': {'message': 'fixture-key generation failed'}}]) if stream_error
                else Response({'data': [{'b64_json': 'not base64'}]}))
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    tools = registry(workspace, adapter())
    with pytest.raises(ProviderError) as failed:
        tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': '封面'})
    assert failed.value.stop_tool and failed.value.response_received
    assert 'fixture-key' not in str(failed.value)
    with store._connect() as db:
        receipt = db.execute("SELECT status,output FROM tool_receipts WHERE task_id='task'").fetchone()
    assert receipt['status'] == 'completed' and json.loads(receipt['output'])['stopTool']
    assert canvas.load(project)['nodes'][0]['data']['status'] == '生成失败'
    with pytest.raises(DesignToolError):
        tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': '改写后重试'})
    assert len(calls) == 1


def test_gateway_returns_unconfirmed_timeout_and_keeps_unknown_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': 'timeout boundary'}).json()['id']
        from test_conversation_context import add_turn
        add_turn(app.state.store, 'timeout-task', '封面', project=project, status='running')
        monkeypatch.setattr(app.state.providers, 'image', lambda *a, **k: adapter())
        def timeout(*a, **k): raise TimeoutError('no response')
        monkeypatch.setattr('urllib.request.urlopen', timeout)
        response = client.post(f'/api/projects/{project}/agent-tools/generate_image',
                               headers={'x-aics-task-id': 'timeout-task'}, json={'prompt': '封面'})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'generation_unconfirmed' and response.json()['retryable'] is False
        assert response.json()['errorCode'] == 'image_response_timeout'
        assert response.json()['billingCertainty'] == 'unknown'
        assert client.post(f'/api/projects/{project}/tasks/timeout-task/tool-result',json={'name':'generate_image','arguments':{'prompt':'封面'}}).json()=={'state':'unconfirmed'}
        retry=client.post(f'/api/projects/{project}/agent-tools/generate_image',headers={'x-aics-task-id':'timeout-task'},json={'prompt':'封面'})
        assert retry.status_code==422 and '尚未确认' in retry.text
        with app.state.store._connect() as db:
            assert db.execute("SELECT status FROM tool_receipts WHERE task_id='timeout-task'").fetchone()[0] == 'running'
