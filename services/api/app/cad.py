"""Durable project-scoped CAD builds shared by the Agent and parameter panel."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from .assets import AssetStore
from .cad_program import CadBuildRequest, Parameter, resolve_parameters
from .canvas import CanvasStore

_services = {}
_guard = threading.RLock()
TERMINAL = {'succeeded', 'failed', 'cancelled'}


def cad_service(store):
    key = str(store.catalog_path)
    with _guard:
        if key not in _services or _services[key].stopping: _services[key] = CadService(store)
        return _services[key]


class CadService:
    def __init__(self, store):
        self.store, self.assets, self.canvas = store, AssetStore(store), CanvasStore(store)
        self.lock = threading.RLock()
        self.processes = {}
        self.threads = {}
        self.stopping = False
        self.health = {'available':None, 'status':'checking'}
        with store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cad_builds (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, request_key TEXT NOT NULL, digest TEXT NOT NULL, task_id TEXT, node_id TEXT, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT, created_at REAL, UNIQUE(project_id,request_key))')
            db.execute("UPDATE cad_builds SET status='failed',error='应用已重启，原构建已停止；可重试' WHERE status IN ('queued','running')")

    def node(self, project_id, node_id):
        node = next((n for n in self.canvas.load(project_id)['nodes'] if n['id'] == node_id), None)
        if not node or node.get('data', {}).get('kind') != 'cad': raise ValueError('CAD 节点不存在或不属于当前项目')
        return node

    def submit(self, project_id, request, *, task_id=None, receipt=None, binding=None):
        request = CadBuildRequest.model_validate(request)
        if not self.store.get_project(project_id): raise ValueError('项目不存在')
        if self.stopping: raise ValueError('应用正在退出')
        original = request.model_dump(mode='json')
        digest = hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        key = f'{task_id}:{receipt}' if receipt else request.request_id or uuid4().hex
        with self.lock, self.canvas._lock:
            with self.store._connect() as db:
                old = db.execute('SELECT * FROM cad_builds WHERE project_id=? AND request_key=?', (project_id,key)).fetchone()
            if old:
                if old['digest'] != digest: raise ValueError('同一请求 ID 不能用于不同构建')
                return self.get(project_id,old['id'])
            if task_id:
                with self.store._connect() as db:
                    task = db.execute('SELECT status FROM tasks WHERE id=? AND project_id=?',(task_id,project_id)).fetchone()
                if not task or task['status'] == 'cancelled': raise ValueError('任务不存在或已取消')
            if request.canvas_node_id:
                node = self.node(project_id, request.canvas_node_id)
                data = node['data']
                if not task_id and request.canvas_node_id in self.canvas.active_node_ids(project_id):
                    raise ValueError('这个模型正被 Agent 使用，请等待完成后修改参数')
                if data.get('assetId') and request.base_revision != data.get('cadRevision'):
                    raise ValueError('模型版本已变化，请刷新后重试')
                if not data.get('assetId') and request.base_revision:
                    raise ValueError('空白模型没有基础版本')
                base = data.get('cad') or {}
                if request.source is None: request.source = base.get('source')
                if request.parameter_definitions is None: request.parameter_definitions = [Parameter.model_validate(item) for item in base.get('parameter_definitions', [])]
                inherited = {k:v for k,v in base.get('parameters', {}).items() if not next((d.get('expression') for d in base.get('parameter_definitions', []) if d['name']==k),None)}
                names = {d.name if hasattr(d,'name') else d['name'] for d in request.parameter_definitions}
                request.parameters = {**{k:v for k,v in inherited.items() if k in names}, **request.parameters}
                if not request.reference_asset_ids: request.reference_asset_ids = base.get('reference_asset_ids', [])
                if not request.assumptions: request.assumptions = base.get('assumptions', [])
            if not request.source or not request.source.strip(): raise ValueError('缺少建模程序')
            for asset_id in request.reference_asset_ids:
                asset = self.assets.get_asset(project_id=project_id, asset_id=asset_id)
                if not asset or asset['mime'] not in {'image/png','image/jpeg','image/webp','image/gif'}: raise ValueError('参考图片不存在或不属于当前项目')
            payload = request.model_dump(mode='json')
            payload['parameter_definitions'] = payload['parameter_definitions'] or []
            resolve_parameters(payload['parameter_definitions'] or [],payload['parameters'])
            payload.update(_receipt=receipt, _binding=binding or {})
            if task_id:
                group = request.canvas_node_id or json.dumps((binding or {}).get('itemIds') or [request.title],sort_keys=True)
                payload['_repairGroup'] = group
                with self.store._connect() as db:
                    failures = db.execute("SELECT COUNT(*) FROM cad_builds WHERE project_id=? AND task_id=? AND status='failed' AND json_extract(payload,'$._repairGroup')=?",(project_id,task_id,group)).fetchone()[0]
                if failures >= 2: raise ValueError('这个模型已经自动修复一次，请说明问题并等待用户调整要求')
            build_id = uuid4().hex
            with self.store._connect() as db:
                # Separate UI requests cannot race to replace one model.
                if request.canvas_node_id and db.execute("SELECT 1 FROM cad_builds WHERE project_id=? AND node_id=? AND status IN ('queued','running')",(project_id,request.canvas_node_id)).fetchone():
                    raise ValueError('这个模型已有构建正在运行')
                db.execute('INSERT INTO cad_builds VALUES (?,?,?,?,?,?,?,?,?,?,?)',(build_id,project_id,key,digest,task_id,request.canvas_node_id,'queued',json.dumps(payload,ensure_ascii=False),None,None,time.time()))
            thread = threading.Thread(target=self._run,args=(project_id,build_id,payload,task_id),daemon=True,name=f'cad-{build_id[:8]}')
            self.threads[build_id] = thread
            thread.start()
            return self.get(project_id,build_id)

    def get(self, project_id, build_id):
        with self.store._connect() as db:
            row = db.execute('SELECT * FROM cad_builds WHERE project_id=? AND id=?',(project_id,build_id)).fetchone()
        if not row: raise ValueError('CAD 构建不存在或不属于当前项目')
        return {'id':row['id'],'status':row['status'],'nodeId':row['node_id'],'result':json.loads(row['result']) if row['result'] else None,'error':row['error']}

    def cancel(self, project_id, build_id):
        with self.lock:
            build = self.get(project_id,build_id)
            if build['status'] not in TERMINAL:
                self._status(build_id,'cancelled',error='构建已取消')
                process = self.processes.get(build_id)
                if process and process.poll() is None: process.terminate()
            return self.get(project_id,build_id)

    def _status(self, build_id, status, *, result=None, error=None):
        with self.store._connect() as db:
            db.execute('UPDATE cad_builds SET status=?,result=?,error=? WHERE id=?',(status,json.dumps(result,ensure_ascii=False) if result else None,error,build_id))

    def _cancelled(self, project_id, build_id, task_id):
        if self.stopping or self.get(project_id,build_id)['status']=='cancelled': return True
        if task_id:
            with self.store._connect() as db:
                row=db.execute('SELECT status FROM tasks WHERE id=? AND project_id=?',(task_id,project_id)).fetchone()
            return not row or row['status']=='cancelled'
        return False

    def _worker(self, payload, directory, *, cancelled=lambda:False, build_id=None, timeout=120, startup_timeout=300):
        frozen = getattr(sys,'frozen',False)
        component_worker = os.environ.get('AICS_CAD_WORKER','').strip()
        component_pythonpath = os.environ.get('AICS_CAD_PYTHONPATH','').strip()
        if os.environ.get('AICS_LITE_RUNTIME') == '1' and not component_worker and not component_pythonpath:
            raise ValueError('本地 CAD 组件尚未安装。请打开“设置 → 能力组件”按需安装后重试。')
        if component_worker:
            if not Path(component_worker).is_file(): raise ValueError('本地 CAD 组件文件缺失，请在设置中重新安装。')
            command = [component_worker]
        else:
            command = [sys.executable,'--cad-worker'] if frozen else [sys.executable,'-m','app.cad_worker']
        env = {key:value for key,value in os.environ.items() if key in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','TMPDIR','LANG','LC_ALL'}}
        # CAD dependencies resolve a home/cache directory during import. Keep it
        # inside this disposable build, without inheriting credentials or config.
        env.update(HOME=str(Path(directory).resolve()), USERPROFILE=str(Path(directory).resolve()))
        if not frozen:
            python_paths = [str(Path(__file__).resolve().parent.parent)]
            if component_pythonpath: python_paths.insert(0, component_pythonpath)
            env['PYTHONPATH'] = os.pathsep.join(python_paths)
        env.update(PYTHONNOUSERSITE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        with (Path(directory)/'worker.log').open('wb') as log:
            process = subprocess.Popen(command,cwd=directory,env=env,stdin=subprocess.PIPE,stdout=log,stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if build_id:
                with self.lock: self.processes[build_id]=process
            try:
                process.stdin.write(json.dumps(payload,ensure_ascii=False).encode()); process.stdin.close()
                started = time.monotonic()
                ready_at = None
                import psutil
                monitored = psutil.Process(process.pid)
                while process.poll() is None:
                    if cancelled(): raise ValueError('构建已取消')
                    now = time.monotonic()
                    if ready_at is None and (Path(directory)/'ready.json').is_file(): ready_at = now
                    if ready_at is None and now-started > startup_timeout: raise ValueError('CAD 运行依赖加载超时，请重启应用后重试')
                    if ready_at is not None and now-ready_at > timeout: raise ValueError('CAD 构建超过执行时限，已停止；请简化模型')
                    if log.tell() > 4*1024*1024: raise ValueError('CAD 输出日志超过限制')
                    try:
                        if monitored.memory_info().rss > 2*1024**3: raise ValueError('CAD 构建超过 2 GB 内存限制，请简化模型')
                    except psutil.NoSuchProcess: pass
                    time.sleep(.1)
                path = Path(directory)/'result.json'
                if not path.is_file(): raise ValueError('CAD 进程退出，未返回结果；请检查运行依赖或简化模型')
                result = json.loads(path.read_text(encoding='utf-8'))
                if not result.get('ok'): raise ValueError(result.get('error','CAD 构建失败'))
                return result
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                if build_id:
                    with self.lock: self.processes.pop(build_id,None)

    def _run(self, project_id, build_id, payload, task_id):
        from .node_context import active_task
        token = active_task.set(task_id)
        try:
            with self.lock:
                if self._cancelled(project_id,build_id,task_id): return
                self._status(build_id,'running')
            with tempfile.TemporaryDirectory(prefix='langju-cad-') as directory:
                result = self._worker(payload,directory,build_id=build_id,cancelled=lambda:self._cancelled(project_id,build_id,task_id))
                with self.lock, self.canvas._lock:
                    if self._cancelled(project_id,build_id,task_id): raise ValueError('构建已取消')
                    if payload.get('canvas_node_id'):
                        current = self.node(project_id,payload['canvas_node_id'])
                        if current['data'].get('cadRevision') != payload.get('base_revision'):
                            raise ValueError('模型已被修改，已保留最新版本')
                    files = {}
                    for role,filename in result['files'].items():
                        asset = self.assets.add_bytes(project_id=project_id,kind='cad',filename=filename,content=(Path(directory)/filename).read_bytes(),metadata={'cadRole':role,'cadGroup':build_id,'taskId':task_id})
                        files[role] = asset['id']
                    manifest = {k:v for k,v in payload.items() if not k.startswith('_') and k not in {'request_id'}}
                    manifest.update(schemaVersion=1,revision=build_id,parameters=result['parameters'],files=files,checks=result['checks'],engine=result['engine'],unit='mm')
                    asset = self.assets.add_bytes(project_id=project_id,kind='cad',filename=f'{build_id}.cad.json',content=json.dumps(manifest,ensure_ascii=False,indent=2).encode(),metadata={'cadRole':'model','cadGroup':build_id,'taskId':task_id,'executionReceipt':payload.get('_receipt'),'title':payload['title'],'files':files})
                    data = {'kind':'cad','cad':manifest,'cadRevision':build_id,'previewAssetId':files['glb'],'thumbnailAssetId':files['thumbnail'],'deliveryBinding':payload.get('_binding',{}),'summary':'尺寸单位 mm；STEP、STL 和建模程序可导出。','title':payload['title']}
                    node = self.canvas.ensure_asset_node(project_id,asset,title=payload['title'],task_id=task_id,data=data,target_node_id=payload.get('canvas_node_id'),execution_receipt=payload.get('_receipt'))
                    self._status(build_id,'succeeded',result={'status':'succeeded','assetId':asset['id'],'node':node,'checks':result['checks'],'outputKind':'cad'})
        except Exception as error:
            with self.lock:
                cancelled = self._cancelled(project_id,build_id,task_id)
                self._status(build_id,'cancelled' if cancelled else 'failed',error=str(error)[:3000])
        finally:
            active_task.reset(token)
            with self.lock: self.threads.pop(build_id,None)

    def wait(self, project_id, build_id):
        while True:
            build = self.get(project_id,build_id)
            if build['status'] in TERMINAL: return build
            time.sleep(.1)

    def check_health(self):
        try:
            with tempfile.TemporaryDirectory(prefix='langju-cad-health-') as directory:
                self.health = self._worker({'health':True},directory,timeout=120,cancelled=lambda:self.stopping)
        except Exception as error: self.health = {'available':False,'error':str(error)}
        return self.health

    def shutdown(self):
        self.stopping = True
        with self.lock:
            with self.store._connect() as db:
                builds = db.execute("SELECT id,project_id FROM cad_builds WHERE status IN ('queued','running')").fetchall()
            for build in builds: self.cancel(build['project_id'],build['id'])
            threads = list(self.threads.values())
        for thread in threads: thread.join(timeout=4)


def cad_manifest(assets, project_id, asset_id):
    asset = assets.get_asset(project_id=project_id,asset_id=asset_id)
    if not asset or asset.get('metadata',{}).get('cadRole')!='model': raise ValueError('CAD 模型不存在')
    try:
        content = Path(asset['absolutePath']).read_bytes()
        if hashlib.sha256(content).hexdigest() != asset['sha256']: raise ValueError('CAD 模型清单发生变化，需要重新构建')
        manifest = json.loads(content)
    except OSError as error: raise ValueError('CAD 模型清单丢失') from error
    for child_id in manifest['files'].values():
        child = assets.get_asset(project_id=project_id,asset_id=child_id)
        if not child or not Path(child['absolutePath']).is_file(): raise ValueError('CAD 关联文件丢失')
        if hashlib.sha256(Path(child['absolutePath']).read_bytes()).hexdigest() != child['sha256']:
            raise ValueError('CAD 文件内容发生变化，需要重新构建')
    return manifest
