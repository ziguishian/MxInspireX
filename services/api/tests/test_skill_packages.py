"""Real package/storage/API paths with a fake GitHub transport; never run imported code."""
from io import BytesIO
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import json
import stat

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.skills import SkillService, SkillError, SkillConflict
from app.skill_packages import GitHubSkillInstaller, package_definition, github_source, export_package
from app.task_policy import is_skill_creation
from test_conversation_context import workspace, add_turn

SHA = 'a' * 40
FILES = {
    'SKILL.md': b'---\nname: packaging-design\ndescription: >-\n  Create packaging from an existing brand.\nlicense: MIT\nmetadata:\n  author: example\nallowed-tools: Read\n---\n\n# Workflow\nRead [guide](references/guide.md).\n',
    'agents/openai.yaml': 'interface:\n  display_name: 包装设计\n  short_description: 包装方法\npolicy:\n  allow_implicit_invocation: false\ndependencies:\n  tools:\n    - type: mcp\n      value: design\n'.encode(),
    'references/guide.md': '包装说明'.encode(),
    'scripts/example.py': b'raise RuntimeError("must never execute")\n',
    'LICENSE.txt': b'MIT example license\n',
}


def archive(files, prefix='repo-commit/skills/packaging/'):
    data = BytesIO()
    with ZipFile(data, 'w', ZIP_DEFLATED) as output:
        for path, content in files.items():
            output.writestr(prefix + path, content)
    return data.getvalue()


def transport(content, requests=None):
    def handle(request):
        if requests is not None:
            requests.append(str(request.url))
        assert 'authorization' not in request.headers
        url = str(request.url)
        if url == 'https://api.github.com/repos/example/skills':
            return httpx.Response(200, json={'default_branch': 'main'})
        if url.startswith('https://api.github.com/repos/example/skills/commits/'):
            return httpx.Response(200, json={'sha': SHA})
        assert url == f'https://codeload.github.com/example/skills/zip/{SHA}'
        return httpx.Response(200, content=content)
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_codex_package_install_export_update_and_restore(workspace):
    service = SkillService(workspace)
    requests = []
    installer = GitHubSkillInstaller(service, transport(archive(FILES), requests))
    inspected = installer.inspect('https://github.com/example/skills')
    assert inspected['source']['commit'] == SHA
    assert inspected['candidates'][0]['title'] == '包装设计'
    assert len(inspected['candidates'][0]['warnings']) == 3
    installed = installer.install('https://github.com/example/skills', SHA, 'skills/packaging', 'install-1')
    assert installed['explicitOnly'] is True
    assert service.runtime('unused')['catalog'] == []
    count = len(requests)
    assert installer.install('https://github.com/example/skills', SHA, 'skills/packaging', 'install-1') == installed
    assert len(requests) == count, 'replay must not contact GitHub'
    with pytest.raises(SkillConflict):
        installer.install('https://github.com/example/skills', SHA, 'skills/packaging', 'different-op')
    with ZipFile(BytesIO(export_package(service, installed['id']))) as output:
        assert {p.removeprefix('packaging-design/'): output.read(p) for p in output.namelist()} == FILES
    disabled = service.write({'expected_version': 1, 'enabled': False}, skill_id=installed['id'])
    assert disabled['contentHash'] == installed['contentHash']
    assert service.resource(installed['id'], 2, 'agents/openai.yaml') == FILES['agents/openai.yaml']
    updated = service.write({'expected_version': 2, 'instructions': '# Updated\nUse the original guide.', 'enabled': True}, skill_id=installed['id'])
    assert updated['source']['modifiedLocally'] is True
    assert service.resource(installed['id'], 3, 'scripts/example.py') == FILES['scripts/example.py']
    assert b'license: MIT' in service.resource(installed['id'], 3, 'SKILL.md')
    add_turn(workspace, 'task', '使用 packaging-design', status='running')
    service.bind('one', 'task', installed['id'], active=True, version=1, operation_id='load')
    service.delete(installed['id'], 3)
    active = service.runtime('task')['active'][0]
    assert active['version'] == 1 and active['compatibilityWarnings']
    assert 'Workflow' in active['instructions']


def test_multiple_skills_and_root_package(workspace):
    files = {**{'first/' + p: v for p,v in FILES.items()}, **{'second/' + p: v.replace(b'packaging-design', b'other-design') if p == 'SKILL.md' else v for p,v in FILES.items()}}
    installer = GitHubSkillInstaller(SkillService(workspace), transport(archive(files, 'root/')))
    assert len(installer.inspect('https://github.com/example/skills')['candidates']) == 2
    with pytest.raises(SkillError, match='多个 Skill'):
        installer.install('https://github.com/example/skills')
    root = GitHubSkillInstaller(SkillService(workspace), transport(archive(FILES, 'root/')))
    assert root.inspect('https://github.com/example/skills')['candidates'][0]['path'] == ''
    assert root.install('https://github.com/example/skills')['version'] == 1


