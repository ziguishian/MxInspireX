"""Task-local batch scope, backed by real canvas outputs rather than chat claims."""
import copy
import json
import re

COMPLETE = {'ready', 'passed'}
NEXT = r'(?:下一批|下批|第二批|第三批|第[二三四五六七八九十\d]+批)'
EDIT = r'(?:修改|调整|重做|重新生成|改为|改成|改一下|改一改|把.+改)'


def explicit_batch_intent(brief):
    text = str(brief).strip()
    if re.search(EDIT, text) and re.search(r'上一批|上批|刚才|之前|原来|按计划|按原计划', text):
        return 'revise'
    if re.search(r'(?:不要|先不|不用|暂不).{0,8}' + NEXT, text):
        return 'resume'
    if re.search(NEXT, text):
        return 'next_batch'
    if re.search(r'继续.*(?:未完成|没完成|缺项)|补齐|补完|接着完成', text):
        return 'resume'
    return None


def with_evidence(context, artifacts, nodes, output=None):
    from .deliverable_tracking import delivery_items
    rows = delivery_items(context, artifacts, nodes)
    by_node = {a['nodeId']: a for a in artifacts}
    for row in rows:
        row['artifacts'] = [{k: by_node[id][k] for k in ('nodeId', 'assetId', 'fingerprint') if k in by_node[id]} for id in row['nodeIds']]
        if row['status'] == 'ready':
            row['status'] = 'passed'
    return rows


def observe(store, project_id, task_id, context, output=None):
    """Local file/content checks only; never generates or requests a preview."""
    from .delivery import DeliveryService
    service = DeliveryService(store)
    nodes = service.canvas.load(project_id)['nodes']
    scope = (context.get('designPlan') or {}).get('scopeId')
    refs = [{'entity_type': 'canvas_node', 'entity_id': n['id']} for n in nodes
            if scope and n.get('data', {}).get('deliveryBinding', {}).get('scopeId') == scope]
    report = service.inspect(project_id, task_id, refs, [], False, [])
    return with_evidence(context, report['artifacts'], nodes, output)


def set_progress(context, rows):
    context['deliveryProgress'] = rows
    batch = context.get('designBatch')
    if not batch:
        return
    current = [copy.deepcopy(r) for r in rows if r['id'] in batch.get('itemIds', [])]
    for row in current:
        original = batch.get('revisionBaseline', {}).get(row['id'])
        if batch['intent'] == 'revise' and original and original == row.get('artifacts') and row['status'] in COMPLETE:
            row.update(status='pending', issue='等待本轮修改')
    batch['currentProgress'] = current


def legacy_scope(store, project_id, source_id, context, plan):
    """Recover the most recent addition across old continuation-only turns."""
    selected, additions, seen = None, 0, set()
    with store._connect() as db:
        for _ in range(50):
            batch = context.get('designBatch') or {}
            ids = [d['id'] for d in plan.get('deliverables', [])]
            if batch:
                return selected or batch.get('itemIds') or ids, batch.get('number', 1) + additions
            seen.add(source_id)
            parent_id = (context.get('continuation') or {}).get('taskId')
            if not parent_id or parent_id in seen: break
            row = db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?', (parent_id, project_id)).fetchone()
            if not row: break
            parent = json.loads(row[0])
            parent_plan = parent.get('designPlan') or parent.get('planBaseline') or {}
            if not parent_plan or parent_plan.get('scopeId') != plan.get('scopeId'): break
            old = {d['id'] for d in parent_plan.get('deliverables', [])}
            added = [id for id in ids if id not in old]
            if added:
                selected = selected or added
                additions += 1
            source_id, context, plan = parent_id, parent, parent_plan
    return selected or plan.get('currentItemIds') or ids, 1 + additions


