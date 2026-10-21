import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.mascot import MascotService, normalize_atlas
from app.mascot_routes import router
from app.storage import ProjectStore


def atlas_bytes(*, opaque=False, blank=False, clipped=False):
    image = Image.new('RGBA', (768, 512), (240, 240, 240, 255) if opaque else (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i in range(6 - int(blank)):
        x, y = i % 3 * 256, i // 3 * 256
        draw.rounded_rectangle((x + (0 if clipped else 50), y + 40, x + 206, y + 225), 30, fill=(60 + i * 20, 150, 150, 255))
    data = io.BytesIO()
    image.save(data, 'PNG')
    return data.getvalue()


@pytest.fixture
def service(tmp_path, monkeypatch):
    import app.mascot as module
    calls = []
    adapter = SimpleNamespace()
    def generate(**kwargs):
        calls.append(kwargs)
        return atlas_bytes()
    adapter.generate = generate
    candidate = SimpleNamespace(model='test-image', provider='openai-compatible', adapter=adapter, options={}, adjustments=[])
    monkeypatch.setattr(module, 'build_image_route', lambda *args, **kwargs: ({'mode': 'auto', 'tier': 'draft', 'primaryModel': 'test-image'}, [candidate]))
    value = MascotService(ProjectStore(str(tmp_path)), SimpleNamespace())
    value.test_calls, value.test_adapter = calls, adapter
    return value


def payload():
    return {'prompt': '薄荷绿色的可爱猫咪', 'provider': {'key': 'openai-compatible', 'baseUrl': 'https://example.com/v1'}, 'model': ''}


def client_for(service):
    app = FastAPI()
    app.state.mascot = service
    app.include_router(router)
    return TestClient(app)


def test_generate_preview_apply_reset_and_reload(service):
    client = client_for(service)
    request = {'requestId': str(uuid4()), **payload()}
    response = client.post('/api/mascot/generations', json=request)
    assert response.status_code == 202
    identity = response.json()['id']
    generated = client.get(f'/api/mascot/generations/{identity}').json()
    assert generated['status'] == 'succeeded'
    assert client.get('/api/mascot').json()['active'] is None
    image_response = client.get(generated['imageUrl'])
    assert image_response.headers['content-type'] == 'image/png'
    assert Image.open(io.BytesIO(image_response.content)).size == (1536, 1024)
    assert len(service.test_calls) == 1
    assert '3 columns' in service.test_calls[0]['prompt']
    # Re-delivery of the same POST cannot purchase another image.
    assert client.post('/api/mascot/generations', json=request).json()['id'] == identity
    assert len(service.test_calls) == 1
    assert client.put('/api/mascot', json={'generationId': identity}).json()['active']['id'] == identity
    restored = MascotService(service.store, service.providers)
    assert restored.settings()['active']['id'] == identity
    assert restored.activate(None)['active'] is None
    assert restored.image_path(identity).exists()


def test_bundled_presets_switch_persist_and_do_not_generate(service):
    client = client_for(service)
    assert client.get('/api/mascot').json()['activePreset'] == 'robot'
    for preset in ['cream-cat', 'cloud', 'sprout', 'robot']:
        response = client.put('/api/mascot', json={'presetId': preset})
        assert response.status_code == 200
        assert response.json() == {'active': None, 'activePreset': preset, 'latest': None}
        assert MascotService(service.store, service.providers).settings()['activePreset'] == preset
    assert service.test_calls == []


def test_presets_preserve_custom_generation_and_reject_invalid_selection(service):
    identity, _ = service.create(str(uuid4()), payload())
    service.generate(identity)
    client = client_for(service)
    custom = client.put('/api/mascot', json={'generationId': identity}).json()
    assert custom['activePreset'] is None
    preset = client.put('/api/mascot', json={'presetId': 'cream-cat'}).json()
    assert preset['active'] is None
    assert preset['latest']['id'] == identity
    assert service.image_path(identity).exists()
    for invalid in ({'presetId': '../secret'}, {'presetId': 'unknown'}, {'presetId': 'cloud', 'generationId': identity}):
        assert client.put('/api/mascot', json=invalid).status_code == 422
        assert service.settings()['activePreset'] == 'cream-cat'
    assert client.put('/api/mascot', json={'generationId': identity}).json()['active']['id'] == identity
    reset = client.put('/api/mascot', json={'generationId': None}).json()
    assert reset['activePreset'] == 'robot'
    assert reset['latest']['id'] == identity
    assert len(service.test_calls) == 1


@pytest.mark.parametrize('kwargs', [{'opaque': True}, {'blank': True}, {'clipped': True}])
def test_invalid_atlas_is_rejected(kwargs):
    with pytest.raises(ValueError):
        normalize_atlas(atlas_bytes(**kwargs))


def test_character_registration_has_a_common_baseline():
    image = Image.open(io.BytesIO(normalize_atlas(atlas_bytes())))
    boxes = [image.crop((col * 512, row * 512, (col + 1) * 512, (row + 1) * 512)).getbbox() for row in range(2) for col in range(3)]
    assert len(set(boxes)) == 1
    assert boxes[0][3] <= 487  # Lanczos alpha edges stay inside the cell.


def test_real_image_route_preserves_alpha_ratio_and_single_call(tmp_path):
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return atlas_bytes()
    adapter = SimpleNamespace(api='images', generate=generate)
    registry = SimpleNamespace(image=lambda *args, **kwargs: adapter)
    service = MascotService(ProjectStore(str(tmp_path)), registry)
    identity, _ = service.create(str(uuid4()), {**payload(), 'model': 'gpt-image-1'})
    service.generate(identity)
    assert service.get(identity)['status'] == 'succeeded', service.get(identity)['error']
    assert len(calls) == 1
    assert calls[0]['background'] == 'transparent'
    assert calls[0]['output_format'] == 'png'
    assert calls[0]['size'] == '1536x1024'


def test_failure_keeps_active_and_does_not_retry(service):
    first, _ = service.create(str(uuid4()), payload())
    service.generate(first)
    service.activate(first)
    second, _ = service.create(str(uuid4()), payload())
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError('Authorization Bearer secret-must-not-leak')
    service.test_adapter.generate = fail
    service.generate(second)
    service.generate(second)
    result = service.settings()
    assert result['active']['id'] == first
    assert result['latest']['status'] == 'failed'
    assert 'secret' not in result['latest']['error']
    assert len(calls) == 1
    with pytest.raises(ValueError):
        service.activate(second)


def test_concurrency_idempotency_restart_and_validation(service):
    request_id = str(uuid4())
    identity, _ = service.create(request_id, payload())
    with pytest.raises(ValueError):
        service.create(request_id, {**payload(), 'prompt': 'another prompt'})
    with pytest.raises(ValueError):
        service.create(str(uuid4()), payload())
    restored = MascotService(service.store, service.providers)
    assert restored.get(identity)['status'] == 'failed'
    assert len(service.test_calls) == 0
    client = client_for(restored)
    for changes in ({'prompt': ' '}, {'provider': {'key': 'ollama'}}, {'provider': {'key': 'openai-compatible', 'baseUrl': 'https://x/?key=secret'}}):
        assert client.post('/api/mascot/generations', json={'requestId': str(uuid4()), **payload(), **changes}).status_code == 422
    assert client.put('/api/mascot', json={'generationId': str(uuid4())}).status_code == 422
    assert client.get('/api/mascot/generations/not-a-uuid/image').status_code == 422
    assert client.get(f'/api/mascot/generations/{identity}/image').status_code == 404
