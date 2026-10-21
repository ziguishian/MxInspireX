import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from test_delivery_contract import workspace, task
from app.design_tools import DesignToolRegistry, DesignToolError
from app.providers.http import OpenAICompatibleImageProvider
from app.providers.openrouter_image import OpenRouterImageProvider
from app.task_focus import TaskFocus


def png(color):
    output = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(output, format='PNG')
    return output.getvalue()


@pytest.mark.parametrize('api', ['images', 'gemini', 'chat_completions', 'openrouter'])
def test_all_reference_bytes_reach_image_provider(tmp_path, api):
    contents = [png('red'), png('blue')]
    paths = []
    for i, content in enumerate(contents):
        path = tmp_path / f'{i}.png'; path.write_bytes(content); paths.append(str(path))
    output = base64.b64encode(png('green')).decode()
    body = {'candidates': [{'content': {'parts': [{'inlineData': {'data': output, 'mimeType': 'image/png'}}]}}]} if api == 'gemini' else {'choices': [{'message': {'images': [{'image_url': {'url': f'data:image/png;base64,{output}'}}]}}]} if api == 'chat_completions' else {'data': [{'b64_json': output}]}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(body).encode()
    provider_cls = OpenRouterImageProvider if api == 'openrouter' else OpenAICompatibleImageProvider
    provider = provider_cls(base_url='https://fixture.invalid/v1', provider_key='fixture', model='gpt-image-2', credentials=SimpleNamespace(get=lambda _: 'fixture'), api=api)
    with patch('urllib.request.urlopen', return_value=Response()) as network:
        assert provider.generate(prompt='参考两张图', source_asset_path=paths[0], source_asset_paths=paths) == png('green')
    request = network.call_args.args[0]
    if api == 'images':
        assert request.full_url.endswith('/images/edits')
        assert request.data.count(b'name="image[]"') == 2
        for content in contents: assert content in request.data
    else:
        for content in contents: assert request.data.count(base64.b64encode(content)) == 1


def test_node_composer_enforces_all_inputs_and_writes_only_downstream(workspace):
    store, project, assets, canvas = workspace
    images = [assets.add_bytes(project_id=project, kind='image', filename=f'{color}.png', content=png(color)) for color in ['red', 'blue']]
    sources = [canvas.create_node(project, kind='image', title='参考图', asset_id=image['id']) for image in images]
    text = canvas.create_node(project, kind='text', title='约束', data={'text': '保持蓝色'})
    target = canvas.create_node(project, kind='image', title='生成结果')
    context = {'userMessage': '根据连接素材生成', 'canvasParams': {'kind': 'image', 'canvasNodeId': target['id'], 'source_asset_ids': [image['id'] for image in images], 'reference_node_ids': [node['id'] for node in sources] + [text['id']]}}
    task(store, project, context=context)
    captured = []
    def generate(**kwargs): captured.append(kwargs); return png('green')
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=SimpleNamespace(image=lambda *args, **kwargs: SimpleNamespace(generate=generate)))
    focus = TaskFocus(store, canvas).resolve(project, 'task', context)
    assert set(focus['nodeIds']) == {target['id'], text['id'], *(node['id'] for node in sources)}
    # A conflicting target must fail; omitting it uses the composer and all explicit inputs.
    result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': '按参考创作', 'canvas_node_id': sources[0]['id'], 'output_mode': 'create'})
    assert result['status'] == 'reference_mismatch' and not captured
    assert result['errors'][0]['field'] == 'canvas_node_id'
    result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt':'按参考创作'})
    assert len(captured[0]['source_asset_paths']) == 2
    assert result['asset']['metadata']['sourceAssetIds'] == [image['id'] for image in images]
    assert 'source_asset_paths' not in result['asset']['metadata']['params']
    assert result['node']['id'] == target['id']
    board = canvas.load(project)
    for node in sources:
        assert next(n for n in board['nodes'] if n['id'] == node['id']) == node


def test_missing_or_non_image_references_fail_before_provider(workspace):
    store, project, assets, canvas = workspace
    audio = assets.add_bytes(project_id=project, kind='audio', filename='audio.wav', content=b'fixture')
    registry = SimpleNamespace(image=lambda *args, **kwargs: pytest.fail('Must not contact provider'))
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=registry)
    for asset_id in ['missing', audio['id']]:
        with pytest.raises(DesignToolError, match='图像资产'):
            tools.generate_image(project_id=project, prompt='test', source_asset_ids=[asset_id])
    with pytest.raises(DesignToolError, match='最多支持两张'):
        tools.generate_video(project_id=project, prompt='test', source_asset_ids=['one', 'two', 'three'])


def test_canvas_node_image_self_reference_stops_before_provider_or_placeholder(workspace):
    store, project, assets, canvas = workspace
    original = assets.add_bytes(project_id=project, kind='image', filename='original.png', content=png('red'))
    target = canvas.create_node(project, kind='image', title='已有内容', asset_id=original['id'])
    context = {'taskSurface': 'canvas_node', 'userMessage': '修改当前图像',
               'canvasParams': {'kind': 'image', 'canvasNodeId': target['id'], 'source_asset_ids': [original['id']]},
               'canvasNodeId': target['id'], 'referencedNodes': [{'id': target['id'], 'projectId': project}]}
    task(store, project, context=context)
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas,
                               provider_registry=SimpleNamespace(image=lambda *args, **kwargs: pytest.fail('Must not contact provider')))
    before = canvas.load(project)
    result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': '夜景'})
    assert result['status'] == 'self_reference_not_allowed'
    assert canvas.load(project) == before
