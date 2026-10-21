import base64
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.assets import AssetStore
from app.design_tools import DesignToolRegistry, DesignToolError
from app.skills import SkillService, SkillError, SkillConflict
from app.task_policy import is_skill_management, delivery_contract, execution_flow, is_simple_conversation
from app.design_planning import planning_profile
from app.storage import ProjectStore
from app.main import app
from test_conversation_context import workspace, add_turn


def spec(**values):
    return {'name': 'packaging-design', 'title': '包装设计', 'description': '按需求设计包装，不用于普通问候',
            'instructions': '先确认本轮交付，复用已确认视觉，再生成效果图。', 'required_tools': ['generate_image'], **values}


def test_create_update_conflict_and_replay(workspace):
    service = SkillService(workspace)
    original = service.write(spec(), operation_id='create-1')
    assert service.write(spec(), operation_id='create-1') == original
    assert not service.bindings('unrelated')
    with pytest.raises(SkillConflict):
        service.write(spec())
    payload = {'expected_version': 1, 'instructions': '保留原方案中的莓红色'}
    updated = service.write(payload, skill_id=original['id'], operation_id='edit-1')
    assert updated['version'] == 2
    assert service.write(payload, skill_id=original['id'], operation_id='edit-1') == updated
    assert service.get(original['id'], 1)['instructions'] == original['instructions']
    with pytest.raises(SkillConflict, match='已被修改'):
        service.write({'expected_version': 1, 'title': '过期改动'}, skill_id=original['id'])
    with pytest.raises(SkillConflict, match='同一操作'):
        service.write(spec(name='another'), operation_id='create-1')
    files = workspace.workspace_root / 'skills' / original['id'] / 'versions' / '1'
    assert (files / 'SKILL.md').read_text().startswith('---\nname: "packaging-design"')
    assert json.loads((files / 'langju.json').read_text())['schemaVersion'] == 1


def test_concurrent_updates_have_one_winner(workspace):
    service = SkillService(workspace)
    skill = service.write(spec())
    def write(title):
        try:
            return service.write({'expected_version': 1, 'title': title}, skill_id=skill['id'])['version']
        except SkillConflict:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(write, ['甲', '乙']), key=str) == [2, 'conflict']


def test_shared_resources_copy_and_workspace_isolation(workspace, tmp_path):
    asset = AssetStore(workspace).add_bytes(project_id='one', kind='text', filename='guide.txt', content='企业已授权的工艺资料'.encode())
    service = SkillService(workspace)
    source = {'path': 'references/guide.txt', 'sourceAssetId': asset['id']}
    skill = service.write(spec(instructions='阅读[工艺](references/guide.txt)。', resources=[source]), project_id='one', operation_id='copy-once')
    with pytest.raises(SkillError, match='不属于'):
        service.write(spec(name='foreign-resource', resources=[source]), project_id='two')
    AssetStore(workspace).delete_asset(project_id='one', asset_id=asset['id'])
    assert service.write(spec(instructions='阅读[工艺](references/guide.txt)。', resources=[source]), project_id='one', operation_id='copy-once')['id'] == skill['id']
    assert service.resource(skill['id'], 1, source['path']).decode() == '企业已授权的工艺资料'
    updated = service.write({'expected_version': 1, 'title': '新名称'}, skill_id=skill['id'])
    assert service.resource(skill['id'], 2, source['path']) == service.resource(skill['id'], 1, source['path'])
    assert updated['resources'][0]['sha256']
    other = SkillService(ProjectStore(str(tmp_path / 'another-workspace')))
    assert other.list()['total'] == 0
    with pytest.raises(SkillError):
        other.get(skill['id'])


@pytest.mark.parametrize('path', ['../secret.txt', 'references/../../secret.txt', '/tmp/secret.txt', 'assets\\secret.txt', 'assets/run.py', 'assets/a/../x.txt'])
def test_resource_paths_and_scripts_rejected(workspace, path):
    with pytest.raises(SkillError):
        SkillService(workspace).write(spec(resources=[{'path': path, 'text': 'x'}]))


def test_validation_integrity_and_pagination(workspace):
    service = SkillService(workspace)
    with pytest.raises(SkillError, match='工具依赖不存在'):
        service.write(spec(required_tools=['invented_tool']))
    with pytest.raises(SkillError, match='不存在的资源'):
        service.write(spec(instructions='请读[规则](references/missing.md)'))
    skill = service.write(spec(resources=[{'path': 'references/long.txt', 'text': '一' * 7000}]))
    add_turn(workspace, 'read', '查看包装 Skill', status='running')
    first = service.execute('skill_read', 'one', 'read', {'skill_id': skill['id'], 'resource': 'references/long.txt'})
    assert len(first['text']) == 6000 and first['nextOffset'] == 6000
    last = service.execute('skill_read', 'one', 'read', {'skill_id': skill['id'], 'resource': 'references/long.txt', 'offset': 6000})
    assert len(last['text']) == 1000 and last['nextOffset'] is None
    path = workspace.workspace_root / 'skills' / skill['id'] / 'versions/1/references/long.txt'
    path.write_text('tampered')
    with pytest.raises(SkillError, match='校验失败'):
        service.resource(skill['id'], 1, 'references/long.txt')
    path.unlink()
    path.symlink_to(workspace.catalog_path)
    with pytest.raises(SkillError, match='符号链接'):
        service.resource(skill['id'], 1, 'references/long.txt')


