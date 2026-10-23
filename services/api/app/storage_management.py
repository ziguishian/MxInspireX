"""Read workspace usage without following links or deleting user files."""
import os
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix='/api/storage', tags=['storage'])


def workspace_usage(root: Path) -> dict:
    total = 0
    partial = False

    def failed(_error):
        nonlocal partial
        partial = True

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        # Junctions and symlinks may point outside the workspace.
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()
                   and not getattr(Path(directory) / name, 'is_junction', lambda: False)()]
        for name in files:
            path = Path(directory) / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                partial = True
    return {'path': str(root), 'bytes': total, 'partial': partial}


@router.get('')
def storage_usage(request: Request):
    return workspace_usage(request.app.state.store.workspace_root)


@router.delete('/cache')
def clear_preview_cache(request: Request):
    previews = request.app.state.project_previews
    previews.cache.clear()
    previews.html_cache.clear()
    return {'cleared': True}
