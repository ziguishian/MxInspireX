import base64
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.conversation_memory import ConversationMemoryService
from app.design_tools import DesignToolRegistry
from app.providers.http import OpenAICompatibleImageProvider
from app.providers.openrouter_image import OpenRouterImageProvider
from test_conversation_memory import workspace, turn, picture, update
from test_image_dispatch import Response, image_bytes


def setup(store, modes=('inspiration', 'identity'), user_message=None):
    if user_message is None:
        user_message = ('参考这张图的配色和氛围制作海报' if modes == ('inspiration',)
                        else '保持这张图中的产品主体和外观，制作一张海报' if modes == ('identity',)
                        else '把这张图中的产品改成红色，其他内容不变' if modes == ('edit',)
                        else '结合这些图片完成产品海报设计')
    assets = [picture(store, str(i), source='input-reference') for i in range(len(modes))]
    turn(store, 'current', user_message, referencedAssets=[{'id':a['id']} for a in assets])
    update(ConversationMemoryService(store), 'current', selected=['asset:'+a['id'] for a in assets])
    adapter = OpenRouterImageProvider('https://fixture.invalid/v1', 'openrouter', 'openai/gpt-image-2.5-sunburst', SimpleNamespace(get=lambda _: 'fixture-key'), supports_streaming=True)
    registry = DesignToolRegistry(store, asset_store=AssetStore(store), provider_registry=SimpleNamespace(image=lambda *a,**kw: adapter))
    arguments = {'prompt':'水杯海报，深蓝背景、柔和侧光、哑光材质，右侧留白放标题“清凉一夏”，保留产品外观与标识比例。', 'model':adapter.model, 'provider':'openrouter',
                 'output_mode':'create', 'source_asset_ids':[a['id'] for a in assets],
                 'reference_analysis':{'images':[{'asset_id':a['id'],'mode':mode,
                     'visual_prompt':'深蓝背景、浅色主体、右侧留白、柔和侧光、哑光材质',
                     'use':'将蓝色层次和右侧留白应用到水杯海报','avoid':'参考里的旧标题和无关装饰',
                     'preserve':'用户产品外观与标识比例' if mode!='inspiration' else ''} for a,mode in zip(assets,modes)],
                     'synthesis':'以用户水杯为主体，右侧放清凉一夏标题，融合蓝色层次，保留产品身份'}}
    return registry, assets, arguments


def execute(registry, args):
    return registry.execute(project_id='one', task_id='current', name='generate_image', arguments=args)


def test_all_reference_fields_and_batch_items_are_reported_before_dispatch(workspace):
    registry,_,args=setup(workspace)
    args['reference_analysis']['synthesis']=''
    for item in args['reference_analysis']['images']:
        item['visual_prompt']=''
        item['use']=''
    with patch('urllib.request.urlopen') as transport:
        result=execute(registry,args)
        batch=registry.execute(project_id='one',task_id='current',name='generation_reference_check',arguments={
            'operations':[{'tool':'generate_image','arguments':args},{'tool':'generate_image','arguments':args}]})
    transport.assert_not_called()
    assert result['submitted'] is False and len(result['errors'])>=5
    assert {item['operationIndex'] for item in batch['errors']}=={0,1}
    assert len(batch['errors'])>=10


@pytest.mark.parametrize('modes', [('inspiration',), ('identity',), ('edit',), ('inspiration','identity')])
def test_reference_modes_control_actual_pixels_and_save_design_provenance(workspace, modes):
    registry, assets, args = setup(workspace, modes)
    original = CanvasStore(workspace).ensure_asset_node('one', assets[0])
    response = Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})
    with patch('urllib.request.urlopen', return_value=response) as transport:
        result = execute(registry, args)
        replay = execute(registry, args)
    assert result['status'] == 'succeeded' and replay['assetId'] == result['assetId']
    assert transport.call_count == 1
    payload = json.loads(transport.call_args.args[0].data)
    wanted = [a for a,mode in zip(assets,modes) if mode != 'inspiration']
    actual = payload.get('input_references', [])
    assert len(actual) == len(wanted)
    assert payload['stream'] is (not wanted)
    for item,asset in zip(actual,wanted):
        assert base64.b64decode(item['image_url']['url'].split(',',1)[1]) == Path(asset['absolutePath']).read_bytes()
    assert args['prompt'] in payload['prompt']
    assert args['reference_analysis']['synthesis'] not in payload['prompt']
    assert '视觉反推描述' not in payload['prompt'] and '不沿用：' not in payload['prompt']
    assert all(asset['id'] not in payload['prompt'] for asset in assets)
    if wanted: assert '输入图 1' in payload['prompt']
    if modes == ('inspiration',): assert '输入图' not in payload['prompt']
    if 'edit' in modes: assert payload['prompt'].startswith('图像编辑任务')
    metadata = result['asset']['metadata']
    assert metadata['sourceAssetIds'] == [a['id'] for a in assets]
    assert metadata['providerInputAssetIds'] == [a['id'] for a in wanted]
    assert metadata['referenceSnapshot']['analysis'] == args['reference_analysis']
    assert metadata['referenceSnapshot']['providerInputAssetIds'] == metadata['providerInputAssetIds']
    nodes = CanvasStore(workspace).load('one')['nodes']
    assert any(n['id']==original['id'] and n['data']['assetId']==assets[0]['id'] for n in nodes)
    assert result['node']['id'] != original['id']


