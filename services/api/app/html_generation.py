"""Visible, task-owned placeholders while the model streams HTML arguments."""
import json
from .canvas import CanvasStore


class HtmlGenerationPreviews:
    def __init__(self, store, canvas=None):
        self.store, self.canvas = store, canvas or CanvasStore(store)

    def _matches(self, node, task_id, call_id=None):
        data = node.get('data') or {}
        return data.get('generationPreviewTaskId') == task_id and (call_id is None or data.get('generationPreviewCallId') == call_id)

    def begin(self, project_id, task_id, call_id):
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
            raise ValueError('生成标识无效')
        with self.canvas._lock:
            with self.store._connect() as db:
                task = db.execute('SELECT status,input_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
            if not task or task['status'] != 'running':
                raise ValueError('任务不存在或已停止')
            nodes = self.canvas.load(project_id)['nodes']
            for node in nodes:
                if self._matches(node, task_id, call_id): return {'nodeId': node['id']}
            context = json.loads(task['input_json'] or '{}')
            canvas = context.get('canvasParams') or {}
            repairs = context.get('deliveryRepairNodes') or []
            target = canvas.get('canvasNodeId') if canvas.get('kind') == 'html' else repairs[0] if context.get('deliveryRepairOnly') and len(repairs) == 1 else None
            original = next((node for node in nodes if node['id'] == target and node['data'].get('kind') == 'html'), None)
            if original:
                self.canvas.update_node(project_id, original['id'], {'data': {'generating': True, 'status': '正在生成网页…',
                    'generationPreviewTaskId': task_id, 'generationPreviewCallId': call_id,
                    'generationPreviewOriginalStatus': original['data'].get('status', '')}})
                return {'nodeId': original['id']}
            node = self.canvas.create_node(project_id, kind='html', title='生成网页', task_id=task_id,
                data={'generating': True, 'draft': False, 'status': '正在生成网页…',
                      'generationPreviewTaskId': task_id, 'generationPreviewCallId': call_id, 'generationPreviewCreated': True})
            return {'nodeId': node['id']}

    def bind(self, project_id, task_id, call_id, arguments):
        # Scope/semantic validation happens before this internal target binding.
        # Explicit edits still write their original node and discard the blank preview.
        if arguments.get('canvas_node_id'): return arguments
        with self.canvas._lock:
            for node in self.canvas.load(project_id)['nodes']:
                if self._matches(node, task_id, call_id):
                    return {**arguments, 'canvas_node_id': node['id']}
        return arguments

    def finish(self, project_id, task_id, call_id=None):
        with self.canvas._lock:
            document = self.canvas.load(project_id)
            matched = [node for node in document['nodes'] if self._matches(node, task_id, call_id)]
            if not matched: return
            removed = set()
            for node in matched:
                data = node['data']
                if data.get('generationPreviewCreated') and not any(data.get(key) for key in ('html', 'text', 'assetId', 'asset')):
                    removed.add(node['id'])
                else:
                    data['generating'] = False
                    if data.get('status') == '正在生成网页…': data['status'] = data.get('generationPreviewOriginalStatus', '')
                    data.pop('generationPreviewTaskId', None)
                    data.pop('generationPreviewCallId', None)
                    data.pop('generationPreviewOriginalStatus', None)
                    data.pop('generationPreviewCreated', None)
            document['nodes'] = [node for node in document['nodes'] if node['id'] not in removed]
            document['edges'] = [edge for edge in document['edges'] if edge['source'] not in removed and edge['target'] not in removed]
            self.canvas.save(project_id, document)
