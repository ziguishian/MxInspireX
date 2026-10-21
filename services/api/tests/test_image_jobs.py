import copy
import json
import threading
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.image_jobs import ImageJobs
from test_design_execution import env
from test_gift_plan_recovery import gift_plan


def wait(jobs, project, task, operation):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = jobs.read(project, task, operation['operationId'])
        if result['state'] != 'running': return result
        time.sleep(.01)
    raise AssertionError('local fixture operation did not settle')


def setup(env):
    store, project, _, tools, enqueue, call = env
    task = enqueue('制作七项礼盒，每项一张概念图，跳过参考。')
    with store._connect() as db: db.execute("UPDATE tasks SET status='running' WHERE id=?", (task,))
    assert call(task, 'design_plan', plan=gift_plan())['status'] == 'ready'
    return store, project, tools, task, ImageJobs(store, tools.executions)


def test_seven_image_jobs_finish_after_submitter_disconnect_and_are_not_recharged(env):
    store, project, tools, task, jobs = setup(env)
    release = threading.Event()
    submitted = []
    operations = []
    def generate(args):
        assert release.wait(10)
        submitted.append(args['deliverable_ids'][0])
        return tools.execute(project_id=project, task_id=task, name='generate_image', arguments=args)
    for item in gift_plan()['deliverables']:
        args = {'prompt': item['title'], 'provider': 'local-placeholder', 'deliverable_ids': [item['id']]}
        op = jobs.submit(project, task, args, lambda a=args: generate(a))
        assert op['state'] == 'running'
        assert jobs.submit(project, task, args, lambda: pytest.fail('duplicate charge'))['operationId'] == op['operationId']
        operations.append((args, op))
    assert not submitted
    release.set()
    results = [wait(jobs, project, task, op) for _, op in operations]
    assert all(r['state'] == 'completed' and r['output']['status'] == 'succeeded' for r in results), results
    assert len(submitted) == len(set(submitted)) == 7
    restarted = ImageJobs(store, tools.executions)
    for (args, op), result in zip(operations, results):
        again = restarted.submit(project, task, args, lambda: pytest.fail('restart must reuse saved assets'))
        assert again['output']['assetId'] == result['output']['assetId']
        assert restarted.read_arguments(project, task, args)['operationId'] == op['operationId']
    assert len(tools.asset_store.list_assets(project)) == 7


def test_orphaned_job_queries_original_receipt_and_never_submits_again(env):
    store, project, tools, task, jobs = setup(env)
    args = {'prompt': '礼盒', 'deliverable_ids': ['gift-box']}
    op_id, encoded = jobs.identity(project, task, args)
    with store._connect() as db:
        db.execute('INSERT INTO image_operations VALUES (?,?,?,?,?,?,?,?,?)',
                   (op_id, project, task, encoded, 'running', None, None, jobs.now(), jobs.now()))
    op = jobs.submit(project, task, args, lambda: pytest.fail('unknown charge must not be resubmitted'))
    assert op['state'] == 'unconfirmed' and op['retryable'] is False
    fingerprint, _ = tools.executions.claim(task, 'generate_image', args)
    tools.executions.complete(task, fingerprint, {'status': 'succeeded', 'assetId': 'late-saved'})
    assert jobs.read(project, task, op_id)['output']['assetId'] == 'late-saved'


def test_operation_lookup_checks_project_and_task_ownership(env):
    store, project, tools, task, jobs = setup(env)
    op = jobs.submit(project, task, {'prompt': '本地预检'}, lambda: {'status': 'image_parameters_invalid'})
    for other_project, other_task in [('different-project', task), (project, 'other-task')]:
        with pytest.raises(HTTPException) as error:
            jobs.read(other_project, other_task, op['operationId'])
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            jobs.read_arguments(other_project, other_task, {'prompt': '本地预检'})
        assert error.value.status_code == 404
    wait(jobs, project, task, op)
    with store._connect() as db: db.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (task,))
    assert jobs.read(project, task, op['operationId'])['state'] == 'cancelled'
    with pytest.raises(HTTPException): jobs.submit(project, task, {'prompt': '新的'}, lambda: pytest.fail('cancelled'))


