"""User-authored raster layout boards; editable strokes and immutable PNG refs."""
from io import BytesIO
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from PIL import Image, ImageChops, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canvas import CanvasConflict

router = APIRouter(tags=['canvas'])


class Stroke(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    tool: Literal['pen', 'eraser']
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    width: float = Field(ge=1, le=64)
    points: list[tuple[float, float]] = Field(min_length=1, max_length=20000)


class Drawing(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    width: int = Field(ge=256, le=2048, strict=True)
    height: int = Field(ge=256, le=2048, strict=True)
    strokes: list[Stroke] = Field(max_length=2000)

    @model_validator(mode='after')
    def validate_points(self):
        if sum(len(s.points) for s in self.strokes) > 100000:
            raise ValueError('笔迹过多，请新建另一张画板')
        if any(not (0 <= x <= self.width and 0 <= y <= self.height) for s in self.strokes for x, y in s.points):
            raise ValueError('笔迹坐标超出画板')
        return self


class SaveDrawing(BaseModel):
    baseRevision: str = Field(min_length=1, max_length=64)
    drawing: Drawing


def empty_drawing():
    return {'width': 1024, 'height': 768, 'strokes': [], 'revision': str(uuid4()), 'hasContent': False}


def render_drawing(drawing):
    image = Image.new('RGB', (drawing['width'], drawing['height']), 'white')
    draw = ImageDraw.Draw(image)
    for stroke in drawing['strokes']:
        points = [tuple(point) for point in stroke['points']]
        color = 'white' if stroke['tool'] == 'eraser' else stroke['color']
        width = max(1, round(stroke['width']))
        if len(points) > 1:
            draw.line(points, fill=color, width=width, joint='curve')
        radius = width / 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
    has_content = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox() is not None
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue(), has_content


def save_drawing(canvas, assets, project_id, node_id, payload):
    drawing = payload.drawing.model_dump(mode='json')
    # Use the same lock as Agent and user canvas writes; create the PNG only
    # after checking ownership, active tasks and the stroke revision.
    with canvas._lock:
        board = canvas.load(project_id)
        node = next((n for n in board['nodes'] if n['id'] == node_id), None)
        if not node or node.get('data', {}).get('editor') != 'drawing':
            raise ValueError('画板不存在或不属于当前项目')
        if node_id in canvas.active_node_ids(project_id, board):
            raise CanvasConflict('画板正被当前任务引用，请等待完成或停止任务后再绘画')
        previous = node['data'].get('drawing') or {}
        if all(previous.get(key) == value for key, value in drawing.items()):
            return node  # A lost save response can be retried without a new asset.
        if previous.get('revision') != payload.baseRevision:
            raise CanvasConflict('画板已在其他页面更新，请重新载入后绘画；本地笔迹尚未覆盖远端')
        content, has_content = render_drawing(drawing)
        revision = str(uuid4())
        asset = assets.add_bytes(project_id=project_id, kind='image', filename='布局画板.png', content=content,
            metadata={'source': 'canvas-drawing', 'referenceRole': 'layout', 'drawingNodeId': node_id,
                      'drawingRevision': revision, 'imageOutput': {'width': drawing['width'], 'height': drawing['height'],
                      'verified': True, 'hasTransparency': False}}) if has_content else None
        return canvas.update_node(project_id, node_id, {'data': {
            'drawing': {**drawing, 'revision': revision, 'hasContent': has_content},
            'assetId': asset['id'] if asset else None, 'asset': asset,
            'draft': not has_content, 'error': '', 'status': '已保存' if has_content else '空白画板',
            'referenceRole': 'layout',
        }})


@router.put('/api/projects/{project_id}/canvas/{node_id}/drawing')
def update_drawing(project_id: str, node_id: str, payload: SaveDrawing, request: Request):
    state = request.app.state
    if state.store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='项目不存在')
    try:
        node = save_drawing(state.design_tools.canvas_store, state.assets, project_id, node_id, payload)
        return {'node': node, 'projectId': project_id}
    except CanvasConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
