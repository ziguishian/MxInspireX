from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.storage import ProjectStore
from app.assets import AssetStore
from app.canvas import CanvasStore
from app.models import new_project
from app.workflow_routes import router
from app.capability_contracts import CapabilityRegistry
import pytest

def test_template_copies_assets_and_opens_independent_board(tmp_path):
    store=ProjectStore(str(tmp_path)); assets=AssetStore(store); canvas=CanvasStore(store)
    project=store.create_project(new_project(name='source',slug='source',brief='',budget_minor=None,currency='CNY',root_path=str(tmp_path/'source')))
    asset=assets.add_bytes(project_id=project['id'],kind='image',filename='reference.svg',content=b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    source=canvas.create_node(project['id'],kind='image',title='input',asset_id=asset['id'])
    canvas.create_node(project['id'],kind='image',title='output',data={'prompt':'make image','params':{'model':'test','apiKey':'not-saved'}})
    canvas.create_node(project['id'],kind='upload',title='folder',data={'workflowFolder':True,'folderEntries':[{'kind':'image','title':'nested image','assetId':asset['id']},{'kind':'text','title':'note','text':'batch input'}]})
    app=FastAPI(); app.include_router(router); app.state.store=store; app.state.assets=assets; app.state.design_tools=SimpleNamespace(canvas_store=canvas)
    with TestClient(app) as client:
        saved=client.post('/api/workflows',json={'name':'My workflow','projectId':project['id']})
        assert saved.status_code==201
        identity=saved.json()['id']; assert 'not-saved' not in saved.text
        assert len(client.get('/api/workflows').json())==1
        # Template owns a copy of reference bytes.
        from pathlib import Path
        Path(assets.get_asset(project_id=project['id'],asset_id=asset['id'])['absolutePath']).unlink()
        opened=client.post(f'/api/workflows/{identity}/open')
        assert opened.status_code==200
        new_id=opened.json()['project']['id']; assert new_id!=project['id']
        board=canvas.load(new_id); assert len(board['nodes'])==3
        entries=next(n['data']['folderEntries'] for n in board['nodes'] if n['data'].get('workflowFolder'))
        assert entries[0]['assetId']!=asset['id']
        assert entries[1]['text']=='batch input'
        assert board['nodes'][0]['data']['assetId']!=source['data']['assetId']
        assert client.post('/api/workflows',json={'name':'','projectId':project['id']}).status_code==422
        assert client.post('/api/workflows/missing/open').status_code==404

def test_explicit_capability_and_node_registration():
    registry=CapabilityRegistry()
    manifest=dict(id='example.echo',version='1.0.0',name='Echo',description='test',execution='local',inputs=[dict(id='text',label='Text',type='text')],outputs=[dict(id='result',label='Result',type='text')])
    registry.register(manifest,lambda **kwargs:kwargs['inputs'])
    registry.register_node(dict(id='example.echo-node',name='Echo',capability='example.echo',inputBindings={'input':'text'},outputBindings={'output':'result'}))
    assert registry.execute('example.echo',{}, {'text':'hello'}, {})=={'text':'hello'}
    with pytest.raises(ValueError): registry.register(manifest,lambda **kwargs:None)
    with pytest.raises(ValueError): registry.execute('example.echo',{}, {}, {})
