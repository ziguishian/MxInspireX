"""Compact cross-project activity; omit traces, prompts, and receipt bodies."""
import json


def list_activity(store):
    fields = 'id,project_id,agent_key,status,input_json,output_json,created_at'
    with store._connect() as db:
        rows = list(db.execute(f"SELECT {fields} FROM tasks WHERE superseded_by IS NULL AND status IN ('queued','pending','running')"))
        # Only the latest conversation needs attention; old failures remain in history.
        for project in db.execute('SELECT id FROM projects'):
            row = db.execute(f"SELECT {fields} FROM tasks WHERE project_id=? AND superseded_by IS NULL AND COALESCE(json_extract(input_json,'$.taskSurface'),'conversation') != 'canvas_node' ORDER BY created_at DESC,COALESCE(turn_order,rowid) DESC LIMIT 1", (project['id'],)).fetchone()
            if row and row['id'] not in {item['id'] for item in rows}: rows.append(row)
        # The latest attempt on each independent node can also need attention.
        canvas_rows = db.execute(f"SELECT {fields} FROM tasks WHERE rowid IN (SELECT MAX(rowid) FROM tasks WHERE superseded_by IS NULL AND json_extract(input_json,'$.taskSurface')='canvas_node' GROUP BY project_id,COALESCE(json_extract(input_json,'$.canvasNodeId'),json_extract(input_json,'$.canvasParams.canvasNodeId')))").fetchall()
        seen = {row['id'] for row in rows}
        rows.extend(row for row in canvas_rows if row['id'] not in seen)
    from .task_updates import TaskUpdates
    updates = TaskUpdates(store)
    result = []
    for row in rows:
        data = json.loads(row['input_json'] or '{}')
        output = json.loads(row['output_json'] or '{}')
        structured = output.get('structured_data') or {}
        from .delivery_findings import annotate_delivery
        annotate_delivery(structured)
        summary = {key: structured[key] for key in ('deliveryStatus', 'referenceSelection', 'clarification', 'deliveryFindings') if key in structured}
        result.append({'id': row['id'], 'projectId': row['project_id'], 'agentKey': row['agent_key'], 'status': row['status'], 'userMessage': str(data.get('userMessage', ''))[:240], 'taskSurface': data.get('taskSurface', 'conversation'), 'canvasNodeId': data.get('canvasNodeId') or (data.get('canvasParams') or {}).get('canvasNodeId'), 'updates': [{'appliedAt': item['appliedAt']} for item in updates.list(row['project_id'], row['id'])], 'output': {'structured_data': summary}, 'createdAt': row['created_at']})
    return result
