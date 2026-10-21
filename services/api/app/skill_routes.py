"""Local library API; agent activation remains on the task-scoped tool gateway."""
from fastapi import APIRouter, Request, Query
from fastapi.responses import Response
from urllib.parse import quote
from pydantic import BaseModel, Field, ConfigDict

from .skills import SkillCreate, SkillUpdate, SkillError, SkillService
from .skill_packages import GitHubSkillInstaller, export_package

router = APIRouter(prefix='/api/skills', tags=['skills'])


def service(request: Request) -> SkillService:
    return request.app.state.skills


@router.get('')
def list_skills(request: Request, query: str = '', offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50), include_disabled: bool = True):
    return service(request).list(query, offset, limit, include_disabled)


@router.get('/tools')
def skill_tools(request: Request):
    return {'tools': service(request).tool_names()}


class GitHubPackage(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=2048)
    ref: str | None = Field(default=None, max_length=180)
    path: str | None = Field(default=None, max_length=240)


@router.post('/github/inspect')
def inspect_github(request: Request, payload: GitHubPackage):
    return GitHubSkillInstaller(service(request)).inspect(**payload.model_dump())


@router.post('/github/install', status_code=201)
def install_github(request: Request, payload: GitHubPackage):
    key = request.headers.get('idempotency-key')
    return GitHubSkillInstaller(service(request)).install(**payload.model_dump(), operation_id='ui:' + key if key else None)


@router.post('', status_code=201)
def create_skill(request: Request, payload: SkillCreate):
    key = request.headers.get('idempotency-key')
    return service(request).write(payload.model_dump(), operation_id='ui:' + key if key else None)


@router.get('/{skill_id}')
def get_skill(request: Request, skill_id: str, version: int | None = Query(None, ge=1)):
    return service(request).get(skill_id, version)


@router.patch('/{skill_id}')
def update_skill(request: Request, skill_id: str, payload: SkillUpdate):
    key = request.headers.get('idempotency-key')
    return service(request).write(payload.model_dump(exclude_none=True), skill_id=skill_id, operation_id='ui:' + key if key else None)


@router.delete('/{skill_id}')
def delete_skill(request: Request, skill_id: str, expected_version: int = Query(..., ge=1)):
    key = request.headers.get('idempotency-key')
    return service(request).delete(skill_id, expected_version, operation_id='ui:' + key if key else None)


@router.get('/{skill_id}/versions')
def skill_versions(request: Request, skill_id: str):
    return {'versions': service(request).versions(skill_id)}


@router.get('/{skill_id}/export')
def download_package(request: Request, skill_id: str, version: int | None = Query(None, ge=1)):
    skills = service(request)
    detail = skills.get(skill_id, version)
    return Response(export_package(skills, skill_id, version), media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="{detail["name"]}.zip"',
        'X-Content-Type-Options': 'nosniff',
    })


@router.get('/{skill_id}/versions/{version}/resources/{resource_path:path}')
def skill_resource(request: Request, skill_id: str, version: int, resource_path: str):
    content = service(request).resource(skill_id, version, resource_path)
    # Passive downloads only: HTML/SVG and other supplied resources must not
    # execute with the local API's origin or appear to be an Agent tool.
    return Response(content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(resource_path.split('/')[-1]),
        'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox",
    })
