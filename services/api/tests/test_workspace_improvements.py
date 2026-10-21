import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_contracts import AgentResult
from app.assets import AssetStore
from app.canvas import CanvasConflict, CanvasStore
from app.content_facts import check_content_facts, fact_sources, numbers
from app.delivery import DeliveryService
from app.design_runtime import DesignRuntimeError
from app.main import app
from app.models import new_project
from app.project_overview import ProjectPreviews, project_overviews, library_assets
from app.storage import ProjectStore
from app.task_policy import is_simple_conversation, execution_flow
from app.task_runtime import TaskRuntime


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    runtime = TaskRuntime(store, design_runtime=SimpleNamespace(run=lambda **kwargs: AgentResult(status='succeeded', structured_data={'answer': '已完成'})))
    project = store.create_project(new_project(name='手动项目', slug='one', brief='你好', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'one')))
    return store, runtime, project


def task(store, project, status='succeeded', user='制作品牌图标', extra=None, answer='完成了品牌图标设计', clarification=None):
    tid = str(uuid4())
    with store._connect() as db:
        db.execute("""INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,output_json,created_at,updated_at)
            VALUES (?,?,'design','design',?,?,?,'2026-09-12T01:00:00Z','2026-09-12T01:02:00Z')""",
            (tid, project['id'], status, json.dumps({'userMessage': user, **(extra or {})}), json.dumps({'structured_data': {'answer': answer, 'clarification': clarification}})))
    return tid


def wait(check):
    end = time.monotonic() + 3
    while not check():
        assert time.monotonic() < end
        time.sleep(.01)


def test_shutdown_pauses_then_resumes_the_same_task(workspace):
    store, runtime, project = workspace
    entered = threading.Event()
    def slow(**kwargs):
        entered.set()
        wait(kwargs['should_cancel'])
        raise DesignRuntimeError('任务已停止', kind='interrupted')
    runtime.design_runtime = SimpleNamespace(run=slow)
    initial = runtime.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief='你好', run_async=True)
    assert entered.wait(1)
    runtime.prepare_shutdown()
    wait(lambda: runtime.get_task(project['id'], initial['id'])['status'] == 'queued')
    assert not runtime.get_task(project['id'], initial['id'])['error']
    resumed = TaskRuntime(store, design_runtime=SimpleNamespace(run=lambda **kwargs: AgentResult(status='succeeded', structured_data={'answer': '继续完成'})))
    assert resumed.recover_pending() == 1
    wait(lambda: resumed.get_task(project['id'], initial['id'])['status'] == 'succeeded')
    assert len(resumed.list_tasks(project['id'])) == 1


def test_transient_retry_reuses_id_but_quota_is_not_retryable(workspace, monkeypatch):
    store, runtime, project = workspace
    tid = task(store, project, status='failed')
    with store._connect() as db:
        db.execute('UPDATE tasks SET error_json=? WHERE id=?', (json.dumps({'message': '504 gateway timeout'}), tid))
    starts = []
    monkeypatch.setattr(runtime, '_start_worker', lambda task_id, brief: starts.append(task_id))
    with pytest.raises(ValueError):
        runtime.retry(project['id'], tid)
    with store._connect() as db:
        db.execute('UPDATE tasks SET error_json=? WHERE id=?', (json.dumps({
            'message': '504 gateway timeout', 'submitted': False, 'billingCertainty': 'not_submitted',
        }), tid))
    assert runtime.retry(project['id'], tid)['status'] == 'queued'
    runtime.retry(project['id'], tid)
    assert starts == [tid]
    assert not DesignRuntimeError('429 insufficient_quota monthly spending limit').retryable
    assert not DesignRuntimeError('403 you have reached the monthly spending limit').retryable
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='failed',error_json=? WHERE id=?", (json.dumps({'message': '403 monthly spending limit'}), tid))
    with pytest.raises(ValueError): runtime.retry(project['id'], tid)


