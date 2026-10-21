from io import BytesIO
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def test_preview_returns_original_upload_and_rejects_missing_document(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    image = BytesIO()
    Image.new('RGBA', (8, 8), (30, 100, 60, 128)).save(image, format='PNG')
    with TestClient(app) as client:
        uploaded = client.post('/api/knowledge/upload', files={'file': ('reference.png', image.getvalue(), 'image/png')})
        assert uploaded.status_code == 201
        doc = uploaded.json()
        response = client.get(f"/api/knowledge/documents/{doc['documentId']}/content")
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/png'
        assert response.content == image.getvalue()
        assert client.get('/api/knowledge/documents/missing/content').status_code == 404


def test_preview_does_not_follow_a_file_outside_knowledge_directory(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        doc = client.post('/api/knowledge/upload', files={'file': ('notes.txt', b'local notes', 'text/plain')}).json()
        source = tmp_path / doc['pathRelative']
        source.unlink()
        outside = tmp_path / 'not-a-knowledge-document.txt'
        outside.write_text('unrelated workspace data')
        source.symlink_to(outside)
        assert client.get(f"/api/knowledge/documents/{doc['documentId']}/content").status_code == 404


def test_project_attachment_preview_preserves_content_and_project_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    image = BytesIO()
    Image.new('RGB', (8, 8), (80, 100, 40)).save(image, format='PNG')
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': '附件预览'}).json()
        other = client.post('/api/projects', json={'name': '其他项目'}).json()
        uploaded = client.post(f"/api/projects/{project['id']}/knowledge/upload", files={'file': ('reference.png', image.getvalue(), 'image/png')})
        assert uploaded.status_code == 201
        doc = uploaded.json()
        response = client.get(f"/api/projects/{project['id']}/knowledge/documents/{doc['documentId']}/content")
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/png'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.content == image.getvalue()
        assert client.get(f"/api/projects/{other['id']}/knowledge/documents/{doc['documentId']}/content").status_code == 404
        assert client.get(f"/api/projects/{project['id']}/knowledge/documents/missing/content").status_code == 404
        assert client.get(f"/api/projects/missing/knowledge/documents/{doc['documentId']}/content").status_code == 404


@pytest.mark.parametrize('replace_directory', [False, True])
def test_project_preview_rejects_symlink_escape(tmp_path, monkeypatch, replace_directory):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': '预览路径边界'}).json()
        doc = client.post(f"/api/projects/{project['id']}/knowledge/upload", files={'file': ('notes.txt', b'notes', 'text/plain')}).json()
        source = Path(project['rootPath']) / doc['pathRelative']
        if replace_directory:
            directory = source.parent
            outside = tmp_path / 'outside-documents'
            directory.rename(outside)
            directory.symlink_to(outside)
        else:
            source.unlink()
            outside = tmp_path / 'outside.txt'
            outside.write_text('unrelated workspace data')
            source.symlink_to(outside)
        assert client.get(f"/api/projects/{project['id']}/knowledge/documents/{doc['documentId']}/content").status_code == 404
