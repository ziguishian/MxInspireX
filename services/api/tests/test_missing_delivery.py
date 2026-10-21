import json
import pytest
from app.missing_delivery import prepare_missing, constrain_missing
from app.execution_store import ExecutionStore
from test_design_execution import env, plan, finish


def source_plan(env):
    store, project, _, tools, enqueue, call = env
    source = enqueue()
    from test_design_execution import plan
    with store._connect() as db:
        inputs = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (source,)).fetchone()[0])
        inputs['designPlan'] = {**plan(), 'ready': True, 'scopeId': 'original-scope', 'revision': 1}
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(inputs), source))
    finish(store, source, {'deliveryStatus':'needs_review'})
    return source


def test_missing_scope_is_server_owned_and_preserves_original_plan(env, monkeypatch):
    store, project, _, tools, enqueue, _ = env
    source = source_plan(env)
    rows = [{'id':'outer','status':'pending','nodeIds':[]}, {'id':'inner','status':'needs_review','nodeIds':['saved']}, {'id':'budget','status':'passed','nodeIds':['text']}]
    monkeypatch.setattr('app.missing_delivery.observe', lambda *a, **kw: rows)
    inputs = {}
    prepare_missing(store, project, source, inputs)
    assert inputs['missingDeliveryOnly']['itemIds'] == ['outer']
    inputs.update(designPlan={'ready':True,'deliverables':plan()['deliverables']},designBatch={'itemIds':['outer','inner','budget']},deliveryProgress=rows)
    constrain_missing(inputs)
    assert inputs['designBatch']['itemIds'] == ['outer']
    assert len(inputs['designPlan']['deliverables']) == 3
    assert inputs['designBatch']['currentProgress'] == [rows[0]]


def test_unknown_request_blocks_missing_generation_and_cross_project_is_rejected(env):
    store, project, _, _, _, _ = env
    source = source_plan(env)
    ExecutionStore(store).claim(source, 'generate_image', {'prompt':'pending'})
    with pytest.raises(ValueError, match='尚未确认'): prepare_missing(store, project, source, {})
    with pytest.raises(ValueError, match='不存在'): prepare_missing(store, 'other', source, {})


def test_enqueue_missing_keeps_saved_outputs_and_scopes_new_generation(env):
    store, project, runtime, tools, enqueue, call = env
    source = enqueue('做礼盒概念和预算，跳过参考')
    assert call(source, 'design_plan', plan=plan())['status'] == 'ready'
    saved = call(source, 'generate_image', prompt='外盒概念', provider='local-placeholder', deliverable_ids=['outer'])
    call(source, 'canvas_create_text', text='预算框架，报价待确认', deliverable_ids=['budget'])
    finish(store, source, {'designPlan': tools._task_input(project, source)['designPlan']})
    continuation = enqueue('继续原设计任务，仅补齐尚未生成的交付项，保留已保存产物。', repairMissingTaskId=source)
    inputs = tools._task_input(project, continuation)
    assert inputs['designBatch']['itemIds'] == ['inner']
    assert len(inputs['designPlan']['deliverables']) == 3
    assert call(continuation, 'design_plan', plan=plan())['status'] == 'plan_reused'
    blocked = call(continuation, 'generate_image', prompt='不能再生成外盒', provider='local-placeholder', deliverable_ids=['outer'])
    assert blocked['status'] == 'batch_scope_required'
    result = call(continuation, 'generate_image', prompt='补齐内装', provider='local-placeholder', deliverable_ids=['inner'])
    assert result['status'] == 'succeeded'
    assert len(tools.asset_store.list_assets(project)) == 2
    assert tools.canvas_store.load(project)['nodes'][0]['id'] == saved['node']['id']


def test_missing_cannot_mix_continuation_modes(env):
    store, project, runtime, tools, enqueue, call = env
    source = source_plan(env)
    with pytest.raises(ValueError, match='不能同时'):
        enqueue('补齐', repairMissingTaskId=source, clarificationTaskId=source)
