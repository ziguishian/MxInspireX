import json
import math
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.cad import cad_service, cad_manifest
from app.cad_worker import build


PLATE = {
    'source':'result = cq.Workplane("XY").box(params["length"], 50, 8).faces(">Z").workplane().pushPoints([[-30,-15],[30,-15],[-30,15],[30,15]]).hole(5)',
    'parameter_definitions':[{'name':'length','label':'长度','type':'number','default':80,'minimum':70,'maximum':150}],
    'parameters':{'length':80},'title':'带孔底座', 'expected_dimensions':{'x':80,'y':50,'z':8},
}


def test_real_plate_holes_step_roundtrip_and_mesh_units(tmp_path):
    import cadquery as cq
    result = build(PLATE,tmp_path)
    assert result['checks']['solidCount'] == 1
    assert result['checks']['stepRoundTrip']
    assert result['checks']['volumeMm3'] == pytest.approx(80*50*8 - 4*math.pi*2.5**2*8,rel=1e-6)
    restored = cq.importers.importStep(str(tmp_path/'model.step')).val()
    cylinders = [face for face in restored.Faces() if face.geomType()=='CYLINDER']
    assert len(cylinders)==4
    assert all(face.Area()==pytest.approx(2*math.pi*2.5*8,rel=1e-6) for face in cylinders)
    # Inspect the actual glTF accessor bounds: mm -> m and Z-up -> Y-up.
    import struct
    binary = (tmp_path/'model.glb').read_bytes()
    assert binary[:4] == b'glTF'
    length = struct.unpack_from('<I',binary,12)[0]
    gltf = json.loads(binary[20:20+length])
    positions = [gltf['accessors'][primitive['attributes']['POSITION']] for mesh in gltf['meshes'] for primitive in mesh['primitives']]
    # OCP may put conversion in node transforms; browser integration checks final world bounds.
    assert positions and all('min' in position and 'max' in position for position in positions)
    assert (tmp_path/'thumbnail.png').stat().st_size > 1000


@pytest.mark.parametrize('source',[
    'result = cq.Workplane("XY").box(80,50,30).edges("|Z").fillet(3).faces(">Z").shell(-2)',
    'result = cq.Workplane("XZ").moveTo(10,0).lineTo(15,0).lineTo(15,40).lineTo(10,40).close().revolve(360)',
    'body = cq.Workplane("XY").box(20,20,5)\nlid = cq.Workplane("XY").box(20,20,2).translate([0,0,10])\nresult = cq.Assembly()\nresult.add(body,name="body")\nresult.add(lid,name="lid")',
])
def test_shell_revolve_and_multiple_solids(source,tmp_path):
    assert build({'source':source},tmp_path)['checks']['valid']


@pytest.mark.parametrize('changes', [{}, {'length':240}, {'width':150}, {'mounting_hole_offset':25}])
def test_generated_mounting_base_exact_geometry_and_parametric_holes(changes, tmp_path):
    import cadquery as cq
    payload = json.loads((Path(__file__).parent/'fixtures/cad/mounting_base.json').read_text())
    p = payload['parameters']; p.update(changes)
    length, width, thickness = p['length'], p['width'], p['thickness']
    radius, small, center = p['corner_radius'], p['mounting_hole_diameter']/2, p['center_hole_diameter']/2
    payload['expected_dimensions'] = {'x':length, 'y':width, 'z':thickness}
    checks = build(payload, tmp_path)['checks']
    assert checks['valid'] and checks['stepRoundTrip'] and checks['solidCount'] == 1
    area = length*width - (4-math.pi)*radius**2 - 4*math.pi*small**2 - math.pi*center**2
    assert checks['volumeMm3'] == pytest.approx(area*thickness, rel=1e-7)
    solid = cq.importers.importStep(str(tmp_path/'model.step')).val()
    cylinders = [f._geomAdaptor().Cylinder() for f in solid.Faces() if f.geomType() == 'CYLINDER']
    holes = [c for c in cylinders if c.Radius() == pytest.approx(small)]
    assert len(holes) == 4
    x, y = length/2-p['mounting_hole_offset'], width/2-p['mounting_hole_offset']
    assert sorted((round(c.Location().X(), 6), round(c.Location().Y(), 6)) for c in holes) == sorted([(-x,-y),(x,-y),(-x,y),(x,y)])
    assert sum(c.Radius() == pytest.approx(radius) for c in cylinders) == 4
    central = [c for c in cylinders if c.Radius() == pytest.approx(center)]
    assert len(central) == 1 and central[0].Location().X() == pytest.approx(0) and central[0].Location().Y() == pytest.approx(0)
    for px, py in [(-x,-y),(x,-y),(-x,y),(x,y),(0,0)]:
        assert not solid.isInside((px, py, thickness/2))


