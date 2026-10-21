"""Real registry + fake image transport: source/output integrity and paid-call counts."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry, DesignToolError
from app.conversation_memory import ConversationMemoryService
from test_conversation_memory import workspace, picture, turn, update
from test_image_reference_design import setup, execute
from test_image_dispatch import Response, image_bytes


def preflight(registry, args, name='generate_image'):
    return registry.execute(project_id='one', task_id='current', name='generation_reference_check',
                            arguments={'operations':[{'tool':name,'arguments':args}]})


def reply():
    return Response({'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}]})


def context_patch(store, **values):
    with store._connect() as db:
        context = json.loads(db.execute("SELECT input_json FROM tasks WHERE id='current'").fetchone()[0])
        context.update(values)
        db.execute("UPDATE tasks SET input_json=? WHERE id='current'", (json.dumps(context),))


def visual_direction():
    return {'audience':'年轻送礼人群','theme':'山间清饮','coreConcept':'以等高线组织包装留白',
            'visualHierarchy':['品名优先、系列名其次'], 'formLanguage':['低矮横向盒体'], 'materialProcess':['本色纸与凹压'],
            'colorRelationships':['雾青对温白'], 'compositionLighting':['低角度柔光产品摄影'], 'avoid':['不要伪文字'],
            'evidence':[{'source':'user','use':'用户要求茶礼盒'}]}


def visual_spec(**changes):
    value = {'subjectStructure':'低矮横向硬盒，盒盖与盒身分缝清楚','formProportion':'3:2 横向比例，盒体高度较低',
             'materialConstruction':'粗纹本色纸包裹，凹压山线与局部烫银','compositionFraming':'正交略俯视并保留桌面留白',
             'lightSurface':'左上方柔光显出纸纤维与凹压边缘','avoid':['不合理拼接、塑料表面、伪文字']}
    return {**value, **changes}


def test_companion_missing_output_mode_passes_first_time_and_receipt_uses_original(workspace):
    registry, assets, args = setup(workspace, ('identity',), '再设计一个偏男性的情侣角色')
    args.pop('output_mode')
    original_args = deepcopy(args)
    original = registry.canvas_store.ensure_asset_node('one', assets[0])
    with patch('urllib.request.urlopen', return_value=reply()) as transport:
        checked = preflight(registry, args)
        assert checked['status'] == 'ready', checked
        request = checked['imageRequests'][0]
        assert request['routeMode'] == 'manual'
        assert request['primaryModel'] == args['model']
        assert request['candidateModels'] == [args['model']]
        assert checked['resolvedOperations'][0]['output'] == {'mode':'create','nodeId':None}
        transport.assert_not_called()
        result = execute(registry, args)
        # A new registry represents restart; successful receipt wins even if
        # the original file is no longer available to resolve again.
        Path(assets[0]['absolutePath']).unlink()
        restarted = DesignToolRegistry(workspace, asset_store=AssetStore(workspace), provider_registry=registry.provider_registry)
        replay = execute(restarted, args)
    assert transport.call_count == 1 and result['assetId'] == replay['assetId']
    assert args == original_args
    assert result['node']['id'] != original['id']
    assert next(n for n in registry.canvas_store.load('one')['nodes'] if n['id']==original['id']) == original
    encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    expected = hashlib.sha256(('generate_image\n'+encoded).encode()).hexdigest()
    with workspace._connect() as db:
        row = db.execute("SELECT fingerprint,args FROM tool_receipts WHERE task_id='current'").fetchone()
    assert row['fingerprint'] == expected and json.loads(row['args']) == args


def test_non_actionable_image_spec_stops_preflight_before_any_provider_call(workspace):
    registry, _, args = setup(workspace, ('identity',))
    context_patch(workspace, designPlan={'scopeId':'quality', 'visualDirection':visual_direction(), 'deliverables':[
        {'id':'hero','title':'茶礼盒主视觉','kind':'image','imageSpec':visual_spec(lightSurface='高级感')}
    ]})
    args['deliverable_ids'] = ['hero']
    with patch('urllib.request.urlopen') as transport:
        result = preflight(registry, args)
    assert result['status'] == 'design_spec_required'
    assert result['errors'][0]['field'] == 'imageSpec'
    transport.assert_not_called()


@pytest.mark.parametrize('change', ['node_content', 'asset_bytes', 'missing_asset'])
def test_preflight_version_changes_block_paid_dispatch(workspace, change):
    registry, assets, args = setup(workspace, ('identity',))
    original = registry.canvas_store.ensure_asset_node('one', assets[0])
    args['canvas_node_id'] = original['id']
    assert preflight(registry, args)['status'] == 'ready'
    if change == 'node_content':
        registry.canvas_store.update_node('one', original['id'], {'data':{'title':'用户已修改'}})
    elif change == 'asset_bytes':
        Path(assets[0]['absolutePath']).write_bytes(b'changed')
    else:
        Path(assets[0]['absolutePath']).unlink()
    with patch('urllib.request.urlopen') as transport:
        rejected = execute(registry, args)
    assert rejected['status'] in {'reference_changed','reference_missing'}
    transport.assert_not_called()
    assert len(registry.canvas_store.load('one')['nodes']) == 1
    if change == 'node_content':
        assert rejected['errors'][0]['nodeIds'] == [original['id']]
        assert preflight(registry, args)['status'] == 'ready'
        with patch('urllib.request.urlopen', return_value=reply()) as transport:
            assert execute(registry, args)['status'] == 'succeeded'
        assert transport.call_count == 1


def test_bound_reference_node_changes_are_checked_even_with_asset_arguments(workspace):
    registry, assets, args = setup(workspace, ('identity',))
    node = registry.canvas_store.ensure_asset_node('one', assets[0])
    context_patch(workspace, referencedNodes=[{'id':node['id']}])
    assert preflight(registry, args)['status'] == 'ready'
    replacement = picture(workspace, 'replacement')
    registry.canvas_store.update_node('one', node['id'], {'data':{'assetId':replacement['id']}})
    with patch('urllib.request.urlopen') as transport:
        rejected = execute(registry, args)
    assert rejected['status'] == 'reference_changed'
    transport.assert_not_called()


def test_selected_candidates_are_not_injected_into_each_item(workspace):
    registry, assets, args = setup(workspace, ('identity',))
    candidate = picture(workspace, 'candidate')
    context_patch(workspace, referenceWorkflow={'status':'selected','assetIds':[candidate['id']],
        'choices':[{'assetId':candidate['id'],'aspects':['配色']}], 'notes':'候选说明'})
    checked = preflight(registry, args)
    assert checked['status'] == 'ready', checked
    assert [r['assetId'] for r in checked['resolvedOperations'][0]['references']] == [assets[0]['id']]
    with patch('urllib.request.urlopen', return_value=reply()) as transport:
        result = execute(registry, args)
    assert result['asset']['metadata']['sourceAssetIds'] == [assets[0]['id']]
    assert '候选说明' not in json.loads(transport.call_args.args[0].data)['prompt']


def test_missing_analysis_reports_operation_and_exact_assets_before_any_generation(workspace):
    registry, assets, args = setup(workspace)
    missing = deepcopy(args)
    missing['reference_analysis']['images'].pop()
    with patch('urllib.request.urlopen') as transport:
        result = registry.execute(project_id='one',task_id='current',name='generation_reference_check',arguments={
            'operations':[{'tool':'generate_image','arguments':args},{'tool':'generate_image','arguments':missing}]})
    assert result['status'] == 'reference_analysis_required'
    assert result['errors'][0]['operationIndex'] == 1
    assert result['errors'][0]['assetIds'] == [assets[-1]['id']]
    assert result['errors'][0]['field'] == 'reference_analysis.images'
    transport.assert_not_called()
    assert registry.canvas_store.load('one')['nodes'] == []
    with workspace._connect() as db:
        assert not db.execute("SELECT 1 FROM conversation_reference_snapshots WHERE id LIKE 'image-preflight:%'").fetchone()


def test_multi_image_edit_and_style_roles_pass_when_singular_pronoun_is_unbound(workspace):
    message = '参考图中的极简背景，把这张图改成米白色，然后加一点轻微淡蓝色'
    registry, assets, args = setup(workspace, ('edit', 'inspiration'), user_message=message)
    args['reference_analysis']['images'][0].update(
        use='把目标墙面改成米白色并加入轻微淡蓝色',
        preserve='墙面比例、展陈分区、丝绸流线和未要求改变的内容',
    )
    args['reference_analysis']['images'][1].update(
        use='只借鉴极简背景的色彩与干净层次',
        preserve='',
    )
    with patch('urllib.request.urlopen') as transport:
        checked = preflight(registry, args)
    assert checked['status'] == 'ready', checked
    intents = checked['resolvedOperations'][0]['referenceIntents']
    assert [item['expectedOperation'] for item in intents] == ['ambiguous', 'ambiguous']
    assert [item['actualMode'] for item in intents] == ['edit', 'inspiration']
    assert checked['imageRequests'][0]['providerInputAssetIds'] == [assets[0]['id']]
    transport.assert_not_called()


@pytest.mark.parametrize('bad', ['missing_node', 'foreign_node', 'text_node', 'node_as_asset'])
def test_invalid_node_bindings_are_not_guessed(workspace, bad):
    registry, assets, args = setup(workspace, ('identity',))
    if bad == 'missing_node': args['canvas_node_id'] = 'missing'
    elif bad == 'foreign_node':
        foreign = picture(workspace, 'foreign', project='two')
        args['canvas_node_id'] = registry.canvas_store.ensure_asset_node('two', foreign)['id']
    elif bad == 'text_node':
        args['canvas_node_id'] = registry.canvas_store.create_node('one',kind='text',title='文案',data={'text':'保留'})['id']
    else:
        node = registry.canvas_store.ensure_asset_node('one',assets[0])
        args['source_asset_ids'] = ['@node:'+node['id']]
    with patch('urllib.request.urlopen') as transport:
        checked = preflight(registry, args)
        result = execute(registry, args)
    assert checked['status'] == result['status'] == 'reference_mismatch'
    transport.assert_not_called()


def test_unknown_receipt_still_blocks_after_restart_and_output_default_change(workspace):
    registry, _, args = setup(workspace, ('identity',))
    args.pop('output_mode')
    assert preflight(registry, args)['status'] == 'ready'
    registry.executions.claim('current', 'generate_image', args)
    restarted = DesignToolRegistry(workspace, asset_store=registry.asset_store, provider_registry=registry.provider_registry)
    with patch('urllib.request.urlopen') as transport:
        for attempt in (args, {**args,'output_mode':'create'}):
            with pytest.raises(DesignToolError, match='尚未确认'):
                execute(restarted, attempt)
    transport.assert_not_called()


def test_local_edit_uses_same_preflight_output_and_preserves_source(workspace):
    registry, assets, _ = setup(workspace, ('identity',))
    original = registry.canvas_store.ensure_asset_node('one', assets[0])
    args = {'asset_id':assets[0]['id'],'operation':'resize','params':{'width':12,'height':10},'canvas_node_id':original['id']}
    assert preflight(registry, args, 'image_edit')['status'] == 'ready'
    with patch('urllib.request.urlopen') as transport:
        result = registry.execute(project_id='one',task_id='current',name='image_edit',arguments=args)
        replay = registry.execute(project_id='one',task_id='current',name='image_edit',arguments=args)
    assert result['assetId'] == replay['assetId'] and result['node']['id'] != original['id']
    transport.assert_not_called()
    assert next(n for n in registry.canvas_store.load('one')['nodes'] if n['id']==original['id']) == original


def test_memory_candidates_can_be_used_per_item_but_explicit_binding_stays_required(workspace):
    registry, assets, args = setup(workspace, ('identity', 'inspiration'))
    args['source_asset_ids'] = [assets[0]['id']]
    args['reference_analysis']['images'] = args['reference_analysis']['images'][:1]
    assert preflight(registry, args)['status'] == 'ready'
    service = ConversationMemoryService(workspace)
    update(service, 'current', references=[{'deliverable_id':'*','memory_ids':['asset:'+a['id'] for a in assets]}])
    with patch('urllib.request.urlopen') as transport:
        rejected = execute(registry, args)
    assert rejected['status'] == 'reference_mismatch'
    assert rejected['errors'][0]['expectedAssetIds'] == [a['id'] for a in assets]
    assert rejected['errors'][0]['actualAssetIds'] == [assets[0]['id']]
    assert rejected['errors'][0]['missingAssetIds'] == [assets[1]['id']]
    assert rejected['errors'][0]['unexpectedAssetIds'] == []
    transport.assert_not_called()


def test_complete_multi_image_analysis_reconciles_strict_binding_without_model_retry(workspace):
    registry, assets, args = setup(workspace, ('identity', 'inspiration'))
    service = ConversationMemoryService(workspace)
    update(service, 'current', references=[{
        'deliverable_id':'*',
        'memory_ids':['asset:'+asset['id'] for asset in assets],
    }])
    # The Agent submitted only the first ID but had already inspected and
    # described every image required by the saved per-item binding. Preflight
    # can therefore repair the ID list locally without another model turn.
    submitted = deepcopy(args)
    submitted['source_asset_ids'] = [assets[0]['id']]
    with patch('urllib.request.urlopen') as transport:
        checked = preflight(registry, submitted)
    assert checked['status'] == 'ready', checked
    resolved = checked['resolvedOperations'][0]
    assert [item['assetId'] for item in resolved['references']] == [asset['id'] for asset in assets]
    assert resolved['memoryReconciliation'] == {
        'submittedAssetIds':[assets[0]['id']],
        'expectedAssetIds':[asset['id'] for asset in assets],
    }
    transport.assert_not_called()

    with patch('urllib.request.urlopen', return_value=reply()) as transport:
        result = execute(registry, submitted)
    assert result['status'] == 'succeeded'
    assert transport.call_count == 1
    resolution = result['asset']['metadata']['referenceSnapshot']['resolution']
    assert resolution['memoryReconciliation'] == resolved['memoryReconciliation']
    assert result['asset']['metadata']['sourceAssetIds'] == [asset['id'] for asset in assets]


def test_strict_binding_never_silently_drops_an_unexpected_analyzed_image(workspace):
    registry, assets, args = setup(workspace, ('identity', 'inspiration'))
    update(ConversationMemoryService(workspace), 'current', references=[{
        'deliverable_id':'*',
        'memory_ids':['asset:'+assets[0]['id']],
    }])
    rejected = preflight(registry, args)
    assert rejected['status'] == 'reference_mismatch'
    assert rejected['errors'][0]['expectedAssetIds'] == [assets[0]['id']]
    assert rejected['errors'][0]['actualAssetIds'] == [asset['id'] for asset in assets]
    assert rejected['errors'][0]['missingAssetIds'] == []
    assert rejected['errors'][0]['unexpectedAssetIds'] == [assets[1]['id']]


def test_legacy_memory_binding_remains_strict_without_migration(workspace):
    registry, assets, args = setup(workspace, ('identity', 'inspiration'))
    with workspace._connect() as db:
        context = json.loads(db.execute("SELECT input_json FROM tasks WHERE id='current'").fetchone()[0])
        for snap in context['conversationMemory']['referenceSnapshots']: snap.pop('bindingPolicy', None)
        db.execute("UPDATE tasks SET input_json=? WHERE id='current'", (json.dumps(context),))
    args['source_asset_ids'] = [assets[0]['id']]
    args['reference_analysis']['images'] = args['reference_analysis']['images'][:1]
    assert preflight(registry, args)['status'] == 'reference_mismatch'


def test_node_position_does_not_invalidate_preflight(workspace):
    registry, assets, args = setup(workspace, ('identity',))
    node = registry.canvas_store.ensure_asset_node('one', assets[0])
    args['canvas_node_id'] = node['id']
    assert preflight(registry, args)['status'] == 'ready'
    registry.canvas_store.update_node('one', node['id'], {'position':{'x':99,'y':12}})
    with patch('urllib.request.urlopen', return_value=reply()) as transport:
        assert execute(registry, args)['status'] == 'succeeded'
    assert transport.call_count == 1


@pytest.mark.parametrize('batch', [False, True])
def test_real_sdk_does_not_inject_candidates_or_need_parameter_repair(workspace, batch):
    import os
    import shutil
    import subprocess
    import sys
    registry, assets, args = setup(workspace, ('identity',))
    args.pop('output_mode')
    args.update(provider='local-placeholder', model='fixture-image')
    original = registry.canvas_store.ensure_asset_node('one', assets[0])
    target = registry.canvas_store.create_node('one', kind='image', title='新角色', data={})
    candidate = picture(workspace, 'unselected')
    context_patch(workspace, agentCollaboration=False, deliveryVerification=False,
        canvasParams={'kind':'image','canvasNodeId':target['id'],'source_asset_ids':[assets[0]['id']]},
        referenceWorkflow={'status':'selected','assetIds':[candidate['id']]})
    root = Path(__file__).resolve().parents[1]
    payload = {'api':'responses','apiKey':'fixture','model':'fixture','baseUrl':'https://image-resolution-fixture.invalid/v1',
        'context':{'projectId':'one','taskId':'current','brief':'再设计一个偏男性的情侣角色',
                   'constraints':registry._task_input('one','current')}}
    env = {**os.environ, 'PYTHONPATH':str(root), 'FIXTURE_PYTHON':sys.executable,
           'FIXTURE_WORKSPACE':str(workspace.workspace_root),'FIXTURE_PROJECT':'one',
           'FIXTURE_IMAGE_ARGS':json.dumps(args), 'FIXTURE_IMAGE_BATCH':'1' if batch else '0'}
    result = subprocess.run([shutil.which('node'), '--import', (root/'tests/fixtures/image_resolution_transport.mjs').as_uri(),
        str(root/'app/openai_agent_worker.mjs')], input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr+result.stdout[-6500:]
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert any(e['type']=='result' for e in events)
    calls = (workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines()
    assert len(calls) == 1
    actual = json.loads(calls[0])
    assert actual['source_asset_paths'] == [assets[0]['absolutePath']]
    nodes = registry.canvas_store.load('one')['nodes']
    assert len(nodes) == 2
    assert next(n for n in nodes if n['id']==original['id']) == original
    assert next(n for n in nodes if n['id']==target['id'])['data']['assetId'] != assets[0]['id']


def test_refreshing_selected_candidates_does_not_downgrade_required_bindings(workspace):
    registry, assets, args = setup(workspace, ('identity', 'inspiration'))
    service = ConversationMemoryService(workspace)
    selected = ['asset:'+a['id'] for a in assets]
    update(service, 'current', references=[{'deliverable_id':'*','memory_ids':selected}])
    refreshed = update(service, 'current', selected=selected)
    assert refreshed['state']['referenceSnapshots'][0].get('bindingPolicy') != 'candidates'
    args['source_asset_ids'] = [assets[0]['id']]
    args['reference_analysis']['images'] = args['reference_analysis']['images'][:1]
    assert preflight(registry, args)['status'] == 'reference_mismatch'
