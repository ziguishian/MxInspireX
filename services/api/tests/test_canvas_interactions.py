import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry, DesignToolError
from app.main import new_project
from app.providers.http import OpenAICompatibleSpeechProvider, ProviderError
from app.storage import ProjectStore


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='画布测试', slug='canvas-test', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'canvas-test')))
    from app.task_runtime import TaskRuntime
    from test_conversation_context import add_turn
    TaskRuntime(store)
    add_turn(store,'task','',project=project['id'],status='running')
    return project['id'], store, CanvasStore(store), AssetStore(store)


def test_generation_placeholder_is_visible_and_replaced_without_losing_edges(workspace):
    project_id, store, canvas, assets = workspace
    source = canvas.create_node(project_id, kind='text', title='参考')
    target = canvas.create_node(project_id, kind='image', title='待生成', data={'previewSize': {'width': 650, 'height': 400}})
    edge = canvas.link_nodes(project_id, source_node_id=source['id'], target_node_id=target['id'])
    seen = {}

    def generate(**kwargs):
        pending = next(n for n in canvas.load(project_id)['nodes'] if n['id'] == target['id'])
        assert pending['data']['generating'] is True
        seen.update(kwargs)
        return b'fake-test-image'

    registry = SimpleNamespace(image=lambda *args, **kwargs: SimpleNamespace(generate=generate))
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets, provider_registry=registry)
    # A blank node submitted through its composer is an explicit create target.
    with patch.object(tools, '_task_input', return_value={'canvasParams': {'canvasNodeId': target['id'], 'kind': 'image'}}):
        result = tools.execute(project_id=project_id, task_id='task', name='generate_image', arguments={'prompt':'海报', 'model':'gpt-image-2.5-sunburst', 'canvas_node_id':target['id'], 'params':{'aspectRatio':'9:16', 'quality':'high', 'style':'插画'}})
    assert result['node']['id'] == target['id']
    assert result['node']['data']['generating'] is False
    assert result['node']['data']['assetId'] == result['assetId']
    assert result['node']['data']['previewSize'] == {'width': 650, 'height': 400}
    assert seen['size'] == '1152x2048' and seen['quality'] == 'high'
    assert '插画' in seen['prompt']
    board = canvas.load(project_id)
    assert len(board['nodes']) == 2 and board['edges'][0]['id'] == edge['id']


def test_direct_image_generation_keeps_existing_image_and_creates_result_node(workspace):
    project_id, store, canvas, assets = workspace
    source=assets.add_bytes(project_id=project_id,kind='image',filename='original.png',content=b'original-image')
    original=canvas.ensure_asset_node(project_id,source)
    captured=[]
    provider=SimpleNamespace(image=lambda *args,**kwargs:SimpleNamespace(generate=lambda **kwargs:captured.append(kwargs) or b'new-image'))
    tools=DesignToolRegistry(store,canvas_store=canvas,asset_store=assets,provider_registry=provider)
    result=tools.generate_image(project_id=project_id,prompt='调整画面',canvas_node_id=original['id'])
    board={node['id']:node for node in canvas.load(project_id)['nodes']}
    assert result['node']['id']!=original['id'] and len(board)==2
    assert board[original['id']]['data']['assetId']==source['id']
    assert captured[0]['source_asset_path']==assets.get_asset(project_id=project_id,asset_id=source['id'])['absolutePath']


def test_validation_failure_before_dispatch_does_not_create_a_failed_node(workspace):
    project_id, store, canvas, assets = workspace
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets)
    with pytest.raises(DesignToolError):
        tools.execute(project_id=project_id, task_id='task', name='generate_image', arguments={'prompt':'test'})
    assert canvas.load(project_id)['nodes']==[]