def prepare(store, project_id, source, previous, inputs, brief):
    plan = previous.get('designPlan') or previous.get('planBaseline')
    if not plan or not plan.get('ready'):
        return
    rows = observe(store, project_id, source['id'], {**previous, 'designPlan': plan}, json.loads(source['output_json'] or '{}'))
    prior_batch = previous.get('designBatch') or {}
    legacy_ids, legacy_number = legacy_scope(store, project_id, source['id'], previous, plan) if not prior_batch else ([], 1)
    prior_ids = prior_batch.get('itemIds') or plan.get('currentItemIds') or legacy_ids or [d['id'] for d in plan['deliverables']]
    by_id = {r['id']: r for r in rows}
    unfinished = [id for id in prior_ids if by_id.get(id, {}).get('status') not in COMPLETE]
    # An interrupted next-batch registration must stay in that transition.
    pending_transition = prior_batch.get('status') == 'needs_plan'
    suggested = plan.get('deferred', [])
    intent = explicit_batch_intent(brief)
    if intent is None:
        intent = prior_batch.get('intent') if pending_transition else 'resume' if unfinished or not suggested else 'next_batch'
    number = prior_batch.get('number', legacy_number) + (1 if intent == 'next_batch' and not pending_transition else 0)
    baseline = prior_batch.get('previousItemIds') if pending_transition else [d['id'] for d in plan['deliverables']]
    inputs['designPlan'] = copy.deepcopy(plan)
    inputs['designBatch'] = {'version': 1, 'intent': intent, 'number': number, 'sourceTaskId': source['id'],
        'status': 'needs_plan' if intent in {'next_batch', 'revise'} else 'ready',
        'previousItemIds': baseline or [], 'itemIds': [] if intent in {'next_batch', 'revise'} else prior_ids,
        'previousBatchItemIds': prior_batch.get('previousBatchItemIds', prior_ids) if pending_transition else prior_ids,
        'suggestedNext': suggested}
    inputs['continuation']['intent'] = intent
    set_progress(inputs, rows)


def register(context, plan):
    batch = copy.deepcopy(context.get('designBatch') or {'version': 1, 'intent': 'initial', 'number': 1, 'previousItemIds': []})
    all_ids = [d['id'] for d in plan['deliverables']]
    supplied = plan.get('currentItemIds') or []
    prior = set(batch.get('previousItemIds', []))
    if batch['intent'] == 'next_batch':
        ids = supplied or [id for id in all_ids if id not in prior]
        if not ids or prior.intersection(ids):
            raise ValueError('下一批需要新增交付项 ID。先把下一批建议登记为清单，currentItemIds 只列本批新增项；上一批资产会自动保留。')
    elif batch['intent'] == 'revise':
        old = {d['id']: d for d in (context.get('planBaseline') or {}).get('deliverables', [])}
        changed = [d['id'] for d in plan['deliverables'] if d['id'] in old and any(d.get(k) != old[d['id']].get(k) for k in ('title', 'acceptance', 'representation'))]
        ids = supplied or changed or batch.get('itemIds') or batch.get('previousBatchItemIds') or all_ids
        if 'revisionBaseline' not in batch:
            batch['revisionBaseline'] = {r['id']: r.get('artifacts', []) for r in context.get('deliveryProgress', []) if r['id'] in ids}
    else:
        ids = supplied or batch.get('itemIds') or all_ids
        if batch['intent'] == 'resume' and supplied:
            unfinished = {r['id'] for r in context.get('deliveryProgress', []) if r['id'] in batch.get('itemIds', []) and r['status'] not in COMPLETE}
            if not unfinished.issubset(ids):
                raise ValueError('继续未完成项时需保留本批缺项；修改范围请先依据用户明确要求选择修改任务。')
    if len(set(ids)) != len(ids) or not set(ids).issubset(all_ids):
        raise ValueError('currentItemIds 必须是不重复的本计划交付项 ID')
    plan['currentItemIds'] = ids
    batch.update(itemIds=ids, status='ready' if plan['ready'] else 'needs_plan', suggestedNext=plan.get('deferred', []))
    return batch


def instruction(context):
    batch = context.get('designBatch') or {}
    if batch.get('status') == 'needs_plan':
        return ('先调用 design_plan 登记本批计划和 currentItemIds，收到 ready 后再提交生成。'
                '制作下一批时使用新增 ID，旧项和真实资产自动保留；修改上一批图像时选择旧项，将原图作为来源并新建结果节点。')
    return '按 designBatch.itemIds 执行本批，已完成项沿用真实资产；累计清单供追溯。图像改版保留原节点并新建结果，新增交付项仍需先登记。'


def refresh(store, project_id, task_id):
    with store._connect() as db:
        row = db.execute('SELECT input_json,output_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
    if not row:
        return {}
    data = json.loads(row['input_json'])
    if not data.get('designPlan'):
        return data
    rows = observe(store, project_id, task_id, data, json.loads(row['output_json'] or '{}'))
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        latest = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()[0])
        if latest.get('designPlan') == data.get('designPlan'):
            set_progress(latest, rows)
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(latest, ensure_ascii=False), task_id))
        return latest
