import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.conversation_memory import ConversationMemoryService
from test_conversation_memory import workspace,turn,picture,update

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=Path(__file__).parent/'fixtures'


def run(store,logo,brooch,api,mode='normal',recovery=None,policy=None,brief=None,constraints=None,model='fixture'):
    payload={'apiKey':'fixture-only','model':model,'api':api,'baseUrl':'http://memory-fixture.invalid/v1',
        'modelCapabilities':{'contextLength':128000},'maxOutputTokens':4096,'persistentSessions':True,'recovery':recovery or {},'executionPolicy':policy or {},
        'memory':ConversationMemoryService(store).runtime('one','current',images=True),
        'toolGateway':{'baseUrl':'http://memory-fixture.invalid','projectId':'one','taskId':'current'},
        'context':{'projectId':'one','taskId':'current','brief':'这是原 Logo，标准色为蓝色，做水杯',
          'constraints':{'executionFlow':'direct','agentCollaboration':False,'memoryProtocol':1,'svgPolicy':{'allowed':False,'mode':'off'}}}}
    if brief is not None: payload['context']['brief'] = brief
    payload['context']['constraints'].update(constraints or {})
    env={**os.environ,'PYTHONPATH':str(ROOT),'FIXTURE_PYTHON':sys.executable,'FIXTURE_WORKSPACE':str(store.workspace_root),
        'FIXTURE_MEMORY_MODE':mode,'FIXTURE_LOGO':logo['id'],'FIXTURE_BROOCH':brooch['id']}
    result=subprocess.run([shutil.which('node'),'--import',(FIXTURES/'memory_transport.mjs').resolve().as_uri(),str(ROOT/'app/openai_agent_worker.mjs')],input=json.dumps(payload),text=True, encoding='utf-8',capture_output=True,env=env,timeout=60)
    return result,[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]


