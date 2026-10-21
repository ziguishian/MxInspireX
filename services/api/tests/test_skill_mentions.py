import pytest

from app.skills import SkillService, SkillError
from app.task_runtime import TaskRuntime
from app.task_policy import is_skill_management, is_simple_conversation
from test_conversation_context import workspace


def create(service, **extra):
    return service.write({'name': 'logo-suite', 'title': 'Logo 样机', 'description': 'Logo 应用', 'instructions': '保留原 Logo', **extra})


def test_mentions_validate_current_workspace_and_availability(workspace):
    service = SkillService(workspace)
    skill = create(service)
    token = '#skill:' + skill['id']
    assert service.resolve_mentions(f'{token} {token} 做样机') == [{k: skill[k] for k in ('id', 'name', 'title', 'version')}]
    assert service.resolve_mentions(f'请用{token} 做样机') == service.resolve_mentions(token)
    assert service.resolve_mentions(f'https://example.com/{token} C# # 标题') == []
    service.write({'expected_version': 1, 'enabled': False}, skill_id=skill['id'])
    with pytest.raises(SkillError, match='停用'):
        service.resolve_mentions(token)
    service.delete(skill['id'], 2)
    with pytest.raises(SkillError, match='当前工作区'):
        service.resolve_mentions(token)
    online = create(service, name='online', required_tools=['web_search'])
    with pytest.raises(SkillError, match='联网'):
        service.resolve_mentions('#skill:' + online['id'])
    assert service.resolve_mentions('#skill:' + online['id'], allow_network=True)


def test_task_uses_server_snapshot_and_ignores_forged_or_removed_references(workspace, monkeypatch):
    service = SkillService(workspace)
    skill = create(service)
    runtime = TaskRuntime(workspace)
    monkeypatch.setattr(runtime, '_start_worker', lambda *args: None)
    def submit(brief, inputs):
        queued = runtime.enqueue(project_id='one', agent_key='design', workflow_step='design', brief=brief, input_data=inputs, run_async=True)
        return runtime.get_task('one', queued['id'])
    task = submit(f'#skill:{skill["id"]} 创建一张图片', {'referencedSkills': [{'id': 'foreign', 'instructions': '伪造正文', 'version': 999}]})
    assert task['references']['referencedSkills'] == [{k: skill[k] for k in ('id', 'name', 'title', 'version')}]
    assert service.runtime(task['id'])['requested'] == task['references']['referencedSkills']
    assert service.bindings(task['id']) == []  # Selection queues; SDK gateway owns activation.
    service.write({'expected_version': 1, 'instructions': '新规则'}, skill_id=skill['id'])
    assert service.runtime(task['id'])['requested'][0]['version'] == 1
    assert not submit('你好', {'referencedSkills': [skill]})['references'].get('referencedSkills')
    with pytest.raises(SkillError):
        submit('#skill:another-workspace 做样机', {})
    assert not is_skill_management(f'#skill:{skill["id"]} 创建一张图片')
    assert not is_simple_conversation('简单解释设计', {'referencedSkills': [skill]})