@pytest.mark.parametrize('prompt', ['你好呀', '你能做什么？', '你可以做什么？', '什么是品牌识别？', 'Logo 和 IP 有什么区别？', '请总结这段文字：我们的品牌面向年轻家庭，提供圆润温暖的宠物用品。', '把这段文字润色：我们会在明天下午发货。'])
def test_lightweight_text_avoids_extra_agent_stages(prompt):
    assert is_simple_conversation(prompt)
    assert not is_simple_conversation(prompt, {'referencedNodes': [{'id': 'one'}]})


@pytest.mark.parametrize('prompt', ['帮我生成一张宠物海报', '总结刚才的所有设计要求', '最新的市场趋势是什么', '请读取 https://example.com 并总结', '为这张图生成视频', '明天上午自动生成一张图', '请解释一下药物的用量'])
def test_tool_history_and_high_stakes_requests_keep_regular_routing(prompt):
    assert not is_simple_conversation(prompt)


def test_project_summary_uses_latest_turn_without_exposing_history(workspace):
    store, runtime, project = workspace
    task(store, project)
    overview = project_overviews(store, store.list_projects())[0]
    assert overview['status'] == 'draft' and overview['latestTaskStatus'] == 'succeeded'
    assert overview['summary'] == '完成了品牌图标设计'
    assert 'output_json' not in overview and 'trace' not in overview
    task(store, project, clarification={'questions': [{'id': 'one', 'question': '配色？'}]})
    assert project_overviews(store, store.list_projects())[0]['latestTaskStatus'] == 'awaiting_input'
    task(store, project, status='failed', user='最新修改需求')
    assert project_overviews(store, store.list_projects())[0]['summary'] == '最新修改需求'


def test_previews_are_small_cached_and_exclude_far_away_empty_nodes(workspace):
    store, runtime, project = workspace
    canvas = CanvasStore(store)
    canvas.create_node(project['id'], kind='image', title='空节点', position={'x': 99999, 'y': 0})
    content = canvas.create_node(project['id'], kind='html', title='当前成果', data={'html': '<html>' + 'x' * 200000 + '</html>'})
    previews = ProjectPreviews(store, canvas)
    first = previews.get(project['id'])
    assert len(first['nodes']) == 1 and first['nodes'][0]['id'] == content['id']
    assert len(json.dumps(first)) < 2000 and 'html' not in first['nodes'][0]['data']
    assert previews.get(project['id']) is first
    canvas.update_node(project['id'], content['id'], {'data': {'title': '已修改'}})
    assert previews.get(project['id'])['nodes'][0]['data']['title'] == '已修改'
    assets = AssetStore(store)
    assets.add_bytes(project_id=project['id'], kind='text', filename='example.txt', content=b'content', metadata={'prompt': 'PRIVATE_PROMPT'})
    listed = library_assets(store)
    assert len(listed) == 1 and 'PRIVATE_PROMPT' not in json.dumps(listed)


def test_project_preview_uses_the_first_visual_asset_including_3d(workspace):
    store, _, project = workspace
    canvas = CanvasStore(store)
    canvas.create_node(project['id'], kind='text', title='说明', data={'text': '先写一个说明'})
    model = canvas.create_node(project['id'], kind='3d', title='首个模型', asset_id='model-one', data={
        'asset': {'id': 'model-one', 'projectId': project['id'], 'pathRelative': 'assets/model.glb'},
    })
    canvas.create_node(project['id'], kind='image', title='后续图片', asset_id='image-two', data={
        'asset': {'id': 'image-two', 'projectId': project['id'], 'mime': 'image/png', 'pathRelative': 'assets/image.png'},
    })
    preview = ProjectPreviews(store, canvas).get(project['id'])
    assert [node['id'] for node in preview['nodes']] == [model['id']]
    assert preview['nodes'][0]['data']['kind'] == '3d'


