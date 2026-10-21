from fastapi import APIRouter, HTTPException, Request
from .cad import cad_service, cad_manifest
from .cad_program import CadBuildRequest
from fastapi.responses import Response
from pathlib import Path
import io
import json
import zipfile

router = APIRouter()


@router.get('/api/cad/health')
def health(request: Request):
    return cad_service(request.app.state.store).health


@router.post('/api/projects/{project_id}/cad/builds',status_code=202)
def create(project_id: str, payload: CadBuildRequest, request: Request):
    try: return cad_service(request.app.state.store).submit(project_id,payload)
    except ValueError as error: raise HTTPException(422,str(error)) from error


@router.get('/api/projects/{project_id}/cad/builds/{build_id}')
def get(project_id: str, build_id: str, request: Request):
    try: return cad_service(request.app.state.store).get(project_id,build_id)
    except ValueError as error: raise HTTPException(404,str(error)) from error


@router.post('/api/projects/{project_id}/cad/builds/{build_id}/cancel')
def cancel(project_id: str, build_id: str, request: Request):
    try: return cad_service(request.app.state.store).cancel(project_id,build_id)
    except ValueError as error: raise HTTPException(404,str(error)) from error


@router.get('/api/projects/{project_id}/cad/models/{asset_id}')
def model(project_id: str, asset_id: str, request: Request):
    try: return cad_manifest(request.app.state.assets,project_id,asset_id)
    except ValueError as error: raise HTTPException(404,str(error)) from error


@router.get('/api/projects/{project_id}/cad/models/{asset_id}/export')
def export(project_id: str, asset_id: str, request: Request):
    try:
        assets = request.app.state.assets
        manifest = cad_manifest(assets,project_id,asset_id)
        stream = io.BytesIO()
        extensions = {'step':'step','stl':'stl','glb':'glb','source':'py','parameters':'json','thumbnail':'png'}
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            for role, child_id in manifest['files'].items():
                asset = assets.get_asset(project_id=project_id,asset_id=child_id)
                archive.write(asset['absolutePath'],f'{role}.{extensions[role]}')
        return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="cad-model.zip"'})
    except (ValueError, OSError) as error: raise HTTPException(422,str(error)) from error
