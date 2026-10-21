import pytest

from app.design_state import read_state
from app.main import new_project
from test_design_execution import env, finish


SHIP = '设计一套观光船概念方案，总长28.8米，总宽7.6米，空高不超过4.5米，约80人含船员。不要PPT。'
BRIEF = {'summary': SHIP, 'assumptions': ['以现代画舫为视觉方向'], 'openQuestions': ['营运航区是什么？']}


def test_brief_preserves_raw_request_and_sourced_dimensions_across_reload(env):
    store, project, runtime, tools, enqueue, call = env
    task = enqueue(SHIP)
    original = tools._task_input(project, task)
    result = call(task, 'design_state', brief=BRIEF, decisions=[
        {'field': 'length', 'label': '总长', 'value': '28.8米', 'status': 'confirmed', 'quote': '总长28.8米'},
        {'field': 'height', 'label': '空高上限', 'value': '不超过4.5米', 'status': 'confirmed', 'quote': '空高不超过4.5米'},
    ])
    assert result['status'] == 'recorded'
    state = read_state(store, project, task)
    assert state['brief'] == {**BRIEF, 'sourceTaskId': task, 'status': 'derived'}
    assert state['decisions']['length']['quote'] == '总长28.8米'
    assert state['goal'] == original['designState']['goal']
    current = tools._task_input(project, task)
    assert current['userMessage'] == SHIP
    assert current['deliveryContract'] == original['deliveryContract']
    assert runtime.get_task(project, task)['designState'] == state
    assert call(task, 'design_plan')['state']['brief'] == state['brief']


def test_brief_and_decisions_save_atomically_without_promoting_assumptions(env, tmp_path):
    store, project, _, _, enqueue, call = env
    task = enqueue(SHIP)
    before = read_state(store, project, task)
    result = call(task, 'design_state', brief=BRIEF, decisions=[
        {'field': 'length', 'value': '28.8米', 'status': 'confirmed', 'quote': '总长28.8米'},
        {'field': 'capacity', 'value': '100人', 'status': 'confirmed', 'quote': '约100人含船员'},
    ])
    assert result['status'] == 'invalid'
    assert read_state(store, project, task) == before
    assert call(task, 'design_state', brief=BRIEF)['status'] == 'recorded'
    assert read_state(store, project, task)['decisions'] == before['decisions']
    # A source task from another project cannot introduce confirmed facts.
    other = store.create_project(new_project(
        name='其他项目', slug='other', brief='100人', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'other')))
    result = env[2].enqueue(project_id=other['id'], agent_key='design', workflow_step='design', brief='100人', run_async=True)
    assert call(task, 'design_state', decisions=[{'field': 'capacity', 'value': '100人', 'status': 'confirmed', 'quote': '100人', 'sourceTaskId': result['id']}])['status'] == 'invalid'


@pytest.mark.parametrize('brief', [
    {'summary': ' '}, {'summary': 'x' * 3001}, {'summary': '设计', 'assumptions': ['']},
    {'summary': '设计', 'openQuestions': ['问题'] * 9}, {'summary': '设计', 'status': 'confirmed'},
])
def test_invalid_brief_does_not_change_saved_state(env, brief):
    store, project, _, _, enqueue, call = env
    task = enqueue(SHIP)
    before = read_state(store, project, task)
    assert call(task, 'design_state', brief=brief)['status'] == 'invalid'
    assert read_state(store, project, task) == before


def test_acceptance_reuses_brief_but_changed_request_invalidates_it(env):
    store, project, _, _, enqueue, call = env
    task = enqueue(SHIP)
    call(task, 'design_state', brief=BRIEF)
    finish(store, task, {})
    resumed = enqueue('继续')
    assert read_state(store, project, resumed)['brief']['sourceTaskId'] == task
    finish(store, resumed, {})
    changed = enqueue('继续，人数改为60人，只做侧视图')
    assert 'brief' not in read_state(store, project, changed)
    call(changed, 'design_state', brief={'summary': '只做侧视图，人数60人'})
    call(changed, 'design_state', decisions=[{'field': 'capacity', 'value': '60人', 'quote': '人数改为60人', 'status': 'confirmed'}])
    assert 'brief' not in read_state(store, project, changed)


@pytest.mark.parametrize('message', ['根据以下补充信息继续原设计任务。', '继续'])
def test_clarification_keeps_answers_but_discards_outdated_brief(env, message):
    store, project, _, _, enqueue, call = env
    task = enqueue(SHIP)
    call(task, 'design_state', brief=BRIEF)
    finish(store, task, {'clarification': {'questions': [{'id': 'area', 'question': '营运航区是什么？'}]}})
    continued = enqueue(message, clarificationTaskId=task,
                        clarificationAnswers=[{'questionId': 'area', 'value': '', 'skipped': True}])
    state = read_state(store, project, continued)
    assert 'brief' not in state
    assert any(d['status'] == 'skipped' for d in state['decisions'].values())


def test_simple_edit_and_client_supplied_brief_do_not_trigger_refinement(env):
    store, project, _, _, enqueue, call = env
    task = enqueue('只把背景改成白色', designState={'brief': BRIEF})
    assert 'brief' not in call(task, 'design_state')['state']
    assert 'brief' not in read_state(store, project, task)
