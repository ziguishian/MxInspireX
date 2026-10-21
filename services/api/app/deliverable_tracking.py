"""Associate planned deliverables with real, versioned canvas outputs."""

CREATORS = {'generate_image': 'image', 'generate_video': 'video', 'generate_audio': 'audio', 'generate_3d': '3d', 'generate_cad': 'cad',
            'generate_text': 'text', 'canvas_create_text': 'text', 'canvas_create_html': 'html', 'canvas_create_svg': 'image'}


def assign_delivery(context, name, args, nodes, ready_ids=()):
    plan = context.get('designPlan') or {}
    items = {d['id']: d for d in plan.get('deliverables', [])}
    if not items: return {}, None
    target = args.get('canvas_node_id') or args.get('node_id')
    node = next((n for n in nodes if n['id'] == target), {})
    kind = CREATORS.get(name) or node.get('data', {}).get('kind')
    if name not in CREATORS and name != 'canvas_update_node': return {}, None
    ids = args.get('deliverable_ids')
    batch = context.get('designBatch') or {}
    target_binding = node.get('data', {}).get('deliveryBinding', {})
    if batch and target and target_binding.get('scopeId') == plan.get('scopeId'):
        if not set(target_binding.get('itemIds', [])).issubset(batch.get('itemIds', [])):
            return {}, {'status': 'batch_scope_required', 'instruction': '目标节点属于其他批次。请新建本批产物；修改旧节点需先登记为本轮修改项。'}
    if ids is None:
        binding = node.get('data', {}).get('deliveryBinding', {})
        ids = [i for i in binding.get('itemIds', []) if i in items] if binding.get('scopeId') == plan.get('scopeId') else []
        if not ids:
            matching = [d['id'] for d in items.values() if d['kind'] == kind and (not batch or d['id'] in batch.get('itemIds', []))]
            if len(matching) > 1:
                return {}, {'status': 'delivery_assignment_required', 'instruction': '本轮有多个同类型交付项，请用 deliverable_ids 指定本次实际覆盖的项，不能凭类型存在判定全部完成。', 'deliverables': list(items.values())}
            ids = matching
    if not isinstance(ids, list) or any(i not in items or items[i]['kind'] != kind for i in ids):
        return {}, {'status': 'delivery_assignment_required', 'instruction': 'deliverable_ids 必须对应当前计划中相同类型的交付项。'}
    if batch and not ids and kind != 'text':
        return {}, {'status': 'delivery_assignment_required', 'instruction': '请指定本批实际交付的 deliverable_ids；新增物料先登记到 design_plan，不能用空列表跳过批次校验。'}
    decisions = context.get('designState', {}).get('decisions', {})
    blocked = [(items[i]['title'], field) for i in ids for field in items[i].get('blockingFields', []) if decisions.get(field, {}).get('status') != 'confirmed']
    if blocked:
        return {}, {'status': 'dependency_required', 'instruction': '这些交付项缺少必要条件；先推进其他不受影响的项，不要重问已回答的基础问题。', 'dependencies': blocked}
    prerequisites = {dep for item in ids for dep in items[item].get('dependsOn', []) if dep not in ready_ids}
    if prerequisites:
        return {}, {'status': 'dependency_required', 'instruction': '先等待这些前置交付成功，再读取真实产物作为输入。其他无依赖图片可继续并行生成；不要猜测上游资产 ID。',
                    'dependencies': [{'id': dep, 'title': items.get(dep, {}).get('title', dep)} for dep in sorted(prerequisites)]}
    if name == 'generate_image' and any(items[i].get('representation') in {'vector', 'model'} for i in ids):
        return {}, {'status': 'representation_required', 'instruction': '该旧交付项要求矢量或模型，不能以栅格图冒充。SVG 绘图已禁用，请说明该项未交付并继续可执行项；模型产物使用获准的 3D/CAD 工具。'}
    if name == 'canvas_create_svg' and any(items[i].get('representation') == 'raster' for i in ids):
        return {}, {'status': 'representation_required', 'instruction': '该交付项要求栅格效果图，请使用 generate_image；SVG 不能代替样机、场景渲染或插画。'}
    if not ids: return {}, None
    return {'scopeId': plan.get('scopeId'), 'itemIds': list(dict.fromkeys(ids)), 'revision': plan.get('revision', 1)}, None


def delivery_items(context, artifacts, nodes):
    plan = context.get('designPlan') or {}
    decisions = context.get('designState', {}).get('decisions', {})
    by_node = {n['id']: n for n in nodes}
    rows = []
    for item in plan.get('deliverables', []):
        matches = [a for a in artifacts if a['kind'] == item['kind'] and
                   (binding := by_node.get(a['nodeId'], {}).get('data', {}).get('deliveryBinding', {})).get('scopeId') == plan.get('scopeId')
                   and item['id'] in binding.get('itemIds', [])]
        # Old plans have no binding metadata. Only an unambiguous single item
        # and single artifact may migrate automatically; never fan one image
        # out to several promised views.
        if not matches and not plan.get('scopeId'):
            same_kind = [d for d in plan['deliverables'] if d['kind'] == item['kind']]
            candidates = [a for a in artifacts if a['kind'] == item['kind']]
            if len(same_kind) == len(candidates) == 1: matches = candidates
        missing_fields = [f for f in item.get('blockingFields', []) if decisions.get(f, {}).get('status') != 'confirmed']
        state = 'blocked' if missing_fields else 'generating' if any(by_node.get(a['nodeId'], {}).get('data', {}).get('generating') for a in matches) else 'ready' if any(a['ready'] and not by_node.get(a['nodeId'], {}).get('data', {}).get('error') for a in matches) else 'pending'
        rows.append({'id': item['id'], 'title': item['title'], 'kind': item['kind'], 'acceptance': item['acceptance'],
                     'status': state, 'nodeIds': [a['nodeId'] for a in matches], 'blockingFields': missing_fields,
                     'representation': item.get('representation', 'auto'), 'dependsOn': item.get('dependsOn', [])})
    ready_ids = {row['id'] for row in rows if row['status'] == 'ready'}
    for row in rows:
        row['blockingDeliverables'] = [dep for dep in row['dependsOn'] if dep not in ready_ids]
        if row['status'] == 'pending' and row['blockingDeliverables']: row['status'] = 'blocked'
    return rows


def record_progress(store, project_id, task_id, report):
    import json
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if not row: return
        data = json.loads(row[0])
        from .design_batches import set_progress
        set_progress(data, report.get('deliverables', []))
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data, ensure_ascii=False), task_id))
