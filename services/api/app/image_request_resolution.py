"""Resolve image inputs and destinations without asking the model to wire nodes.

Preflight and dispatch share this resolver. Receipt keys always use the caller's
original arguments; the derived request and version checks are not idempotency keys.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .asset_identity import asset_id
from .node_context import fingerprint, check_canvas_inputs

IMAGE_TOOLS = {'generate_image', 'image_edit'}


class ImageRequestError(ValueError):
    def __init__(self, message, *, code='reference_mismatch', field='source_asset_ids', asset_ids=(), node_ids=()):
        super().__init__(message)
        self.code, self.field = code, field
        self.asset_ids, self.node_ids = list(asset_ids), list(node_ids)


def error_result(name, error, operation_index=None):
    detail = {'field': getattr(error, 'field', 'reference_analysis' if getattr(error, 'code', '') == 'reference_analysis_required' else 'references'),
              'assetIds': getattr(error, 'asset_ids', []), 'nodeIds': getattr(error, 'node_ids', []), 'message': str(error)}
    if isinstance(getattr(error, 'details', None), dict):
        detail.update(error.details)
    if operation_index is not None:
        detail['operationIndex'] = operation_index
    issues = getattr(error, 'issues', None)
    errors = [{**detail, **issue} for issue in issues] if issues else [detail]
    return {'tool': name, 'status': getattr(error, 'code', 'reference_mismatch'), 'instruction': str(error), 'errors': errors, 'submitted': False}


def node_asset(node):
    data = node.get('data') or {}
    return data.get('assetId') or (data.get('asset') or {}).get('id')


def normalize_image_request(registry, project_id, task_id, name, arguments, binding=None):
    """Resolve deterministic fields only; no writes, semantic guesses or models."""
    from .design_tools import image_reference_ids
    from .generation_inputs import planned_inputs
    from .task_focus import TaskFocus
    args = deepcopy(arguments or {})
    context = registry._task_input(project_id, task_id) if task_id else {}
    nodes = registry.canvas_store.load(project_id)['nodes']
    board = {n['id']: n for n in nodes}
    canvas = context.get('canvasParams') or {}
    canvas_task = context.get('taskSurface') == 'canvas_node'
    try:
        check_canvas_inputs(registry.store, registry.canvas_store, project_id, task_id, context)
    except ValueError as error:
        raise ImageRequestError(str(error), code='reference_changed', field='reference_node_ids') from error
    canvas_target = canvas.get('canvasNodeId') if canvas.get('kind') == 'image' else None
    target = args.get('canvas_node_id')
    if args.get('output_mode') not in (None, 'create', 'edit'):
        raise ImageRequestError('output_mode 必须为 edit 或 create', field='output_mode')
    if target and canvas_target and target != canvas_target:
        raise ImageRequestError('输出位置与当前画布输入节点冲突，请刷新引用后重试。', field='canvas_node_id', node_ids=[target, canvas_target])
    target = canvas_target or target
    declared_reference_nodes = [r.get('id') or r.get('nodeId') for r in context.get('referencedNodes', [])
                                if isinstance(r, dict) and r.get('projectId', project_id) == project_id]
    declared_reference_nodes += list(canvas.get('reference_node_ids') or [])
    if canvas_task and target and target in declared_reference_nodes:
        raise ImageRequestError('输出节点不能同时引用自己。请断开自连线，并仅使用直接连入的上游节点。',
                                code='self_reference_not_allowed', field='reference_node_ids', node_ids=[target])
    origins = {}
    source_nodes = []
    sources = []

    def add(identity, origin):
        identity = asset_id(identity)
        if not isinstance(identity, str) or not identity or identity.startswith(('node:', '@node:')):
            raise ImageRequestError('来源必须为图像资产 ID；节点请通过 canvas_node_id 指定，不能混填。', asset_ids=[identity])
        if identity not in sources:
            sources.append(identity)
        origins.setdefault(identity, [])
        if origin not in origins[identity]:
            origins[identity].append(origin)

    if target:
        node = board.get(target)
        if not node or node.get('data', {}).get('kind') != 'image':
            raise ImageRequestError('图像节点不存在、不属于当前项目或不是图像节点。', field='canvas_node_id', node_ids=[target])
        saved = node.get('data', {}).get('deliveryBinding', {})
        batch, plan = context.get('designBatch') or {}, context.get('designPlan') or {}
        if batch and saved.get('scopeId') == plan.get('scopeId') and not set(saved.get('itemIds', [])).issubset(batch.get('itemIds', [])):
            raise ImageRequestError('目标节点属于其他批次；作为新项参考请使用 source_asset_ids，修改旧项需先登记修改批次。', code='batch_scope_required', field='canvas_node_id', node_ids=[target])
        target_data = node.get('data') or {}
        target_has_content = bool(node_asset(node) or target_data.get('localFile') or target_data.get('job') or target_data.get('cad') or
                                  target_data.get('imageAssetIds') or str(target_data.get('text') or '').strip() or
                                  str(target_data.get('summary') or '').strip() or str(target_data.get('html') or '').strip())
        if canvas_task and target_has_content:
            raise ImageRequestError('已有内容的节点不能作为输出目标。请新建空白节点，将当前节点连线到新节点后生成。',
                                    code='self_reference_not_allowed', field='canvas_node_id',
                                    asset_ids=[node_asset(node)] if node_asset(node) else [], node_ids=[target])
        if not canvas_task:
            source_nodes.append(target)
        original = node_asset(node)
        if original:
            if canvas_task:
                raise ImageRequestError('已有内容的节点不能作为输出目标或引用自身资产。请新建空白节点，将它连接到新节点后生成。',
                                        code='self_reference_not_allowed', field='canvas_node_id', asset_ids=[original], node_ids=[target])
            if name == 'image_edit' and args.get('asset_id') and asset_id(args['asset_id']) != original:
                raise ImageRequestError('image_edit.asset_id 与指定原图节点不一致。', field='asset_id', asset_ids=[asset_id(args['asset_id']), original], node_ids=[target])
            add(original, 'source_node')
            if name == 'image_edit':
                args['asset_id'] = original
            args.pop('canvas_node_id', None)
        elif target == canvas_target and not any(node.get('data', {}).get(k) for k in ('asset', 'text', 'html')):
            args['canvas_node_id'] = target
        else:
            raise ImageRequestError('只能填充当前画布输入的空白图像节点。', field='canvas_node_id', node_ids=[target])
    if name == 'image_edit':
        if not args.get('asset_id'):
            raise ImageRequestError('请明确 image_edit.asset_id 原图。', field='asset_id')
        args['asset_id'] = asset_id(args['asset_id'])
        add(args['asset_id'], 'explicit')
    for identity in image_reference_ids(args.get('source_asset_id'), args.get('source_asset_ids')):
        add(identity, 'explicit')
    if canvas_target:
        for identity in image_reference_ids(canvas.get('source_asset_id'), canvas.get('source_asset_ids')):
            add(identity, 'canvas')
    target_asset = node_asset(board.get(target, {})) if target else None
    if canvas_task and target_asset and target_asset in sources:
        raise ImageRequestError('输出节点的当前资产不能出现在它自己的来源列表中。',
                                code='self_reference_not_allowed', field='source_asset_ids', asset_ids=[target_asset], node_ids=[target])
    ids = args.get('deliverable_ids')
    if ids is None:
        ids = (binding or {}).get('itemIds')
    if ids is None:
        saved = board.get(target, {}).get('data', {}).get('deliveryBinding', {})
        plan = context.get('designPlan') or {}
        ids = saved.get('itemIds') if saved.get('scopeId') == plan.get('scopeId') else None
        if ids is None:
            matches = [d['id'] for d in plan.get('deliverables', []) if d['kind'] == 'image'
                       and (not context.get('designBatch') or d['id'] in context['designBatch'].get('itemIds', []))]
            ids = matches if len(matches) == 1 else []
    if args.get('deliverable_ids') is None and ids:
        args['deliverable_ids'] = ids
    if name == 'generate_image':
        for ref in planned_inputs(context, ids):
            if ref['source'] == 'asset':
                add(ref['id'], 'plan')
    # Selection and recall are candidates. Only this item's chosen sources,
    # plan inputs and explicit canvas inputs become provider references.
    # Selection notes remain in task context and the reference snapshot. The
    # Agent translates them into visible choices, never asset IDs in the prompt.
    if name == 'image_edit' and args.get('operation') != 'inpaint' and set(sources) != {args['asset_id']}:
        raise ImageRequestError('本地图像操作只处理 asset_id 指定的原图，不接受其他图像来源。', field='source_asset_ids', asset_ids=sources)
    # Track only referenced nodes whose image is actually consumed, plus the
    # explicit output/source node. Unrelated canvas movement is not a change.
    declared_nodes = [r.get('id') or r.get('nodeId') for r in context.get('referencedNodes', []) if r.get('projectId', project_id) == project_id]
    declared_nodes += [r.get('nodeId') for r in context.get('referencedAssets', []) if r.get('projectId', project_id) == project_id]
    canvas_nodes = canvas.get('reference_node_ids') or []
    declared_nodes += canvas_nodes
    for identity in declared_nodes:
        if identity in board and (node_asset(board[identity]) in sources or (canvas_target and identity in canvas_nodes and board[identity].get('data', {}).get('kind') in {'text','html'})) and identity not in source_nodes:
            source_nodes.append(identity)
    if (arguments or {}).get('output_mode') == 'edit' and not sources:
        raise ImageRequestError('编辑图片必须明确原图来源，不能退回纯文字生成。', field='source_asset_ids')
    # Composer references are inputs, not in-place canvas targets. Image work
    # always preserves sources and resolves to a newly created output node.
    args['output_mode'] = 'create'
    args['source_asset_id'] = sources[0] if sources else None
    args['source_asset_ids'] = sources
    # Normalize mention syntax in analysis too, without deriving its content.
    analysis = args.get('reference_analysis')
    if isinstance(analysis, dict) and isinstance(analysis.get('images'), list):
        for entry in analysis['images']:
            if isinstance(entry, dict):
                entry['asset_id'] = asset_id(entry.get('asset_id'))
    mask = (args.get('params') or {}).get('maskAssetId')
    if mask:
        args['params']['maskAssetId'] = asset_id(mask)
    if task_id:
        TaskFocus(registry.store, registry.canvas_store).validate_ids(project_id, task_id, context,
            node_ids=source_nodes, asset_ids=[*sources, *([asset_id(mask)] if mask else [])])
    args['_image_resolution'] = {'origins': origins, 'sourceNodeIds': source_nodes}
    return args


def prepare_image_request(registry, project_id, task_id, name, arguments, binding=None, *, preflight=False):
    """Resolve references, dependencies and versions for both execution paths."""
    from .conversation_memory import ConversationMemoryService
    from .generation_inputs import bind_generation_inputs, planned_inputs
    from .visual_series import bind_visual_series
    from .image_reference_design import prepare_reference_design, drawing_reference_ids, compile_design_spec
    args = normalize_image_request(registry, project_id, task_id, name, arguments, binding)
    context = registry._task_input(project_id, task_id) if task_id else {}
    nodes = registry.canvas_store.load(project_id)['nodes']
    binding = binding or {}
    pending = []
    is_generation = name == 'generate_image'
    is_inpaint = name == 'image_edit' and args.get('operation') == 'inpaint'
    if is_generation or is_inpaint:
        # Validate the item's declared memory selection before resolving future
        # deliverables, which have not existed when that selection was made.
        args['_reference_snapshot'] = ConversationMemoryService(registry.store).validate_generation(project_id, task_id, args, freeze=not preflight)
    direction = context.get('referenceWorkflow') or {}
    selected_choices = [c for c in direction.get('choices', []) if c.get('assetId') in args['source_asset_ids']]
    selection_id = hashlib.sha256(json.dumps([(args.get('_reference_snapshot') or {}).get('id'), selected_choices,
        direction.get('notes') if selected_choices else None], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if is_generation:
        scope = (context.get('designPlan') or {}).get('scopeId')
        for ref in planned_inputs(context, binding.get('itemIds', args.get('deliverable_ids') or [])):
            if ref['source'] != 'deliverable':
                continue
            selected = [n for n in nodes if n.get('data', {}).get('deliveryBinding', {}).get('scopeId') == scope
                        and ref['id'] in n['data']['deliveryBinding'].get('itemIds', [])]
            if not selected or any(n['data'].get('generating') or n['data'].get('error') for n in selected):
                pending.append(ref['id'])
        if pending and not preflight:
            raise ImageRequestError('前置产物尚未完成：' + '、'.join(pending), code='dependency_required', field='deliverable_ids')
        args = bind_generation_inputs(context, binding, args, nodes, registry.asset_store, project_id, deferred_ids=pending)
        args = bind_visual_series(context, binding, args, nodes, registry.asset_store, project_id)
    if is_generation:
        args = compile_design_spec(context, binding, args)
    intents = []
    corrections = []
    if is_generation or is_inpaint:
        from .image_intent import canonicalize_reference_modes, derive_image_intents
        intents = derive_image_intents(context, args['source_asset_ids'],
            asset_lookup=lambda identity: registry.asset_store.get_asset(project_id=project_id, asset_id=identity) if registry.asset_store else None)
        normalized_analysis, corrections = canonicalize_reference_modes(intents, args.get('reference_analysis'))
        from .product_identity import bind_identity_analysis
        args['reference_analysis'] = bind_identity_analysis(normalized_analysis, args.get('_reference_snapshot') or {}, intents)
    refs = []
    origins = args['_image_resolution']['origins']
    modes = {r.get('asset_id'): r.get('mode') for r in (args.get('reference_analysis') or {}).get('images', []) if isinstance(r, dict)} if isinstance(args.get('reference_analysis'), dict) else {}
    roles = {}
    snapshot = args.get('_reference_snapshot') or {}
    source_nodes = set(args['_image_resolution']['sourceNodeIds'])
    for ref in snapshot.get('inputBindings', []):
        source_nodes.update(ref.get('nodeIds', []))
        for identity in ref.get('assetIds', []):
            roles.setdefault(identity, set()).add(ref.get('role'))
            origins.setdefault(identity, [])
            if 'plan' not in origins[identity]: origins[identity].append('plan')
    for identity, uses in roles.items():
        semantic = uses.intersection({'identity', 'layout', 'edit', 'inspiration'})
        # Identity + layout can be satisfied by preserving both; inspiration
        # conflicts with every requirement that actually preserves pixels.
        if ('inspiration' in semantic and len(semantic) > 1) or ('edit' in semantic and 'identity' in semantic):
            raise ImageRequestError('同一参考的计划用途冲突，请明确本项用途。', field='reference_analysis', asset_ids=[identity])
        declared = modes.get(identity)
        if declared and ((declared == 'inspiration' and semantic.intersection({'identity','layout','edit'}))
                         or ('inspiration' in semantic and declared != 'inspiration')
                         or ('edit' in semantic and declared != 'edit')):
            raise ImageRequestError('参考分析与计划中的保留用途冲突。', code='reference_analysis_required', field='reference_analysis', asset_ids=[identity])
    assets_to_check = list(args['source_asset_ids'])
    visual_previews = []
    mask = (args.get('params') or {}).get('maskAssetId')
    if mask and mask not in assets_to_check: assets_to_check.append(mask)
    for identity in assets_to_check:
        asset = registry.asset_store.get_asset(project_id=project_id, asset_id=identity) if registry.asset_store else None
        if not asset or asset.get('kind') != 'image' or asset.get('mime') == 'image/svg+xml':
            raise ImageRequestError('引用必须是当前项目内的可用图像资产：' + str(identity), asset_ids=[identity])
        path = Path(asset['absolutePath'])
        content = path.read_bytes() if path.is_file() else b''
        if not content or hashlib.sha256(content).hexdigest() != asset['sha256']:
            raise ImageRequestError('引用文件缺失或内容已变化：' + identity, code='reference_missing', asset_ids=[identity])
        if identity != mask:
            from .vision_preview import make_vision_preview
            preview = make_vision_preview(content)
            visual_previews.append({
                'assetId': identity,
                'status': 'ready' if preview else 'omitted',
                **({key: preview[key] for key in ('mime', 'width', 'height', 'originalWidth', 'originalHeight', 'byteSize', 'originalByteSize')} if preview else {'originalByteSize': len(content)}),
            })
        refs.append({'assetId': identity, 'sha256': asset['sha256'], 'mode': 'mask' if identity == mask else modes.get(identity),
                     'origins': origins.get(identity, ['mask'])})
    reconciliation = (args.get('_image_resolution') or {}).get('memoryReconciliation')
    summary = {'references': refs, 'nodeVersions': {n['id']: fingerprint(n) for n in nodes if n['id'] in source_nodes},
               'output': {'mode': 'create', 'nodeId': args.get('canvas_node_id')}, 'binding': binding, 'pendingDependencies': list(dict.fromkeys(pending)), 'referenceSelectionId': selection_id,
               'agentVisualPreviews': visual_previews}
    if args.get('_design_spec'):
        summary['designSpec'] = args['_design_spec']
    if reconciliation:
        summary['memoryReconciliation'] = reconciliation
    args['_image_resolution'] = summary
    if is_generation or is_inpaint:
        prompt = args.get('prompt', '') if is_generation else (args.get('params') or {}).get('prompt', '')
        summary['referenceIntents'] = intents
        summary['referenceModeCorrections'] = corrections
        # This check is shared with dispatch, before any placeholder or paid call.
        _, designed, pixels = prepare_reference_design(prompt, args['source_asset_ids'], args.get('reference_analysis'), snapshot,
            required=bool(context.get('memoryProtocol')), masked_edit=bool(mask),
            layout_source_ids=drawing_reference_ids(registry.asset_store, project_id, args['source_asset_ids']))
        applied = {r['asset_id']:r['mode'] for r in designed.get('analysis', {}).get('images', [])}
        for ref in refs:
            if ref['mode'] != 'mask': ref['mode'] = applied.get(ref['assetId'], ref['mode'])
        summary['providerInputAssetIds'] = pixels
        summary['providerInputKind'] = 'original_assets'
        for intent in intents:
            intent['actualMode'] = applied.get(intent['assetId'])
            intent['providerInput'] = intent['assetId'] in pixels
        args['_reference_snapshot'] = {**snapshot, 'resolution': summary}
    return args


def preflight_key(task_id, name, original):
    data = json.dumps([task_id, name, original], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'image-preflight:' + hashlib.sha256(data.encode()).hexdigest()


def save_preflights(registry, task_id, records):
    if not task_id: return
    from .conversation_memory import ConversationMemoryService
    ConversationMemoryService(registry.store)
    # Existing snapshot storage is durable across worker/API restarts. Save only
    # after the entire group's validation passes, never alongside a paid call.
    with registry.store._connect() as db:
        for name, original, summary in records:
            db.execute('INSERT OR REPLACE INTO conversation_reference_snapshots VALUES(?,?,?)',
                (preflight_key(task_id, name, original), task_id, json.dumps({'kind':'image-preflight', 'resolution':summary}, ensure_ascii=False)))


def check_preflight(registry, project_id, task_id, name, original, resolved):
    if not task_id: return
    with registry.store._connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_reference_snapshots'").fetchone(): return
        row = db.execute('SELECT body FROM conversation_reference_snapshots WHERE id=? AND task_id=?',
                         (preflight_key(task_id, name, original), task_id)).fetchone()
    if not row: return  # Historical/direct calls still run the same validation.
    prior = json.loads(row[0])['resolution']
    current = resolved['_image_resolution']
    board = {n['id']: n for n in registry.canvas_store.load(project_id)['nodes']}
    changed = [identity for identity, version in prior['nodeVersions'].items()
               if identity not in board or fingerprint(board[identity]) != version]
    old_refs = {r['assetId']: r['sha256'] for r in prior['references']}
    new_refs = {r['assetId']: r['sha256'] for r in current['references']}
    mismatched = [identity for identity, sha in old_refs.items() if new_refs.get(identity) != sha]
    if (changed or mismatched or prior['output'] != current['output'] or prior['binding'] != current['binding']
            or prior.get('referenceSelectionId') != current.get('referenceSelectionId')
            or (not prior['pendingDependencies'] and old_refs != new_refs)):
        raise ImageRequestError('预检后的引用、输出位置或交付版本已变化，请刷新引用并重新预检。', code='reference_changed',
                                field='references', asset_ids=mismatched, node_ids=changed)


def preflight_images(registry, project_id, task_id, arguments):
    from .deliverable_tracking import assign_delivery
    from .image_reference_design import prepare_reference_design, drawing_reference_ids
    from .image_output import prepare_image_output
    context = registry._task_input(project_id, task_id) if task_id else {}
    operations = arguments.get('operations', [])
    ready_ids = {r['id'] for r in context.get('deliveryProgress', []) if r['status'] in {'ready', 'passed', 'needs_review'}}
    ready_ids.update(identity for op in operations for identity in (op.get('arguments') or {}).get('deliverable_ids', []))
    snapshots, requests, resolutions, records, failures = [], [], [], [], []
    for index, operation in enumerate(operations):
        name, original = operation.get('tool'), operation.get('arguments') or {}
        try:
            args = normalize_image_request(registry, project_id, task_id, name, original) if name in IMAGE_TOOLS else original
            binding, blocked = assign_delivery(context, name, args, registry.canvas_store.load(project_id)['nodes'], ready_ids)
            if blocked:
                failures.append({'tool':'generation_reference_check', **blocked, 'submitted':False, 'errors':[{'operationIndex':index, 'field':'deliverable_ids', 'message':blocked['instruction']}]})
                continue
            if context.get('designBatch') and binding and not set(binding['itemIds']).issubset(context['designBatch']['itemIds']):
                raise ImageRequestError('批量生成只提交本批 itemIds，累计旧项保留。', code='batch_scope_required', field='deliverable_ids')
            if name not in IMAGE_TOOLS: continue
            args = prepare_image_request(registry, project_id, task_id, name, original, binding, preflight=True)
            summary = args['_image_resolution']
            resolutions.append({'operationIndex':index, **summary})
            records.append((name, original, summary))
            if name != 'generate_image': continue
            prompt, snapshot, pixels = prepare_reference_design(args.get('prompt', ''), args['source_asset_ids'], args.get('reference_analysis'),
                args['_reference_snapshot'], required=bool(context.get('memoryProtocol')),
                masked_edit=bool((args.get('params') or {}).get('maskAssetId')),
                layout_source_ids=drawing_reference_ids(registry.asset_store, project_id, args['source_asset_ids']))
            _, options = prepare_image_output(prompt, args.get('params') or {}, background=args.get('background'))
            provider, _, route, candidates = registry._image_configurations(project_id=project_id, task_id=task_id,
                provider=args.get('provider'), model=args.get('model'), params=options, quality=args.get('quality'),
                has_references=bool(pixels), reference_count=len(pixels), prompt=prompt)
            candidate = candidates[0]
            snapshots.append(snapshot)
            requests.append({'deliverableIds':args.get('deliverable_ids', []), 'provider':provider, 'model':candidate.model,
                'routeMode':route['mode'], 'primaryModel':route['primaryModel'], 'candidateModels':route['candidateModels'],
                'api':getattr(candidate.adapter, 'api', 'images'), 'providerInputAssetIds':pixels,
                'parameterAdjustments':candidate.adjustments,
                'params':{k:v for k,v in candidate.options.items() if k in {'size','aspectRatio','aspect_ratio','resolution','quality'}}})
        except (ValueError, RuntimeError) as error:
            failures.append(error_result('generation_reference_check', error, index))
    if failures:
        return {**failures[0], 'submitted':False, 'errors':[error for failure in failures for error in failure['errors']]}
    save_preflights(registry, task_id, records)
    return {'tool':'generation_reference_check', 'status':'ready', 'snapshots':snapshots, 'imageRequests':requests, 'resolvedOperations':resolutions}
