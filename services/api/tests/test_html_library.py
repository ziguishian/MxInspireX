import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from test_delivery_contract import workspace
from app.project_overview import ProjectPreviews, library_assets
from app.main import app


def test_existing_html_is_indexed_without_exporting_or_changing_assets(workspace):
    store, project, assets, canvas = workspace
    page = canvas.create_node(project, kind='html', title='我的/网页', data={'html': '<h1>HTML_BODY</h1>'})
    canvas.create_node(project, kind='html', title='空网页')
    canvas.create_node(project, kind='text', title='文本', data={'text': 'not html'})
    service = ProjectPreviews(store, canvas)
    with patch.object(canvas, 'load', wraps=canvas.load) as read:
        first, second = service.html_assets(), service.html_assets()
        assert read.call_count == 1
    assert first == second and len(first) == 1
    assert first[0]['htmlNodeId'] == page['id'] and first[0]['pathRelative'] == '我的_网页.html'
    assert 'HTML_BODY' not in json.dumps(first)
    assert first[0]['byteSize'] == len('<h1>HTML_BODY</h1>'.encode())
    assert library_assets(store) == []
    assert assets.list_assets(project) == []


def test_html_preview_uses_latest_source_and_embeds_local_images(workspace):
    store, project, _, canvas = workspace
    source = '<img src="asset://image-one"><button>OLD</button>'
    page = canvas.create_node(project, kind='html', title='页面', data={'html': source, 'htmlAssets': {'image-one': 'data:image/png;base64,YQ=='}})
    service = ProjectPreviews(store, canvas)
    first = service.html_assets()[0]
    document = service.html_document(project, page['id'])
    assert 'data:image/png;base64,YQ==' in document['html'] and 'asset://' not in document['html']
    canvas.update_node(project, page['id'], {'data': {'html': '<button>NEW</button>', 'title': '新页面'}})
    updated = service.html_assets()[0]
    assert updated['revision'] != first['revision'] and updated['pathRelative'] == '新页面.html'
    assert service.html_document(project, page['id'])['html'] == '<button>NEW</button>'
    canvas.apply_changes(project, {'removeNodeIds': [page['id']]})
    assert service.html_assets() == []
    with pytest.raises(ValueError): service.html_document(project, page['id'])


def test_html_routes_return_only_requested_document_and_handle_missing(workspace, monkeypatch):
    store, project, _, canvas = workspace
    page = canvas.create_node(project, kind='html', title='页面', data={'html': '<h1>Requested</h1>'})
    canvas.create_node(project, kind='text', title='其他', data={'text': 'UNRELATED_CONTENT'})
    monkeypatch.setattr(app.state, 'project_previews', ProjectPreviews(store, canvas), raising=False)
    client = TestClient(app)
    catalog = client.get('/api/library/html')
    assert catalog.status_code == 200 and len(catalog.json()) == 1
    response = client.get(f'/api/projects/{project}/canvas/html/{page["id"]}')
    assert response.status_code == 200 and response.headers['content-type'].startswith('application/json')
    assert response.json()['html'] == '<h1>Requested</h1>' and 'UNRELATED_CONTENT' not in response.text
    assert client.get(f'/api/projects/wrong-project/canvas/html/{page["id"]}').status_code == 404
    assert client.get(f'/api/projects/{project}/canvas/html/missing').status_code == 404