@pytest.mark.parametrize('failure', ['missing','omitted_image','wrong_asset','duplicate','empty_synthesis','missing_preserve','bad_mode'])
def test_incomplete_analysis_stops_before_loading_and_can_be_corrected(workspace, failure):
    registry, _, args = setup(workspace)
    bad = copy.deepcopy(args)
    analysis = bad['reference_analysis']
    if failure == 'missing': bad.pop('reference_analysis')
    elif failure == 'omitted_image': analysis['images'].pop()
    elif failure == 'wrong_asset': analysis['images'][0]['asset_id'] = 'not-selected'
    elif failure == 'duplicate': analysis['images'].append(analysis['images'][0])
    elif failure == 'empty_synthesis': analysis['synthesis'] = ' '
    elif failure == 'missing_preserve': analysis['images'][1].pop('preserve')
    elif failure == 'bad_mode': analysis['images'][0]['mode'] = 'copy'
    with patch('urllib.request.urlopen') as transport:
        rejected = execute(registry, bad)
    assert rejected['status'] == 'reference_analysis_required'
    transport.assert_not_called()
    assert CanvasStore(workspace).load('one')['nodes'] == []
    with workspace._connect() as db:
        assert not db.execute("SELECT 1 FROM tool_receipts WHERE status='running'").fetchone()
    with patch('urllib.request.urlopen', return_value=Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})) as transport:
        assert execute(registry, args)['status'] == 'succeeded'
    assert transport.call_count == 1


def test_batch_requires_analysis_for_every_item_before_any_dispatch(workspace):
    registry, _, args = setup(workspace)
    missing = {k:v for k,v in args.items() if k != 'reference_analysis'}
    with patch('urllib.request.urlopen') as transport:
        result = registry.execute(project_id='one',task_id='current',name='generation_reference_check',arguments={
            'operations':[{'tool':'generate_image','arguments':args},{'tool':'generate_image','arguments':missing}]})
    assert result['status'] == 'reference_analysis_required'
    transport.assert_not_called()
    assert CanvasStore(workspace).load('one')['nodes'] == []


def test_explicit_edit_keeps_original_pixels_and_limits_default_removals(workspace):
    message = '只把杯子改成红色，其他不变'
    registry, assets, args = setup(workspace, ('edit',), user_message=message)
    original = CanvasStore(workspace).ensure_asset_node('one', assets[0])
    args.update(prompt=message, canvas_node_id=original['id'], output_mode='edit')
    item = args['reference_analysis']['images'][0]
    item.update(use='仅把杯子改成红色', preserve='杯子形状、Logo、背景、标题、构图和装饰')
    item.pop('avoid')
    args['reference_analysis']['synthesis'] = message
    original_bytes = Path(assets[0]['absolutePath']).read_bytes()
    with patch('urllib.request.urlopen', return_value=Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})) as transport:
        result = execute(registry, args)
        replay = execute(registry, args)
    assert result['status'] == 'succeeded' and replay['assetId'] == result['assetId']
    assert transport.call_count == 1
    payload = json.loads(transport.call_args.args[0].data)
    assert base64.b64decode(payload['input_references'][0]['image_url']['url'].split(',',1)[1]) == original_bytes
    assert message in payload['prompt']
    assert payload['prompt'].startswith('图像编辑任务')
    assert '未指定修改的内容保持不变' in payload['prompt']
    assert '杯子形状、Logo、背景、标题、构图和装饰' in payload['prompt']
    assert '深蓝背景' not in payload['prompt']
    assert '与本项需求无关的主体、文字和装饰' not in payload['prompt']
    assert Path(assets[0]['absolutePath']).read_bytes() == original_bytes
    nodes = CanvasStore(workspace).load('one')['nodes']
    assert next(n for n in nodes if n['id']==original['id']) == original
    assert len(nodes) == 2 and result['node']['id'] != original['id']


def test_ship_night_scene_is_locally_normalized_and_keeps_ratio_without_agent_retry(workspace):
    message = '@asset:source 生成这张图中这条船在夜晚的场景，然后船上要有人。画面的比例为16:9'
    registry, assets, args = setup(workspace, ('identity',), user_message=message)
    original = CanvasStore(workspace).ensure_asset_node('one', assets[0])
    args.update(prompt=message, params={'aspect_ratio': '16:9'})
    args['reference_analysis']['images'][0].update(
        mode='identity', use='把船放进夜晚场景', preserve='船的身份和外观')
    args['reference_analysis']['synthesis'] = message
    with patch('urllib.request.urlopen', return_value=Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})) as transport:
        result = execute(registry, args)
    assert result['status'] == 'succeeded'
    assert transport.call_count == 1
    assert args['params']['aspect_ratio'] == '16:9'
    resolution = result['asset']['metadata']['referenceSnapshot']['resolution']
    assert resolution['referenceIntents'][0]['actualMode'] == 'edit'
    correction = resolution['referenceModeCorrections'][0]
    assert correction['assetId'] == assets[0]['id']
    assert (correction['beforeMode'], correction['afterMode']) == ('identity', 'edit')
    assert correction['source'] == 'user_text' and correction['reason']
    assert resolution['providerInputAssetIds'] == [assets[0]['id']]
    analysis = result['asset']['metadata']['referenceSnapshot']['analysis']['images'][0]
    assert analysis['mode'] == 'edit'
    assert '船的身份和外观' in analysis['preserve']
    assert '未明确要求改变的主体、文字、Logo、构图和装饰保持不变' in analysis['preserve']
    nodes = CanvasStore(workspace).load('one')['nodes']
    assert next(node for node in nodes if node['id'] == original['id']) == original
    assert result['node']['id'] != original['id']


