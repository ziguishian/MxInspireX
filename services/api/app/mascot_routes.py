from uuid import UUID
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .model_config import ProviderPreference

router = APIRouter(prefix='/api/mascot', tags=['appearance'])


class MascotGenerate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    requestId: UUID
    prompt: str = Field(min_length=4, max_length=2000)
    provider: ProviderPreference
    model: str = Field(default='', max_length=200)


class MascotApply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    generationId: UUID | None = None
    presetId: Literal['robot', 'cream-cat', 'cloud', 'sprout'] | None = None


@router.get('')
def settings(request: Request):
    return request.app.state.mascot.settings()


@router.post('/generations', status_code=202)
def generate(payload: MascotGenerate, request: Request, tasks: BackgroundTasks):
    if payload.provider.key not in {'openrouter', 'openai-compatible', 'openai-image', 'evolink'}:
        raise HTTPException(422, '请先在模型与连接中配置远程图像服务。')
    data = payload.model_dump(mode='json', exclude={'requestId'})
    try:
        identity, created = request.app.state.mascot.create(str(payload.requestId), data)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if created:
        tasks.add_task(request.app.state.mascot.generate, identity)
    return request.app.state.mascot.get(identity)


@router.get('/generations/{identity}')
def generation(identity: UUID, request: Request):
    try:
        return request.app.state.mascot.get(str(identity))
    except KeyError as error:
        raise HTTPException(404, '吉祥物图集不存在') from error


@router.get('/generations/{identity}/image')
def image(identity: UUID, request: Request):
    service = request.app.state.mascot
    item = generation(identity, request)
    path = service.image_path(identity)
    if item['status'] != 'succeeded' or not path.is_file():
        raise HTTPException(404, '图集尚未生成')
    return FileResponse(path, media_type='image/png', filename=f'mascot-{identity}.png', content_disposition_type='inline')


@router.put('')
def apply(payload: MascotApply, request: Request):
    try:
        return request.app.state.mascot.activate(str(payload.generationId) if payload.generationId else None, payload.presetId)
    except (KeyError, ValueError) as error:
        raise HTTPException(422, '请选择一个内置预设或已成功生成的图集。') from error