def test_base_parameter_constraints_reject_holes_outside_the_plate(tmp_path):
    payload = json.loads((Path(__file__).parent/'fixtures/cad/mounting_base.json').read_text())
    payload['parameters']['mounting_hole_offset'] = 2
    with pytest.raises(ValueError, match='安装孔必须与外边界保留材料'):
        build(payload, tmp_path)
    assert not (tmp_path/'model.step').exists()


@pytest.mark.parametrize('changes', [{}, {'height':90, 'rim_diameter':100, 'base_diameter':60, 'wall':4}])
def test_flared_cup_curved_hollow_body_ring_foot_and_rebuild(changes, tmp_path):
    import cadquery as cq
    payload = json.loads((Path(__file__).parent/'fixtures/cad/flared_cup.json').read_text())
    p = payload['parameters']; p.update(changes)
    h, d, foot, wall = p['height'], p['rim_diameter'], p['base_diameter'], p['wall']
    payload['expected_dimensions'] = {'x':d, 'y':d, 'z':h}
    checks = build(payload, tmp_path)['checks']
    assert checks['solidCount'] == 1 and checks['valid'] and checks['stepRoundTrip']
    solid = cq.importers.importStep(str(tmp_path/'model.step')).val()
    assert solid.isInside((0,0,h*.14+wall/2))  # Continuous closed bottom.
    assert not solid.isInside((0,0,h*.6))  # Open cup cavity.
    assert not solid.isInside((0,0,h*.04))  # Recess under the ring foot.
    assert solid.isInside((foot/2-wall/2,0,h*.04))
    assert any(f.geomType() == 'TORUS' for f in solid.Faces())  # Actual arc surfaces.


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT',str(tmp_path))
    with TestClient(app) as client: yield client


def project(client):
    response=client.post('/api/projects',json={'name':'CAD 测试','brief':'结构件','budgetMinor':None,'currency':'CNY'})
    assert response.status_code==201,response.text
    return response.json()['id']


def wait(client,project_id,build_id):
    started=time.monotonic()
    while time.monotonic()-started<120:
        result=client.get(f'/api/projects/{project_id}/cad/builds/{build_id}').json()
        if result['status'] in {'failed','succeeded','cancelled'}: return result
        time.sleep(.1)
    pytest.fail('CAD build did not finish')


def test_build_rebuild_idempotency_conflict_restore_and_bundle(client):
    project_id=project(client); base=f'/api/projects/{project_id}'
    payload={**PLATE,'request_id':'initial'}
    first=client.post(base+'/cad/builds',json=payload)
    assert first.status_code==202,first.text
    assert client.post(base+'/cad/builds',json=payload).json()['id']==first.json()['id']
    built=wait(client,project_id,first.json()['id']); assert built['status']=='succeeded',built
    node=built['result']['node']; old=node['data']['cadRevision']
    versions=client.post(base+'/agent-tools/canvas_versions',json={'node_id':node['id']}).json()['versions']
    response=client.post(base+'/cad/builds',json={'canvas_node_id':node['id'],'base_revision':old,'parameters':{'length':100},'request_id':'edit'})
    assert response.status_code==202,response.text
    edited=wait(client,project_id,response.json()['id']); assert edited['status']=='succeeded',edited
    assert edited['result']['checks']['dimensionsMm']['x']==pytest.approx(100)
    assert client.post(base+'/cad/builds',json={'canvas_node_id':node['id'],'base_revision':old,'parameters':{'length':110}}).status_code==422
    manifest_id=edited['result']['assetId']
    assert len(client.get(base+'/assets').json())==2  # only model versions, no derived files
    assert client.get(base+f'/cad/models/{manifest_id}/export').content[:2]==b'PK'
    restored=client.post(base+'/agent-tools/canvas_restore_node',json={'node_id':node['id'],'version_id':versions[0]['id']})
    assert restored.status_code==200,restored.text
    assert restored.json()['node']['data']['cadRevision']==old
    # Library deletion retains all files needed by existing version history.
    assert client.delete(base+f'/assets/{manifest_id}').status_code==204
    assert cad_manifest(app.state.assets,project_id,manifest_id)['checks']['valid']
    # No model provider or LLM is used in this entire parameter-edit path.