def test_project_previews_preserve_media_types_sizes_and_html_references(workspace):
    store, _, project = workspace
    canvas = CanvasStore(store)
    video = canvas.create_node(project['id'], kind='upload', title='视频', data={
        'asset': {'id': 'video-one', 'projectId': project['id'], 'mime': 'video/mp4', 'pathRelative': '视频.mp4', 'metadata': {'prompt': 'PRIVATE_PROMPT'}},
        'previewSize': {'width': 480, 'height': 270},
    })
    page = canvas.create_node(project['id'], kind='html', title='网页', data={
        'html': '<h1>PAGE_SOURCE</h1>', 'htmlPreviewSize': {'width': 1200, 'height': 800},
        'htmlAssets': {'image-one': 'data:image/png;base64,YQ=='},
    })
    image = canvas.create_node(project['id'], kind='image', title='竖图', asset_id='image-one', data={
        'asset': {'mime': 'image/png', 'metadata': {'imageOutput': {'width': 600, 'height': 900}}},
    })
    canvas.apply_changes(project['id'], {'upsertEdges': [{'id': 'link', 'source': video['id'], 'target': page['id']}]})
    service = ProjectPreviews(store, canvas)
    preview = service.get(project['id'])
    data = {node['id']: node['data'] for node in preview['nodes']}
    # Cards use the first visual output in canvas order instead of a full
    # board contact sheet. The first media node remains the stable cover.
    assert list(data) == [video['id']]
    assert data[video['id']]['assetId'] == 'video-one'
    assert data[video['id']]['asset']['mime'] == 'video/mp4'
    assert data[video['id']]['previewSize'] == {'width': 480, 'height': 270}
    assert preview['edges'] == []
    assert all(value not in json.dumps(preview) for value in ('PAGE_SOURCE', 'PRIVATE_PROMPT', 'base64'))
    assert service.html_document(project['id'], page['id'])['html'] == '<h1>PAGE_SOURCE</h1>'
    canvas.update_node(project['id'], page['id'], {'data': {'html': '<h1>UPDATED</h1>'}})
    assert service.get(project['id'])['revision'] != preview['revision']
    assert service.html_document(project['id'], page['id'])['html'] == '<h1>UPDATED</h1>'


def test_unrelated_canvas_edits_work_during_generation_and_conflicts_preserve_data(workspace):
    store, runtime, project = workspace
    canvas = CanvasStore(store)
    one = canvas.create_node(project['id'], kind='text', title='运行中的节点', data={'text': '原文'})
    two = canvas.create_node(project['id'], kind='text', title='无关节点', data={'text': '旧内容'})
    tid = task(store, project, status='running', extra={'referencedNodes': [{'id': one['id']}]})
    with pytest.raises(CanvasConflict, match='任务使用'):
        canvas.apply_changes(project['id'], {'removeNodeIds': [one['id']]})
    result = canvas.apply_changes(project['id'], {'upsertNodes': [{'id': two['id'], 'position': {'x': 900, 'y': 10}}]})
    assert one['id'] in result['lockedNodeIds']
    before = next(node for node in result['nodes'] if node['id'] == two['id'])
    canvas.update_node(project['id'], two['id'], {'data': {'text': 'Agent 的最新内容'}})
    with pytest.raises(CanvasConflict, match='已被更新'):
        canvas.apply_changes(project['id'], {'upsertNodes': [{'id': two['id'], 'data': {'text': '用户的旧快照'}}], 'expectedNodes': {two['id']: {'data': before['data']}}})
    assert canvas.load(project['id'])['nodes'][1]['data']['text'] == 'Agent 的最新内容'
    # Position-only updates do not replace newly generated content.
    canvas.apply_changes(project['id'], {'upsertNodes': [{'id': two['id'], 'position': {'x': 20, 'y': 30}}], 'expectedNodes': {two['id']: {'position': before['position']}}})
    assert canvas.load(project['id'])['nodes'][1]['data']['text'] == 'Agent 的最新内容'