def test_lost_local_reply_retains_http_validation_semantics(env):
    _, project, _, task, jobs = setup(env)
    def invalid(): raise HTTPException(status_code=422, detail='参数校验失败，尚未生成')
    result = wait(jobs, project, task, jobs.submit(project, task, {'prompt': '待修正'}, invalid))
    assert result['httpStatus'] == 422 and result['output']['detail'].startswith('参数校验失败')


def test_plan_compare_and_swap_rejects_stale_explicit_edits_without_losing_design(env):
    store, project, tools, task, _ = setup(env)
    original = tools._task_input(project, task)['designPlan']
    change = copy.deepcopy(gift_plan()); change['goal'] = '保留礼盒内容，完善秋桂表达'
    updated = tools.design_plan(project_id=project, task_id=task, plan=change, change_reason='补充视觉表达',
                                expected_revision=original['revision'], expected_scope_id=original['scopeId'])
    assert updated['plan']['revision'] == original['revision'] + 1
    stale = tools.design_plan(project_id=project, task_id=task, plan=gift_plan(), change_reason='旧请求迟到',
                              expected_revision=original['revision'], expected_scope_id=original['scopeId'])
    assert stale['status'] == 'plan_conflict' and stale['submitted'] is False
    assert tools._task_input(project, task)['designPlan'] == updated['plan']


def test_local_preflight_rejection_can_be_rechecked_without_replaying_a_charge(env):
    _, project, _, task, jobs = setup(env)
    args = {'prompt': '已补充资料的礼盒'}
    first = jobs.submit(project, task, args, lambda: {'status': 'memory_required', 'submitted': False})
    assert wait(jobs, project, task, first)['output']['status'] == 'memory_required'
    calls = []
    second = jobs.submit(project, task, args, lambda: calls.append('submit') or {'status': 'succeeded', 'assetId': 'once'})
    assert wait(jobs, project, task, second)['output']['assetId'] == 'once'
    jobs.submit(project, task, args, lambda: pytest.fail('success cannot be resubmitted'))
    assert calls == ['submit']