@pytest.mark.parametrize('url', ['http://github.com/o/r', 'https://localhost/o/r', 'https://github.com.evil/o/r', 'https://token@github.com/o/r', 'https://github.com:bad/o/r', 'https://github.com/o/.git', 'https://github.com/o/r?token=secret', 'https://github.com/o/r/tree/main/%2e%2e/private'])
def test_only_public_github_urls(url):
    with pytest.raises(SkillError):
        github_source(url)


def test_branch_paths_and_blob_links():
    source = github_source('https://github.com/o/r/tree/feature/a/skills/one', 'feature/a')
    assert source['ref'] == 'feature/a' and source['path'] == 'skills/one'
    assert github_source('https://github.com/o/r/blob/main/SKILL.md')['path'] == ''


@pytest.mark.parametrize('path', ['../escape', '/private', 'assets/../../escape', 'assets\\evil', '.git/config'])
def test_archive_traversal_rejected(workspace, path):
    installer = GitHubSkillInstaller(SkillService(workspace), transport(archive({**FILES, path: b'x'})))
    with pytest.raises(SkillError, match='路径'):
        installer.install('https://github.com/example/skills', path='skills/packaging')


def test_symlinks_and_oversized_packages_rejected(workspace):
    data = BytesIO(archive(FILES))
    with ZipFile(data, 'a') as output:
        link = ZipInfo('repo-commit/skills/packaging/assets/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(link, '/private/secrets')
    installer = GitHubSkillInstaller(SkillService(workspace), transport(data.getvalue()))
    with pytest.raises(SkillError, match='符号链接'):
        installer.install('https://github.com/example/skills', path='skills/packaging')
    with pytest.raises(SkillError, match='8 MB'):
        package_definition({**FILES, 'assets/big': b'x' * (8 * 1024 * 1024 + 1)})
    with pytest.raises(SkillError, match='256'):
        package_definition({**FILES, **{f'assets/{i}': b'x' for i in range(256)}})


@pytest.mark.parametrize('metadata', [b'name: a\nname: b\ndescription: x', b'name: a\ndescription: &d x\nmetadata: *d', b'name: a\ndescription: !!python/object x'])
def test_yaml_does_not_execute_or_silently_override(metadata):
    with pytest.raises(SkillError):
        package_definition({'SKILL.md': b'---\n' + metadata + b'\n---\nBody'})


def test_github_errors_are_actionable(workspace):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    with pytest.raises(SkillError, match='403'):
        GitHubSkillInstaller(SkillService(workspace), client).inspect('https://github.com/example/skills')


def test_missing_local_tools_block_load_but_preserve_import(workspace):
    files = {**FILES, 'langju.json': json.dumps({'requiredTools': ['not_installed']}).encode()}
    skill = GitHubSkillInstaller(SkillService(workspace), transport(archive(files))).install('https://github.com/example/skills', path='skills/packaging')
    assert skill['missingTools'] == ['not_installed']
    add_turn(workspace, 'task', '使用技能', status='running')
    with pytest.raises(SkillError, match='缺少工具'):
        SkillService(workspace).bind('one', 'task', skill['id'], active=True, operation_id='load')


def test_github_and_export_routes(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    fake = transport(archive(FILES))
    original = GitHubSkillInstaller._download
    def download(self, url, maximum):
        self.client = fake
        return original(self, url, maximum)
    monkeypatch.setattr(GitHubSkillInstaller, '_download', download)
    with TestClient(app) as client:
        assert client.post('/api/skills/github/inspect', json={'url': 'https://localhost/repo'}).status_code == 422
        assert client.post('/api/skills/github/inspect', json={'url': 'https://github.com/example/skills'}).json()['candidates']
        body = {'url': 'https://github.com/example/skills', 'ref': SHA, 'path': 'skills/packaging'}
        response = client.post('/api/skills/github/install', json=body, headers={'Idempotency-Key': 'one'})
        assert response.status_code == 201, response.text
        skill = response.json()
        assert client.post('/api/skills/github/install', json=body, headers={'Idempotency-Key': 'one'}).json()['id'] == skill['id']
        package = client.get(f'/api/skills/{skill["id"]}/export?version=1')
        assert package.headers['content-type'] == 'application/zip'
        with ZipFile(BytesIO(package.content)) as output:
            assert output.read('packaging-design/SKILL.md') == FILES['SKILL.md']
        assert client.get(f'/api/skills/{skill["id"]}/versions/1/resources/scripts/example.py').headers['content-disposition'].startswith('attachment;')


@pytest.mark.parametrize('text,expected', [('请帮我创建一个 Skill，编写并保存到技能库，直到工具确认创建成功。我的需求是：包装设计', True), ('创建品牌全案 skill：流程中生成图片', True), ('列出技能：创建品牌全案', False), ('修改技能 packaging-design', False), ('不要创建技能', False), ('使用包装技能生成图片', False), ('你好', False)])
def test_creation_intent_is_separate_from_workflow(text, expected):
    assert is_skill_creation(text) is expected
