"""Named canvas templates. Assets are copied so deleting a source project is safe."""
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from .models import new_project

router = APIRouter(prefix='/api/workflows', tags=['workflows'])
DATA_KEYS = {'kind', 'title', 'prompt', 'params', 'text', 'html', 'editor', 'colors', 'shots', 'previewSize', 'previewSizingVersion', 'workflowOperation', 'workflowBatchGroup', 'workflowFolder'}
PARAM_KEYS = {'model', 'aspectRatio', 'size', 'quality', 'background', 'output_format', 'duration', 'voice', 'width', 'height'}

def database(store):
    db = store._connect()
    db.execute('CREATE TABLE IF NOT EXISTS workflow_templates (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, document TEXT NOT NULL)')
    return db

@router.get('')
def listing(request: Request):
    with database(request.app.state.store) as db:
        return [dict(id=r['id'], name=r['name'], createdAt=r['created_at'], canvas=json.loads(r['document'])) for r in db.execute('SELECT * FROM workflow_templates ORDER BY created_at DESC')]

@router.post('', status_code=201)
def save_template(payload: dict, request: Request):
    state = request.app.state
    name = str(payload.get('name') or '').strip()
    project_id = str(payload.get('projectId') or '')
    if not name or len(name) > 80: raise HTTPException(422, '名称需为 1–80 个字符')
    if not state.store.get_project(project_id): raise HTTPException(404, '项目不存在')
    board = state.design_tools.canvas_store.load(project_id)
    source_nodes = [n for n in board['nodes'] if not n['data'].get('workflowRunId')]
    extra_edges = []
    # Composer-uploaded references become explicit template inputs, never stale project IDs.
    for node in list(source_nodes):
        reference_id = (node['data'].get('params') or {}).get('source_asset_id')
        if not reference_id: continue
        existing = next((n for n in source_nodes if n['data'].get('assetId') == reference_id),None)
        if not existing:
            existing = {'id':str(uuid4()),'position':{'x':node['position']['x']-800,'y':node['position']['y']},'data':{'kind':'image','title':'共用参考','assetId':reference_id}}
            source_nodes.append(existing)
        if not any(e['source']==existing['id'] and e['target']==node['id'] for e in board['edges']):
            extra_edges.append({'id':str(uuid4()),'source':existing['id'],'target':node['id'],'sourceHandle':'output','targetHandle':'input'})
    if not source_nodes: raise HTTPException(422, '画布没有可保存的节点')
    if any(n['data'].get('generating') for n in source_nodes): raise HTTPException(409, '请等待节点生成结束后保存')
    identity = str(uuid4())
    folder = state.store.workspace_root / 'workflows' / identity
    folder.mkdir(parents=True)
    def save_data(source):
        data = {k:v for k,v in source.items() if k in DATA_KEYS}
        if 'params' in data: data['params'] = {k:v for k,v in data['params'].items() if k in PARAM_KEYS}
        asset_id = source.get('assetId') or (source.get('asset') or {}).get('id')
        if asset_id:
            asset = state.assets.get_asset(project_id=project_id, asset_id=asset_id)
            filename = str(uuid4()) + Path(asset['filename']).suffix if 'filename' in asset else str(uuid4()) + Path(asset['pathRelative']).suffix
            (folder / filename).write_bytes(Path(asset['absolutePath']).read_bytes())
            data['workflowAsset'] = {'file':filename, 'kind':asset['kind'], 'mime':asset['mime']}
        if source.get('workflowFolder'):
            data['folderEntries'] = [save_data(entry) for entry in source.get('folderEntries', [])]
        return data
    nodes = []
    for node in source_nodes:
        data = save_data(node['data'])
        nodes.append({'id':node['id'], 'type':'creative', 'position':node['position'], 'data':data})
    ids = {n['id'] for n in nodes}
    document = {'nodes':nodes, 'edges':[{k:v for k,v in e.items() if k in {'id','source','target','sourceHandle','targetHandle','label','type'}} for e in board['edges']+extra_edges if e['source'] in ids and e['target'] in ids]}
    created = datetime.now(timezone.utc).isoformat()
    with database(state.store) as db:
        db.execute('INSERT INTO workflow_templates VALUES (?,?,?,?)', (identity,name,created,json.dumps(document,ensure_ascii=False)))
    return {'id':identity, 'name':name, 'createdAt':created, 'canvas':document}

@router.post('/{identity}/open')
def open_template(identity: str, request: Request):
    state = request.app.state
    with database(state.store) as db:
        row = db.execute('SELECT * FROM workflow_templates WHERE id=?', (identity,)).fetchone()
    if not row: raise HTTPException(404, '工作流不存在')
    board = json.loads(row['document'])
    slug = 'workflow-' + str(uuid4())
    project = state.store.create_project(new_project(name=row['name'], slug=slug, brief='', budget_minor=None, currency='CNY', root_path=str(state.store.workspace_root / slug)))
    def restore_data(data):
        saved_asset = data.pop('workflowAsset', None)
        if saved_asset:
            path = state.store.workspace_root / 'workflows' / row['id'] / saved_asset['file']
            asset = state.assets.add_bytes(project_id=project['id'], kind=saved_asset['kind'], filename=saved_asset['file'], content=path.read_bytes())
            data.update(asset=asset, assetId=asset['id'])
        data['draft'] = not bool(saved_asset or data.get('text') or data.get('html'))
        for entry in data.get('folderEntries', []):
            restore_data(entry)
    for node in board['nodes']:
        restore_data(node['data'])
    state.design_tools.canvas_store.save(project['id'], board)
    return {'project':project}

@router.get('/{identity}/assets/{node_id}')
def preview_asset(identity: str, node_id: str, request: Request):
    state=request.app.state
    with database(state.store) as db:
        row=db.execute('SELECT * FROM workflow_templates WHERE id=?',(identity,)).fetchone()
    if not row: raise HTTPException(404,'工作流不存在')
    node=next((n for n in json.loads(row['document'])['nodes'] if n['id']==node_id),None)
    asset=(node or {}).get('data',{}).get('workflowAsset')
    if not asset: raise HTTPException(404,'素材不存在')
    folder=(state.store.workspace_root/'workflows'/row['id']).resolve()
    path=(folder/asset['file']).resolve()
    if path.parent!=folder or not path.is_file(): raise HTTPException(404,'素材不存在')
    return FileResponse(path,media_type=asset['mime'],headers={'X-Content-Type-Options':'nosniff'})