def setup(store):
    logo=picture(store,source='input-reference');turn(store,'first','原图',referencedAssets=[{'id':logo['id']}])
    brooch=picture(store,'brooch',taskId='first')
    turn(store,'current','这是原 Logo，标准色为蓝色，做水杯',referencedAssets=[{'id':logo['id']}])
    return logo,brooch


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('mode',['intro','followup','clarify'])
def test_introduction_followup_and_clarification_finish_without_legacy_reimport(workspace,api,mode):
    logo,brooch=setup(workspace)
    brief = '介绍下自己' if mode == 'intro' else '为我的杯子设计一个包装'
    constraints = {'simpleConversation':True} if mode == 'intro' else {'referenceWorkflow':{'status':'required'}} if mode == 'clarify' else {}
    result,events=run(workspace,logo,brooch,api,mode,brief=brief,constraints=constraints)
    assert result.returncode==0,result.stderr+result.stdout[-6000:]
    final=next(e['result'] for e in events if e['type']=='result')
    with workspace._connect() as db:
        assert not db.execute("SELECT 1 FROM sdk_session_operations WHERE operation_id LIKE 'legacy:%'").fetchone()
        items=json.loads(db.execute("SELECT items FROM sdk_sessions WHERE id='project:one'").fetchone()[0])
    assert sum(brief in json.dumps(i,ensure_ascii=False) for i in items if i.get('role')=='user')==1
    assert not (workspace.workspace_root/'provider-calls.jsonl').exists()
    if mode=='clarify':
        assert final['structured_data']['clarification']['questions'][0]['id']=='product'
        assert final['provenance']['modelRequestCount']==1
    if mode=='intro':
        assert final['provenance']['modelRequestCount']==1
        assert final['tool_outputs']==[]
    if mode=='followup':
        assert final['provenance']['modelRequestCount']==1
        assert not any(e.get('phase')=='memory' and '正在整理本轮' in e.get('message','') for e in events)


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_first_image_uses_two_design_calls_and_one_review_without_memory_roundtrip(workspace, api):
    turn(workspace,'current','生成一个青花陶瓷杯')
    memory=ConversationMemoryService(workspace)
    memory.prepare_empty_selection('one','current')
    result,events=run(workspace,{'id':'unused'},{'id':'unused'},api,'fast_image',brief='生成一个青花陶瓷杯',
        constraints={'executionFlow':'design_review','agentCollaboration':True,'deliveryVerification':True})
    assert result.returncode==0,result.stderr+result.stdout[-6000:]
    final=next(e['result'] for e in events if e['type']=='result')
    assert final['provenance']['modelRequestCount']==3
    names=[item['name'] for item in final['tool_outputs']]
    assert names.count('generate_image')==1 and 'delivery_snapshot' not in names
    assert not set(names).intersection({'conversation_memory_read','conversation_memory_update','skill_list','design_plan'})
    calls=[json.loads(line) for line in (workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines()]
    assert len(calls)==1
    assert final['structured_data']['review']['summary']=='杯型完整，蓝白纹样清晰'


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_invalid_reference_loop_stops_as_tool_failure_before_provider_submission(workspace,api):
    logo,brooch=setup(workspace)
    update(ConversationMemoryService(workspace),'current',selected=['asset:'+logo['id']])
    result,events=run(workspace,logo,brooch,api,'invalid_references')
    assert result.returncode!=0
    error=next(e for e in reversed(events) if e['type']=='error')
    assert error['kind']=='tool',error['message']
    assert '参数校验' in error['message']
    failures=[t for t in error['recovery']['toolOutputs'] if t['output'].get('status')=='reference_mismatch']
    assert len(failures)==3
    assert all(t['output'].get('errors') for t in failures)
    assert not (workspace.workspace_root/'provider-calls.jsonl').exists()


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_reference_mismatch_is_reported_as_failure_and_stops_before_provider(workspace,api):
    logo,brooch=setup(workspace)
    update(ConversationMemoryService(workspace),'current',selected=['asset:'+logo['id']])
    result,events=run(workspace,logo,brooch,api,'reference_stalled')
    assert result.returncode!=0
    error=next(e for e in reversed(events) if e['type']=='error')
    assert error['kind']=='tool' and '参数校验' in error['message']
    failures=[t for t in error['recovery']['toolOutputs'] if t['output'].get('status')=='reference_mismatch']
    assert len(failures)==3
    tool_errors=[e for e in events if e.get('phase')=='error' and '工具失败：generate_image' in e.get('message','')]
    assert len(tool_errors)==3
    assert not any('工具完成：generate_image' in e.get('message','') for e in events)
    assert not (workspace.workspace_root/'provider-calls.jsonl').exists()


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_real_sdk_corrects_attachment_label_quote_using_server_evidence(workspace,api):
    logo,brooch=setup(workspace)
    result,events=run(workspace,logo,brooch,api,'source_repair')
    assert result.returncode==0,result.stderr+result.stdout[-4000:]
    # Memory validation remains in recovery evidence, not public progress.
    recovery=[e['recovery'] for e in events if e['type']=='checkpoint'][-1]
    updates=[t['output'] for t in recovery['toolOutputs'] if t['name']=='conversation_memory_update']
    failures=[output for output in updates if output.get('status')=='memory_invalid']
    assert len(failures)==1 and failures[0]['validation']['field']=='source.quote'
    assert sum(output.get('status')=='recorded' for output in updates)==1
    assert not any(e.get('phase') in {'error','tool'} and 'conversation_memory_update' in e.get('message','') for e in events)
    context=ConversationMemoryService(workspace).runtime('one','current')
    assert context['selected'][0]['source']['quote']=='这是原 Logo'
    assert len((workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines())==1


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('legacy_max_turns',[12,2])
def test_real_sdk_stops_rejected_memory_loop_as_tool_error_without_image_calls(workspace,api,legacy_max_turns):
    logo,brooch=setup(workspace)
    result,events=run(workspace,logo,brooch,api,'source_stalled',policy={'max_turns':legacy_max_turns})
    assert result.returncode!=0
    error=[e for e in events if e['type']=='error'][-1]
    assert error['kind']=='tool' and '停止重复修正同一错误' in error['message']
    assert len([t for t in error['recovery']['toolOutputs'] if t['name']=='conversation_memory_update'])==3
    assert error['recovery']['recoveryAttempts']['design']['total']==2
    assert not any('工具完成：conversation_memory_update' in e.get('message','') for e in events)
    assert not (workspace.workspace_root/'provider-calls.jsonl').exists()
    assert not ConversationMemoryService(workspace).runtime('one','current')['analyzed']


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_real_sdk_next_request_uses_memory_originals_and_batch_guard(workspace,api):
    logo,brooch=setup(workspace)
    result,events=run(workspace,logo,brooch,api)
    assert result.returncode==0,result.stderr+result.stdout[-6000:]
    assert any(e['type']=='result' for e in events)
    manifests=[e['manifest'] for e in events if e['type']=='context_manifest']
    assert any(m['memoryIds'] and m['inputImages']==1 for m in manifests)
    calls=[json.loads(line) for line in (workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines()]
    assert len(calls)==1 and calls[0]['quality']=='low' and calls[0]['size']=='1024x1536'
    assert calls[0]['input_fidelity']=='high'


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_real_sdk_fuses_inspiration_as_text_without_submitting_reference_pixels(workspace,api):
    logo,brooch=setup(workspace)
    result,events=run(workspace,logo,brooch,api,'inspiration')
    assert result.returncode==0,result.stderr+result.stdout[-6000:]
    calls=[json.loads(line) for line in (workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines()]
    assert len(calls)==1
    assert 'source_asset_path' not in calls[0] and 'source_asset_paths' not in calls[0]
    assert 'input_fidelity' not in calls[0]
    assert '杯身为蓝色图形、简洁平面构成' in calls[0]['prompt']
    assert '视觉反推描述' not in calls[0]['prompt'] and '本项融合方案' not in calls[0]['prompt']
    assert any(e['type']=='result' for e in events)


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('mode',['analysis_repair','analysis_stalled'])
def test_sdk_requires_visual_analysis_and_bounds_corrections_before_paid_calls(workspace,api,mode):
    logo,brooch=setup(workspace)
    result,events=run(workspace,logo,brooch,api,mode)
    if mode=='analysis_repair':
        assert result.returncode==0,result.stderr+result.stdout[-6000:]
        calls=[json.loads(line) for line in (workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines()]
        assert len(calls)==1 and '杯身为蓝色图形、简洁平面构成' in calls[0]['prompt']
        assert '视觉反推描述' not in calls[0]['prompt']
        assert 'source_asset_path' not in calls[0]
    else:
        assert result.returncode!=0
        error=next(e for e in reversed(events) if e['type']=='error')
        assert error['kind']=='tool',error['recovery'].get('recoveryAttempts')
        assert len([t for t in error['recovery']['toolOutputs'] if t['name']=='generate_image' and t['output'].get('status')=='reference_analysis_required'])==3
        assert not (workspace.workspace_root/'provider-calls.jsonl').exists()


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('model',['fixture','fixture-upgraded'])
def test_sdk_recovery_keeps_old_memory_version_and_paid_receipt(workspace,api,model):
    logo,brooch=setup(workspace)
    result,events=run(workspace,logo,brooch,api,'interrupt')
    assert result.returncode==0
    final=next(e['result'] for e in events if e['type']=='result')
    assert final['structured_data']['deliveryStatus']=='needs_review'
    recovery=final['provenance']['recovery']
    assert recovery['memoryIds'] and recovery['referenceSnapshots']
    turn(workspace,'later','停用蓝色')
    update(ConversationMemoryService(workspace),'later',[{'key':'brand.color','active':False,'source':{'quote':'停用蓝色'}}],[])
    resumed,events=run(workspace,logo,brooch,api,'resume',recovery,model=model)
    assert resumed.returncode==0,resumed.stderr+resumed.stdout[-6000:]
    assert len((workspace.workspace_root/'provider-calls.jsonl').read_text().splitlines())==1
    assert any(e['type']=='result' for e in events)
