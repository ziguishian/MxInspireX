import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from app.assets import AssetStore
from app.canvas import CanvasStore, CanvasConflict
from app.design_tools import DesignToolRegistry
from app.drawing import Drawing, SaveDrawing, save_drawing
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA


@pytest.fixture
def board(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='画板', slug='drawing', brief='', budget_minor=None,
        currency='CNY', root_path=str(tmp_path/'drawing')))['id']
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
    assets, canvas = AssetStore(store), CanvasStore(store)
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    node = tools.canvas_create_node(project_id=project, kind='drawing', title='布局草图', x=33, y=44)['node']
    return store, project, assets, canvas, tools, node


def drawing(strokes=None):
    return {'width':1024, 'height':768, 'strokes':strokes if strokes is not None else [
        {'tool':'pen', 'color':'#ff0000', 'width':20, 'points':[[100,100],[400,100],[400,300]]}]}


def save(board, node, content=None):
    _, project, assets, canvas, _, _ = board
    return save_drawing(canvas, assets, project, node['id'], SaveDrawing(baseRevision=node['data']['drawing']['revision'], drawing=content or drawing()))


def test_roundtrip_pixels_undo_clear_and_idempotent_save(board):
    _, project, assets, canvas, _, node = board
    assert node['data']['kind'] == 'image' and node['data']['editor'] == 'drawing'
    assert not node['data']['drawing']['hasContent'] and not node['data'].get('assetId')
    saved = save(board, node)
    asset = assets.get_asset(project_id=project, asset_id=saved['data']['assetId'])
    with Image.open(asset['absolutePath']) as image:
        assert image.size == (1024,768)
        assert image.getpixel((200,100)) == (255,0,0)
        assert image.getpixel((700,500)) == (255,255,255)
    assert asset['metadata']['referenceRole'] == 'layout'
    assert saved['position'] == {'x':33.0,'y':44.0}
    assert save(board, node)['data']['assetId'] == asset['id']  # Lost response retry.
    assert len(assets.list_assets(project)) == 1
    erased = drawing(drawing()['strokes'] + [{'tool':'eraser','color':'#000000','width':30,'points':[[180,100],[220,100]]}])
    updated = save(board, saved, erased)
    with Image.open(assets.get_asset(project_id=project, asset_id=updated['data']['assetId'])['absolutePath']) as image:
        assert image.getpixel((200,100)) == (255,255,255)
    cleared = save(board, updated, drawing([]))
    assert cleared['data']['assetId'] is None and not cleared['data']['drawing']['hasContent']
    assert assets.get_asset(project_id=project, asset_id=asset['id'])  # Prior references remain immutable.
    restored = save(board, cleared)
    assert restored['data']['drawing']['strokes'] == drawing()['strokes']
    assert len(canvas.load(project)['nodes']) == 1


def test_stale_writer_foreign_node_and_active_reference_are_rejected(board):
    store, project, assets, canvas, _, node = board
    updated = save(board, node)
    with pytest.raises(CanvasConflict):
        save(board, node, drawing([]))
    other = store.create_project(new_project(name='另一个',slug='other',brief='',budget_minor=None,currency='CNY',root_path=str(store.workspace_root/'other')))['id']
    with pytest.raises(ValueError, match='不属于'):
        save_drawing(canvas, assets, other, node['id'], SaveDrawing(baseRevision=node['data']['drawing']['revision'],drawing=drawing()))
    with store._connect() as db:
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES ('using',?,'design','design','running',?,'now','now')",
                   (project,json.dumps({'referencedAssets':[{'id':updated['data']['assetId']}]})))
    with pytest.raises(CanvasConflict, match='引用'):
        save(board, updated, drawing([]))
    assert len(assets.list_assets(project)) == 1


@pytest.mark.parametrize('bad', [
    {'width':99999}, {'height':0}, {'strokes':[{'tool':'pen','color':'url(x)','width':1,'points':[[0,0]]}]},
    {'strokes':[{'tool':'pen','color':'#000000','width':1,'points':[[float('nan'),0]]}]},
    {'strokes':[{'tool':'pen','color':'#000000','width':1,'points':[[2049,0]]}]},
])
def test_drawing_validates_bounds_and_finite_coordinates(bad):
    with pytest.raises(ValidationError): Drawing.model_validate({**drawing(), **bad})


def test_drawing_reaches_image_provider_as_layout_without_overwriting_board(board):
    _, project, assets, canvas, tools, node = board
    saved = save(board, node)
    source = saved['data']['assetId']
    result_png = BytesIO(); Image.new('RGB',(64,64),'blue').save(result_png,'PNG')
    calls = []
    tools.provider_registry = SimpleNamespace(image=lambda *args,**kw:SimpleNamespace(generate=lambda **kw:calls.append(kw) or result_png.getvalue()))
    result = tools.generate_image(project_id=project, prompt='根据草图布局设计展厅', source_asset_id=source, canvas_node_id=node['id'],
        reference_analysis={'images':[{'asset_id':source, 'mode':'inspiration','visual_prompt':'红线标示左上区域和右侧边界',
            'use':'按草图布局制作正式展厅','avoid':'不保留草稿红色笔触'}], 'synthesis':'保留草图的主体位置，制作真实空间效果'})
    assert calls[0]['source_asset_path'] == assets.get_asset(project_id=project, asset_id=source)['absolutePath']
    assert '结构布局草稿' in calls[0]['prompt'] and '不要把草稿笔触' in calls[0]['prompt']
    assert result['node']['id'] != node['id']
    original = next(n for n in canvas.load(project)['nodes'] if n['id']==node['id'])
    assert original['data']['drawing'] == saved['data']['drawing'] and original['data']['assetId'] == source
    generated = assets.get_asset(project_id=project,asset_id=result['assetId'])
    assert generated['metadata']['referenceSnapshot']['analysis']['images'][0]['mode'] == 'layout'


def test_drawing_http_route_saves_png_and_returns_conflict(board, monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient
    store, project, assets, _, tools, node = board
    for key, value in [('store',store),('assets',assets),('design_tools',tools)]:
        monkeypatch.setattr(app.state, key, value, raising=False)
    client = TestClient(app)
    url = f'/api/projects/{project}/canvas/{node["id"]}/drawing'
    body = {'baseRevision':node['data']['drawing']['revision'],'drawing':drawing()}
    response = client.put(url,json=body)
    assert response.status_code == 200
    assert response.json()['node']['data']['assetId']
    assert client.put(url,json={**body,'drawing':drawing([])}).status_code == 409
    assert client.put(url,json={**body,'drawing':{**drawing(),'width':90000}}).status_code == 422
    assert client.put('/api/projects/missing/canvas/node/drawing',json=body).status_code == 404


def test_explicit_sketch_edit_preserves_edit_scope():
    from app.image_reference_design import prepare_reference_design
    analysis = {'images':[{'asset_id':'sketch','mode':'edit','visual_prompt':'红色矩形','use':'修改指定角落',
                          'preserve':'保留其他红色笔触'}],'synthesis':'只修改指定角落，保留其他笔触'}
    prompt, snapshot, ids = prepare_reference_design('只改角落', ['sketch'], analysis, {},
        required=True, masked_edit=True, layout_source_ids=['sketch'])
    assert ids == ['sketch'] and snapshot['analysis']['images'][0]['mode'] == 'edit'
    assert '不要把草稿笔触' not in prompt