def test_http_accepts_once_and_observes_late_result_by_id_or_original_arguments(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    store, project, tools, task, jobs = setup(env)
    monkeypatch.setattr(app.state, 'store', store, raising=False)
    monkeypatch.setattr(app.state, 'design_tools', tools, raising=False)
    monkeypatch.setattr(app.state, 'tasks', env[2], raising=False)
    monkeypatch.setattr(app.state, 'image_jobs', jobs, raising=False)
    release = threading.Event()
    entered = threading.Event()
    from app.providers.local import LocalImageProvider
    generate = LocalImageProvider.generate
    calls = []
    def slow(self, **kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(10)
        return generate(self, **kwargs)
    monkeypatch.setattr(LocalImageProvider, 'generate', slow)
    client = TestClient(app)
    prefix = f'/api/projects/{project}/tasks/{task}'
    url = f'/api/projects/{project}/agent-tools/generate_image'
    headers = {'x-aics-task-id': task, 'x-aics-async-tool': '1'}
    args = {'prompt': '礼盒外盒', 'provider': 'local-placeholder', 'deliverable_ids': ['gift-box']}
    try:
        accepted = client.post(url, json=args, headers=headers)
        assert accepted.status_code == 202
        operation = accepted.json()
        assert entered.wait(5)
        assert client.post(url, json=args, headers=headers).json()['operationId'] == operation['operationId']
        assert client.get(prefix+'/image-operations/'+operation['operationId']).json()['state'] == 'running'
        assert client.post(prefix+'/tool-result', json={'name': 'generate_image', 'arguments': args}).json()['operationId'] == operation['operationId']
    finally:
        release.set()
    result = wait(jobs, project, task, operation)
    assert result['output']['assetId']
    assert client.get(prefix+'/image-operations/'+operation['operationId']).json()['output']['assetId'] == result['output']['assetId']
    assert len(calls) == 1


def test_audio_http_operation_survives_disconnect_without_second_submission(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    store, project, tools, task, _ = setup(env)
    jobs = ImageJobs(store,tools.executions,'generate_audio')
    for name,value in {'store':store,'design_tools':tools,'tasks':env[2],'audio_jobs':jobs}.items():
        monkeypatch.setattr(app.state,name,value,raising=False)
    release=threading.Event();calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        assert release.wait(10)
        return {'tool':'generate_audio','status':'succeeded','assetId':'original-audio'}
    monkeypatch.setattr(tools,'execute',generate)
    client=TestClient(app)
    url=f'/api/projects/{project}/agent-tools/generate_audio'
    prefix=f'/api/projects/{project}/tasks/{task}'
    args={'prompt':'测试音频'};headers={'x-aics-task-id':task,'x-aics-async-tool':'1'}
    try:
        response=client.post(url,json=args,headers=headers)
        assert response.status_code==202
        op=response.json()
        assert client.post(url,json=args,headers=headers).json()['operationId']==op['operationId']
        assert client.get(prefix+'/audio-operations/'+op['operationId']).json()['state']=='running'
        assert client.post(prefix+'/tool-result',json={'name':'generate_audio','arguments':args}).json()['state']=='running'
    finally: release.set()
    assert wait(jobs,project,task,op)['output']['assetId']=='original-audio'
    assert ImageJobs(store,tools.executions,'generate_audio').submit(project,task,args,lambda:pytest.fail('never resubmit'))['output']['assetId']=='original-audio'
    assert len(calls)==1


@pytest.mark.parametrize('terminal_status', ['succeeded', 'failed'])
def test_late_saved_image_updates_terminal_delivery_and_checkpoint_without_re_review(env, terminal_status):
    from app.delivery import DeliveryService
    from app.late_image_results import sync_late_images
    store, project, tools, task, jobs = setup(env)
    delivery = DeliveryService(store, tools.asset_store, tools.canvas_store)
    for item in gift_plan()['deliverables'][:6]:
        tools.execute(project_id=project, task_id=task, name='generate_image', arguments={
            'prompt': item['title'], 'provider': 'local-placeholder', 'deliverable_ids': [item['id']]})
    old = delivery.inspect_task(project, task)
    checks = [{'category': 'content', 'status': 'passed', 'artifactId': a['nodeId'], 'message': '原六张已审查'} for a in old['artifacts']]
    output = {'status': terminal_status, 'artifact_refs': old['artifact_refs'], 'structured_data': {
        'delivery': old, 'deliveryStatus': 'needs_review', 'review': {'passed': True, 'checks': checks}}}
    tools.executions.save(task, {'finalResult': output})
    # The last Provider call was already running when the text task ended.
    args = {'prompt': '迟到的茶罐丝绸套', 'provider': 'local-placeholder', 'deliverable_ids': ['gift-silk']}
    late = tools.execute(project_id=project, task_id=task, name='generate_image', arguments=args)
    op_id, encoded = jobs.identity(project, task, args)
    with store._connect() as db:
        db.execute('INSERT INTO image_operations VALUES (?,?,?,?,?,?,?,?,?)',
            (op_id, project, task, encoded, 'completed', json.dumps(late), 200, jobs.now(), jobs.now()))
        db.execute("UPDATE tasks SET status=?,output_json=?,error_json=? WHERE id=?", (terminal_status, json.dumps(output), json.dumps({'message':'original download failure'}), task))
    env[2].sync_image_results = lambda p, t: sync_late_images(jobs, delivery, p, t)
    with patch('app.providers.local.LocalImageProvider.generate', side_effect=AssertionError('no paid regeneration')):
        current = env[2].get_task(project, task)['output']
        assert env[2].list_tasks(project)[0]['output'] == current
    assert len(current['structured_data']['delivery']['artifacts']) == 7
    assert 'review' not in current['structured_data']
    assert current['structured_data']['deliveryStatus'] == 'passed'
    assert current['status'] == 'succeeded'
    assert env[2].get_task(project, task)['status'] == 'succeeded'
    if terminal_status == 'failed':
        assert current['provenance']['recoveredExecution']['previousError']['message'] == 'original download failure'
    assert not current['structured_data']['deliveryFindings']
    assert tools.executions.load(task)['finalResult']['structured_data'] == current['structured_data']
    assert len(tools.asset_store.list_assets(project)) == 7
