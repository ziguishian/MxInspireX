import base64
import io
import json
import urllib.error
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.image_parameters import ImageParameterError, nearest_native_gpt_size, prepare_image_parameters
from app.image_quality import apply_image_quality
from app.main import app
from app.providers.http import OpenAICompatibleImageProvider, ProviderError
from app.providers.openrouter_image import OpenRouterImageProvider
from test_image_dispatch import Response, image_bytes, registry, workspace


# OpenRouter discovery snapshot, 2026-09-16. These are model capabilities,
# separate from both the router's global ratios and native Images API limits.
# https://openrouter.ai/api/v1/images/models
SUNBURST_ROUTER_PARAMETERS = {
    'aspect_ratio': {'type': 'enum', 'values': ['1:1', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16', '21:9', 'auto']},
    'quality': {'type': 'enum', 'values': ['auto', 'low', 'medium', 'high', 'xhigh', 'max']},
}
NATIVE_INVALID_SIZES = ['1025x1536', '4096x4096', '3840x3840', '2048x512', '512x512']


@pytest.mark.parametrize('size,expected', [
    ('3840x1200', '3840x1280'),
    ('1025x1536', '1024x1536'),
    ('4096x4096', '2880x2880'),
    ('512x512', '816x816'),
])
def test_nearest_native_size_repairs_only_mechanical_dimension_errors(size, expected):
    assert nearest_native_gpt_size(size) == expected


@pytest.mark.parametrize('model', ['gpt-image-2.5-sunburst', 'openai/gpt-image-2.5-flare', 'gpt-image-2.5-sunburst-2026-09-08'])
@pytest.mark.parametrize('tier,expected', [('final', 'high'), ('standard', 'medium'), ('draft', 'low')])
def test_model_specific_quality(model, tier, expected):
    options, report = apply_image_quality({'quality': 'high', 'input_fidelity': 'high'}, model=model, tier=tier, has_references=True)
    assert options['quality'] == expected == report['quality'] == report['requestedQuality']
    assert 'input_fidelity' not in options and 'inputFidelity' not in report


@pytest.mark.parametrize('size', ['1024x1536', '1536x864', '1024x1280', '3840x2160'])
def test_explicit_size_wins_over_inherited_hints(size):
    for gateway in (False, True):
        options = prepare_image_parameters({'size': size, 'aspectRatio': '4:5', 'aspect_ratio': '1:1', 'resolution': '4K'}, model='gpt-image-2.5-sunburst', openrouter=gateway)
        assert options == {'size': size, 'quality': 'max'}


@pytest.mark.parametrize('size', NATIVE_INVALID_SIZES)
def test_native_invalid_dimensions_never_dispatch(size):
    adapter = OpenAICompatibleImageProvider('https://fixture.invalid/v1', 'fixture', 'gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'test-key'))
    with patch('urllib.request.urlopen') as transport, pytest.raises(ProviderError) as error:
        adapter.generate(prompt='海报', size=size)
    assert error.value.status_code == 400
    assert isinstance(error.value.__cause__, ImageParameterError)
    assert f'size={size}' in str(error.value)
    transport.assert_not_called()


@pytest.mark.parametrize('adapter_type', [OpenAICompatibleImageProvider, OpenRouterImageProvider])
@pytest.mark.parametrize('size', ['bad-size', '0x1024', '-16x1024', '1024x'])
def test_malformed_dimensions_never_dispatch(size, adapter_type):
    adapter = adapter_type('https://fixture.invalid/v1', 'fixture', 'gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'test-key'))
    with patch('urllib.request.urlopen') as transport, pytest.raises(ProviderError) as error:
        adapter.generate(prompt='海报', size=size)
    assert error.value.status_code == 400
    assert isinstance(error.value.__cause__, ImageParameterError)
    transport.assert_not_called()


@pytest.mark.parametrize('size', NATIVE_INVALID_SIZES)
def test_openrouter_explicit_pixels_are_dispatched_for_router_normalization(size):
    adapter = OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', 'openai/gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'test-key'),
                                     supported_parameters=SUNBURST_ROUTER_PARAMETERS)
    content = image_bytes()
    response = Response({'data': [{'b64_json': base64.b64encode(content).decode()}]})
    with patch('urllib.request.urlopen', return_value=response) as transport:
        result = adapter.generate(prompt='海报', size=size, aspectRatio='4:5', resolution='4K')
    assert result == content and transport.call_count == 1
    payload = json.loads(transport.call_args.args[0].data)
    assert payload['size'] == size and payload['quality'] == 'max'
    assert 'aspect_ratio' not in payload and 'resolution' not in payload


@pytest.mark.parametrize('ratio,size', [('1:1', '1024x1024'), ('3:2', '1536x1024'), ('2:3', '1024x1536'), ('16:9', '1536x864'), ('9:16', '864x1536')])
def test_direct_api_converts_ratio_to_valid_pixels(ratio, size):
    options = prepare_image_parameters({'size': 'auto', 'aspectRatio': ratio}, model='gpt-image-2.5-flare')
    assert options == {'quality': 'max', 'size': size}


@pytest.mark.parametrize('resolution', ['1K', '2K', '4K'])
@pytest.mark.parametrize('ratio', ['1:1', '16:9', '4:5', '3:1'])
def test_derived_dimensions_stay_in_model_limits(resolution, ratio):
    options = prepare_image_parameters({'aspectRatio': ratio, 'resolution': resolution}, model='gpt-image-2.5-sunburst')
    width, height = map(int, options['size'].split('x'))
    assert not width % 16 and not height % 16
    assert max(width, height) <= 3840 and 655360 <= width * height <= 8294400
    a, b = map(int, ratio.split(':'))
    assert width * b == height * a


@pytest.mark.parametrize('ratio', ['4:5', '5:4', '1:2', '16:10', '8:5', '3:1'])
@pytest.mark.parametrize('resolution', [None, '1K', '2K', '4K'])
def test_openrouter_ratios_missing_from_model_catalog_use_exact_valid_pixels(ratio, resolution):
    params = {'aspectRatio': ratio, **({'resolution': resolution} if resolution else {})}
    options = prepare_image_parameters(params, model='openai/gpt-image-2.5-sunburst', openrouter=True,
                                       supported_parameters=SUNBURST_ROUTER_PARAMETERS)
    width, height = map(int, options['size'].split('x'))
    a, b = map(int, ratio.split(':'))
    assert width * b == height * a
    assert width % 16 == height % 16 == 0
    assert max(width, height) <= 3840 and 655360 <= width * height <= 8294400
    assert set(options) == {'size', 'quality'} and options['quality'] == 'max'
    assert prepare_image_parameters(options, model='openai/gpt-image-2.5-sunburst', openrouter=True,
                                    supported_parameters=SUNBURST_ROUTER_PARAMETERS) == options


@pytest.mark.parametrize('ratio', ['4:5', '5:4', '1:2'])
@pytest.mark.parametrize('resolution', [None, '1K', '2K', '4K'])
def test_openrouter_without_model_catalog_keeps_router_ratio_and_tier(ratio, resolution):
    params = {'aspectRatio': ratio, **({'resolution': resolution} if resolution else {})}
    options = prepare_image_parameters(params, model='openai/gpt-image-2.5-sunburst', openrouter=True)
    assert options == {'aspect_ratio': ratio, 'quality': 'max', **({'resolution': resolution} if resolution else {})}


@pytest.mark.parametrize('supported_parameters', [None, SUNBURST_ROUTER_PARAMETERS])
@pytest.mark.parametrize('ratio', ['16:10', '8:5', '3:1'])
def test_openrouter_unlisted_gpt_ratio_uses_exact_pixels(supported_parameters, ratio):
    options = prepare_image_parameters({'aspectRatio': ratio, 'resolution': '2K'}, model='openai/gpt-image-2.5-sunburst', openrouter=True,
                                       supported_parameters=supported_parameters)
    width, height = map(int, options['size'].split('x'))
    a, b = map(int, ratio.split(':'))
    assert width * b == height * a and width % 16 == height % 16 == 0
    assert set(options) == {'size', 'quality'}
    if ratio != '3:1': assert options['size'] == '2048x1280'
    options = prepare_image_parameters({'size': '2400x800'}, model='openai/gpt-image-2.5-sunburst', openrouter=True,
                                       supported_parameters=supported_parameters)
    assert options == {'size': '2400x800', 'quality': 'max'}


@pytest.mark.parametrize('ratio,normalized', [('32:18', '16:9'), ('6:8', '3:4'), ('47:20', '2.35:1')])
def test_openrouter_equivalent_ratios_use_supported_wire_spelling(ratio, normalized):
    assert prepare_image_parameters({'aspectRatio': ratio}, model='generic-image', openrouter=True) == {'aspect_ratio': normalized}


def test_non_custom_model_does_not_invent_support_for_arbitrary_ratios():
    with pytest.raises(ImageParameterError, match='aspect_ratio=16:10'):
        prepare_image_parameters({'aspectRatio': '16:10'}, model='generic-image', openrouter=True)


def test_openrouter_invalid_ratio_is_repairable_before_loading(workspace, monkeypatch):
    project, store, canvas, _ = workspace
    adapter = OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', 'openai/gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'test-key'),
                                     supported_parameters=SUNBURST_ROUTER_PARAMETERS)
    tools = registry(workspace, adapter)
    args = {'prompt': '制作海报', 'provider': 'openrouter', 'model': adapter.model, 'params': {'aspectRatio': '4:13'}}
    with patch('urllib.request.urlopen') as transport:
        rejected = tools.execute(project_id=project, task_id='task', name='generate_image', arguments=args)
    assert rejected['status'] == 'image_parameters_invalid'
    assert '3:1' in rejected['instruction']
    transport.assert_not_called()
    assert not canvas.load(project)['nodes']
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM tool_receipts WHERE status='running'").fetchone()[0] == 0
    calls = []
    def dispatch(request, **kwargs):
        payload = json.loads(request.data)
        calls.append(payload)
        assert payload['quality'] == 'low' and payload['aspect_ratio'] == '3:4' and payload['resolution'] == '1K'
        assert canvas.load(project)['nodes'][0]['data']['generating']
        return Response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    corrected = {**args, 'params': {'aspectRatio': '3:4'}}
    result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments=corrected)
    replay = tools.execute(project_id=project, task_id='task', name='generate_image', arguments=corrected)
    assert len(calls) == 1
    assert result['asset']['metadata']['imageQuality']['quality'] == 'low'
    assert replay['assetId'] == result['assetId']