def test_video_style_and_camera_reach_provider_prompt(workspace):
    project_id, store, canvas, assets = workspace
    captured = {}
    def generate(**kwargs):
        captured.update(kwargs)
        assert canvas.load(project_id)['nodes'][0]['data']['generating']
        return {'content': b'video-fixture', 'extension': 'mp4'}
    registry = SimpleNamespace(video=lambda *args, **kwargs: SimpleNamespace(generate=generate))
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets, provider_registry=registry)
    result = tools.execute(project_id=project_id, task_id='video-settings', name='generate_video', arguments={
        'prompt': '产品展示', 'model': 'test-video',
        'params': {'style': '电影感', 'camera': '环绕', 'duration': 8, 'resolution': '1080p', 'aspectRatio': '9:16'},
    })
    assert '视觉风格：电影感' in captured['prompt'] and '镜头运动：环绕' in captured['prompt']
    assert 'style' not in captured and 'camera' not in captured
    assert captured['duration'] == 8 and captured['resolution'] == '1080p'
    assert not result['node']['data']['generating']


def test_delete_restore_and_move_preserve_other_agent_outputs(workspace):
    project_id, store, canvas, assets = workspace
    asset = assets.add_bytes(project_id=project_id, kind='image', filename='example.png', content=b'test')
    first = canvas.ensure_asset_node(project_id, asset)
    second = canvas.create_node(project_id, kind='text', title='另外一个输出', data={'text':'旧内容'})
    edge = canvas.link_nodes(project_id, source_node_id=first['id'], target_node_id=second['id'])
    doc = canvas.apply_changes(project_id, {'removeNodeIds':[first['id']]})
    assert len(doc['nodes']) == 1 and not doc['edges']
    assert asset['id'] in doc['hiddenAssetIds']
    canvas.update_node(project_id, second['id'], {'data':{'text':'Agent 新结果'}})
    doc = canvas.apply_changes(project_id, {'upsertNodes':[first, {'id':second['id'], 'position':{'x':100, 'y':50}}], 'upsertEdges':[edge]})
    assert len(doc['nodes']) == 2 and len(doc['edges']) == 1
    assert not doc['hiddenAssetIds']
    assert next(n for n in doc['nodes'] if n['id'] == second['id'])['data']['text'] == 'Agent 新结果'


def test_audio_adapter_sends_voice_speed_and_saves_playable_asset(workspace):
    project_id, store, canvas, assets = workspace
    target = canvas.create_node(project_id, kind='audio', title='音频节点', data={'draft': True})
    captured = {}
    class Response:
        headers = {'Content-Type':'audio/mpeg'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'ID3test-audio'
    def respond(request, **kwargs):
        captured['url'] = request.full_url
        captured['payload'] = json.loads(request.data)
        assert request.get_header('Authorization') == 'Bearer fixture-secret'
        return Response()
    registry = SimpleNamespace(catalog=None, credentials=SimpleNamespace(get=lambda key:'fixture-secret'), _meter=lambda kind, adapter:adapter)
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets, provider_registry=registry)
    with patch('app.providers.http.urllib.request.urlopen', respond):
        result = tools.execute(project_id=project_id, task_id='audio-test', name='generate_audio', arguments={'prompt':'你好', 'model':'tts-model', 'canvas_node_id':target['id'], 'params':{'baseUrl':'https://fixture.invalid/v1', 'voice':'alloy', 'speed':1.25}})
    assert captured['url'] == 'https://fixture.invalid/v1/audio/speech'
    assert captured['payload']['voice'] == 'alloy' and captured['payload']['speed'] == 1.25
    assert result['node']['data']['kind'] == 'audio'
    assert result['node']['data']['generating'] is False
    assert result['asset']['mime'] == 'audio/mpeg'
    assert result['node']['id'] == target['id']
    assert len(canvas.load(project_id)['nodes']) == 1


@pytest.mark.parametrize('kind', ['text', 'video'])
def test_node_composer_result_replaces_the_selected_node(workspace, kind):
    project_id, store, canvas, assets = workspace
    target = canvas.create_node(project_id, kind=kind, title='待生成', data={'draft': True, 'generating': True})
    registry = SimpleNamespace(video=lambda *args, **kwargs: SimpleNamespace(generate=lambda **options: {'content': b'video-fixture', 'extension': 'mp4'}))
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets, provider_registry=registry)
    name, arguments = ('canvas_create_text', {'title': '文案', 'text': '生成的文案'}) if kind == 'text' else ('generate_video', {'prompt': '产品视频', 'model': 'test-video'})
    result = tools.execute(project_id=project_id, task_id='composer-test', name=name, arguments={**arguments, 'canvas_node_id': target['id']})
    assert result['node']['id'] == target['id']
    assert result['node']['data']['generating'] is False
    assert result['node']['data']['draft'] is False
    assert len(canvas.load(project_id)['nodes']) == 1
    if kind == 'text':
        assert result['node']['data']['text'] == '生成的文案'
    else:
        assert result['node']['data']['asset']['mime'] == 'video/mp4'


