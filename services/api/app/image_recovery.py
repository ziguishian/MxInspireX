"""Retrieve accepted EvoLink jobs. This service cannot submit generation."""
import json
import threading
from uuid import uuid4

from fastapi import HTTPException

from .billing import billing_scope
from .image_output import reject_svg_output


class ImageRecovery:
    _lock = threading.RLock()

    def __init__(self, tools, jobs=None):
        self.tools, self.store, self.jobs = tools, tools.store, jobs
        with self.store._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS provider_image_results (
                fingerprint TEXT NOT NULL, project_id TEXT NOT NULL, task_id TEXT NOT NULL,
                job_id TEXT NOT NULL, model TEXT NOT NULL, base_url TEXT NOT NULL, metadata TEXT NOT NULL,
                PRIMARY KEY(task_id,fingerprint))''')

    def remember(self, project, task, fingerprint, body, model, base_url, metadata):
        if not task or not fingerprint or not isinstance(body.get('id'), str): return
        with self.store._connect() as db:
            db.execute('INSERT OR IGNORE INTO provider_image_results VALUES (?,?,?,?,?,?,?)',
                (fingerprint, project, task, body['id'], model, base_url, json.dumps(metadata, ensure_ascii=False)))

    def list(self, project, task):
        with self.store._connect() as db:
            rows = db.execute('''SELECT p.*,r.status receipt_status,r.output FROM provider_image_results p
                JOIN tool_receipts r ON r.fingerprint=p.fingerprint AND r.task_id=p.task_id
                WHERE p.project_id=? AND p.task_id=?''', (project, task)).fetchall()
        return [{'id': r['fingerprint'], 'providerTaskId': r['job_id'], 'model': r['model'], 'kind':json.loads(r['metadata']).get('kind','image'),
                 'saved': bool(json.loads(r['output'] or '{}').get('assetId'))} for r in rows]

    def recover(self, project, task, fingerprint):
        # Serialize only explicit recovery clicks; no live generation is blocked.
        with self._lock:
            with self.store._connect() as db:
                state = db.execute('SELECT status FROM tasks WHERE project_id=? AND id=?', (project, task)).fetchone()
                row = db.execute('SELECT * FROM provider_image_results WHERE project_id=? AND task_id=? AND fingerprint=?',
                    (project, task, fingerprint)).fetchone()
            if not state or not row: raise HTTPException(404, '原生成记录不存在')
            if state['status'] in {'running','queued','cancelled'}:
                raise HTTPException(409, '运行中或已取消的任务不能通过此入口恢复')
            # Reconcile saved files first, including a crash between save/receipt.
            self.tools.executions.reconcile(task)
            with self.store._connect() as db:
                receipt = db.execute('SELECT output,args FROM tool_receipts WHERE task_id=? AND fingerprint=?', (task, fingerprint)).fetchone()
            if not receipt: raise HTTPException(404, '原工具回执不存在')
            output = json.loads(receipt['output'] or '{}')
            if output.get('assetId'):
                self._settle(project, task, json.loads(receipt['args']), output)
                return {'state':'saved','assetId':output['assetId'],'message':'原结果已保存，没有重新生成。'}
            meta = json.loads(row['metadata'])
            kind = meta.get('kind','image')
            if kind == 'audio':
                from .providers.evolink import EvoLinkAudioProvider
                adapter = self.tools.provider_registry._meter('audio', EvoLinkAudioProvider(base_url=row['base_url'],provider_key='evolink',model=row['model'],credentials=self.tools.provider_registry.credentials))
            else:
                adapter = self.tools.provider_registry.image('evolink', base_url=row['base_url'], model=row['model'])
            with billing_scope(project_id=project, task_id=task):
                result = adapter.retrieve(job_id=row['job_id'])
            if result['status'] != 'completed':
                terminal = result['status'] in {'failed','cancelled'}
                return {'state':result['status'], 'message':'服务商原任务已结束，未返回媒体。' if terminal else '原任务仍在生成，请稍后再次查询。'}
            content = result['content']
            verified = {'verified': content.startswith(b'ID3') or len(content)>2 and content[0]==255 and content[1]&224==224, 'format':'mp3'} if kind == 'audio' else reject_svg_output(content)
            if not verified.get('verified'):
                raise HTTPException(502, '原结果未通过媒体格式校验，未保存，请核对服务商任务。')
            with self.store._connect() as db:
                if db.execute('SELECT status FROM tasks WHERE id=?', (task,)).fetchone()[0] == 'cancelled':
                    raise HTTPException(409, '任务已取消，未修改画布')
            extension = {'jpeg':'jpg'}.get(verified.get('format'), verified.get('format') or 'png')
            target = meta.get('canvasNodeId')
            node = next((n for n in self.tools.canvas_store.load(project)['nodes'] if n['id'] == target), None)
            # User edits or an occupied target are never overwritten by a late result.
            if not node or any(node.get('data',{}).get(k) for k in ('assetId','text','html','drawing')):
                target = None
            meta.update(taskId=task, executionReceipt=fingerprint, provider='evolink', model=row['model'],
                        providerTaskId=row['job_id'], imageOutput=verified, canvasNodeId=target)
            asset = self.tools.asset_store.add_bytes(project_id=project, kind=kind, filename=f'recovered-{uuid4().hex}.{extension}',
                content=content, metadata=meta)
            node = self.tools.canvas_store.ensure_asset_node(project, asset, task_id=task, target_node_id=target, execution_receipt=fingerprint)
            if meta.get('deliveryBinding'):
                node = self.tools.canvas_store.update_node(project,node['id'],{'data':{'deliveryBinding':meta['deliveryBinding']}})
            output = {'tool':'generate_'+kind,'status':'succeeded','assetId':asset['id'],'asset':asset,'node':node,
                      'outputKind':kind,'provider':'evolink','model':row['model'],'recoveredFromProviderTaskId':row['job_id']}
            self.tools.executions.complete(task, fingerprint, output)
            self._settle(project, task, json.loads(receipt['args']), output)
            return {'state':'saved','assetId':asset['id'],'message':'原结果已取回并保存到画布，没有重新生成。'}

    def _settle(self, project, task, arguments, output):
        if not self.jobs: return
        jobs = self.jobs.get(output['tool']) if isinstance(self.jobs,dict) else self.jobs
        if not jobs: return
        operation, _ = jobs.identity(project, task, arguments)
        jobs._complete(operation, output)
        if jobs.on_settled: jobs.on_settled(project, task)
