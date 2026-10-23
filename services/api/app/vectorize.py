"""Explicit local image tracing. Never enables model-authored SVG output."""
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from fastapi import APIRouter, HTTPException, Request, Body
from PIL import Image, ImageOps
from .canvas_layout import node_preview_size

router = APIRouter(tags=['canvas'])


def trace_image(content):
    import vtracer
    with Image.open(BytesIO(content)) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError('图片过大，请先缩小到 4000 万像素以内')
        image = ImageOps.exif_transpose(source).convert('RGBA')
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, 'PNG')
    svg = vtracer.convert_raw_image_to_svg(buffer.getvalue(), img_format='png', colormode='color', hierarchical='stacked', mode='spline', filter_speckle=4, color_precision=6, path_precision=3)
    root = ElementTree.fromstring(svg)
    for element in root.iter():
        if element.tag.split('}')[-1] not in {'svg', 'g', 'path'} or any(k.lower().startswith('on') or k.endswith('href') for k in element.attrib):
            raise ValueError('矢量输出包含不支持的内容')
    if not any(e.tag.split('}')[-1] == 'path' for e in root.iter()):
        raise ValueError('没有找到可转换的图形')
    return svg.encode('utf-8'), image.size


def vectorize_node(canvas, assets, project_id, node_id, target_node_id=None):
    # Serialize repeat clicks; reuse the output for exactly the same source.
    with canvas._lock:
        board = canvas.load(project_id)
        source = next((n for n in board['nodes'] if n['id'] == node_id), None)
        if not source or source['data'].get('generating'):
            raise ValueError('请先选择已完成的图片节点')
        target = next((n for n in board['nodes'] if n['id'] == target_node_id), None) if target_node_id else None
        if target_node_id and (not target or target['data'].get('assetId') or target['data'].get('generating') or target['data'].get('kind') != 'image'):
            raise ValueError('矢量输出必须是空白图像节点')
        asset_id = source['data'].get('assetId') or source['data'].get('asset', {}).get('id')
        asset = assets.get_asset(project_id=project_id, asset_id=asset_id or '')
        if not asset or asset['mime'] not in {'image/png', 'image/jpeg', 'image/webp'}:
            raise ValueError('仅支持已保存的 PNG、JPEG、WebP 图片')
        for node in board['nodes']:
            if node['data'].get('vectorSource') == asset['sha256'] and node['data'].get('vectorSourceNode') == node_id:
                if target:
                    return canvas.update_node(project_id, target_node_id, {'data': {**node['data'], 'title':target['data'].get('title','矢量'), 'workflowRunId':target['data'].get('workflowRunId')}})
                return node
        content, size = trace_image(Path(asset['absolutePath']).read_bytes())
        result = assets.add_bytes(project_id=project_id, kind='image', filename='vectorized.svg', content=content,
                                  metadata={'localVectorTrace': True, 'sourceAssetId': asset_id, 'width': size[0], 'height': size[1]})
        if target:
            return canvas.update_node(project_id,target_node_id,{'data':{'asset':result,'assetId':result['id'],'vectorSource':asset['sha256'],'vectorSourceNode':node_id,'draft':False}})
        width = node_preview_size(source['data'])['width']
        position = {'x': source['position']['x'] + width + 80, 'y': source['position']['y']}
        return canvas.create_node(project_id, position=position, kind='image', title=f'{source["data"].get("title", "图片")} · 矢量', asset_id=result['id'],
                                  data={'asset': result, 'vectorSource': asset['sha256'], 'vectorSourceNode': node_id, 'draft': False})


@router.post('/api/projects/{project_id}/canvas/{node_id}/vectorize')
def vectorize(project_id: str, node_id: str, request: Request, payload: dict = Body(default={})):
    state = request.app.state
    if not state.store.get_project(project_id): raise HTTPException(404, '项目不存在')
    try:
        canvas = state.design_tools.canvas_store
        node = vectorize_node(canvas, state.assets, project_id, node_id, payload.get("targetNodeId"))
        return {'node': node, 'canvas': canvas.load(project_id)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(422, '图片文件无法读取，请重新上传后转换') from error