def test_new_outputs_are_compact_and_media_rebinding_does_not_scatter_them(workspace):
    project_id, store, canvas, assets = workspace
    first = canvas.create_node(project_id, kind='image', title='前一张', position={'x':1200, 'y':800})
    second = canvas.create_node(project_id, kind='image', title='后一张')
    assert second['position'] == {'x':1968.0,'y':800.0}
    third = canvas.create_node(project_id, kind='image', title='第三张')
    fourth = canvas.create_node(project_id, kind='image', title='第四张')
    assert third['position']['x'] == 2736
    assert fourth['position']['x'] == 1200 and 800 < fourth['position']['y'] < 1300
    asset = assets.add_bytes(project_id=project_id, kind='image', filename='generated.png', content=b'image')
    bound = canvas.ensure_asset_node(project_id, asset, target_node_id=second['id'])
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets)
    rebound = tools.canvas_create_media(project_id=project_id, task_id='task', asset_id=asset['id'], x=9000,y=9000)
    assert rebound['node']['position'] == bound['position']


def test_browser_can_preflight_canvas_edits():
    from fastapi.testclient import TestClient
    from app.main import app
    response = TestClient(app).options('/api/projects/test/canvas', headers={'Origin':'http://127.0.0.1:5173', 'Access-Control-Request-Method':'PATCH', 'Access-Control-Request-Headers':'content-type'})
    assert response.status_code == 200
    assert 'PATCH' in response.headers['access-control-allow-methods']


@pytest.mark.parametrize('kind', ['image', 'video', 'audio', 'text', 'html', 'upload', '3d', 'document'])
def test_custom_frame_is_persisted_and_used_to_place_new_outputs(workspace, kind):
    from app.canvas_layout import node_width, node_height
    project_id, store, canvas, assets = workspace
    original = canvas.create_node(project_id, kind=kind, title='调整节点', position={'x': 100, 'y': 200})
    enlarged = {**original, 'data': {**original['data'], 'previewSize': {'width': 800, 'height': 600}}}
    canvas.apply_changes(project_id, {'upsertNodes': [enlarged], 'expectedNodes': {original['id']: original}})
    restored = CanvasStore(store).load(project_id)['nodes'][0]
    assert restored['data']['previewSize'] == {'width': 800, 'height': 600}
    # Media follows its actual/requested ratio (default 16:9), so a legacy
    # saved height cannot stretch it. Other kinds keep independent dimensions.
    assert node_width(restored) == 800 and node_height(restored) == (490 if kind in {'image','video'} else 640)
    # The wider row budget fits the text beside the custom 800 px frame.
    assert canvas.create_node(project_id, kind='text', title='新内容')['position'] == {'x': 948, 'y': 200}
    # Undo restores the missing field as well as explicit dimensions.
    canvas.apply_changes(project_id, {'upsertNodes': [original], 'expectedNodes': {original['id']: enlarged}})
    assert 'previewSize' not in canvas.load(project_id)['nodes'][0]['data']


def test_frame_size_limits_and_html_compatibility():
    from app.canvas_layout import node_preview_size
    assert node_preview_size({'kind': 'image', 'previewSize': {'width': -1, 'height': 9000}}) == {'width': 213, 'height': 120}
    assert node_preview_size({'kind': 'audio', 'previewSize': {'width': float('inf'), 'height': float('nan')}}) == {'width': 220, 'height': 138}
    legacy = {'kind': 'html', 'htmlPreviewSize': {'width': 1200, 'height': 800}}
    assert node_preview_size(legacy) == {'width': 1200, 'height': 800}
    assert node_preview_size({**legacy, 'previewSize': {'width': 500, 'height': 400}}) == {'width': 500, 'height': 400}
