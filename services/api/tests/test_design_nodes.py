from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_nodes import design_node_data
from app.design_tools import DesignToolRegistry
from app.main import new_project
from app.storage import ProjectStore
from app.vectorize import vectorize_node, router


def test_local_vector_paths_repeat_and_source_preserved(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='test', slug='test', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path/'test')))['id']
    assets, canvas = AssetStore(store), CanvasStore(store)
    image = Image.new('RGBA', (64,64)); ImageDraw.Draw(image).ellipse((8,8,56,56),fill='orange')
    buf=BytesIO(); image.save(buf,'PNG')
    asset=assets.add_bytes(project_id=project,kind='image',filename='source.png',content=buf.getvalue())
    source=canvas.create_node(project,kind='image',title='source',asset_id=asset['id'])
    node=vectorize_node(canvas,assets,project,source['id'])
    from app.canvas_layout import node_preview_size
    assert node['position']['x'] == source['position']['x'] + node_preview_size(source['data'])['width'] + 80
    assert node['position']['y'] == source['position']['y']
    result=assets.get_asset(project_id=project,asset_id=node['data']['assetId'])
    svg=Path(result['absolutePath']).read_text()
    assert '<path' in svg and '<image' not in svg and 'base64' not in svg
    assert vectorize_node(canvas,assets,project,source['id'])['id']==node['id']
    assert len(canvas.load(project)['nodes'])==2
    assert canvas.load(project)['nodes'][0]['data']['assetId']==asset['id']
    assert Path(assets.get_asset(project_id=project,asset_id=asset['id'])['absolutePath']).read_bytes()==buf.getvalue()
    target = canvas.create_node(project,kind='image',title='workflow result',data={'draft':True,'workflowRunId':'test-run'})
    placed = vectorize_node(canvas,assets,project,source['id'],target['id'])
    assert placed['id'] == target['id'] and placed['data']['assetId'] == result['id']
    assert placed['data']['workflowRunId'] == 'test-run'
    with pytest.raises(ValueError): vectorize_node(canvas,assets,project,source['id'],target['id'])
    with pytest.raises(ValueError): vectorize_node(canvas,assets,project,node['id'])
    app = FastAPI()
    app.include_router(router)
    app.state.store = store
    app.state.assets = assets
    app.state.design_tools = SimpleNamespace(canvas_store=canvas)
    with TestClient(app) as client:
        response = client.post(f'/api/projects/{project}/canvas/{source["id"]}/vectorize')
        assert response.status_code == 200
        assert response.json()['node']['id'] == node['id']
        assert len(response.json()['canvas']['nodes']) == 3
        assert client.post(f'/api/projects/{project}/canvas/missing/vectorize').status_code == 422
        assert client.post('/api/projects/missing/canvas/missing/vectorize').status_code == 404


def test_design_node_validation_and_canonical_text():
    palette=design_node_data('palette',{'colors':['#123456','#FF0000']})
    assert '#123456、#FF0000' in palette['text']
    with pytest.raises(ValueError): design_node_data('palette',{'colors':['not a color']})
    shots=[{'description':'远景','duration':2,'camera':'推近'},{'description':'细节','duration':3,'camera':''}]
    data=design_node_data('storyboard',{'shots':shots})
    assert data['text'].index('远景') < data['text'].index('细节')
    with pytest.raises(ValueError): design_node_data('storyboard',{'shots':[{'duration':float('nan')}]})
    with pytest.raises(ValueError): design_node_data('storyboard',{'shots':[{'duration':1.5}]})


def test_create_edit_and_reload_constraints(tmp_path):
    store=ProjectStore(str(tmp_path))
    project=store.create_project(new_project(name='test',slug='test',brief='',budget_minor=None,currency='CNY',root_path=str(tmp_path/'test')))['id']
    canvas=CanvasStore(store); tools=DesignToolRegistry(store,canvas_store=canvas)
    for editor in ['palette','storyboard']:
        node=tools.canvas_create_node(project_id=project,kind=editor)['node']
        assert node['data']['kind']=='text' and node['data']['editor']==editor
    palette=canvas.load(project)['nodes'][0]
    palette['data'].update(colors=['#00FF00'],text='stale')
    canvas.apply_changes(project, {'upsertNodes':[palette]})
    assert '#00FF00' in canvas.load(project)['nodes'][0]['data']['text']
