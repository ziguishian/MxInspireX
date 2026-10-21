import io
import json
import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.evolink import EVOLINK_BASE_URL, normalize_evolink_model


def test_speech_uses_dedicated_async_api_and_only_download_get_retries():
    from app.providers.evolink import EvoLinkAudioProvider
    adapter = EvoLinkAudioProvider(base_url=EVOLINK_BASE_URL,provider_key='evolink',model='qwen-audio-3.1-tts-flash',credentials=Credentials())
    body={'id':'audio-original','status':'completed','results':['https://cdn.example/audio.mp3']}
    with patch.object(adapter,'_json',return_value=body) as api, patch.object(adapter,'_download',return_value=b'audio'):
        assert adapter.generate(text='欢迎来到小岛',speed=1)==b'audio'
    api.assert_called_once_with('/audios/generations',{'model':'qwen-audio-3.1-tts-flash','prompt':'欢迎来到小岛','voice':'longanhuan_v3.1','speech_rate':1,'response_format':'mp3'})


def test_result_download_retries_get_without_reposting_or_sending_key():
    from app.providers.evolink import EvoLinkImageProvider
    import io
    adapter = EvoLinkImageProvider(base_url=EVOLINK_BASE_URL,provider_key='evolink',model='gpt-image-2',credentials=Credentials())
    with patch('app.providers.evolink.urllib.request.urlopen',side_effect=[OSError('reset'),io.BytesIO(b'image')]) as download, patch('app.providers.evolink.time.sleep'), patch.object(adapter,'_json') as submit:
        assert adapter._download({'id':'original','results':['https://cdn.example/image.png']})==b'image'
    assert download.call_count==2
    assert all(not call.args[0].has_header('Authorization') and call.args[0].method=='GET' if hasattr(call.args[0],'method') else not call.args[0].has_header('Authorization') for call in download.call_args_list)
    submit.assert_not_called()
from app.image_quality import apply_image_quality
from app.main import app
from app.providers.http import ProviderError
from app.providers.registry import ProviderRegistry
from app.schedules import ProviderRef


class Credentials:
    def get(self, provider):
        return 'evolink-test-key' if provider == 'evolink' else None


def response(body):
    return io.BytesIO(json.dumps(body).encode())


def test_upload_cache_requires_valid_expiry_and_exact_file_and_credential(tmp_path):
    from app.providers.evolink import EvoLinkTransport
    EvoLinkTransport._upload_cache.clear()
    source = tmp_path / 'reference.png'
    source.write_bytes(b'first')
    adapter = ProviderRegistry(Credentials()).image('evolink', model='gpt-image-2')
    now = 1800000000
    uploaded = {'success':True, 'data':{'file_url':'https://files.evolink.ai/ref.png',
                'expires_at':datetime.fromtimestamp(now+7200,timezone.utc).isoformat()}}
    with patch('app.providers.evolink.time.time',return_value=now), patch.object(adapter,'_json',return_value=uploaded) as transport:
        assert adapter._upload(source) == adapter._upload(source)
        assert transport.call_count == 1 and adapter.last_upload_cache_hits == 1
        source.write_bytes(b'changed')
        adapter._upload(source)
        assert transport.call_count == 2
        with patch.object(adapter.credentials,'get',return_value='different-key'):
            adapter._upload(source)
        assert transport.call_count == 3
    with patch('app.providers.evolink.time.time',return_value=now+7000), patch.object(adapter,'_json',return_value=uploaded) as transport:
        adapter._upload(source)
        adapter._upload(source)
        assert transport.call_count == 2  # insufficient lifetime: no reuse
    EvoLinkTransport._upload_cache.clear()


