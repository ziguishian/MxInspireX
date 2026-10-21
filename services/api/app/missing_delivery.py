"""Explicit, server-validated continuation of missing planned deliverables."""
import copy
import json
from .design_batches import observe, set_progress


def prepare_missing(store, project_id, source_id, inputs):
    with store._connect() as db:
        source = db.execute('SELECT * FROM tasks WHERE id=? AND project_id=? AND superseded_by IS NULL', (source_id, project_id)).fetchone()
        if source is None or source['status'] not in {'succeeded', 'failed'}:
            raise ValueError('原任务不存在或尚未结束，请先核对原请求')
        active = db.execute("SELECT 1 FROM tasks WHERE project_id=? AND superseded_by IS NULL AND status IN ('running','queued')", (project_id,)).fetchone()
        if active: raise ValueError('项目仍有任务执行中，请等待完成后补齐')
        receipts = db.execute('SELECT status,output FROM tool_receipts WHERE task_id=?', (source_id,)).fetchall()
    for receipt in receipts:
        value = json.loads(receipt['output'] or '{}')
        if receipt['status'] == 'running' or value.get('status') == 'generation_unconfirmed' or value.get('billingCertainty') == 'unknown':
            raise ValueError('原请求结果尚未确认，请先核对原请求、产物和计费；不能直接补齐')
    previous = json.loads(source['input_json'])
    plan = previous.get('designPlan') or previous.get('planBaseline')
    if not plan or not plan.get('ready'): raise ValueError('原任务没有就绪的交付清单，请在对话中明确要补齐的内容')
    rows = observe(store, project_id, source_id, {**previous, 'designPlan': plan}, json.loads(source['output_json'] or '{}'))
    scope = (previous.get('designBatch') or {}).get('itemIds') or [item['id'] for item in plan['deliverables']]
    missing = [row['id'] for row in rows if row['id'] in scope and row['status'] not in {'ready', 'passed', 'needs_review'}]
    if not missing: raise ValueError('原计划产物均已保存；如有质量问题，请使用对应产物的修改建议')
    for key in ('referencedAssets', 'referencedNodes', 'referencedFiles', 'canvasParams', 'imageStyle', 'referenceWorkflow', 'requiredArtifacts', 'deliveryContract'):
        if key in previous: inputs[key] = copy.deepcopy(previous[key])
        else: inputs.pop(key, None)
    inputs['missingDeliveryOnly'] = {'sourceTaskId': source_id, 'itemIds': missing}
    return source


def constrain_missing(inputs):
    policy = inputs.get('missingDeliveryOnly')
    if not policy: return
    batch = inputs.get('designBatch')
    if not batch or not inputs.get('designPlan'): raise ValueError('原交付计划无法恢复，请核对原任务')
    batch.update(intent='resume', status='ready', itemIds=policy['itemIds'])
    inputs['designPlan']['currentItemIds'] = policy['itemIds']
    set_progress(inputs, inputs.get('deliveryProgress') or [])