def test_agent_derived_native_pixels_only_supply_ratio_at_creative_resolution(workspace, monkeypatch):
    project, _, _, _ = workspace
    adapter = OpenAICompatibleImageProvider(
        'https://fixture.invalid/v1', 'openai-image', 'gpt-image-2.5-sunburst',
        SimpleNamespace(get=lambda _: 'test-key'),
    )
    tools = registry(workspace, adapter)
    arguments = {
        'prompt': '三比一横版背景', 'provider': 'openai-image',
        'model': adapter.model, 'params': {'size': '3840x1200'},
    }
    checked = tools.execute(
        project_id=project, task_id='task', name='generation_reference_check',
        arguments={'operations':[{'tool':'generate_image','arguments':arguments}]},
    )
    assert checked['status'] == 'ready'
    assert checked['imageRequests'][0]['params']['size'] == '1440x480'
    assert not checked['imageRequests'][0]['parameterAdjustments']
    response = Response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    with patch('urllib.request.urlopen', return_value=response) as transport:
        result = tools.execute(
            project_id=project, task_id='task', name='generate_image',
            arguments=arguments,
        )
    payload = json.loads(transport.call_args.args[0].data)
    assert payload['size'] == '1440x480'
    assert result['asset']['metadata']['imageQuality']['discardToolDimensions'] is True
    assert result['asset']['metadata']['imageQuality']['resolution'] == '1K'
    assert result['imageRoute']['parameterAdjustments'] == []


