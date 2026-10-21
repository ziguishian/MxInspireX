import json
import os
import shutil
import subprocess
from pathlib import Path
import pytest
from test_delivery_contract import workspace, task
from app.design_tools import DesignToolRegistry
from app.html_generation import HtmlGenerationPreviews


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
@pytest.mark.parametrize('mode', ['complete', 'interrupted'])
def test_sdk_shows_html_progress_before_arguments_finish(api, mode):
    root = Path(__file__).resolve().parents[1]
    payload = {'api':api,'model':'fixture','apiKey':'fixture','baseUrl':'http://fixture.invalid/v1',
        'context':{'projectId':'one','taskId':'current','brief':'制作网页方案','constraints':{'agentCollaboration':False,'executionFlow':'direct'}}}
    result = subprocess.run([shutil.which('node'),'--import',(root/'tests/fixtures/html_progress_transport.mjs').resolve().as_uri(),str(root/'app/openai_agent_worker.mjs')],input=json.dumps(payload),text=True, encoding='utf-8',capture_output=True,timeout=30,env={**os.environ,'HTML_PROGRESS_FIXTURE':mode})
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    public = [event for event in events if event['type']=='event']
    assert any(event.get('phase')=='generation' for event in public), result.stderr+result.stdout[-3000:]
    assert 'PRIVATE_HTML_SENTINEL' not in json.dumps(public)
    assert (result.returncode == 0) == (mode == 'complete'), result.stderr+result.stdout[-3000:]
    if mode == 'complete':
        assert next(i for i,e in enumerate(public) if e.get('phase')=='generation') < next(i for i,e in enumerate(public) if e.get('phase')=='tool' and '调用工具' in e.get('message',''))


def test_placeholder_is_reused_for_completion_and_cleaned_on_interruption(workspace):
    store, project, assets, canvas = workspace
    task(store, project)
    previews = HtmlGenerationPreviews(store, canvas)
    first = previews.begin(project, 'task', 'call')
    assert previews.begin(project, 'task', 'call') == first
    before = canvas.load(project)['nodes'][0]
    assert before['data']['generating'] and not before['data'].get('html')
    result = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets).execute(project_id=project,task_id='task',name='canvas_create_html',arguments={'html':'<h1>完成</h1>'},preview_call_id='call')
    assert result['node']['id'] == first['nodeId']
    assert result['node']['position'] == before['position']
    previews.finish(project, 'task', 'call')
    saved = canvas.load(project)['nodes'][0]
    assert saved['data']['html'] and not saved['data']['generating'] and 'generationPreviewTaskId' not in saved['data']
    previews.begin(project, 'task', 'interrupted')
    previews.finish(project, 'task')
    assert [node['id'] for node in canvas.load(project)['nodes']] == [first['nodeId']]


@pytest.mark.parametrize('content', ['', '<h1>原网页</h1>'])
def test_node_composer_preserves_original_on_cancel(workspace, content):
    store, project, _, canvas = workspace
    node = canvas.create_node(project, kind='html', title='已有网页', data={'html':content})
    task(store, project)
    with store._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps({'canvasParams':{'canvasNodeId':node['id'],'kind':'html'}}),'task'))
    previews = HtmlGenerationPreviews(store, canvas)
    assert previews.begin(project,'task','call')['nodeId'] == node['id']
    assert canvas.load(project)['nodes'][0]['data']['generating']
    previews.finish(project, 'task')
    current = canvas.load(project)['nodes'][0]
    assert current['data']['html'] == content and not current['data']['generating']


def test_previews_reject_other_projects_and_stopped_tasks(workspace):
    store, project, _, canvas = workspace
    task(store, project)
    previews = HtmlGenerationPreviews(store, canvas)
    with pytest.raises(ValueError): previews.begin('wrong-project','task','call')
    with store._connect() as db: db.execute("UPDATE tasks SET status='cancelled' WHERE id='task'")
    with pytest.raises(ValueError): previews.begin(project,'task','call')
    assert canvas.load(project)['nodes'] == []


def test_loading_flags_do_not_invalidate_observed_node_versions(workspace):
    from app.node_context import observe
    store, project, assets, canvas = workspace
    node = canvas.create_node(project, kind='html', title='已有网页', data={'html':'<h1>原页面</h1>'})
    task(store, project, context={'canvasParams':{'kind':'html','canvasNodeId':node['id']}})
    observe(store,project,'task',[node])
    previews = HtmlGenerationPreviews(store,canvas)
    previews.begin(project,'task','edit')
    result = DesignToolRegistry(store,asset_store=assets,canvas_store=canvas).execute(project_id=project,task_id='task',name='canvas_create_html',arguments={'html':'<h1>更新</h1>','canvas_node_id':node['id']},preview_call_id='edit')
    previews.finish(project,'task')
    assert result['node']['id']==node['id'] and len(canvas.load(project)['nodes'])==1


@pytest.mark.parametrize('cancel', [False, True])
def test_task_lifecycle_cleans_preview_when_worker_exits_early(workspace, cancel):
    from app.task_runtime import TaskRuntime
    store, project, _, canvas = workspace
    task(store, project)
    previews = HtmlGenerationPreviews(store, canvas)
    class InterruptedRuntime:
        def run(self, **kwargs):
            previews.begin(project, 'task', 'unclosed-stream')
            assert canvas.load(project)['nodes'][0]['data']['generating']
            if cancel: runtime.cancel(project, 'task')
            raise RuntimeError('网页输出中断')
    runtime = TaskRuntime(store, design_runtime=InterruptedRuntime())
    if cancel:
        assert runtime.run('task', brief='制作网页')['status'] == 'cancelled'
    else:
        with pytest.raises(RuntimeError, match='网页输出中断'): runtime.run('task', brief='制作网页')
    assert canvas.load(project)['nodes'] == []
