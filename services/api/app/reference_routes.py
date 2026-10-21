from fastapi import APIRouter, File, UploadFile, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict

from .reference_library import ReferenceError
from .reference_network import import_page

router = APIRouter(prefix='/api/references', tags=['references'])


@router.get('')
def list_references(request: Request, q: str = '', industry: str = '', design_type: str = '', offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100)):
    return request.app.state.references.search(q, industry, design_type, offset=offset, limit=limit)


@router.get('/categories')
def categories(request: Request):
    return request.app.state.references.categories()


@router.get('/lessons')
def list_lessons(request: Request, q: str = '', media_kind: str = '', limit: int = Query(24, ge=1, le=100)):
    # Planner-side retrieval remains capped at three; the library view may
    # list more so the user can inspect and remove saved workspace knowledge.
    return {'items': request.app.state.references.search_lessons(q, media_kind, limit)}


class DesignLesson(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mediaKind: str
    tags: list[str] = []
    strategy: str = Field(min_length=1, max_length=500)
    avoid: list[str] = []


@router.post('/lessons', status_code=201)
def create_lesson(request: Request, payload: DesignLesson):
    return request.app.state.references.add_lesson(payload.model_dump())


@router.delete('/lessons/{identity}')
def delete_lesson(request: Request, identity: str):
    request.app.state.references.delete_lesson(identity)
    return {'deleted': True}


class Category(BaseModel):
    dimension: str
    name: str = Field(min_length=1, max_length=50)


@router.post('/categories')
def create_category(request: Request, payload: Category):
    return request.app.state.references.category(payload.dimension, payload.name)


@router.post('/upload', status_code=201)
async def upload(request: Request, files: list[UploadFile] = File(...)):
    if len(files) > 50:
        raise ReferenceError('每批最多上传 50 张图片')
    items, errors = [], []
    for file in files:
        try:
            content = await file.read(request.app.state.references.max_bytes + 1)
            items.append(request.app.state.references.add(content, file.filename or '参考图片'))
        except ReferenceError as error:
            errors.append({'filename': file.filename, 'message': str(error)})
        finally:
            await file.close()
    request.app.state.reference_analyzer.wake.set()
    return {'items': items, 'errors': errors}


class LinkImport(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    limit: int = Field(default=6, ge=1, le=12)


@router.post('/import-url', status_code=201)
def import_url(request: Request, payload: LinkImport):
    result = import_page(request.app.state.references, payload.url, limit=payload.limit)
    request.app.state.reference_analyzer.wake.set()
    return result


class AssetImport(BaseModel):
    projectId: str
    assetId: str


@router.post('/from-asset', status_code=201)
def from_asset(request: Request, payload: AssetImport):
    from pathlib import Path
    asset = request.app.state.assets.get_asset(project_id=payload.projectId, asset_id=payload.assetId)
    if not asset or asset['mime'] not in {'image/png', 'image/jpeg', 'image/webp'}:
        raise ReferenceError('只能收藏存在的 JPEG、PNG、WebP 图片资产')
    item = request.app.state.references.add(Path(asset['absolutePath']).read_bytes(), Path(asset['pathRelative']).name,
        metadata={'title': asset.get('metadata', {}).get('caption') or Path(asset['pathRelative']).stem, 'sourceType': 'project', 'notes': asset.get('metadata', {}).get('prompt', '')})
    request.app.state.reference_analyzer.wake.set()
    return item


@router.post('/selections/{selection_id}/upload')
async def selection_upload(request: Request, selection_id: str, project_id: str, files: list[UploadFile] = File(...)):
    import json
    from .reference_workflow import loads
    store = request.app.state.store
    with store._connect() as db:
        row = db.execute('SELECT * FROM reference_selections WHERE id=? AND project_id=?', (selection_id, project_id)).fetchone()
    if not row or row['status'] != 'pending':
        raise ReferenceError('这批参考已经处理，请在最新对话上传')
    if not 1 <= len(files) <= 6:
        raise ReferenceError('每次可提供 1–6 张自己的参考图')
    result = await upload(request, files)
    if not result['items']:
        raise ReferenceError('没有上传成功的参考图片')
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh = db.execute('SELECT * FROM reference_selections WHERE id=? AND status=?', (selection_id, 'pending')).fetchone()
        if not fresh:
            raise ReferenceError('参考选择已更新，请刷新对话')
        card = loads(fresh['data_json'])
        incoming = list({i['id']: i for i in result['items']}.values())
        previous = [i for i in card['items'] if i['id'] not in {r['id'] for r in incoming}]
        card['items'] = previous[:6-len(incoming)] + incoming
        db.execute('UPDATE reference_selections SET data_json=? WHERE id=?', (json.dumps(card, ensure_ascii=False), selection_id))
        task = db.execute('SELECT input_json,output_json FROM tasks WHERE id=?', (fresh['task_id'],)).fetchone()
        output = loads(task['output_json'])
        output.setdefault('structured_data', {})['referenceSelection'] = card
        inputs = loads(task['input_json'])
        inputs['referenceCandidates'] = list(dict.fromkeys([*inputs.get('referenceCandidates', []), *(i['id'] for i in incoming)]))
        db.execute('UPDATE tasks SET output_json=?,input_json=? WHERE id=?', (json.dumps(output, ensure_ascii=False), json.dumps(inputs, ensure_ascii=False), fresh['task_id']))
    return {'card': card, 'uploadedIds': [i['id'] for i in incoming], 'errors': result['errors']}


@router.get('/{identity}/content')
def content(request: Request, identity: str):
    library = request.app.state.references
    return FileResponse(library.path(identity), media_type=library.get(identity)['mime'], headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/{identity}/thumbnail')
def thumbnail(request: Request, identity: str):
    return FileResponse(request.app.state.references.path(identity, True), media_type='image/jpeg', headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/{identity}')
def detail(request: Request, identity: str):
    return request.app.state.references.get(identity)


class ReferenceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(None, max_length=300)
    industries: list[str] | None = None
    designTypes: list[str] | None = None
    tags: list[str] | None = None
    colors: list[str] | None = None
    description: str | None = Field(None, max_length=4000)
    notes: str | None = Field(None, max_length=4000)
    author: str | None = Field(None, max_length=300)
    rightsStatus: str | None = Field(None, max_length=300)


@router.patch('/{identity}')
def update(request: Request, identity: str, payload: ReferenceUpdate):
    return request.app.state.references.update(identity, payload.model_dump(exclude_none=True))


@router.delete('/{identity}')
def delete(request: Request, identity: str):
    request.app.state.references.delete(identity)
    return {'deleted': True}


@router.post('/{identity}/analyze')
def analyze(request: Request, identity: str):
    request.app.state.reference_analyzer.retry(identity)
    return request.app.state.references.get(identity)


@router.post('/{identity}/save')
def save(request: Request, identity: str):
    return request.app.state.references.save(identity)
