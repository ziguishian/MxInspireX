import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.canvas import CanvasStore
from app.skills import SkillService
from test_conversation_context import workspace, add_turn

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures'


def run_worker(workspace, task_id, project_id, mode, api, skill_id='', recovery=None, persistent=False):
    from app.svg_policy import ensure_task_policy
    svg_policy = ensure_task_policy(workspace, task_id)
    state = SkillService(workspace).runtime(task_id)
    if mode == 'svg_legacy_snapshot':
        svg_policy = {'mode':'auto','allowed':True}
    author = mode.startswith('create')
    # Full tool-catalog integration, not a small-context budget fixture.
    payload = {'apiKey': 'fixture-key-only', 'model': 'fixture', 'api': api, 'baseUrl': 'http://skill-fixture.invalid/v1',
               'modelCapabilities': {'contextLength': 128000}, 'maxOutputTokens': 4096, 'skills': state,
               'persistentSessions': persistent, 'recovery': recovery or {},
               'toolGateway': {'baseUrl': 'http://skill-fixture.invalid', 'projectId': project_id, 'taskId': task_id},
               'context': {'projectId': project_id, 'taskId': task_id, 'brief': '创建包装设计Skill' if author else '处理当前需求',
                           'constraints': {'svgPolicy': svg_policy, 'skillManagement': author, 'skillCreationRequired': author, 'executionFlow': 'direct', 'agentCollaboration': False}}}
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONPATH': str(ROOT), 'FIXTURE_PYTHON': sys.executable, 'FIXTURE_WORKSPACE': str(workspace.workspace_root),
           'FIXTURE_SKILL_MODE': mode, 'FIXTURE_SKILL_ID': skill_id}
    result = subprocess.run([shutil.which('node'), '--import', (FIXTURES / 'skills_transport.mjs').resolve().as_uri(), str(ROOT / 'app/openai_agent_worker.mjs')],
                            input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, env=env, timeout=60)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    return result, events


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_creates_then_other_project_loads_and_uses_skill(workspace, api):
    add_turn(workspace, 'author', '创建包装设计Skill', status='running')
    result, events = run_worker(workspace, 'author', 'one', 'create', api)
    assert result.returncode == 0, result.stderr + result.stdout[-3000:]
    assert any(e['type'] == 'result' for e in events)
    service = SkillService(workspace)
    skill = service.list()['skills'][0]
    assert not service.bindings('author')
    assert CanvasStore(workspace).load('one')['nodes'] == []
    add_turn(workspace, 'use', '处理当前需求', project='two', status='running')
    result, events = run_worker(workspace, 'use', 'two', 'use', api, skill['id'])
    assert result.returncode == 0, result.stderr + result.stdout[-3000:]
    assert service.bindings('use')[0]['version'] == 1
    assert len(CanvasStore(workspace).load('two')['nodes']) == 1
    assert any(e['type'] == 'event' and e.get('phase') == 'skill' for e in events)


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_hash_selection_loads_before_first_request_and_does_not_reload_unloaded_binding(workspace, api):
    service = SkillService(workspace)
    skill = service.write({'name': 'logo-suite', 'description': 'Logo 样机', 'instructions': '莓红色_SKILL_RULE_V1', 'required_tools': ['export_deliverable']})
    selected = service.resolve_mentions('#skill:' + skill['id'])
    add_turn(workspace, 'mention', '#skill:' + skill['id'], status='running', extra={'referencedSkills': selected})
    result, events = run_worker(workspace, 'mention', 'one', 'mention', api, skill['id'])
    assert result.returncode == 0, result.stderr + result.stdout[-3000:]
    assert service.bindings('mention')[0]['version'] == 1
    assert any(e.get('phase') == 'skill' for e in events)
    service.bind('one', 'mention', skill['id'], active=False, operation_id='explicit-unload')
    result, events = run_worker(workspace, 'mention', 'one', 'mention_unloaded', api, skill['id'])
    assert result.returncode == 0, result.stderr + result.stdout[-3000:]
    assert not service.bindings('mention')[0]['active']
    assert not any(e.get('phase') == 'skill' for e in events)


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_unload_then_reload_updates_context(workspace, api):
    service = SkillService(workspace)
    skill = service.write({'name': 'packaging-design', 'description': '包装', 'instructions': '莓红色_SKILL_RULE_V1'})
    add_turn(workspace, 'use', '处理当前需求', status='running')
    result, events = run_worker(workspace, 'use', 'one', 'unload', api, skill['id'])
    assert result.returncode == 0, result.stderr + result.stdout[-3000:]
    assert service.bindings('use')[0]['active']


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_restart_restores_deleted_original_version(workspace, api):
    service = SkillService(workspace)
    skill = service.write({'name': 'packaging-design', 'description': '包装', 'instructions': '莓红色_SKILL_RULE_V1'})
    add_turn(workspace, 'use', '处理当前需求', status='running')
    result, events = run_worker(workspace, 'use', 'one', 'interrupt', api, skill['id'], persistent=True)
    assert result.returncode == 0
    assert service.bindings('use')[0]['active']
    final = next(e['result'] for e in events if e['type'] == 'result')
    assert final['structured_data']['deliveryStatus'] == 'needs_review'
    recovery = final['provenance']['recovery']
    assert recovery['skillBindings'][0]['version'] == 1
    with workspace._connect() as db:
        stored = json.loads(db.execute('SELECT items FROM sdk_sessions').fetchone()['items'])
    assert '历史 Skill 操作摘要' not in json.dumps(stored, ensure_ascii=False)
    service.write({'expected_version': 1, 'instructions': 'NEW_VERSION_ONLY'}, skill_id=skill['id'])
    service.delete(skill['id'], 2)
    resumed, events = run_worker(workspace, 'use', 'one', 'resume', api, skill['id'], recovery=recovery, persistent=True)
    assert resumed.returncode == 0, resumed.stderr + json.dumps([e.get('message') for e in events if e['type'] == 'error'], ensure_ascii=False)
    with workspace._connect() as db:
        stored = json.loads(db.execute('SELECT items FROM sdk_sessions').fetchone()['items'])
    assert sum(i.get('name') == 'skill_load' and i['type'] == 'function_call' for i in stored) == 1
    assert '历史 Skill 操作摘要' not in json.dumps(stored, ensure_ascii=False)
    assert service.bindings('use')[0]['version'] == 1
    assert len(CanvasStore(workspace).load('one')['nodes']) == 1


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_creation_continues_past_draft_and_validation_failure(workspace, api):
    add_turn(workspace, 'author', '创建包装设计Skill', status='running')
    result, events = run_worker(workspace, 'author', 'one', 'create_retry', api, persistent=True)
    assert result.returncode == 0, result.stderr + result.stdout[-4000:]
    assert SkillService(workspace).list()['total'] == 1
    assert CanvasStore(workspace).load('one')['nodes'] == []
    assert any(e.get('phase') == 'progress' and '尚未保存' in e.get('message', '') for e in events)
    texts = [e for e in events if e.get('phase') == 'text']
    assert texts and all('PREMATURE' not in e['message'] for e in texts)
    recovery = [e['recovery'] for e in events if e['type'] == 'checkpoint'][-1]
    assert recovery['stageTurns']['design'] >= 4


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_creation_never_claims_success_without_receipt(workspace, api):
    add_turn(workspace, 'author', '创建包装设计Skill', status='running')
    result, events = run_worker(workspace, 'author', 'one', 'create_stalled', api)
    assert result.returncode != 0
    assert SkillService(workspace).list()['total'] == 0
    assert not any(e['type'] == 'result' or e.get('phase') == 'text' for e in events)
    assert any('尚未创建成功' in e.get('message', '') for e in events)


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
@pytest.mark.parametrize('name', ['logo-mockup-suite','tourism-ip-design','notebook-print-design','scenic-wayfinding-design','xiaohongshu-visual-post'])
def test_builtin_loaded_and_executed_with_real_sdk_and_local_tools(workspace,api,name):
    from app.bundled_skills import install_bundled_skills
    from app.assets import AssetStore
    service=SkillService(workspace)
    install_bundled_skills(service)
    skill=service.list(query=name)['skills'][0]
    add_turn(workspace,'builtin','分别生成笔记本封面和封底图片，不需要下载包' if name=='notebook-print-design' else '使用内置技能',project='two',status='running')
    result,events=run_worker(workspace,'builtin','two','builtin:'+name,api,skill['id'])
    assert result.returncode == 0,result.stderr+result.stdout[-5000:]
    assert service.bindings('builtin')[0]['skillId'] == skill['id']
    assert any(e['type']=='result' for e in events)
    assert len(CanvasStore(workspace).load('two')['nodes']) == 1
    assert not AssetStore(workspace).list_assets('two')
    assert 'canvas_create_svg' not in service.get(skill['id'])['requiredTools']