def test_bind_unbind_rebind_and_retired_version_recovery(workspace):
    service = SkillService(workspace)
    skill = service.write(spec())
    add_turn(workspace, 'use', '使用包装技能', project='two', status='running')
    add_turn(workspace, 'new', '使用包装技能', project='two', status='running')
    def bind(active, operation):
        return service.bind('two', 'use', skill['id'], active=active, operation_id=operation)
    bind(True, 'load-1')
    bind(False, 'unload-1')
    bind(True, 'load-1')  # Retransmission is not a new activation.
    assert not service.bindings('use')[0]['active']
    bind(True, 'load-2')
    service.write({'expected_version': 1, 'instructions': '新版规则'}, skill_id=skill['id'])
    service.delete(skill['id'], 2)
    reopened = SkillService(workspace)
    assert reopened.runtime('use')['active'][0]['instructions'] == skill['instructions']
    assert reopened.runtime('use')['active'][0]['version'] == 1
    assert reopened.list()['total'] == 0
    with pytest.raises(SkillError):
        reopened.bind('two', 'new', skill['id'], active=True, operation_id='load-new')
    assert reopened.execute('skill_read', 'two', 'use', {'skill_id': skill['id']})['version'] == 1
    with workspace._connect() as db:
        state = json.loads(db.execute('SELECT input_json FROM tasks WHERE id="use"').fetchone()[0])
    assert state['skillBindings'][0]['active'] and state['skillBindings'][0]['version'] == 1
    reopened.inherit('two', 'new', 'use')
    assert reopened.bindings('new')[0]['version'] == 1
    with pytest.raises(SkillError):
        reopened.inherit('one', 'new', 'use')


def test_network_role_and_task_boundaries(workspace):
    registry = DesignToolRegistry(workspace)
    skill = registry.skills.write(spec(required_tools=['web_search']))
    add_turn(workspace, 'use', '使用技能', status='running')
    with pytest.raises(SkillError, match='未允许联网'):
        registry.execute(project_id='one', task_id='use', name='skill_load', arguments={'skill_id': skill['id']}, operation_id='network')
    with pytest.raises(SkillError, match='有效的任务'):
        registry.execute(project_id='two', task_id='use', name='skill_list')
    for role in ('research', 'review', 'repair'):
        with pytest.raises(SkillError, match='不能修改'):
            registry.execute(project_id='one', task_id='use', name='skill_create', arguments=spec(), agent_role=role, operation_id=role)
    with workspace._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id="use"', (json.dumps({'deliveryRepairOnly': True}),))
    with pytest.raises(SkillError, match='不能修改'):
        registry.execute(project_id='one', task_id='use', name='skill_delete', arguments={'skill_id': skill['id'], 'expected_version': 1}, operation_id='repair-main')


@pytest.mark.parametrize('brief', ['创建一个品牌全案Skill', '创建一个生成图片的skill', '把刚才的包装流程保存为技能', '删除包装设计 Skill', '更新展厅Skill：先生成三张图，再做网页', '查看 skill 列表'])
def test_management_is_not_media_or_planning(brief):
    assert is_skill_management(brief)
    assert not delivery_contract(brief)
    assert execution_flow(brief) == 'direct'
    assert planning_profile(brief) is None
    assert not is_simple_conversation(brief)


def test_mixed_request_and_management_gateway_guard(workspace):
    assert not is_skill_management('加载包装skill，做两张图片')
    assert delivery_contract('加载包装skill，做两张图片')[0]['count'] == 2
    assert is_simple_conversation('你好')
    add_turn(workspace, 'author', '创建一个生成图片的 Skill', status='running')
    registry = DesignToolRegistry(workspace)
    with pytest.raises(DesignToolError, match='只管理 Skill'):
        registry.execute(project_id='one', task_id='author', name='generate_image', arguments={'prompt': '不应调用模型'})
    assert registry.skills.runtime('author', simple=True) == {'catalog': [], 'bindings': [], 'active': []}


