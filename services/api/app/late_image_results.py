"""Reconcile saved late images without generation or another paid review."""
import json

from .delivery_findings import annotate_delivery


def sync_late_images(jobs, delivery, project_id, task_id):
    with jobs.store._connect() as db:
        row = db.execute('SELECT status,input_json,output_json,error_json FROM tasks WHERE project_id=? AND id=?',
                         (project_id, task_id)).fetchone()
        if not row or row['status'] not in {'succeeded', 'failed'} or not row['output_json']:
            return
        operations = db.execute(f'SELECT id FROM {jobs.table} WHERE project_id=? AND task_id=?',
                                (project_id, task_id)).fetchall()
    if not operations:
        return
    output = json.loads(row['output_json'])
    data = output.setdefault('structured_data', {})
    previous = {(a.get('nodeId'), a.get('assetId')) for a in (data.get('delivery') or {}).get('artifacts', [])}
    late, confirmed = [], []
    for operation in operations:
        result = jobs.read(project_id, task_id, operation['id']).get('output') or {}
        node_id = (result.get('node') or {}).get('id')
        if result.get('status') == 'succeeded' and result.get('assetId') and node_id:
            confirmed.append((node_id, result['assetId']))
            if (node_id, result['assetId']) not in previous:
                late.append((node_id, result['assetId']))
    # Repair legacy records whose delivery was reconciled but execution stayed
    # failed. Require a real successful operation and recheck local artifacts.
    if not late and row['status'] == 'failed' and data.get('deliveryStatus') in {'passed','pending'}:
        late = confirmed
    if not late:
        return
    report = delivery.inspect_task(project_id, task_id, output.get('artifact_refs'))
    # A subsequent user edit may have replaced the content on this node.
    actual = {(a.get('nodeId'), a.get('assetId')) for a in report['artifacts']}
    late = [pair for pair in late if pair in actual]
    if not late:
        return
    data.update(delivery=report, deliveryStatus='pending' if report['pendingMedia'] or report['pendingPreview'] else 'passed' if report['passed'] else 'needs_review')
    annotate_delivery(data)
    if data['deliveryStatus'] == 'passed':
        data['answer'] = '作品已保存到右侧画布。'
        output['status'] = 'succeeded'
        if row['status'] == 'failed':
            output.setdefault('provenance', {})['recoveredExecution'] = {
                'previousStatus': row['status'], 'previousError': json.loads(row['error_json'] or '{}'),
                'reason': '原请求的真实媒体已保存，全部交付已完成；没有重新生成。'}
    refs = [*(output.get('artifact_refs') or []), *report['artifact_refs']]
    output['artifact_refs'] = list({(r['entity_type'], r['entity_id']): r for r in refs}.values())
    now = jobs.now()
    with jobs.store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        passed = data['deliveryStatus'] == 'passed'
        changed = db.execute('UPDATE tasks SET status=?,error_json=?,output_json=?,updated_at=? WHERE project_id=? AND id=? AND status=? AND input_json=? AND output_json=?',
            ('succeeded' if passed else row['status'], None if passed else row['error_json'], json.dumps(output, ensure_ascii=False), now, project_id, task_id, row['status'], row['input_json'], row['output_json'])).rowcount
        if not changed:
            return
        checkpoint = db.execute('SELECT payload FROM agent_checkpoints WHERE task_id=?', (task_id,)).fetchone()
        if checkpoint:
            state = json.loads(checkpoint['payload'])
            if state.get('finalResult'):
                state['finalResult'].update(status=output.get('status', row['status']), structured_data=data, artifact_refs=output['artifact_refs'])
                db.execute('UPDATE agent_checkpoints SET payload=?,updated_at=? WHERE task_id=?',
                           (json.dumps(state, ensure_ascii=False), now, task_id))