@pytest.mark.parametrize('tool', ['image_edit', 'generate_image'])
@pytest.mark.parametrize('invalid_mode', ['inspiration', 'identity', None])
def test_masked_edit_repairs_analysis_before_sending_original_and_mask(workspace, tool, invalid_mode):
    registry, assets, args = setup(workspace, ('edit',))
    original = CanvasStore(workspace).ensure_asset_node('one', assets[0])
    data = io.BytesIO()
    Image.new('RGBA', (30,24), (255,255,255,0)).save(data, format='PNG')
    mask = registry.asset_store.add_bytes(project_id='one', kind='image', filename='mask.png', content=data.getvalue())
    adapter = OpenAICompatibleImageProvider('https://fixture.invalid/v1', 'openai-compatible', 'gpt-image-1.5', SimpleNamespace(get=lambda _: 'fixture-key'))
    registry.provider_registry = SimpleNamespace(image=lambda *a,**kw: adapter)
    turn(workspace, 'masked', '只修改遮罩内的颜色，其余内容保持原样',
         referencedAssets=[{'id':assets[0]['id']}, {'id':mask['id']}],
         mediaProvider={'image':{'key':'openai-compatible','model':adapter.model,'manual':True}})
    update(ConversationMemoryService(workspace), 'masked', selected=['asset:'+assets[0]['id']])
    analysis = args['reference_analysis']
    analysis['images'][0].update(use='仅修改遮罩内的颜色', avoid='', preserve='遮罩外全部内容')
    analysis['synthesis'] = '只修改遮罩内的颜色，其余内容保持原样'
    args = {'reference_analysis':analysis, 'canvas_node_id':original['id']}
    if tool == 'image_edit':
        args.update(asset_id=assets[0]['id'], operation='inpaint', params={'maskAssetId':mask['id'], 'prompt':analysis['synthesis']})
    else:
        args.update(source_asset_id=assets[0]['id'], prompt=analysis['synthesis'], params={'maskAssetId':mask['id']})
    bad = copy.deepcopy(args)
    if invalid_mode is None:
        bad.pop('reference_analysis')
    else:
        bad['reference_analysis']['images'][0]['mode'] = invalid_mode
    if invalid_mode is None:
        with patch('urllib.request.urlopen') as transport:
            if tool == 'generate_image':
                checked = registry.execute(project_id='one', task_id='masked', name='generation_reference_check',
                    arguments={'operations':[{'tool':tool, 'arguments':bad}]})
                assert checked['status'] == 'reference_analysis_required'
            rejected = registry.execute(project_id='one', task_id='masked', name=tool, arguments=bad)
        assert rejected['status'] == 'reference_analysis_required'
        transport.assert_not_called()
        assert CanvasStore(workspace).load('one')['nodes'] == [original]
        with workspace._connect() as db:
            assert not db.execute("SELECT 1 FROM tool_receipts WHERE status='running'").fetchone()
        submitted = args
    else:
        if tool == 'generate_image':
            checked = registry.execute(project_id='one', task_id='masked', name='generation_reference_check',
                arguments={'operations':[{'tool':tool, 'arguments':bad}]})
            assert checked['status'] == 'ready'
            correction = checked['resolvedOperations'][0]['referenceModeCorrections'][0]
            assert (correction['beforeMode'], correction['afterMode']) == (invalid_mode, 'edit')
        submitted = bad
    with patch('urllib.request.urlopen', return_value=Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})) as transport:
        result = registry.execute(project_id='one', task_id='masked', name=tool, arguments=submitted)
        replay = registry.execute(project_id='one', task_id='masked', name=tool, arguments=submitted)
    assert result['status'] == 'succeeded' and replay['assetId'] == result['assetId']
    assert transport.call_count == 1
    request = transport.call_args.args[0]
    assert request.full_url.endswith('/images/edits')
    assert Path(assets[0]['absolutePath']).read_bytes() in request.data and data.getvalue() in request.data
    assert analysis['synthesis'].encode() in request.data
    assert result['asset']['metadata']['providerInputAssetIds'] == [assets[0]['id']]
    nodes = CanvasStore(workspace).load('one')['nodes']
    assert next(n for n in nodes if n['id']==original['id']) == original
    assert result['node']['id'] != original['id']
