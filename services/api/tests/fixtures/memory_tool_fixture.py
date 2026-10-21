import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from app.assets import AssetStore
from app.design_tools import DesignToolRegistry
from app.providers.local import LocalImageProvider
from app.storage import ProjectStore
from app.providers.http import ProviderError
from app.providers.image_request import image_request_started

request=json.load(sys.stdin)
store=ProjectStore(os.environ['FIXTURE_WORKSPACE'])
class Provider(LocalImageProvider):
    api='images'
    def generate(self,**args):
        with (store.workspace_root/'provider-calls.jsonl').open('a') as f:f.write(json.dumps(args)+'\n')
        if os.environ.get('FIXTURE_GIFT_MODE') in {'partial_late','durable_partial'} and args['prompt'].startswith('迷你茶叶陶罐'):
            image_request_started()
            raise ProviderError('图像响应连接中断，结果待确认；停止自动重发。',stop_tool=True,error_code='image_result_unconfirmed')
        return super().generate(**args)
registry=DesignToolRegistry(store,asset_store=AssetStore(store),provider_registry=SimpleNamespace(image=lambda *a,**kw:Provider()))
if request.get('fixtureAfterReview') and request['name'] == 'delivery_verify':
    if os.environ.get('FIXTURE_MODE') == 'review_bookkeeping':
        with store._connect() as db:
            context = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?',(request['taskId'],)).fetchone()[0])
            context['fixtureBookkeeping'] = True
            db.execute('UPDATE tasks SET input_json=? WHERE id=?',(json.dumps(context),request['taskId']))
    elif os.environ.get('FIXTURE_MODE') == 'review_changed':
        node = registry.canvas_store.load(request['projectId'])['nodes'][0]
        registry.canvas_store.update_node(request['projectId'], node['id'], {'data':{'productionNotes':['审查后出现新的制作条件']}})
try:
    if os.environ.get('FIXTURE_HTML_PREVIEW') == '1' and request['name'] == 'delivery_verify':
        from app.delivery import DeliveryService
        delivery = DeliveryService(store)
        for node in delivery.canvas.load(request['projectId'])['nodes']:
            if node.get('data', {}).get('kind') == 'html' and not delivery.check(request['projectId'],node):
                delivery.record_check(request['projectId'],node['id'],delivery.fingerprint(node),{'passed':True,'errors':[]})
    if request['name']=='fixture_receipt':
        result=registry.executions.result_status(request['taskId'],'generate_image',request['arguments'])
    else:
        result=registry.execute(project_id=request['projectId'],task_id=request['taskId'],name=request['name'],arguments=request['arguments'],operation_id=request.get('callId'),agent_role=request.get('role','design'))
    print(json.dumps({'status':200,'body':result},ensure_ascii=False))
except ProviderError as error:
    if error.error_code!='image_result_unconfirmed':raise
    print(json.dumps({'status':200,'body':{'tool':request['name'],'status':'generation_unconfirmed','errorCode':error.error_code,'retryable':False,'billingCertainty':'unknown'}}))
except ValueError as error:
    print(json.dumps({'status':422,'body':{'detail':str(error)}}))
