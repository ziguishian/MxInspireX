import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_canvas_references import png
from test_delivery_contract import workspace, task
from app.design_tools import DesignToolRegistry, DesignToolError
from app.providers.openrouter_video import OpenRouterVideoProvider
from app.task_policy import delivery_contract
from app.video import VideoJobService
from app.video_inputs import video_inputs


@pytest.mark.parametrize('brief,expected', [
    ('@asset:a @asset:b 这两张图做首尾帧，做礼盒打开的视频', {'video': 1}),
    ('使用两张图片作为首尾帧，生成视频', {'video': 1}),
    ('首帧用这张图片，尾帧用那张照片，生成视频', {'video': 1}),
    ('两张图片做首尾帧，制作一段视频', {'video': 1}),
    ('先生成两张图片做首尾帧，再生成视频', {'image': 2, 'video': 1}),
    ('用这两张图做首尾帧，再生成一张海报和一段视频', {'image': 1, 'video': 1}),
    ('用这两张图做首尾帧并生成一张海报和一段视频', {'image': 1, 'video': 1}),
])
def test_frame_references_are_inputs_not_deliverables(brief, expected):
    assert {item['kind']: item['count'] for item in delivery_contract(brief)} == expected


def test_explicit_image_output_contract_is_preserved():
    assert {item['kind']: item['count'] for item in delivery_contract('这两张图做首尾帧，做视频', {'deliveryContract': [{'kind': 'image', 'count': 3}]})} == {'image': 3, 'video': 1}


@pytest.mark.parametrize('params', [{'duration_seconds': 8}, {'seconds': '8'}, {'duration': 8}])
def test_video_duration_aliases(params):
    assert video_inputs(params=params)[2] == {'duration': 8}


@pytest.mark.parametrize('kwargs', [
    {'source_asset_ids': ['a','b','c']}, {'source_asset_id': 'b', 'source_asset_ids': ['a','b']},
    {'source_asset_id': 'a', 'last_frame_asset_id': 'b', 'params': {'end_frame_asset_id': 'c'}},
    {'last_frame_asset_id': 'b'}, {'params': {'duration': 8, 'duration_seconds': 5}},
    {'params': {'duration_seconds': 0}}, {'params': {'duration': 5.5}}, {'params': {'duration': True}},
    {'params': {'last_frame_asset': '/unscoped/private.png'}}, {'params': {'frame_images': []}},
])
def test_conflicting_or_invalid_frames_and_duration_are_rejected(kwargs):
    with pytest.raises(ValueError): video_inputs(**kwargs)


