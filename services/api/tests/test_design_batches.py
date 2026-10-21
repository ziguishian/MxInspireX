"""Real local assets and task transitions, without upstream requests."""
import json
from pathlib import Path
from test_design_execution import env, finish


def plan(prefix='B1', count=6):
    return {'goal': '展会品牌物料分批延展', 'preserve': ['沿用原 Logo'],
        'deliverables': [{'id': f'{prefix}-{i}', 'title': f'{prefix}物料{i}', 'kind': 'image', 'representation': 'raster', 'acceptance': '原 Logo 与配色保持一致'} for i in range(count)],
        'coverage': [], 'deferred': ['下一批建议：海报、邀请图、社交封面、导视、接待台、桌布'], 'openQuestions': [], 'research': '采用用户原图'}


def create_first(env, count=6, completed=None):
    store, _, _, _, enqueue, call = env
    task = enqueue('展会物料延展。跳过参考')
    assert call(task, 'design_plan', plan=plan(count=count))['status'] == 'ready'
    nodes = [call(task, 'generate_image', prompt=f'物料{i}', provider='local-placeholder', deliverable_ids=[f'B1-{i}'])['node'] for i in range(count if completed is None else completed)]
    report = call(task, 'delivery_verify')
    finish(store, task, {'delivery': report, 'deliveryStatus': 'passed' if report['passed'] else 'pending', 'review': {'passed': report['passed']}, 'answer': '下一批做海报等，回复继续。'})
    return task, nodes


def test_next_batch_registers_before_generation_and_preserves_real_outputs(env):
    store, project, runtime, tools, enqueue, call = env
    first, old_nodes = create_first(env)
    second = enqueue('好的，继续', designBatch={'intent': 'resume', 'status': 'ready', 'itemIds': ['B1-0']})
    task = runtime.get_task(project, second)
    assert task['designBatch']['intent'] == 'next_batch' and task['designBatch']['status'] == 'needs_plan'
    assert task['designBatch']['itemIds'] == []
    assert len(task['deliveryProgress']) == 6 and all(r['status'] == 'passed' for r in task['deliveryProgress'])
    before = len(tools.asset_store.list_assets(project))
    assert call(second, 'generate_image', prompt='旧项', provider='local-placeholder', deliverable_ids=['B1-0'])['status'] == 'planning_required'
    assert call(second, 'generation_reference_check', operations=[{'tool': 'generate_image', 'arguments': {'deliverable_ids': ['B2-0']}}])['status'] == 'planning_required'
    assert len(tools.asset_store.list_assets(project)) == before
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tool_receipts WHERE task_id=?', (second,)).fetchone()[0] == 0
    saved = call(second, 'design_plan', plan=plan('B2'))
    assert saved['status'] == 'ready', saved
    assert len(saved['plan']['deliverables']) == 12 and saved['plan']['scopeId'] == first
    assert saved['batch']['number'] == 2 and saved['batch']['itemIds'] == [f'B2-{i}' for i in range(6)]
    assert all(r['status'] == 'pending' for r in saved['batch']['currentProgress'])
    assert len([r for r in saved['progress'] if r['status'] == 'passed']) == 6
    assert call(second, 'design_plan', plan=plan('B2'))['plan']['revision'] == saved['plan']['revision']
    assert call(second, 'generate_image', prompt='空清单绕过', provider='local-placeholder', deliverable_ids=[])['status'] == 'delivery_assignment_required'
    assert call(second, 'generate_image', prompt='复用', provider='local-placeholder', deliverable_ids=['B1-0'])['reused']
    assert call(second, 'generate_image', prompt='误覆盖', provider='local-placeholder', canvas_node_id=old_nodes[0]['id'], output_mode='edit', deliverable_ids=['B2-0'])['status'] == 'batch_scope_required'
    for i in range(6):
        assert call(second, 'generate_image', prompt=f'新物料{i}', provider='local-placeholder', output_mode='create', deliverable_ids=[f'B2-{i}']).get('assetId')
    current = runtime.get_task(project, second)
    assert len(current['designBatch']['currentProgress']) == 6
    assert all(r['status'] == 'passed' for r in current['designBatch']['currentProgress'])
    assert len(current['deliveryProgress']) == 12 and len(tools.asset_store.list_assets(project)) == before + 6
    actual = {n['id']: n for n in tools.canvas_store.load(project)['nodes']}
    assert all(actual[n['id']]['data']['assetId'] == n['data']['assetId'] for n in old_nodes)


def test_partial_batch_resumes_and_missing_file_invalidates_completion(env):
    _, project, runtime, tools, enqueue, call = env
    _, nodes = create_first(env, completed=2)
    continued = enqueue('继续未完成项')
    task = runtime.get_task(project, continued)
    assert task['designBatch']['intent'] == 'resume' and task['designBatch']['number'] == 1
    assert len(task['designBatch']['itemIds']) == 6
    assert sum(r['status'] in {'ready', 'passed'} for r in task['deliveryProgress']) == 2
    assert call(continued, 'generate_image', prompt='旧项', provider='local-placeholder', deliverable_ids=['B1-0'])['reused']
    asset = tools.asset_store.get_asset(project_id=project, asset_id=nodes[0]['data']['assetId'])
    Path(asset['absolutePath']).unlink()
    assert call(continued, 'design_plan')['progress'][0]['status'] == 'pending'


