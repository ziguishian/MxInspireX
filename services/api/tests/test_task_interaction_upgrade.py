import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import app, new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime
from app.task_updates import TaskUpdates
from app.canvas import CanvasStore
from app.billing import BillingService
from app.model_catalog import ModelCatalog
from app.execution_store import ExecutionStore


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='交互测试', slug='interaction', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'interaction')))
    runtime = TaskRuntime(store)
    runtime._start_worker = lambda *args: False
    task = runtime.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief='制作方案', run_async=True)
    with store._connect() as db: db.execute("UPDATE tasks SET status='running' WHERE id=?", (task['id'],))
    canvas = CanvasStore(store)
    billing = BillingService(store, ModelCatalog(store))
    calls = []
    def execute(**kwargs): calls.append(kwargs); return {'status': 'succeeded'}
    for key, value in {'store': store, 'tasks': runtime, 'billing': billing, 'design_tools': SimpleNamespace(store=store, canvas_store=canvas, execute=execute)}.items(): monkeypatch.setattr(app.state, key, value, raising=False)
    return store, project['id'], task['id'], runtime, canvas, billing, calls, TestClient(app)


def test_updates_are_durable_deduplicated_scoped_and_guard_stale_tools(workspace):
    store, project, task, runtime, _, _, calls, client = workspace
    url = f'/api/projects/{project}/tasks/{task}/updates'
    payload = {'requestId': 'steer-1', 'text': '不要蓝色，改用绿色'}
    first = client.post(url, json=payload)
    assert first.status_code == 200 and first.json()['appliedAt'] is None
    assert client.post(url, json=payload).json() == first.json()
    assert client.post(url, json={**payload, 'text': '红色'}).status_code == 409
    assert client.get(f'/api/projects/other/tasks/{task}/updates').status_code == 404
    tool = f'/api/projects/{project}/agent-tools/canvas_create_text'
    stale = client.post(tool, json={'text':'蓝色'}, headers={'x-aics-task-id':task})
    assert stale.json()['status'] == 'task_update_pending' and not calls
    client.post(url + '/acknowledge', json={'revision': 1})
    assert TaskUpdates(ProjectStore(str(store.workspace_root))).list(project,task)[0]['appliedAt']
    assert runtime.get_task(project,task)['updates'][0]['text'] == payload['text']
    assert client.post(tool, json={'text':'绿色'}, headers={'x-aics-task-id':task,'x-aics-update-revision':'1'}).json()['status'] == 'succeeded'
    assert len(calls) == 1
    # Even a stale task input write cannot erase human steering.
    with store._connect() as db: db.execute("UPDATE tasks SET input_json='{}',status='succeeded' WHERE id=?", (task,))
    assert len(TaskUpdates(store).list(project,task)) == 1
    assert client.post(url, json={'requestId':'late','text':'另一个要求'}).status_code == 409
    assert client.post(url, json=payload).json()['id'] == 'steer-1'


def test_inspection_reads_saved_outputs_and_pending_cost_without_replaying(workspace):
    store, project, task, _, canvas, billing, calls, client = workspace
    node = canvas.create_node(project,kind='text',title='已保存方案',data={'text':'保留原作'})
    executions = ExecutionStore(store)
    fp, _ = executions.claim(task,'canvas_create_text',{'secretPrompt':'DO-NOT-EXPOSE'})
    executions.complete(task,fp,{'status':'succeeded','node':node})
    rejected, _ = executions.claim(task,'generate_image',{'prompt':'INVALID-PRIVATE'})
    executions.complete(task, rejected, {'status':'invalid_parameters', 'submitted':False})
    pending, _ = executions.claim(task,'generate_image',{'prompt':'DO-NOT-EXPOSE'})
    with billing._connect() as db:
        db.execute('INSERT INTO credit_ledger VALUES (?,?,?,?,?)', ('pending',project,task,'now',json.dumps({'id':'pending','provider':'fixture','model':'image','kind':'image','status':'pending','points':None})))
    url=f'/api/projects/{project}/tasks/{task}/inspection'
    before = executions.load(task)
    result=client.get(url)
    assert result.status_code == 200, result.text
    assert result.json()['nodes'][0]['id'] == node['id']
    assert result.json()['billing'][0]['status'] == 'pending'
    receipts = result.json()['receipts']
    assert any(r['submitted'] is False for r in receipts)
    assert any(r['status'] == 'running' and r['submitted'] is None for r in receipts)
    assert '不能证明未收费' in result.json()['billingNote']
    assert 'DO-NOT-EXPOSE' not in result.text
    assert client.get(url).json() == result.json()
    assert not calls and executions.load(task) == before
    assert client.get(f'/api/projects/other/tasks/{task}/inspection').status_code == 404


def test_activity_includes_independent_canvas_work_and_omits_large_traces(workspace):
    store, project, task, _, _, _, _, client=workspace
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded',output_json=?,trace_json=? WHERE id=?", (json.dumps({'structured_data':{'deliveryStatus':'needs_review','review':{'status':'timed_out'}}}),json.dumps([{'message':'PRIVATE_TRACE'}]),task))
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES('canvas',?,'design','design','running',?,'later','later')", (project,json.dumps({'taskSurface':'canvas_node','canvasNodeId':'image-1','userMessage':'画布生成'})))
    response=client.get('/api/tasks/activity')
    records={item['id']:item for item in response.json()}
    assert records['canvas']['canvasNodeId']=='image-1'
    assert 'review' not in records[task]['output']['structured_data']
    assert 'PRIVATE_TRACE' not in response.text


def test_inspection_includes_async_job_and_final_delivery_without_cross_project_nodes(workspace):
    store, project, task, _, canvas, _, calls, client = workspace
    pending = canvas.create_node(project, kind='video', title='视频处理中', data={})
    saved = canvas.create_node(project, kind='video', title='已保存视频', data={})
    canvas.create_node(project, kind='video', title='其他任务', data={})
    executions = ExecutionStore(store)
    fp, _ = executions.claim(task, 'generate_video', {'prompt': 'video'})
    executions.complete(task, fp, {'status': 'processing', 'node': None,
        'job': {'metadata': {'canvasNodeId': pending['id']}}})
    output = {'structured_data': {'delivery': {'artifacts': [{'nodeId': saved['id']}, {'nodeId': 'other-project-node'}]}}}
    with store._connect() as db:
        db.execute('UPDATE tasks SET output_json=? WHERE id=?', (json.dumps(output), task))
    before = executions.load(task)
    result = client.get(f'/api/projects/{project}/tasks/{task}/inspection').json()
    assert {n['id'] for n in result['nodes']} == {pending['id'], saved['id']}
    assert not calls and executions.load(task) == before
