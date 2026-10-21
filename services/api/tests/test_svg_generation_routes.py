from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.local import LocalImageProvider


@pytest.mark.parametrize('fields', [{'extension':'svg'}, {'params':{'output_format':'svg'}}])
def test_direct_api_rejects_svg_before_provider_dispatch(tmp_path, monkeypatch, fields):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name':'禁用 SVG'}).json()['id']
        with patch.object(app.state.providers, 'image') as provider:
            response = client.post(f'/api/projects/{project}/generations/image', json={'prompt':'封面', **fields})
        assert response.status_code == 422 and '全局禁用' in response.text
        provider.assert_not_called()
        assert app.state.assets.list_assets(project) == []


def test_direct_api_cannot_save_returned_svg_but_still_generates_png(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name':'图像返回格式'}).json()['id']
        bad = Mock(return_value=b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        with patch.object(app.state.providers, 'image', return_value=SimpleNamespace(generate=bad)):
            failed = client.post(f'/api/projects/{project}/generations/image', json={'prompt':'封面','imageRatio':'3:4'})
        assert failed.status_code == 400 and '图像服务返回了 SVG' in failed.text
        assert bad.call_count == 1 and bad.call_args.kwargs['output_format'] == 'png'
        assert app.state.assets.list_assets(project) == []
        rows = client.get(f'/api/projects/{project}/generations').json()
        assert rows[0]['status'] == 'failed'
        with patch.object(app.state.providers, 'image', return_value=LocalImageProvider()):
            good = client.post(f'/api/projects/{project}/generations/image', json={'prompt':'封面','imageRatio':'3:4'})
        assert good.status_code == 201 and good.json()['asset']['mime'] == 'image/png'
        assert len(app.state.assets.list_assets(project)) == 1
        removed = client.post(f'/api/projects/{project}/agent-tools/canvas_create_svg', json={'svg':'<svg/>'})
        assert removed.status_code == 404