def test_cancelled_transition_does_not_skip_batch(env):
    store, project, runtime, _, enqueue, call = env
    create_first(env, count=1)
    second = enqueue('制作下一批')
    with store._connect() as db: db.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (second,))
    resumed = enqueue('继续')
    batch = runtime.get_task(project, resumed)['designBatch']
    assert batch['intent'] == 'next_batch' and batch['number'] == 2 and batch['status'] == 'needs_plan'
    assert call(resumed, 'design_plan', plan=plan('B2', 2))['status'] == 'ready'


def test_revision_creates_new_image_node_with_separate_current_and_cumulative_progress(env):
    _, project, runtime, tools, enqueue, call = env
    _, nodes = create_first(env, count=2)
    revised = enqueue('修改上一批，把第一个物料改为绿色')
    assert runtime.get_task(project, revised)['designBatch']['intent'] == 'revise'
    value = plan(count=1); value['currentItemIds'] = ['B1-0']
    value['deliverables'][0]['acceptance'] = '保留原 Logo，改为绿色'
    saved = call(revised, 'design_plan', plan=value)
    assert saved['status'] == 'ready', saved
    assert len(saved['plan']['deliverables']) == 2 and saved['batch']['currentProgress'][0]['status'] == 'pending'
    assert all(r['status'] == 'passed' for r in saved['progress'])
    assert call(revised, 'generate_image', prompt='绿色', provider='local-placeholder', deliverable_ids=['B1-0'])['status'] == 'batch_scope_required'
    edited = call(revised, 'generate_image', prompt='绿色', provider='local-placeholder', canvas_node_id=nodes[0]['id'], source_asset_id=nodes[0]['data']['assetId'], output_mode='edit', deliverable_ids=['B1-0'])
    assert edited['node']['id'] != nodes[0]['id']
    assert runtime.get_task(project, revised)['designBatch']['currentProgress'][0]['status'] == 'passed'
    board={node['id']:node for node in tools.canvas_store.load(project)['nodes']}
    assert board[nodes[0]['id']]['data']['assetId']==nodes[0]['data']['assetId']
    assert len(board) == 3


def test_legacy_progress_rebuilt_from_real_assets(env):
    store, project, runtime, _, enqueue, _ = env
    first, _ = create_first(env, count=2)
    with store._connect() as db:
        data = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (first,)).fetchone()[0])
        data.pop('designBatch'); data.pop('deliveryProgress'); data['designPlan'].pop('currentItemIds')
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), first))
    task = runtime.get_task(project, enqueue('好的，继续'))
    assert task['designBatch']['intent'] == 'next_batch'
    assert len(task['deliveryProgress']) == 2 and all(r['status'] == 'passed' for r in task['deliveryProgress'])


def test_explicit_next_batch_can_finish_while_previous_missing_items_remain_cumulative(env):
    store, project, runtime, tools, enqueue, call = env
    create_first(env, count=2, completed=1)
    second = enqueue('制作下一批')
    value = plan('B2', 2)
    saved = call(second, 'design_plan', plan=value)
    assert saved['status'] == 'ready'
    call(second, 'generate_image', prompt='新海报', provider='local-placeholder', output_mode='create', deliverable_ids=['B2-0'])
    report = call(second, 'delivery_verify')
    finish(store, second, {'delivery': report})
    resumed = enqueue('继续')
    batch = runtime.get_task(project, resumed)['designBatch']
    assert batch['intent'] == 'resume' and batch['number'] == 2 and batch['itemIds'] == ['B2-0', 'B2-1']
    call(resumed, 'generate_image', prompt='新邀请图', provider='local-placeholder', output_mode='create', deliverable_ids=['B2-1'])
    report = call(resumed, 'delivery_verify')
    assert report['passed'], report['issues']
    assert len(report['artifacts']) == 2 and len(report['deliverables']) == 4
    assert next(r for r in report['deliverables'] if r['id']=='B1-1')['status'] == 'pending'
    assert all(r['status']=='passed' for r in report['designBatch']['currentProgress'])
    from app.delivery_findings import annotate_delivery
    data = {'delivery': report}
    annotate_delivery(data)
    assert data['deliveryStatus'] == 'passed'


def test_legacy_cancelled_after_appending_next_plan_resumes_only_new_items(env):
    store, project, runtime, _, enqueue, call = env
    create_first(env,count=2)
    second=enqueue('好的，继续')
    assert call(second,'design_plan',plan=plan('B2',2))['status']=='ready'
    with store._connect() as db:
        data=json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?',(second,)).fetchone()[0])
        data.pop('designBatch');data.pop('deliveryProgress');data['designPlan'].pop('currentItemIds')
        db.execute("UPDATE tasks SET status='cancelled',input_json=? WHERE id=?",(json.dumps(data),second))
    task=runtime.get_task(project,enqueue('继续'))
    assert task['designBatch']['intent']=='resume' and task['designBatch']['number']==2
    assert task['designBatch']['itemIds']==['B2-0','B2-1']
    assert len(task['deliveryProgress'])==4
    assert all(r['status']=='pending' for r in task['designBatch']['currentProgress'])


def test_final_review_overrides_an_earlier_unverified_progress_snapshot(env):
    store, project, runtime, _, enqueue, _ = env
    first, _ = create_first(env,count=1)
    with store._connect() as db:
        data=json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?',(first,)).fetchone()[0])
        data['deliveryProgress'][0]['status']='needs_review'
        db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(data),first))
    task=runtime.get_task(project,enqueue('继续'))
    assert task['designBatch']['intent']=='next_batch'
    assert task['deliveryProgress'][0]['status']=='passed'
