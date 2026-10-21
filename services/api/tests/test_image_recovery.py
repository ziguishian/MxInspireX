import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from fastapi import HTTPException
from app.image_jobs import ImageJobs
from app.image_recovery import ImageRecovery
from test_design_execution import env

def prepare(env,kind='image'):
    store, project, _, tools, enqueue, _ = env
    task=enqueue('生成一张产品图，跳过参考')
    args={'prompt':'产品图'}
    fingerprint,_=tools.executions.claim(task,'generate_'+kind,args)
    node=tools.canvas_store.create_node(project,kind=kind,title='生成媒体',data={'generating':False},task_id=task,execution_receipt=fingerprint)
    with store._connect() as db: db.execute("UPDATE tasks SET status='failed' WHERE id=?",(task,))
    jobs=ImageJobs(store,tools.executions,'generate_'+kind)
    operation,encoded=jobs.identity(project,task,args)
    with store._connect() as db:
        db.execute(f'INSERT INTO {jobs.table} VALUES (?,?,?,?,?,?,?,?,?)',(operation,project,task,encoded,'completed',json.dumps({'status':'generation_unconfirmed'}),200,jobs.now(),jobs.now()))
    recovery=ImageRecovery(tools,jobs)
    recovery.remember(project,task,fingerprint,{'id':'original-job'},'qwen-audio-3.1-tts-flash' if kind=='audio' else 'gpt-image-2','https://api.evolink.ai/v1',{'canvasNodeId':node['id'],'kind':kind})
    image=io.BytesIO();Image.new('RGB',(32,32)).save(image,format='PNG')
    adapter=SimpleNamespace(retrieve=Mock(return_value={'jobId':'original-job','status':'completed','content':b'ID3original audio' if kind=='audio' else image.getvalue()}),generate=Mock(side_effect=AssertionError('never regenerate')))
    tools.provider_registry=SimpleNamespace(image=lambda *a,**k:adapter,_meter=lambda *a:adapter,credentials=SimpleNamespace(get=lambda _:None))
    return project,task,fingerprint,node,recovery,adapter,jobs,operation

@pytest.mark.parametrize('kind',['image','audio'])
def test_recovery_is_idempotent_scoped_and_survives_restart(env,kind):
    project,task,fingerprint,node,recovery,adapter,jobs,operation=prepare(env,kind)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:recovery.recover(project,task,fingerprint),range(2)))
    assert results[0]['assetId']==results[1]['assetId']
    adapter.retrieve.assert_called_once_with(job_id='original-job')
    assert len(env[3].asset_store.list_assets(project))==1
    assert ImageRecovery(env[3],jobs).recover(project,task,fingerprint)['state']=='saved'
    assert jobs.read(project,task,operation)['output']['assetId']==results[0]['assetId']
    with pytest.raises(HTTPException) as error: recovery.recover('other',task,fingerprint)
    assert error.value.status_code==404

def test_recovery_preserves_new_user_content(env):
    project,task,fingerprint,node,recovery,adapter,*_=prepare(env)
    env[3].canvas_store.update_node(project,node['id'],{'data':{'text':'用户新内容'}})
    result=recovery.recover(project,task,fingerprint)
    board=env[3].canvas_store.load(project)
    assert next(n for n in board['nodes'] if n['id']==node['id'])['data']['text']=='用户新内容'
    assert any(n['id']!=node['id'] and n['data'].get('assetId')==result['assetId'] for n in board['nodes'])

@pytest.mark.parametrize('status',['running','queued','cancelled'])
def test_active_and_cancelled_recovery_does_not_download(env,status):
    project,task,fingerprint,_,recovery,adapter,*_=prepare(env)
    with env[0]._connect() as db: db.execute('UPDATE tasks SET status=? WHERE id=?',(status,task))
    with pytest.raises(HTTPException): recovery.recover(project,task,fingerprint)
    adapter.retrieve.assert_not_called()

def test_pending_or_invalid_original_result_never_creates_asset(env):
    project,task,fingerprint,_,recovery,adapter,*_=prepare(env)
    adapter.retrieve.return_value={'status':'processing'}
    assert recovery.recover(project,task,fingerprint)['state']=='processing'
    adapter.retrieve.return_value={'status':'completed','content':b'not an image'}
    with pytest.raises(HTTPException): recovery.recover(project,task,fingerprint)
    assert not env[3].asset_store.list_assets(project)


def test_late_audio_preview_updates_failed_task_without_generation(env):
    from app.delivery import DeliveryService
    from app.late_image_results import sync_late_images
    project,task,fingerprint,node,recovery,adapter,jobs,operation=prepare(env,'audio')
    store=env[0]
    with store._connect() as db:
        data=json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?',(task,)).fetchone()[0])
        data.update(userMessage='生成音频',requiredArtifacts=['audio'],deliveryContract=[{'kind':'audio','count':1}],deliveryVerification=True)
        db.execute('UPDATE tasks SET input_json=?,output_json=? WHERE id=?',(json.dumps(data),json.dumps({'status':'failed','structured_data':{'deliveryStatus':'needs_review'}}),task))
    delivery=DeliveryService(store,env[3].asset_store,env[3].canvas_store)
    jobs.on_settled=lambda p,t:sync_late_images(jobs,delivery,p,t)
    recovery.recover(project,task,fingerprint)
    claimed=delivery.claim_previews()
    assert len(claimed)==1 and claimed[0]['kind']=='audio'
    delivery.record_check(project,node['id'],claimed[0]['fingerprint'],{'passed':True,'errors':[],'duration':3.2})
    env[2].sync_image_results=jobs.on_settled
    result=env[2].list_tasks(project)[0]
    assert result['status']=='succeeded' and result['output']['structured_data']['deliveryStatus']=='passed'
    adapter.retrieve.assert_called_once()
