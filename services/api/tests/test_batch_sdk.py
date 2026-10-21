import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
from test_design_execution import env
from test_design_batches import create_first, plan

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_real_sdk_registers_next_batch_before_dispatch_and_preserves_assets(env,api):
    store, project, runtime, tools, enqueue, _ = env
    _, old = create_first(env,count=2)
    task=enqueue('好的，继续')
    constraints={**tools._task_input(project,task),'executionFlow':'direct','agentCollaboration':False}
    payload={'apiKey':'fixture-only','model':'fixture','api':api,'baseUrl':'http://batch-fixture.invalid/v1',
        'modelCapabilities':{'contextLength':128000},'maxOutputTokens':4096,'persistentSessions':True,
        'toolGateway':{'baseUrl':'http://batch-fixture.invalid','projectId':project,'taskId':task},
        'context':{'projectId':project,'taskId':task,'brief':'好的，继续','constraints':constraints}}
    environment={**os.environ,'PYTHONPATH':str(ROOT),'FIXTURE_PYTHON':sys.executable,'FIXTURE_WORKSPACE':str(store.workspace_root),'FIXTURE_PROJECT':project,'FIXTURE_BATCH_PLAN':json.dumps(plan('B2',2))}
    result=subprocess.run([shutil.which('node'),'--import',(ROOT/'tests/fixtures/batch_transport.mjs').resolve().as_uri(),str(ROOT/'app/openai_agent_worker.mjs')],input=json.dumps(payload),text=True, encoding='utf-8',capture_output=True,env=environment,timeout=60)
    assert result.returncode==0,result.stderr+result.stdout[-5000:]
    events=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert any(e['type']=='result' for e in events)
    calls=[json.loads(line) for line in (store.workspace_root/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(calls)==2 and all('第二批新物料 B2-' in c['prompt'] for c in calls)
    current=runtime.get_task(project,task)
    assert current['designBatch']['itemIds']==['B2-0','B2-1']
    assert len(current['deliveryProgress'])==4
    nodes={n['id']:n for n in tools.canvas_store.load(project)['nodes']}
    assert all(nodes[n['id']]['data']['assetId']==n['data']['assetId'] for n in old)