def test_factual_checks_separate_visible_placeholders_from_supported_specs():
    sources = [{'source': '用户消息 one', 'values': numbers('船长32.8米，最大航速31节')}]
    assert check_content_facts('<p>32.8 m / 31 kn</p>', 'html', sources)['status'] == 'source_matched'
    assert check_content_facts('<p>7.2 m / 31 kn</p>', 'html', sources)['status'] == 'needs_confirmation'
    assert check_content_facts('<p>概念示意，参数待确认</p><p>7.2 m</p>', 'html', sources)['status'] == 'illustrative'
    assert check_content_facts('<script>参数为概念示意</script><p>7.2 m</p>', 'html', sources)['status'] == 'needs_confirmation'
    assert check_content_facts('<span hidden>参数为概念示意</span><p>7.2 m</p>', 'html', sources)['status'] == 'needs_confirmation'
    assert check_content_facts('<style>.x{width:32.8m}</style><h1>欢迎</h1>', 'html', sources)['status'] == 'not_applicable'


def test_factual_evidence_excludes_other_projects_future_turns_and_assistant_guesses(workspace):
    store, runtime, project = workspace
    task(store, project, user='船长32.8米', answer='最高航速31节')
    current = task(store, project, user='做一个网站')
    task(store, project, user='船宽7.2米')
    other = {**project, 'id': 'foreign'}
    task(store, other, user='航速40节')
    evidence = fact_sources(store, project['id'], current)
    assert check_content_facts('船长32.8米', 'text', evidence)['status'] == 'source_matched'
    for value in ['31节', '7.2米', '40节']:
        assert check_content_facts(value, 'text', evidence)['status'] == 'needs_confirmation'


def test_delivery_rejects_unsubstantiated_specs_until_the_artifact_labels_them(workspace):
    store, runtime, project = workspace
    assets, canvas = AssetStore(store), CanvasStore(store)
    tid = task(store, project, user='为概念游艇制作网站')
    node = canvas.create_node(project['id'], kind='html', title='官网', task_id=tid, data={'html': '<p>船长32.8米，航速31节</p>'})
    service = DeliveryService(store, assets, canvas)
    check = service.inspect(project['id'], tid)
    assert not check['passed'] and '未核实' in check['issues'][0]
    canvas.update_node(project['id'], node['id'], {'data': {'html': '<p>概念示意，参数待确认</p><p>船长32.8米，航速31节</p>'}})
    assert service.inspect(project['id'], tid)['passed']


def test_api_overviews_and_preview_handle_malformed_old_task_output(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': '测试项目'}).json()
        tid = task(app.state.store, project)
        with app.state.store._connect() as db: db.execute("UPDATE tasks SET output_json='not-json' WHERE id=?", (tid,))
        response = client.get('/api/projects')
        assert response.status_code == 200 and response.json()[0]['latestTaskStatus'] == 'succeeded'
        assert client.get(f"/api/projects/{project['id']}/preview").status_code == 200
        assert client.get('/api/library/assets').json() == []
        assert client.get('/api/projects/missing/preview').status_code == 404


def test_direct_canvas_tools_obey_running_task_locks(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': '编辑锁验收'}).json()
        canvas = app.state.design_tools.canvas_store
        one = canvas.create_node(project['id'], kind='text', title='任务输入', data={'text': '原文'})
        two = canvas.create_node(project['id'], kind='text', title='独立节点', data={'text': '可编辑'})
        task(app.state.store, project, status='running', extra={'referencedNodes': [{'id': one['id']}]})
        route = f"/api/projects/{project['id']}/agent-tools"
        assert client.post(route + '/canvas_update_node', json={'node_id': one['id'], 'patch': {'data': {'text': '冲突'}}}).status_code == 409
        assert client.post(route + '/canvas_link_nodes', json={'source_node_id': one['id'], 'target_node_id': two['id']}).status_code == 409
        assert client.post(route + '/canvas_update_node', json={'node_id': two['id'], 'patch': {'data': {'text': '已修改'}}}).status_code == 200
        assert canvas.load(project['id'])['nodes'][0]['data']['text'] == '原文'
