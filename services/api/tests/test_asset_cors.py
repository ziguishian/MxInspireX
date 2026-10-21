from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.assets import AssetStore
from app.main import app, get_store
from app.models import new_project
from app.storage import ProjectStore


@pytest.fixture
def asset_api(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='图片下载测试', slug='download', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'download')))
    assets = AssetStore(store)
    content = b'\x89PNG\r\n\x1a\noriginal-image-content'
    asset = assets.add_bytes(project_id=project['id'], kind='image', filename='原图.png', content=content)
    monkeypatch.setattr(app.state, 'assets', assets, raising=False)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app, raise_server_exceptions=False), f"/api/projects/{project['id']}/assets/{asset['id']}/content", content, assets
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_preview_and_download_responses_vary_by_origin(asset_api):
    client, url, content, _ = asset_api
    preview = client.get(url)
    assert preview.status_code == 200 and preview.content == content
    assert 'origin' in preview.headers['vary'].lower()
    assert 'access-control-allow-origin' not in preview.headers
    for origin in ['http://127.0.0.1:5173', 'http://localhost:5173']:
        download = client.get(url, headers={'Origin': origin})
        assert download.content == content
        assert download.headers['access-control-allow-origin'] == origin
        assert download.headers['vary'].lower().split(', ').count('origin') == 1
        assert 'Content-Disposition' in download.headers['access-control-expose-headers']
    blocked = client.get(url, headers={'Origin': 'https://untrusted.invalid'})
    assert 'access-control-allow-origin' not in blocked.headers
    assert 'origin' in blocked.headers['vary'].lower()


def test_range_preview_and_preflight_keep_cache_and_cors_headers(asset_api):
    client, url, content, _ = asset_api
    response = client.get(url, headers={'Range': 'bytes=0-7'})
    assert response.status_code == 206 and response.content == content[:8]
    assert 'origin' in response.headers['vary'].lower()
    preflight = client.options(url, headers={'Origin': 'http://127.0.0.1:5173', 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'range'})
    assert preflight.status_code == 200
    assert preflight.headers['access-control-allow-origin'] == 'http://127.0.0.1:5173'


def test_missing_and_failed_assets_remain_readable_errors(asset_api):
    client, url, _, assets = asset_api
    origin = {'Origin': 'http://127.0.0.1:5173'}
    missing = client.get(url.replace('/content', '-missing/content'), headers=origin)
    assert missing.status_code == 404
    assert missing.headers['access-control-allow-origin'] == origin['Origin']
    with patch.object(assets, 'get_asset', side_effect=RuntimeError('fixture storage failure')):
        failed = client.get(url, headers=origin)
        assert failed.status_code == 500
        assert failed.headers['access-control-allow-origin'] == origin['Origin']
        assert 'origin' in failed.headers['vary'].lower()
        assert 'fixture storage failure' not in failed.text
