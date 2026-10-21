"""Read-only request inspection; never reconcile, replay, or call providers."""
import json
from .credit_reporting import observed_tokens, estimated_cost_cny
from .evolink_billing import has_reported_cost


def performance_summary(store, task):
    """Observed calls only. Route attempts wrapping a whole Agent are not calls."""
    with store._connect() as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = db.execute('SELECT data_json FROM model_call_trace WHERE task_id=? ORDER BY created_at,rowid', (task['id'],)).fetchall() if 'model_call_trace' in tables else []
        saved = db.execute('SELECT payload FROM agent_checkpoints WHERE task_id=?', (task['id'],)).fetchone() if 'agent_checkpoints' in tables else None
    checkpoint = json.loads(saved[0]) if saved else {}
    metrics = (task.get('output') or {}).get('provenance', {}).get('performance') or checkpoint.get('performance')
    calls = [json.loads(row[0]) for row in rows]
    images = {}
    for index, call in enumerate(calls):
        if call.get('call_kind') != 'image_generation' or not call.get('submitted'):
            continue
        key = (call.get('fingerprint') or call.get('started_at') or index, call.get('provider'), call.get('model'))
        images[key] = call
    extra_text = [c for c in calls if c.get('call_kind') in {'generate_text', 'web_search'} and c.get('submitted')]
    usage = [c for c in calls if c.get('call_kind') == 'sdk_response'] or [entry.get('data', {}) for entry in task.get('trace', []) if entry.get('phase') == 'model_call']
    def tokens(field):
        return sum(u[field] for u in usage) if usage and all(isinstance(u.get(field), (int, float)) for u in usage) else None
    def total(values):
        return sum(values) if values else None
    local = [c for c in calls if c.get('call_kind') == 'runtime_timing']
    # Include uploads failing before submission, deduplicate each route attempt.
    media = {}
    for index, call in enumerate(calls):
        if call.get('call_kind') == 'image_generation' and isinstance(call.get('timingMs'), dict):
            media[(call.get('fingerprint') or call.get('started_at') or index, call.get('provider'), call.get('model'))] = call
    timing = {phase:total([c['latency_ms'] for c in local if c.get('phase') == phase and isinstance(c.get('latency_ms'), (int,float))])
              for phase in ('contextPreparationMs','imagePreflightMs','assetSaveMs')}
    prepared = metrics.get('contextPreparationMs') if metrics else None
    if isinstance(prepared, (int,float)):
        timing['contextPreparationMs'] = (timing['contextPreparationMs'] or 0) + prepared
    timing['textModelMs'] = total([c['latency_ms'] for c in usage if isinstance(c.get('latency_ms'), (int,float))])
    for phase in ('referenceUploadMs','providerSubmitMs','providerWaitMs','observedQueueMs','observedProcessingMs','resultDownloadMs'):
        timing[phase] = total([c['timingMs'][phase] for c in media.values() if isinstance(c['timingMs'].get(phase), (int,float))])
    return {
        'sdkRequests': metrics.get('sdkRequests') if metrics else None,
        'completedResponses': metrics.get('completedResponses', checkpoint.get('responseCount')) if metrics else None,
        'additionalTextRequests': len(extra_text) if metrics else None,
        'imageRequests': len(images) if images else None,
        'inputTokens': tokens('inputTokens'), 'outputTokens': tokens('outputTokens'),
        'usageScope': 'sdk_responses',
        'stageMs': metrics.get('stageMs') if metrics else None,
        'firstArtifactMs': metrics.get('firstArtifactMs') if metrics else None,
        'timingMs': timing,
        'referenceUploadCacheHits': total([c['referenceUploadCacheHits'] for c in media.values() if isinstance(c.get('referenceUploadCacheHits'), int)]),
        'timingNote': '各阶段为累计实测耗时，并行任务不可直接相加。排队/处理按查询到的服务商状态估计，包含在服务商等待内，不代表上游精确生成时长；未观测为 —。',
        'coverage': metrics.get('coverage', 'partial') if metrics else 'legacy_unknown',
        'note': '只统计已观测记录；SDK 请求含未确认结果，图片按提交标识去重。主 Agent 路由记录不重复计数，缺少统计为 null。',
    }


def inspect_task(store, billing, canvas_store, project_id, task):
    receipts = []
    node_ids, asset_ids = set(), set()
    with store._connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='tool_receipts'").fetchone()
        rows = db.execute("SELECT name,status,output,updated_at FROM tool_receipts WHERE task_id=? ORDER BY updated_at", (task['id'],)).fetchall() if exists else []
    for row in rows:
        result = json.loads(row['output'] or '{}')
        # Return only identifiers and receipt state, never tool arguments or raw responses.
        node = result.get('node') or {}
        asset = result.get('asset') or {}
        if node.get('id'): node_ids.add(node['id'])
        if result.get('assetId') or asset.get('id'): asset_ids.add(result.get('assetId') or asset['id'])
        job = result.get('job') or {}
        if (job.get('metadata') or {}).get('canvasNodeId'):
            node_ids.add(job['metadata']['canvasNodeId'])
        receipts.append({'tool': row['name'], 'status': row['status'], 'resultStatus': result.get('status'), 'updatedAt': row['updated_at']})
    data = (task.get('output') or {}).get('structured_data') or {}
    node_ids.update(data.get('createdNodeIds') or [])
    node_ids.update(item.get('nodeId') for item in data.get('deliveryProgress', []) if item.get('nodeId'))
    # Async media receipts may only contain a job; final local delivery owns the saved identifiers.
    for item in (data.get('delivery') or {}).get('artifacts', []):
        if item.get('nodeId'): node_ids.add(item['nodeId'])
        if item.get('assetId'): asset_ids.add(item['assetId'])
    board = canvas_store.load(project_id)
    nodes = [node for node in board.get('nodes', []) if node['id'] in node_ids or node.get('data', {}).get('assetId') in asset_ids or node.get('data', {}).get('taskId') == task['id']]
    with billing._connect() as db:
        rows = db.execute('SELECT data_json,created_at FROM credit_ledger WHERE project_id=? AND task_id=? ORDER BY created_at', (project_id, task['id'])).fetchall()
    ledger = []
    for row in rows:
        entry = json.loads(row['data_json'])
        _, _, tokens, missing = observed_tokens(entry.get('usage') or {}, entry.get('kind'))
        estimate = estimated_cost_cny(entry)
        ledger.append({**{key: entry.get(key) for key in ('id', 'provider', 'model', 'kind', 'providerTaskId', 'providerRequestId', 'reconciliation')},
                       'status': 'confirmed' if has_reported_cost(entry) else 'pending',
                       'costCny': entry.get('costCny') if has_reported_cost(entry) else None,
                       'totalTokens': tokens, 'tokenUnreported': int(missing),
                       'estimatedCostCny': float(estimate) if estimate is not None else None, 'createdAt': row['created_at']})
    return {'task': task, 'nodes': nodes, 'receipts': receipts, 'billing': ledger, 'performance': performance_summary(store, task),
            'billingNote': '本地账本不是服务商账单。缺少记录或金额待核算均不能证明未收费；结果不确定时请核对服务商后台的请求和账单。'}