def test_ui_api_lifecycle_and_passive_resources(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        body = spec(resources=[{'path': 'assets/example.html', 'text': '<script>throw new Error()</script>'}])
        response = client.post('/api/skills', json=body, headers={'Idempotency-Key': 'ui-create'})
        assert response.status_code == 201, response.text
        skill = response.json()
        assert client.post('/api/skills', json=body, headers={'Idempotency-Key': 'ui-create'}).json()['id'] == skill['id']
        assert 'skill_load' in client.get('/api/skills/tools').json()['tools']
        assert client.get('/api/skills?query=packaging-design').json()['total'] == 1
        resource = client.get(f"/api/skills/{skill['id']}/versions/1/resources/assets/example.html")
        assert resource.status_code == 200
        assert resource.headers['content-disposition'].startswith('attachment;')
        assert resource.headers['content-security-policy'] == "default-src 'none'; sandbox"
        update = client.patch(f"/api/skills/{skill['id']}", json={'expected_version': 1, 'enabled': False})
        assert update.status_code == 200 and update.json()['version'] == 2
        assert client.get('/api/skills?query=packaging-design&include_disabled=false').json()['total'] == 0
        assert client.get('/api/skills?query=packaging-design').json()['total'] == 1
        assert client.patch(f"/api/skills/{skill['id']}", json={'expected_version': 1, 'title': '过期修改'}).status_code == 409
        assert len(client.get(f"/api/skills/{skill['id']}/versions").json()['versions']) == 2
        assert client.get(f"/api/skills/{skill['id']}?version=1").json()['instructions'] == skill['instructions']
        assert client.delete(f"/api/skills/{skill['id']}?expected_version=2").status_code == 200
        assert client.get(f"/api/skills/{skill['id']}").status_code == 404


def test_binary_references_use_local_readers_without_canvas_mutations(workspace):
    from io import BytesIO
    from docx import Document
    from PIL import Image
    document = Document()
    document.add_paragraph('Packaging material specification')
    doc = BytesIO()
    document.save(doc)
    picture = BytesIO()
    Image.new('RGB', (50, 40), 'red').save(picture, format='PNG')
    service = SkillService(workspace)
    skill = service.write(spec(resources=[{'path': 'references/material.docx', 'dataBase64': base64.b64encode(doc.getvalue()).decode()},
                                         {'path': 'references/style.png', 'dataBase64': base64.b64encode(picture.getvalue()).decode()}]))
    add_turn(workspace, 'reader', '查看参考资料', status='running')
    read = lambda path: service.execute('skill_read', 'one', 'reader', {'skill_id': skill['id'], 'resource': path}, role='research')
    assert 'Packaging material' in read('references/material.docx')['text']
    assert read('references/style.png')['image'].startswith('data:image/jpeg;base64,')
    assert not service.bindings('reader')


def test_catalogue_matches_sdk_tools_and_multiple_skills_remain_pinned(workspace):
    import re
    from pathlib import Path
    service = SkillService(workspace)
    source = (Path(__file__).parents[1] / 'app/openai_agent_worker.mjs').read_text()
    tools = set(re.findall(r'makeTool\(\s*[\'"]([^\'"]+)', source)) | set(DesignToolRegistry.SKILL_TOOLS) | set(DesignToolRegistry.MEMORY_TOOLS)
    assert set(service.tool_names()) == tools
    first = service.write(spec())
    second = service.write(spec(name='space-design', required_tools=['canvas_create_html']))
    add_turn(workspace, 'multi', '使用包装与空间技能，输出 SVG 矢量稿', status='running')
    for index, skill in enumerate((first, second)):
        service.bind('one', 'multi', skill['id'], active=True, operation_id=f'multi-{index}')
    assert len(service.runtime('multi')['active']) == 2
    assert not is_skill_management('使用包装skill创建网页')
    assert not is_skill_management('用包装skill生成图片')


def test_agent_pages_do_not_skip_catalogue_or_resource_entries(workspace):
    service = SkillService(workspace)
    for index in range(13):
        service.write(spec(name=f'method-{index}', description='范围'*500))
    add_turn(workspace, 'catalogue', '查询技能', status='running')
    first = service.execute('skill_list', 'one', 'catalogue', {'limit': 50})
    second = service.execute('skill_list', 'one', 'catalogue', {'offset': first['nextOffset']})
    assert len(first['skills']) == 10 and len(second['skills']) == 3
    assert len({s['id'] for s in first['skills'] + second['skills']}) == 13
    assert all(len(s['description']) <= 200 for s in first['skills'])
    skill = service.write(spec(resources=[{'path': f'references/r{i}.md', 'text': '参考'} for i in range(12)]))
    first = service.execute('skill_read', 'one', 'catalogue', {'skill_id': skill['id']})
    second = service.execute('skill_read', 'one', 'catalogue', {'skill_id': skill['id'], 'resource_offset': first['nextResourceOffset']})
    assert len(first['resources']) == 8 and len(second['resources']) == 4