@pytest.mark.parametrize('input_mode', ['explicit', 'legacy', 'ordered', 'canvas'])
def test_first_and_last_bytes_reach_openrouter_and_survive_backfill(workspace, input_mode):
    store, project, assets, canvas = workspace
    contents = [png('red'), png('blue')]
    images = [assets.add_bytes(project_id=project, kind='image', filename=f'{i}.png', content=content) for i, content in enumerate(contents)]
    ids = [image['id'] for image in images]
    sources = [canvas.create_node(project, kind='image', title=f'参考{i}', asset_id=id) for i, id in enumerate(ids)]
    target = canvas.create_node(project, kind='video', title='礼盒开盒', data={'generating':True})
    context = {'userMessage': f'@asset:{ids[0]} @asset:{ids[1]} 这两张图做首尾帧，做礼盒打开的视频'}
    if input_mode == 'canvas':
        context['canvasParams'] = {'kind':'video','canvasNodeId':target['id'],'source_asset_id':ids[0],'last_frame_asset_id':ids[1], 'source_asset_ids':ids, 'reference_node_ids':[n['id'] for n in sources]}
    task(store, project, context=context)
    adapter = OpenRouterVideoProvider(provider_key='openrouter', credentials=SimpleNamespace(get=lambda _: 'fixture'), endpoint='https://openrouter.ai/api/v1', model='bytedance/seedance-2.5')
    providers = SimpleNamespace(video=lambda *a, **kw: adapter)
    service = VideoJobService(store, providers, assets, canvas)
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=providers, video_service=service)
    args = {'prompt':'礼盒打开','provider':'openrouter','params':{'duration_seconds':8,'camera_motion':'slow_push_in'}, 'output_mode':'edit','canvas_node_id':target['id']}
    if input_mode == 'explicit': args.update(source_asset_id=ids[0], last_frame_asset_id=ids[1])
    elif input_mode == 'legacy': args.update(source_asset_id=ids[0]); args['params']['end_frame_asset_id'] = ids[1]
    elif input_mode == 'ordered': args['source_asset_ids'] = ids
    else:
        # The composer must restore both inputs even when the model omits or reverses them.
        args.update(source_asset_id=ids[1], last_frame_asset_id=ids[0], canvas_node_id=sources[0]['id'], output_mode='create')
    # In the chat case the target is an existing output; make it part of this conversation's focus.
    if input_mode != 'canvas':
        with store._connect() as db:
            context['userMessage'] += f' @node:{target["id"]}'
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context),'task'))
    with patch.object(adapter, '_request', return_value={'id':'remote-job','status':'pending'}) as post:
        result = tools.execute(project_id=project, task_id='task', name='generate_video', arguments=args)
        body = post.call_args.args[1]
        assert body['duration'] == 8
        assert '镜头运动：slow_push_in' in body['prompt']
        assert [frame['frame_type'] for frame in body['frame_images']] == ['first_frame','last_frame']
        assert [base64.b64decode(frame['image_url']['url'].split(',')[1]) for frame in body['frame_images']] == contents
        assert not any(key in body for key in ('source_asset_id','last_frame_asset_id','end_frame_asset_id','duration_seconds'))
        assert tools.execute(project_id=project, task_id='task', name='generate_video', arguments=args)['job']['id'] == result['job']['id']
        assert post.call_count == 1
    assert result['job']['metadata']['sourceAssetIds'] == ids
    assert result['job']['metadata']['lastFrameAssetId'] == ids[1]
    assert result['job']['metadata']['params']['duration'] == 8
    with patch.object(adapter, 'retrieve', return_value={'status':'completed', 'content':b'fixture-video'}):
        complete = service.refresh(project, result['job']['id'])
    assert complete['asset']['metadata']['sourceAssetIds'] == ids
    assert complete['asset']['metadata']['lastFrameAssetId'] == ids[1]
    board = canvas.load(project)
    assert next(n for n in board['nodes'] if n['id'] == target['id'])['data']['assetId'] == complete['asset']['id']
    for node in sources: assert next(n for n in board['nodes'] if n['id'] == node['id']) == node


def test_tail_validation_happens_before_paid_submission(workspace):
    store, project, assets, canvas = workspace
    first = assets.add_bytes(project_id=project, kind='image', filename='first.png', content=png('red'))
    tail = assets.add_bytes(project_id=project, kind='image', filename='tail.png', content=png('blue'))
    audio = assets.add_bytes(project_id=project, kind='audio', filename='audio.wav', content=b'fixture')
    providers = SimpleNamespace(video=lambda *a, **kw: SimpleNamespace(generate=lambda **kw: pytest.fail('Must not submit')))
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=providers)
    for invalid in ['missing', audio['id']]:
        with pytest.raises(DesignToolError, match='图像资产'):
            tools.generate_video(project_id=project, prompt='开盒', source_asset_id=first['id'], last_frame_asset_id=invalid)
    with pytest.raises(DesignToolError, match='不支持首尾帧'):
        tools.generate_video(project_id=project, prompt='开盒', source_asset_ids=[first['id'],tail['id']])
    task(store, project, context={'userMessage':f'@asset:{first["id"]} 做视频'})
    with pytest.raises(ValueError, match='本轮引用'):
        tools.execute(project_id=project, task_id='task', name='generate_video', arguments={'prompt':'开盒','output_mode':'create','source_asset_id':first['id'],'params':{'end_frame_asset_id':tail['id']}})
    Path(assets.get_asset(project_id=project, asset_id=tail['id'])['absolutePath']).unlink()
    with pytest.raises(DesignToolError, match='文件不存在'):
        tools.generate_video(project_id=project, prompt='开盒', source_asset_id=first['id'], last_frame_asset_id=tail['id'])


