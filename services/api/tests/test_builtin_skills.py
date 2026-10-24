"""Shipped skills remain workspace-local, portable and safe across app upgrades."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.bundled_skills import BUNDLE_ROOT, install_bundled_skills, read_bundles
from app.main import app
from app.skills import SkillService, SkillError, digest
from app.skill_packages import export_package, package_definition
from app.storage import ProjectStore
from test_conversation_context import workspace, add_turn

NAMES = {'logo-mockup-suite', 'tourism-ip-design', 'notebook-print-design', 'scenic-wayfinding-design', 'xiaohongshu-visual-post', 'exhibition-hall-design'}


def changed_bundle(tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(BUNDLE_ROOT, root)
    manifest = json.loads((root/'manifest.json').read_text())
    for item in manifest['skills']:
        item['revision'] = '1.4.0'
        file = root/item['name']/'SKILL.md'
        file.write_bytes(file.read_bytes() + '\n新增发布版说明。\n'.encode())
        item['files']['SKILL.md'] = digest(file.read_bytes())
    (root/'manifest.json').write_text(json.dumps(manifest))
    return root


def test_builtins_portable_complete_and_no_automatic_execution(workspace):
    service = SkillService(workspace)
    from app.assets import AssetStore
    AssetStore(workspace)
    values = install_bundled_skills(service)
    assert {v['name'] for v in values} == NAMES
    assert next(v for v in values if v['name'] == 'tourism-ip-design')['title'] == '原创 IP 形象设计'
    assert next(v for v in values if v['name'] == 'scenic-wayfinding-design')['title'] == '空间导览与导视设计'
    assert all(not v['missingTools'] and not v['compatibilityWarnings'] for v in values)
    assert len(service.runtime('new')['catalog']) == 6
    assert service.runtime('new')['active'] == []
    assert install_bundled_skills(service) == []
    for item in values:
        data = export_package(service, item['id'])
        with ZipFile(BytesIO(data)) as archive:
            files = {name.removeprefix(item['name']+'/'):archive.read(name) for name in archive.namelist()}
        portable, _ = package_definition(files)
        assert portable['name'] == item['name'] and not portable['source']
        assert 'agents/openai.yaml' in files
        assert all(not name.startswith('scripts/') for name in files)
        assert {'generate_image', 'generate_batch'} <= set(portable['requiredTools'])
        assert not {'canvas_create_html', 'canvas_create_svg', 'export_deliverable'} & set(portable['requiredTools'])
        assert not any(name.endswith(('.html', '.svg')) for name in files)
        for link in re.findall(r'\]\(([^)]+)\)', portable['instructions']):
            assert link in files
        assert service.get(item['id'])['version'] == 1
    with workspace._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM assets').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM task_skill_bindings').fetchone()[0] == 0


def test_restarts_upgrades_keep_user_edits_disabled_deleted_and_pinned(workspace, tmp_path):
    service = SkillService(workspace)
    installed = {s['name']:s for s in install_bundled_skills(service)}
    edited = installed['logo-mockup-suite']
    updated = service.write({'expected_version':1,'title':'我的样机方法','instructions':'保留我的自定义规则'}, skill_id=edited['id'])
    assert updated['builtin']['modifiedLocally'] is True
    assert service.resource(edited['id'], 2, 'agents/openai.yaml')
    disabled = installed['tourism-ip-design']
    service.write({'expected_version':1,'enabled':False}, skill_id=disabled['id'])
    deleted = installed['scenic-wayfinding-design']
    service.delete(deleted['id'],1)
    original = installed['notebook-print-design']
    add_turn(workspace,'print','做笔记本',status='running')
    service.bind('one','print',original['id'],active=True,operation_id='load')
    upgraded = install_bundled_skills(service, changed_bundle(tmp_path))
    assert len(upgraded) == 4
    assert service.get(edited['id'])['title'] == '我的样机方法'
    assert service.get(edited['id'])['version'] == 2
    assert service.get(disabled['id'])['enabled'] is False
    assert service.get(disabled['id'])['version'] == 3
    assert service.get(deleted['id'],allow_deleted=True)['deleted']
    assert service.get(original['id'])['builtin']['revision'] == '1.4.0'
    active = service.runtime('print')['active'][0]
    assert active['version'] == 1 and active['contentHash'] == original['contentHash']


def test_notebook_upgrade_removes_layout_template_but_preserves_pinned_version(workspace, tmp_path):
    legacy = tmp_path / 'legacy'
    shutil.copytree(BUNDLE_ROOT, legacy)
    manifest = json.loads((legacy/'manifest.json').read_text())
    entry = next(item for item in manifest['skills'] if item['name'] == 'notebook-print-design')
    directory = legacy / entry['name']
    template = directory / 'assets/a5-cover-template.html'
    template.parent.mkdir(exist_ok=True)
    template.write_text('<html><body>Legacy cover layout</body></html>')
    config = directory / 'langju.json'
    definition = json.loads(config.read_text())
    definition['requiredTools'] += ['canvas_create_html', 'export_deliverable']
    config.write_text(json.dumps(definition))
    entry['revision'] = '1.2.0'
    entry['files'].update({'langju.json': digest(config.read_bytes()),
                           'assets/a5-cover-template.html': digest(template.read_bytes())})
    (legacy/'manifest.json').write_text(json.dumps(manifest))
    service = SkillService(workspace)
    original = next(s for s in install_bundled_skills(service, legacy) if s['name'] == entry['name'])
    add_turn(workspace, 'old-notebook', '继续笔记本任务', status='running')
    service.bind('one', 'old-notebook', original['id'], active=True, operation_id='load-original')

    upgraded = install_bundled_skills(service)
    assert len(upgraded) == 1
    current = service.get(original['id'])
    assert current['version'] == 2
    assert not {'canvas_create_html', 'export_deliverable'} & set(current['requiredTools'])
    assert not any(resource['path'].endswith('.html') for resource in current['resources'])
    add_turn(workspace, 'new-notebook', '分别生成封面和封底图片', status='running')
    service.bind('one', 'new-notebook', original['id'], active=True, operation_id='load-current')
    assert service.runtime('new-notebook')['active'][0]['version'] == 2
    pinned = service.runtime('old-notebook')['active'][0]
    assert pinned['version'] == 1 and pinned['contentHash'] == original['contentHash']
    assert service.resource(original['id'], 1, 'assets/a5-cover-template.html') == template.read_bytes()
    assert install_bundled_skills(service) == []


def test_name_collision_not_adopted_or_resurrected(workspace, tmp_path):
    service = SkillService(workspace)
    own = service.write({'name':'logo-mockup-suite','description':'我的技能','instructions':'自定义'})
    assert len(install_bundled_skills(service)) == 5
    assert not service.get(own['id']).get('builtin')
    service.delete(own['id'],1)
    install_bundled_skills(service, changed_bundle(tmp_path))
    assert not service.list('logo-mockup-suite')['skills']


def test_concurrent_install_and_crash_receipt_recovery(workspace):
    service = SkillService(workspace)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _:install_bundled_skills(service), range(2)))
    assert service.list()['total'] == 6
    original = {v['name']:v['id'] for v in service.list()['skills']}
    # Simulate package commits surviving while the marker transaction did not.
    with workspace._connect() as db:
        db.execute('DELETE FROM bundled_skill_installs')
    install_bundled_skills(service)
    assert {v['name']:v['id'] for v in service.list()['skills']} == original
    assert all(v['version'] == 1 for v in service.list()['skills'])


def test_corrupt_release_does_not_partially_install(workspace, tmp_path):
    root = changed_bundle(tmp_path)
    (root/'xiaohongshu-visual-post/SKILL.md').write_text('tampered')
    service = SkillService(workspace)
    with pytest.raises(SkillError,match='校验失败'):
        install_bundled_skills(service, root)
    assert service.list()['total'] == 0


def test_workspace_bootstrap_via_real_api_and_switch(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_TEST_MODE','1')
    first = None
    for n in range(2):
        monkeypatch.setenv('AICS_WORKSPACE_ROOT',str(tmp_path/f'workspace-{n}'))
        with TestClient(app) as client:
            result = client.get('/api/skills').json()
            assert result['total'] == 6
            assert {s['name'] for s in result['skills']} == NAMES
            if n == 0:
                first = result['skills'][0]['id']
            else:
                assert client.get('/api/skills/'+first).status_code == 404
