import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.canvas import CanvasStore
from app.main import app
from app.models import new_project
from app.storage import ProjectStore


def make_project(store, slug='legacy-project'):
    return store.create_project(new_project(name='旧项目', slug=slug, brief='', budget_minor=None,
        currency='CNY', root_path=str(store.workspace_root / slug)))


def test_reading_an_empty_canvas_does_not_create_directories(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path / 'workspace-data'))
    project = make_project(store)
    canvas = CanvasStore(store)

    def forbid_mkdir(*args, **kwargs):
        raise PermissionError('Reading a canvas must not write directories')

    with monkeypatch.context() as context:
        context.setattr(Path, 'mkdir', forbid_mkdir)
        assert canvas.load(project['id'])['nodes'] == []
    assert not (Path(project['rootPath']) / 'canvas').exists()
    node = canvas.create_node(project['id'], kind='text', title='新节点')
    assert canvas.load(project['id'])['nodes'][0]['id'] == node['id']


def test_catalog_only_legacy_project_is_rebased_and_can_save_canvas(tmp_path):
    store = ProjectStore(str(tmp_path / 'workspace-data'))
    project = make_project(store)
    # Reproduce an imported catalog whose managed project folder was not copied.
    old_root = tmp_path / 'old-machine' / 'workspace-data' / project['slug']
    local_root = Path(project['rootPath'])
    shutil.rmtree(local_root)
    with store._connect() as connection:
        connection.execute('UPDATE projects SET root_path=? WHERE id=?', (str(old_root), project['id']))

    migrated = ProjectStore(str(store.workspace_root))
    restored = migrated.get_project(project['id'])
    assert restored['rootPath'] == str(local_root)
    assert json.loads((local_root / 'project.json').read_text())['id'] == project['id']
    assert not old_root.exists()
    canvas = CanvasStore(migrated)
    node = canvas.create_node(project['id'], kind='text', title='继续创作')
    assert canvas.load(project['id'])['nodes'][0]['id'] == node['id']


def test_missing_external_project_path_is_not_silently_rebased(tmp_path):
    store = ProjectStore(str(tmp_path / 'workspace-data'))
    project = make_project(store)
    external = tmp_path / 'external-drive' / 'custom-folder'
    with store._connect() as connection:
        connection.execute('UPDATE projects SET root_path=? WHERE id=?', (str(external), project['id']))
    reopened = ProjectStore(str(store.workspace_root))
    assert reopened.get_project(project['id'])['rootPath'] == str(external)


@pytest.mark.parametrize('origin,allowed', [('http://127.0.0.1:5173', True), ('http://localhost:5173', True), ('https://untrusted.example', False)])
def test_unexpected_canvas_failure_remains_readable_only_to_allowed_origins(tmp_path, monkeypatch, origin, allowed):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('AICS_TEST_MODE', '1')
    with TestClient(app, raise_server_exceptions=False) as client:
        project = client.post('/api/projects', json={'name': '画布读取失败测试'}).json()

        def fail_load(*args, **kwargs):
            raise PermissionError('private filesystem details')

        monkeypatch.setattr(app.state.design_tools.canvas_store, 'load', fail_load)
        response = client.get(f'/api/projects/{project["id"]}/canvas', headers={'Origin': origin})

    assert response.status_code == 500
    assert response.json()['detail'] == '服务器处理请求失败，请重试或查看任务日志'
    assert 'private filesystem details' not in response.text
    if allowed:
        assert response.headers['access-control-allow-origin'] == origin
        assert 'Origin' in response.headers['vary']
    else:
        assert 'access-control-allow-origin' not in response.headers
