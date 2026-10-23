import copy

import pytest

from app.design_planning import save_design_plan, reused_plan_receipt, VisualDirection
from app.image_reference_design import DesignSpecError
from test_design_execution import env
from test_gift_plan_recovery import gift_plan


@pytest.mark.parametrize('missing', ['direction', 'spec', 'concrete'])
def test_invalid_visual_plan_is_not_saved_as_ready(env, missing):
    store, project, _, tools, enqueue, _ = env
    task = enqueue()
    plan = gift_plan()
    if missing == 'direction':
        plan['visualDirection'] = None
    elif missing == 'spec':
        plan['deliverables'][0]['imageSpec'] = None
    else:
        plan['deliverables'][0]['imageSpec']['subjectStructure'] = '高级感'
    with pytest.raises(DesignSpecError):
        save_design_plan(store, project, task, plan)
    assert not tools._task_input(project, task).get('designPlan')


def test_saved_brief_supplies_direction_and_legacy_invalid_plan_is_not_reused(env):
    import json
    store, project, _, tools, enqueue, _ = env
    task = enqueue()
    plan = gift_plan()
    direction = plan.pop('visualDirection')
    context = tools._task_input(project, task)
    context['designState'] = {'brief': {'visualDirection': direction}}
    with store._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context), task))
    result = save_design_plan(store, project, task, plan)
    assert result['plan']['ready']
    assert result['plan']['visualDirection'] == VisualDirection.model_validate(direction).model_dump()
    legacy = copy.deepcopy(result['plan'])
    legacy['visualDirection'] = None
    rejected = reused_plan_receipt({'designPlan': legacy})
    assert rejected['status'] == 'design_spec_required'
    assert rejected['submitted'] is False
    assert 'change_reason' in rejected['instruction']


def test_valid_multi_image_plan_and_legacy_compact_plan_remain_executable(env):
    store, project, _, _, enqueue, _ = env
    result = save_design_plan(store, project, enqueue(), gift_plan())
    assert result['plan']['ready']
    assert len(result['plan']['deliverables']) == 7
    assert reused_plan_receipt({'designPlan': result['plan']})['status'] == 'plan_reused'
    from test_design_execution import plan
    compact = save_design_plan(store, project, enqueue(), plan())
    assert compact['plan']['ready']


@pytest.mark.parametrize('kind', ['text', 'html'])
def test_text_node_is_not_persisted_as_image_asset_input(env, kind):
    store, project, _, tools, enqueue, _ = env
    task = enqueue()
    node = tools.canvas_store.create_node(project, kind=kind, title='text source', data={'text':'blue teapot'})
    value = gift_plan()
    value['deliverables'][0]['inputs'] = [{'source':'asset','id':node['id'],'role':'content','purpose':'use latest text'}]
    with pytest.raises(ValueError, match='不能填写文字或 HTML 节点 ID'):
        save_design_plan(store, project, task, value)
    assert not tools._task_input(project, task).get('designPlan')
    value['deliverables'][0]['inputs'] = []
    assert save_design_plan(store, project, task, value)['plan']['ready']


def test_plain_node_text_inventory_error_is_correctable_before_writing(env):
    store, project, _, tools, enqueue, call = env
    target = tools.canvas_store.create_node(project, kind='text', title='output')
    task = enqueue('只生成一句文字描述', taskSurface='canvas_node',
                   canvasParams={'kind':'text','canvasNodeId':target['id']})
    args = {'text':'蓝色茶壶，黄色背景。','canvas_node_id':target['id'],
            'application_items':[{'title':'description','priority':'recommended','deliverable_id':'invented'}]}
    rejected = call(task, 'canvas_create_text', **args)
    assert rejected['status'] == 'invalid_arguments' and rejected['submitted'] is False
    assert rejected['fieldPath'] == 'application_items'
    assert not tools.canvas_store.load(project)['nodes'][0]['data'].get('text')
    del args['application_items']
    saved = call(task, 'canvas_create_text', **args)
    assert saved['node']['id'] == target['id']
    assert saved['node']['data']['text'] == args['text']
    assert call(task, 'canvas_create_text', **args)['node']['id'] == target['id']
    assert len(tools.canvas_store.load(project)['nodes']) == 1