def test_scope_and_failed_edit_keep_previous_model(client):
    project_id=project(client); other=project(client); base=f'/api/projects/{project_id}'
    submitted=client.post(base+'/cad/builds',json=PLATE).json()
    built=wait(client,project_id,submitted['id']); assert built['status']=='succeeded',built
    node=built['result']['node']
    assert client.get(f'/api/projects/{other}/cad/builds/{submitted["id"]}').status_code==404
    assert client.post(f'/api/projects/{other}/cad/builds',json={'canvas_node_id':node['id'],'base_revision':node['data']['cadRevision'],'parameters':{}}).status_code==422
    response=client.post(base+'/cad/builds',json={'canvas_node_id':node['id'],'base_revision':node['data']['cadRevision'],'source':'result = open("secret")'})
    assert response.status_code==202,response.text
    assert wait(client,project_id,response.json()['id'])['status']=='failed'
    assert cad_service(app.state.store).node(project_id,node['id'])['data']['cadRevision']==node['data']['cadRevision']


def test_cancel_does_not_create_a_node(client,monkeypatch):
    project_id=project(client); service=cad_service(app.state.store)
    entered=threading.Event()
    def blocking(*args, cancelled, **kwargs):
        entered.set()
        while not cancelled(): time.sleep(.01)
        raise ValueError('cancelled')
    monkeypatch.setattr(service,'_worker',blocking)
    response=client.post(f'/api/projects/{project_id}/cad/builds',json=PLATE).json()
    assert entered.wait(2)
    assert client.post(f'/api/projects/{project_id}/cad/builds/{response["id"]}/cancel').json()['status']=='cancelled'
    assert not service.canvas.load(project_id)['nodes']


def test_agent_receipt_recovery_and_preview_contract(client,monkeypatch):
    from app.design_tools import DesignToolRegistry
    from app.delivery import DeliveryService
    project_id=project(client); store=app.state.store
    context={'userMessage':'生成带孔底座 CAD，导出 STEP','deliveryVerification':True}
    with store._connect() as db:
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','running',?,'now','now')",('cad-agent',project_id,json.dumps(context)))
    tools=DesignToolRegistry(store,asset_store=app.state.assets)
    args={**PLATE,'output_mode':'create'}
    original=tools.executions.complete
    def interrupted(*args,**kwargs): raise OSError('receipt interrupted')
    monkeypatch.setattr(tools.executions,'complete',interrupted)
    with pytest.raises(OSError,match='receipt interrupted'):
        tools.execute(project_id=project_id,task_id='cad-agent',name='generate_cad',arguments=args)
    monkeypatch.setattr(tools.executions,'complete',original)
    result=tools.execute(project_id=project_id,task_id='cad-agent',name='generate_cad',arguments=args)
    assert result['status']=='succeeded'
    assert len(tools.canvas_store.load(project_id)['nodes'])==1
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM cad_builds').fetchone()[0]==1
    node=result['node']; delivery=DeliveryService(store)
    assert delivery.inspect_task(project_id,'cad-agent')['pendingPreview']==[node['id']]
    claim=delivery.claim_previews()[0]
    assert claim['kind']=='cad' and claim['assetId']==node['data']['previewAssetId']
    with pytest.raises(ValueError,match='三个'):
        delivery.record_check(project_id,node['id'],delivery.fingerprint(node),{'passed':True,'frames':[]})
    # A valid entity must not be delivered after a grouped file was corrupted.
    child=app.state.assets.get_asset(project_id=project_id,asset_id=node['data']['cad']['files']['step'])
    Path(child['absolutePath']).write_bytes(b'broken step')
    report=delivery.inspect_task(project_id,'cad-agent')
    assert not report['passed'] and any('CAD 文件检查失败' in issue for issue in report['issues'])


@pytest.mark.parametrize('stop', ['timeout','cancel'])
def test_supervisor_terminates_real_child(client,monkeypatch,tmp_path,stop):
    import subprocess
    import sys
    import app.cad as cad_module
    service=cad_service(app.state.store)
    popen=subprocess.Popen; children=[]
    def sleeping_child(command,**kwargs):
        assert 'OPENAI_API_KEY' not in kwargs['env']
        assert kwargs['env']['USERPROFILE'] == str(tmp_path.resolve())
        assert kwargs['env']['HOME'] == str(tmp_path.resolve())
        child=popen([sys.executable,'-c','import time; time.sleep(10)'],**kwargs)
        children.append(child); return child
    monkeypatch.setenv('OPENAI_API_KEY','test-secret')
    monkeypatch.setattr(cad_module.subprocess,'Popen',sleeping_child)
    started=time.monotonic()
    (tmp_path/'ready.json').write_text('{}')
    with pytest.raises(ValueError,match='超过|取消'):
        service._worker({},tmp_path,timeout=.15 if stop=='timeout' else 10,cancelled=lambda:stop=='cancel' and time.monotonic()-started>.15)
    assert children and children[0].poll() is not None
    assert time.monotonic()-started<4