def test_single_frame_still_works_and_unreadable_tail_is_not_submitted(tmp_path):
    first = tmp_path / 'first.png'
    first.write_bytes(png('red'))
    adapter = OpenRouterVideoProvider(provider_key='openrouter', credentials=SimpleNamespace(get=lambda _: 'fixture'), endpoint='https://openrouter.ai/api/v1', model='bytedance/seedance-2.5')
    with patch.object(adapter, '_request', return_value={'id':'job'}) as post:
        adapter.generate(prompt='运动', source_asset=str(first), seconds=8)
        body = post.call_args.args[1]
        assert body['duration'] == 8
        assert [frame['frame_type'] for frame in body['frame_images']] == ['first_frame']
        with pytest.raises(ValueError):
            adapter.generate(prompt='运动', source_asset=str(first), duration_seconds=5.5)
        from app.providers.http import ProviderError
        with pytest.raises(ProviderError, match='不存在'):
            adapter.generate(prompt='运动', source_asset=str(first), last_frame_asset=str(tmp_path / 'missing.png'))
        assert post.call_count == 1


def test_video_job_endpoint_preserves_both_frames(workspace):
    from app.main import app, create_video_job
    store, project, assets, canvas = workspace
    images = [assets.add_bytes(project_id=project, kind='image', filename=f'{color}.png', content=png(color)) for color in ['red','blue']]
    adapter = OpenRouterVideoProvider(provider_key='openrouter', credentials=SimpleNamespace(get=lambda _: 'fixture'), endpoint='https://openrouter.ai/api/v1', model='bytedance/seedance-2.5')
    providers = SimpleNamespace(video=lambda *a, **kw: adapter)
    service = VideoJobService(store, providers, assets, canvas)
    state = SimpleNamespace(assets=assets, providers=providers, videos=service, model_catalog=None)
    with patch.object(app, 'state', state), patch('app.main._provider_base_url', return_value='https://openrouter.ai/api/v1'), patch('app.main.MediaModelRouter') as router, patch.object(adapter, '_request', return_value={'id':'job','status':'pending'}) as post:
        router.return_value.route.return_value = 'bytedance/seedance-2.5'
        result = create_video_job(project, {'provider':'openrouter','prompt':'开盒','sourceAssetId':images[0]['id'],'lastFrameAssetId':images[1]['id'],'params':{'duration_seconds':8}}, store)
        assert post.call_args.args[1]['duration'] == 8
        assert [frame['frame_type'] for frame in post.call_args.args[1]['frame_images']] == ['first_frame','last_frame']
        assert result['job']['metadata']['lastFrameAssetId'] == images[1]['id']


@pytest.mark.parametrize('wait_for', ['media','preview','finished_during_check'])
def test_sdk_waits_for_media_despite_other_delivery_issues(workspace, wait_for):
    store, project, _, _ = workspace
    task(store, project, context={'userMessage':'首尾帧视频'})
    root = Path(__file__).resolve().parents[1]
    fixtures = Path(__file__).parent / 'fixtures'
    env = {**os.environ, 'PYTHONPATH':str(root), 'FIXTURE_PYTHON':sys.executable, 'FIXTURE_TOOL_SCRIPT':str(fixtures/'agent_tool_fixture.py'), 'FIXTURE_WORKSPACE':str(store.workspace_root), 'FIXTURE_PROJECT':project, 'FIXTURE_TASK':'task', 'FIXTURE_WAIT_FOR':wait_for}
    payload = {'api':'responses','apiKey':'fixture','model':'fixture-model','baseUrl':'http://fixture.invalid/v1',
               'toolGateway':{'baseUrl':'http://fixture.invalid','projectId':project,'taskId':'task'},
               'context':{'projectId':project,'taskId':'task','brief':'这两张图做首尾帧，做视频','constraints':{'executionFlow':'design_review','deliveryVerification':True,'allowExternalNetwork':False}}}
    result = subprocess.run([shutil.which('node'), '--import', (fixtures/'video_frames_transport.mjs').resolve().as_uri(), str(root/'app/openai_agent_worker.mjs')], input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stdout[-10000:] + result.stderr
    final = next(json.loads(line)['result'] for line in result.stdout.splitlines() if line.startswith('{') and json.loads(line).get('type') == 'result')
    assert final['structured_data']['deliveryStatus'] == 'pending'
    assert final['provenance']['stages'] == ['design']
    assert final['provenance']['awaitingDelivery']
    assert not final['structured_data'].get('review')