def test_parallel_generations_each_send_creative_policy(workspace, monkeypatch):
    project, _, _, _ = workspace
    adapter = OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', 'openai/gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'test-key'))
    tools = registry(workspace, adapter)
    barrier, calls = threading.Barrier(2), []
    def dispatch(request, **kwargs):
        calls.append(json.loads(request.data))
        barrier.wait(timeout=5)
        return Response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    def generate(prompt):
        return tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': prompt, 'provider': 'openrouter', 'model': adapter.model})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(generate, ['纸杯', '帆布袋']))
    assert len(calls) == len({r['assetId'] for r in results}) == 2
    assert all(payload['quality'] == 'low' and payload['resolution'] == '1K' for payload in calls)


@pytest.mark.parametrize('adapter_type,provider_key,model', [
    (OpenAICompatibleImageProvider, 'openai-image', 'gpt-image-2.5-sunburst'),
    (OpenRouterImageProvider, 'openrouter', 'openai/gpt-image-2.5-sunburst'),
])
def test_direct_high_resolution_and_regeneration_preserve_explicit_quality(tmp_path, monkeypatch, adapter_type, provider_key, model):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    adapter = adapter_type('https://fixture.invalid/v1', provider_key, model, SimpleNamespace(get=lambda _: 'test-key'))
    response = Response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    with TestClient(app) as client, patch.object(app.state.providers, 'image', return_value=adapter), patch('urllib.request.urlopen', return_value=response) as transport:
        app.state.model_catalog.save(provider_key, adapter.base_url, {'models': [model]})
        project = client.post('/api/projects', json={'name': 'quality max'}).json()['id']
        result = client.post(f'/api/projects/{project}/generations/image', json={'prompt': '先试试效果', 'provider': provider_key, 'baseUrl': adapter.base_url, 'model': model, 'params': {'size': '1536x864', 'resolution': '4K', 'aspectRatio': '4:5'}})
        assert result.status_code == 201, result.text
        payload = json.loads(transport.call_args.args[0].data)
        assert payload['quality'] == 'high' and payload['size'] == '1536x864'
        assert 'resolution' not in payload and 'aspect_ratio' not in payload and 'input_fidelity' not in payload
        metadata = result.json()['asset']['metadata']
        assert metadata['imageQuality']['quality'] == 'high' and metadata['params']['size'] == '1536x864'
        assert 'resolution' not in metadata['params']
        regenerated = client.post(f'/api/projects/{project}/generations/{result.json()["generationId"]}/regenerate', json={'baseUrl': adapter.base_url})
        assert regenerated.status_code == 201, regenerated.text
        raw = transport.call_args.args[0].data
        if provider_key == 'openrouter':
            payload = json.loads(raw)
            assert payload['quality'] == 'high' and len(payload['input_references']) == 1
        else:
            assert b'name="quality"\r\n\r\nhigh' in raw
            assert b'name="size"\r\n\r\n1536x864' in raw
            assert b'name="input_fidelity"' not in raw
        assert transport.call_count == 2


def test_rejection_does_not_retry_at_lower_quality():
    adapter = OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', 'openai/gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'test-key'))
    refusal = urllib.error.HTTPError('https://fixture.invalid', 400, 'bad quality', {}, io.BytesIO(b'{"error":"quality max unsupported"}'))
    with patch('urllib.request.urlopen', side_effect=refusal) as transport, pytest.raises(ProviderError, match='quality max unsupported'):
        adapter.generate(prompt='效果图')
    assert transport.call_count == 1
    assert json.loads(transport.call_args.args[0].data)['quality'] == 'max'
