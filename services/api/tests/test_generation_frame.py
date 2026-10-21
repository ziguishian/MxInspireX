"""Loading frames follow the effective provider request through completion."""
import base64
import io
import json

import pytest
from PIL import Image
from types import SimpleNamespace

from app.canvas_layout import node_preview_size
from app.providers.http import OpenAICompatibleImageProvider
from app.providers.openrouter_image import OpenRouterImageProvider
from test_image_dispatch import Response, image_bytes, registry, workspace
from test_gpt_image_25_parameters import SUNBURST_ROUTER_PARAMETERS


@pytest.mark.parametrize('edit', [False, True])
@pytest.mark.parametrize('provider,model,params,wire,dimensions,frame', [
    ('fixture', 'gpt-image-1.5', {'aspectRatio': '2:3'}, {'size': '1024x1536'}, (1024, 1536), (720, 1080)),
        ('fixture', 'gpt-image-2.5-sunburst', {'aspectRatio': '9:16'}, {'size': '720x1280'}, (720, 1280), (608, 1080)),
    ('fixture', 'gpt-image-2.5-sunburst', {'size': '1024x1536', 'aspectRatio': '16:9'}, {'size': '1280x720'}, (1280, 720), (720, 405)),
        ('fixture', 'gpt-image-2.5-sunburst', {'aspectRatio': '1:1'}, {'size': '1024x1024'}, (1024, 1024), (720, 720)),
        ('fixture', 'gpt-image-2.5-sunburst', {'aspectRatio': '16:9'}, {'size': '1280x720'}, (1280, 720), (720, 405)),
        ('openrouter', 'openai/gpt-image-2.5-sunburst', {'aspectRatio': '9:16'}, {'aspect_ratio': '9:16', 'resolution': '1K'}, (720, 1280), (608, 1080)),
        ('openrouter', 'openai/gpt-image-2.5-sunburst', {'aspect_ratio': '2:3'}, {'aspect_ratio': '2:3', 'resolution': '1K'}, (672, 1008), (720, 1080)),
        ('openrouter', 'openai/gpt-image-2.5-sunburst', {'aspectRatio': '4:5'}, {'size': '832x1040'}, (832, 1040), (720, 900)),
    ('openrouter', 'openai/gpt-image-2.5-flare', {'aspect_ratio': '4:5', 'resolution': '2K'}, {'size': '832x1040'}, (832, 1040), (720, 900)),
])
def test_loading_and_finished_frames_match_effective_request(workspace, monkeypatch, edit, provider, model, params, wire, dimensions, frame):
    project, _, canvas, assets = workspace
    adapter = (OpenRouterImageProvider if provider == 'openrouter' else OpenAICompatibleImageProvider)(
        'https://fixture.invalid/v1', provider, model, SimpleNamespace(get=lambda _: 'fixture-key'),
        supported_parameters=SUNBURST_ROUTER_PARAMETERS if provider == 'openrouter' else None)
    tools = registry(workspace, adapter)
    args = {'prompt': '海报', 'provider': provider, 'model': model, 'params': params}
    if edit:
        original = canvas.ensure_asset_node(project, assets.add_bytes(project_id=project, kind='image', filename='original.png', content=image_bytes(), metadata={'imageOutput': {'width': 16, 'height': 16}}))
        args.update(canvas_node_id=original['id'], output_mode='edit')
        monkeypatch.setattr(tools, '_task_input', lambda *a: {'canvasParams': {'canvasNodeId': original['id'], 'kind': 'image'}})
    observed = []

    def dispatch(request, **kwargs):
        if request.get_header('Content-type', '').startswith('multipart/form-data'):
            for key, value in wire.items():
                assert f'name="{key}"\r\n\r\n{value}\r\n'.encode() in request.data
        else:
            payload = json.loads(request.data)
            assert {key: payload.get(key) for key in wire} == wire
            if 'size' in wire and provider == 'openrouter':
                assert 'aspect_ratio' not in payload and 'resolution' not in payload
        nodes = canvas.load(project)['nodes']
        pending = [node for node in nodes if node['data'].get('generating')]
        assert len(pending) == 1
        observed.append(pending[0])
        assert node_preview_size(pending[0]['data']) == {'width': frame[0], 'height': frame[1]}
        output = io.BytesIO()
        Image.new('RGB', dimensions, 'blue').save(output, format='PNG')
        return Response({'data': [{'b64_json': base64.b64encode(output.getvalue()).decode()}]})

    monkeypatch.setattr('urllib.request.urlopen', dispatch)
    result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments=args)
    finished = result['node']
    assert len(observed) == 1 and not finished['data']['generating']
    assert finished['id'] == observed[0]['id'] and finished['position'] == observed[0]['position']
    assert node_preview_size(finished['data']) == node_preview_size(observed[0]['data'])
    board=canvas.load(project)['nodes']
    assert len(board) == (2 if edit else 1)
    if edit:
        assert next(node for node in board if node['id']==original['id'])['data']['assetId']==original['data']['assetId']