@pytest.mark.parametrize('expiry',[None,'invalid','2026-10-21T12:00:00'])
def test_upload_without_trusted_expiry_is_never_cached(tmp_path, expiry):
    source=tmp_path/'reference.png'
    source.write_bytes(b'pixels')
    adapter=ProviderRegistry(Credentials()).image('evolink',model='gpt-image-2')
    with patch.object(adapter,'_json',return_value={'success':True,'data':{'file_url':'https://files.evolink.ai/ref.png','expires_at':expiry}}) as transport:
        adapter._upload(source)
        adapter._upload(source)
        assert transport.call_count == 2


def test_registry_text_and_schedule_share_evolink_connection():
    registry = ProviderRegistry(Credentials())
    spec = next(item for item in registry.list() if item['key'] == 'evolink')
    assert spec['configured'] and spec['defaultBaseUrl'] == EVOLINK_BASE_URL
    assert 'evolink-test-key' not in json.dumps(spec)
    provider = registry.text('evolink', model='gpt-5.4')
    with patch('urllib.request.urlopen', return_value=response({'choices': [{'message': {'content': 'ok'}}]})) as transport:
        assert provider.complete(system='system', prompt='hello') == 'ok'
    request = transport.call_args.args[0]
    assert request.full_url == EVOLINK_BASE_URL + '/chat/completions'
    assert request.get_header('Authorization') == 'Bearer evolink-test-key'
    assert ProviderRef(key='evolink', baseUrl=EVOLINK_BASE_URL, model='gpt-5.4').key == 'evolink'


