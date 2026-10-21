"""A newly saved semantic plan drives the real SDK batch and file inputs."""
import json
import os
import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA


def test_sdk_uses_saved_input_graph_and_starts_child_before_unrelated_branch_finishes(tmp_path):
    store=ProjectStore(str(tmp_path))
    project=store.create_project(new_project(name='依赖测试',slug='deps',brief='',budget_minor=None,currency='CNY',root_path=str(tmp_path/'deps')))['id']
    assets=AssetStore(store)
    buffer=BytesIO();Image.new('RGB',(32,32),'#328895').save(buffer,format='PNG')
    reference=assets.add_bytes(project_id=project,kind='image',filename='reference.png',content=buffer.getvalue())
    context={'userMessage':'按已有资料生成两张独立图片，并基于其中一张生成后续图。','agentCollaboration':False,'deliveryVerification':False,'mediaProvider':{'image':{'key':'local-placeholder'}},
             'referencedAssets':[{'id':reference['id'],'projectId':project}]}
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES ('task',?,'design','design','running',?,'now','now')",(project,json.dumps(context)))
    plan={'goal':'按每项真实输入生成三项内容','preserve':[],'deliverables':[
        {'id':id,'title':id,'kind':'image','acceptance':'使用指定输入','inputs':[
            {'source':'deliverable' if id=='child' else 'asset','id':'parent' if id=='child' else reference['id'],'role':'reference','purpose':'使用已完成的产品图' if id=='child' else '使用已有资料'}]}
        for id in ['parent','slow','child']], 'coverage':[],'deferred':[],'openQuestions':[],'research':'已有资料足够'}
    root=Path(__file__).resolve().parents[1];fixtures=root/'tests/fixtures';log=tmp_path/'calls.jsonl'
    env={**os.environ,'PYTHONPATH':str(root),'FIXTURE_PYTHON':sys.executable,'FIXTURE_TOOL_SCRIPT':str(fixtures/'agent_tool_fixture.py'),
         'FIXTURE_WORKSPACE':str(tmp_path),'FIXTURE_PROJECT':project,'FIXTURE_TASK':'task','FIXTURE_DESIGN_PLAN':json.dumps(plan),'FIXTURE_CALL_LOG':str(log)}
    payload={'api':'responses','apiKey':'test-only','model':'fixture-model','baseUrl':'https://fixture.invalid/v1',
             'toolGateway':{'baseUrl':'https://fixture.invalid','projectId':project,'taskId':'task'},
             'context':{'projectId':project,'taskId':'task','brief':context['userMessage'],'constraints':context}}
    worker=os.environ.get('AICS_TEST_WORKER') or str(root/'app/openai_agent_worker.mjs')
    result=subprocess.run([shutil.which('node') or 'node','--import',(fixtures/'dependency_batch_transport.mjs').resolve().as_uri(),worker],input=json.dumps(payload),text=True, encoding='utf-8',capture_output=True,env=env,timeout=30)
    assert result.returncode==0,result.stderr+result.stdout[-4000:]
    events=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    final=next(event['result'] for event in events if event['type']=='result')
    saved=final['structured_data']['designPlan']
    assert [item['dependsOn'] for item in saved['deliverables']]==[[],[],['parent']]
    assert log.exists(),result.stderr+result.stdout[-8000:]
    calls=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    ordered=[(call['event'],call['id']) for call in calls]
    assert ordered.index(('finish','parent'))<ordered.index(('start','child'))<ordered.index(('finish','slow'))
    nodes=CanvasStore(store).load(project)['nodes'];assert len(nodes)==3
    outputs={n['data']['deliveryBinding']['itemIds'][0]:n['data']['assetId'] for n in nodes}
    snapshot=assets.get_asset(project_id=project,asset_id=outputs['child'])['metadata']['referenceSnapshot']
    assert [r['assetId'] for r in snapshot['references']]==[outputs['parent']]
    assert snapshot['inputBindings'][0]['id']=='parent'