def test_catalog_sync_filters_specialized_models_and_cached_read_is_offline(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('AICS_PROVIDER_KEY_EVOLINK', 'evolink-test-key')
    models = ['gpt-5.4', 'claude-sonnet-4-5', 'gemini-3.1-flash-image-preview',
              'gpt-image-2.5-sunburst', 'seedance-2.0-image-to-video', 'suno-v5',
              'evolink-moderation-1.0', 'unrecognized-next-model']
    with TestClient(app) as client:
        with patch('urllib.request.urlopen', return_value=response({'data': [{'id': m} for m in models]})) as upstream:
            result = client.post('/api/providers/openai-compatible/detect', json={'provider': 'evolink'})
        assert result.status_code == 200, result.text
        assert upstream.call_args.args[0].full_url == EVOLINK_BASE_URL + '/models'
        data = result.json()
        assert set(data['textModels']) == {'gpt-5.4', 'claude-sonnet-4-5'}
        assert set(data['imageModels']) == {'gpt-image-2.5-sunburst', 'gemini-3.1-flash-image-preview'}
        assert data['videoModels'] == ['seedance-2.0-image-to-video']
        assert set(data['unknownModels']) == {'suno-v5', 'evolink-moderation-1.0', 'unrecognized-next-model'}
        assert 'evolink-test-key' not in result.text
        with patch('urllib.request.urlopen', side_effect=AssertionError('cached read must not call upstream')):
            cached = client.get('/api/providers/model-catalog?provider=evolink').json()
        assert cached['models'] == sorted(models)
        assert cached['imageModels'] == data['imageModels']
        assert cached['catalogSources'] == ['evolink']


def test_evolink_key_does_not_fall_back_to_other_gateways():
    class OtherCredentials:
        def get(self, key):
            return 'other-key' if key == 'openrouter' else None
    registry = ProviderRegistry(OtherCredentials())
    assert not next(item for item in registry.list() if item['key'] == 'evolink')['configured']
    with patch('urllib.request.build_opener') as transport, pytest.raises(ProviderError, match='API Key'):
        registry.image('evolink', model='gpt-image-2').generate(prompt='test')
    transport.assert_not_called()


@pytest.mark.parametrize('model,params,expected', [
    ('gemini-3.1-flash-image-preview', {'aspectRatio': '16:9', 'resolution': '1K'}, {'size': '16:9', 'quality': '1K'}),
    ('gpt-image-2.5-sunburst', {'size': '1024x1024'}, {'size': '1024x1024', 'quality': 'low'}),
])
def test_image_policy_maps_evolink_parameters_without_quality_upgrade(model, params, expected):
    options, _ = apply_image_quality(params, model=model, provider_api='evolink', provider_key='evolink')
    for key, value in expected.items():
        assert options[key] == value
    from app.evolink import image_parameters
    assert image_parameters(options, model) == options  # adapter repeats preflight


def test_image_upload_poll_download_and_actual_cost(tmp_path):
    source = tmp_path / 'reference.png'
    source.write_bytes(b'input-image')
    adapter = ProviderRegistry(Credentials()).image('evolink', model='gpt-image-2.5-sunburst')
    adapter.poll_interval = 0
    final = {'id': 'task-123', 'status': 'completed', 'results': ['https://cdn.test/image.png'],
             'usage': {'credits_used': 10, 'cost': {'usd': .148, 'cny': 1}}}
    responses = [response({'success': True, 'data': {'file_url': 'https://files.evolink.ai/ref.png'}}),
                 response({'id': 'task-123', 'status': 'pending'}), response({'id': 'task-123', 'status': 'processing'}), response(final)]
    with patch('urllib.request.build_opener') as opener, patch('urllib.request.urlopen', return_value=io.BytesIO(b'output-image')) as download:
        opener.return_value.open.side_effect = responses
        result = adapter.generate(prompt='test', source_asset_path=str(source), size='1024x1024', quality='low')
    assert result == b'output-image'
    requests = [call.args[0] for call in opener.return_value.open.call_args_list]
    assert requests[0].full_url == 'https://files-api.evolink.ai/api/v1/files/upload/base64'
    assert json.loads(requests[0].data)['base64_data'].startswith('data:image/png;base64,')
    payload = json.loads(requests[1].data)
    assert requests[1].full_url == EVOLINK_BASE_URL + '/images/generations'
    assert payload['image_urls'] == ['https://files.evolink.ai/ref.png']
    assert 'source_asset_path' not in payload
    assert payload['quality'] == 'low'
    assert all(request.get_header('Authorization') == 'Bearer evolink-test-key' for request in requests)
    assert all(request.get_header('User-agent') == 'MxinspireX/0.2.0' for request in requests)
    assert all(request.get_header('Accept') == 'application/json' for request in requests)
    assert [r.full_url for r in requests[2:]] == [EVOLINK_BASE_URL + '/tasks/task-123'] * 2
    download_request = download.call_args.args[0]
    assert download_request.full_url == 'https://cdn.test/image.png'
    assert download_request.get_header('User-agent') == 'MxinspireX/0.2.0'
    assert download_request.get_header('Authorization') is None
    assert adapter.last_response['usage']['cost'] == 1
    assert adapter.last_response['usage']['cost_currency'] == 'CNY'


@pytest.mark.parametrize('ending', ['forbidden', 'unauthorized', 'timeout', 'invalid_url'])
def test_reference_upload_failure_never_submits_or_retries_generation(tmp_path, ending):
    source = tmp_path / 'reference.jpg'
    source.write_bytes(b'reference-image')
    adapter = ProviderRegistry(Credentials()).image('evolink', model='gpt-image-2.5-sunburst')
    with patch('urllib.request.build_opener') as opener, patch('app.providers.evolink.image_request_started') as dispatched:
        if ending in {'forbidden', 'unauthorized'}:
            code = 403 if ending == 'forbidden' else 401
            opener.return_value.open.side_effect = urllib.error.HTTPError(
                'https://files-api.evolink.ai/api/v1/files/upload/base64', code, 'denied', {},
                response({'detail': 'error code: 1010 evolink-test-key'}))
        elif ending == 'timeout':
            opener.return_value.open.side_effect = TimeoutError()
        else:
            opener.return_value.open.return_value = response({'success': True, 'data': {'file_url': 'invalid'}})
        with pytest.raises(ProviderError) as failure:
            adapter.generate(prompt='test', source_asset_path=str(source))
    assert failure.value.error_code == 'reference_upload_failed'
    assert failure.value.stop_tool
    assert '尚未提交生成请求' in str(failure.value)
    assert 'evolink-test-key' not in str(failure.value)
    if ending in {'forbidden', 'unauthorized'}:
        assert failure.value.status_code == code
        assert '1010' in str(failure.value)
    opener.return_value.open.assert_called_once()
    assert opener.return_value.open.call_args.args[0].full_url.endswith('/files/upload/base64')
    dispatched.assert_not_called()


@pytest.mark.parametrize('ending', ['failed', 'poll_error', 'timeout', 'malformed'])
def test_accepted_image_is_never_resubmitted(ending):
    adapter = ProviderRegistry(Credentials()).image('evolink', model='gpt-image-2')
    adapter.poll_interval = 0
    responses = [response({'id': 'task-kept', 'status': 'pending'})]
    if ending == 'failed':
        responses.append(response({'id': 'task-kept', 'status': 'failed', 'error': {'message': 'failed'}}))
    elif ending == 'poll_error':
        responses.extend(urllib.error.HTTPError('https://api.evolink.ai/v1/tasks/task-kept', 500, 'error', {}, io.BytesIO()) for _ in range(3))
    elif ending == 'malformed':
        responses = [response({'unexpected': True})]
    else:
        adapter.poll_timeout = 0
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.side_effect = responses
        with pytest.raises(ProviderError) as failure:
            adapter.generate(prompt='test')
    assert failure.value.stop_tool
    assert sum(call.args[0].get_method() == 'POST' for call in opener.return_value.open.call_args_list) == 1
    if ending in {'poll_error', 'timeout'}:
        assert 'task-kept' in str(failure.value)


def test_invalid_reference_or_batch_fails_before_paid_request(tmp_path):
    adapter = ProviderRegistry(Credentials()).image('evolink', model='gpt-image-2')
    with patch('urllib.request.build_opener') as opener:
        with pytest.raises(ProviderError):
            adapter.generate(prompt='test', n=2)
        with pytest.raises(ProviderError):
            adapter.generate(prompt='test', source_asset_path=str(tmp_path / 'missing.png'))
    opener.assert_not_called()


def test_video_submission_and_retrieval_use_task_endpoint():
    adapter = ProviderRegistry(Credentials()).video('evolink', model='seedance-2.0-text-to-video')
    with patch('urllib.request.build_opener') as opener, patch('urllib.request.urlopen', return_value=io.BytesIO(b'video')) as download:
        opener.return_value.open.side_effect = [response({'id': 'v-1', 'status': 'pending', 'usage': {'credits_reserved': 20}}),
            response({'id': 'v-1', 'status': 'completed', 'duration': 95, 'video_duration': 5,
                      'results': ['https://cdn.test/video.mp4'], 'usage': {'cost': {'usd': .5}}})]
        job = adapter.generate(prompt='test', duration=5, resolution='720p', aspectRatio='16:9')
        assert job['jobId'] == 'v-1'
        assert 'cost' not in adapter.last_response['usage']
        result = adapter.retrieve(job_id=job['jobId'])
    requests = [call.args[0] for call in opener.return_value.open.call_args_list]
    assert requests[0].full_url == EVOLINK_BASE_URL + '/videos/generations'
    assert json.loads(requests[0].data) == {'model': 'seedance-2.0-text-to-video', 'prompt': 'test', 'duration': 5, 'quality': '720p', 'aspect_ratio': '16:9'}
    assert requests[1].full_url == EVOLINK_BASE_URL + '/tasks/v-1'
    assert result['content'] == b'video' and result['extension'] == 'mp4'
    assert result['raw']['usage']['cost_currency'] == 'USD'
    assert result['raw']['duration'] == 5
    assert download.call_args.args[0].full_url == 'https://cdn.test/video.mp4'
    assert download.call_args.args[0].get_header('Authorization') is None


def test_video_mode_conflict_does_not_upload_or_submit():
    adapter = ProviderRegistry(Credentials()).video('evolink', model='seedance-2.0-text-to-video')
    with patch('urllib.request.build_opener') as opener, pytest.raises(ProviderError, match='文生视频'):
        adapter.generate(prompt='test', source_asset='reference.png')
    opener.assert_not_called()


def test_minimax_h3_preserves_start_and_end_frame_fields(tmp_path):
    source = tmp_path / 'first.png'
    last = tmp_path / 'last.png'
    source.write_bytes(b'first')
    last.write_bytes(b'last')
    adapter = ProviderRegistry(Credentials()).video('evolink', model='minimax-h3-image-to-video')
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.side_effect = [
            response({'success': True, 'data': {'file_url': 'https://files.test/first.png'}}),
            response({'success': True, 'data': {'file_url': 'https://files.test/last.png'}}),
            response({'id': 'h3-task', 'status': 'pending', 'duration': 0}),
        ]
        job = adapter.generate(prompt='test', source_asset=source, last_frame_asset=last,
                               duration=5, resolution='2k', aspectRatio='auto')
    payload = json.loads(opener.return_value.open.call_args.args[0].data)
    assert payload['image_start'] == 'https://files.test/first.png'
    assert payload['image_end'] == 'https://files.test/last.png'
    assert 'image_urls' not in payload and 'aspect_ratio' not in payload
    assert 'duration' not in job['raw']


@pytest.mark.parametrize('model,params', [
    ('sora-2-preview', {'generate_audio': False}),
    ('minimax-h3-text-to-video', {'resolution': '720p'}),
    ('seedance-2.0-reference-to-video', {'source_asset': 'first.png', 'last_frame_asset': 'last.png'}),
    ('veo-3.1-generate-preview', {'n': 2}),
])
def test_unsupported_video_options_fail_before_upload_or_submission(model, params):
    adapter = ProviderRegistry(Credentials()).video('evolink', model=model)
    with patch('urllib.request.build_opener') as opener, pytest.raises(ProviderError):
        adapter.generate(prompt='test', **params)
    opener.assert_not_called()


def test_evolink_exact_image_size_conflicts_are_not_silently_changed():
    from app.evolink import image_parameters
    with pytest.raises(ValueError, match='冲突'):
        image_parameters({'size': '1024x1024', 'width': 1536, 'height': 1024}, 'qwen-image-3.0')
    assert image_parameters({'size': '16:9', 'resolution': '1.5K'}, 'doubao-seedream-5.0-pro')['quality'] == '1.5K'


def test_audio_retries_only_status_get_and_public_download():
    from app.providers.evolink import EvoLinkAudioProvider
    adapter=EvoLinkAudioProvider(base_url=EVOLINK_BASE_URL,provider_key='evolink',model='qwen-audio-3.1-tts-flash',credentials=Credentials())
    remembered=[]
    adapter.on_task=lambda body:remembered.append(body['id'])
    final={'id':'audio-original','status':'completed','results':['https://cdn.test/audio.mp3']}
    with patch('urllib.request.build_opener') as opener, patch('urllib.request.urlopen') as download, patch('app.providers.evolink.time.sleep'):
        opener.return_value.open.side_effect=[response({'id':'audio-original','status':'pending'}),TimeoutError(),response(final)]
        download.side_effect=[TimeoutError(),io.BytesIO(b'ID3audio')]
        assert adapter.generate(text='欢迎来到暖屿') == b'ID3audio'
    requests=[c.args[0] for c in opener.return_value.open.call_args_list]
    assert [r.get_method() for r in requests]==['POST','GET','GET']
    assert requests[0].full_url.endswith('/audios/generations')
    assert json.loads(requests[0].data)['prompt']=='欢迎来到暖屿'
    assert all(r.full_url.endswith('/tasks/audio-original') for r in requests[1:])
    assert set(remembered)=={'audio-original'}
    assert all(c.args[0].get_header('Authorization') is None for c in download.call_args_list)
