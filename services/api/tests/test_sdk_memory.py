import json
import shutil
import subprocess
import threading
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.agent_sessions import AgentSessionStore
from app.project_context import ProjectContextResolver
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry
from app.execution_store import ExecutionStore
from app.model_catalog import ModelCatalog
from app.budget import BudgetService
from app.providers.http import ProviderError
from test_conversation_context import workspace, add_turn


def test_session_transactions_reopen_isolation_and_lock(workspace):
    add_turn(workspace, 'before', '原始需求')
    add_turn(workspace, 'current', '继续', status='running')
    add_turn(workspace, 'concurrent', '并发', status='running')
    session = AgentSessionStore(workspace)
    def call(action, **values): return session.dispatch('one','current',{'action':action, **values})
    acquired=call('acquire')
    assert acquired['items'][0]['content'][0]['text']=='原始需求'
    tx={'type':'append_items','items':[{'type':'message','role':'user','content':'新消息'}]}
    change={'transaction':tx,'operationId':'once','revision':acquired['revision']}
    assert call('mutate',**change)['revision']==1
    assert call('mutate',**change)['replayed']
    with pytest.raises(ValueError,match='主会话正在执行'):
        session.dispatch('one','concurrent',{'action':'acquire'})
    with pytest.raises(ValueError,match='不属于'):
        session.dispatch('two','current',{'action':'get'})
    reopened=AgentSessionStore(workspace).dispatch('one','current',{'action':'get'})
    assert len(reopened['items'])==3
    call('mutate',transaction={'type':'replace','items':[{'type':'compaction','encrypted_content':'opaque'}]},operationId='compact',revision=1)
    assert call('archive')['items']==reopened['items']
    call('release')
    assert session.dispatch('one','concurrent',{'action':'acquire'})['revision']==2


def test_evidence_inheritance_distinguishes_saved_body_and_summary(workspace):
    add_turn(workspace,'research','搜索航运新闻')
    add_turn(workspace,'current','汇总成网页报告',status='running')
    receipts=ExecutionStore(workspace)
    receipts.save('research',{'toolOutputs':[
        {'name':'web_search','output':{'sources':[{'url':'https://example.com/news','title':'航运新闻','snippet':'76 人'}]}},
        {'name':'web_read','output':{'sourceId':'saved','url':'https://example.com/imo','title':'机构资料','text':'75 起事件','fetchedAt':'2026-09-14T00:00:00Z'}}]})
    packet=ProjectContextResolver(workspace).build('one','current','汇总成网页报告')
    values={r['url']:r for r in packet['evidence']}
    assert values['https://example.com/news']['evidenceType']=='search_summary'
    assert values['https://example.com/imo']['evidenceType']=='web_body'
    assert packet['clock']['timezone']=='Asia/Shanghai'
    assert 'nowUtc' in packet['clock']
    assert ProjectContextResolver(workspace).evidence('one','current',ids=['foreign'])==[]


def test_node_version_prevents_stale_write_and_allows_reread(workspace):
    from app.node_context import observe, active_task
    canvas=CanvasStore(workspace)
    node=canvas.create_node('one',kind='text',title='原文',data={'text':'版本一'})
    observe(workspace,'one','task',[node])
    canvas.update_node('one',node['id'],{'data':{'text':'用户修改'}})
    token=active_task.set('task')
    try:
        with pytest.raises(ValueError,match='已在读取后改变'):
            canvas.update_node('one',node['id'],{'data':{'text':'旧任务覆盖'}})
        observe(workspace,'one','task',canvas.load('one')['nodes'])
        canvas.update_node('one',node['id'],{'data':{'text':'基于用户最新内容修改'}})
    finally: active_task.reset(token)


def test_repair_budget_quota_unknown_prices_and_reservations(workspace):
    add_turn(workspace,'current','修复报告',status='running')
    catalog=ModelCatalog(workspace)
    settings=catalog.settings().model_dump(mode='json')
    key=catalog.price_key('openrouter','https://example.com/v1','fixture')
    settings['prices'][key]={'currency':'CNY','perRequest':.3}
    from app.model_config import ModelSettings
    catalog.save_settings(ModelSettings.model_validate(settings))
    budget=BudgetService(workspace,catalog)
    assert budget.repair_control('current','begin',['node'])['allowed']
    args={'provider':'openrouter','base_url':'https://example.com/v1','model':'fixture','kind':'text','units':{'requests':1}}
    reserved=budget.reserve('current',**args)
    assert reserved['estimatedPoints']==30
    with pytest.raises(ProviderError,match='50 积分'): budget.reserve('current',**args)
    budget.settle('current',reserved['reservationId'],5)
    assert budget.reserve('current',**args)['estimatedPoints']==30
    with pytest.raises(ProviderError,match='缺少价格'): budget.reserve('current',**{**args,'model':'unknown'})
    budget.guard_repair_tool('current','web_search',{})
    with pytest.raises(ProviderError,match='次数'): budget.guard_repair_tool('current','web_search',{})
    with pytest.raises(ProviderError,match='已有节点'): budget.guard_repair_tool('current','generate_image',{})
    budget.repair_control('current','finish')
    assert not budget.repair_control('current','begin')['allowed']


@pytest.mark.parametrize('api',['responses','chat_completions'])
def test_real_sdk_session_survives_worker_restart(workspace,api):
    session=AgentSessionStore(workspace)
    captured=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/agent-session'):
                result=session.dispatch('one',self.headers['x-aics-task-id'],body)
                payload=json.dumps(result).encode(); mime='application/json'
            else:
                captured.append(body)
                text='记得你的名字是 Alexi。'
                identity=f'model-{len(captured)}'
                if api=='responses':
                    output={'type':'message','id':identity,'role':'assistant','status':'completed','content':[{'type':'output_text','text':text,'annotations':[]}]}
                    response={'id':identity,'object':'response','model':'fixture','status':'completed','output':[output],'usage':{'input_tokens':10,'output_tokens':8,'total_tokens':18}}
                    events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}}, {'type':'response.output_item.added','output_index':0,'item':output}, {'type':'response.output_item.done','output_index':0,'item':output}, {'type':'response.completed','response':response}]
                    payload=''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events).encode()
                else:
                    def chunk(delta,reason=None): return {'id':identity,'object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':reason}]}
                    payload=(''.join('data: '+json.dumps(e)+'\n\n' for e in [chunk({'role':'assistant','content':text}),chunk({},'stop')])+'data: [DONE]\n\n').encode()
                mime='text/event-stream'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    worker=Path(__file__).parents[1]/'app/openai_agent_worker.mjs'
    try:
        for task_id,brief in [('first','我的名字是 Alexi'),('second','我叫什么？')]:
            add_turn(workspace,task_id,brief,status='running')
            payload={'persistentSessions':True,'provider':'openrouter' if api=='chat_completions' else 'openai-compatible','api':api,'apiKey':'secret-not-in-checkpoint','model':'fixture','baseUrl':url+'/v1',
                     'toolGateway':{'baseUrl':url,'projectId':'one','taskId':task_id},'context':{'projectId':'one','taskId':task_id,'brief':brief,'constraints':{'simpleConversation':True}}}
            result=subprocess.run([shutil.which('node'),str(worker)],input=json.dumps(payload),text=True,capture_output=True,timeout=20)
            assert result.returncode==0,result.stdout[-3000:]+result.stderr
            assert 'secret-not-in-checkpoint' not in result.stdout
            with workspace._connect() as db: db.execute("UPDATE tasks SET status='succeeded' WHERE id=?",(task_id,))
        serialized=json.dumps(captured[-1],ensure_ascii=False)
        assert '我的名字是 Alexi' in serialized
        assert serialized.count('我叫什么？')==1
        assert len(captured)==2
        assert len(session.dispatch('one','second',{'action':'get'})['items'])==4
    finally:
        server.shutdown();server.server_close()


@pytest.mark.parametrize('api,provider',[('responses','openai-compatible'),('chat_completions','openrouter'),('chat_completions','closeai')])
def test_saved_artifact_finishes_needs_review_without_resubmitting_tool(workspace,api,provider):
    add_turn(workspace,'current','生成说明',status='running',extra={'agentCollaboration':False})
    sessions=AgentSessionStore(workspace)
    registry=DesignToolRegistry(workspace)
    calls=[]; mutations=[]; fail=[True]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            mime='application/json';status=200
            if self.path.endswith('/agent-session'):
                payload=json.dumps(sessions.dispatch('one','current',body)).encode()
            elif '/agent-tools/' in self.path:
                name=self.path.rsplit('/',1)[1]
                if name.startswith('canvas_create'): mutations.append(name)
                payload=json.dumps(registry.execute(project_id='one',task_id='current',name=name,arguments=body)).encode()
            else:
                calls.append(body)
                if len(calls)==2 and fail[0]:
                    status=503;payload=b'{"error":{"message":"simulated interruption"}}'
                else:
                    identity=f'response-{len(calls)}'
                    output=({'type':'function_call','id':'call','call_id':'call','name':'canvas_create_text','arguments':json.dumps({'text':'实际产物','title':'说明'}),'status':'completed'} if len(calls)==1 else
                            {'type':'message','id':identity,'role':'assistant','status':'completed','content':[{'type':'output_text','text':'已生成说明','annotations':[]}]})
                    response={'id':identity,'object':'response','model':'fixture','status':'completed','output':[output],'usage':{'input_tokens':10,'output_tokens':8,'total_tokens':18}}
                    events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}}, {'type':'response.output_item.added','output_index':0,'item':output}, {'type':'response.output_item.done','output_index':0,'item':output}, {'type':'response.completed','response':response}]
                    payload=''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events).encode();mime='text/event-stream'
                    if api=='chat_completions':
                        delta=({'role':'assistant','tool_calls':[{'index':0,'id':'call','type':'function','function':{'name':output['name'],'arguments':output['arguments']}}]} if len(calls)==1 else {'role':'assistant','content':'已生成说明'})
                        chunk=lambda delta,reason=None: {'id':identity,'object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':reason}]}
                        chunks=[chunk(delta),chunk({},'tool_calls' if len(calls)==1 else 'stop'),{**chunk({}),'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18}}]
                        payload=(''.join(f'data: {json.dumps(e)}\n\n' for e in chunks)+'data: [DONE]\n\n').encode()
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}'
    payload={'persistentSessions':True,'api':api,'provider':provider,'apiKey':'fixture','model':'fixture','baseUrl':url+'/v1',
             'toolGateway':{'baseUrl':url,'projectId':'one','taskId':'current'},'context':{'projectId':'one','taskId':'current','brief':'生成说明','constraints':{'agentCollaboration':False}}}
    worker=Path(__file__).parents[1]/'app/openai_agent_worker.mjs'
    def run(): return subprocess.run([shutil.which('node'),str(worker)],input=json.dumps(payload),text=True,capture_output=True,timeout=20)
    try:
        first=run()
        assert first.returncode==0,([json.loads(line).get('message') for line in first.stdout.splitlines() if line.startswith('{\"type\":\"error\"')],first.stderr)
        final=[json.loads(line) for line in first.stdout.splitlines() if line.startswith('{"type":"result"')][-1]
        assert final['result']['structured_data']['deliveryStatus']=='needs_review'
        assert mutations==['canvas_create_text']
        assert len(CanvasStore(workspace).load('one')['nodes'])==1
        items=calls[-1]['input' if api=='responses' else 'messages']
        assert sum(1 for item in items if item.get('role')=='user' and any(p.get('text')=='生成说明' for p in item.get('content',[])))==1
    finally: server.shutdown();server.server_close()


@pytest.mark.parametrize('enabled,failure,base,expected,simple',[
    (False,False,'https://api.openai.com/v1',0,True),
    (True,False,'https://api.openai.com/v1',1,False),
    (True,True,'https://api.openai.com/v1',1,False),
    (True,False,'https://openrouter.ai/api/v1',0,False),
    (True,False,'https://api.closeai.com/v1',0,False),
])
def test_official_compaction_opt_in_billing_fallback_and_switch(workspace,tmp_path,enabled,failure,base,expected,simple):
    add_turn(workspace,'history','重要需求：品牌蓝色。'+'旧研究资料。'*4000)
    add_turn(workspace,'current','记得品牌吗？',status='running')
    root=Path(__file__).parents[1];fixtures=root/'tests/fixtures'
    log=tmp_path/'requests.jsonl'
    env={**os.environ,'PYTHONPATH':str(root),'FIXTURE_WORKSPACE':str(workspace.workspace_root),
         'FIXTURE_PYTHON':sys.executable,'FIXTURE_REQUEST_LOG':str(log)}
    if failure: env['FIXTURE_COMPACTION_FAILURE']='1'
    payload={'persistentSessions':True,'memorySettings':{'compactionEnabled':enabled},'api':'responses','apiKey':'secret-configuration','model':'gpt-fixture','baseUrl':base,
             'toolGateway':{'baseUrl':'http://fixture.invalid','projectId':'one','taskId':'current'},
             'context':{'projectId':'one','taskId':'current','brief':'记得品牌吗？','constraints':{
                 'simpleConversation':simple,'executionFlow':'direct','agentCollaboration':False,'deliveryVerification':False,
                 **({'requiredArtifacts':['text']} if not simple else {}),
             }}}
    def run():
        result=subprocess.run([shutil.which('node'),'--import',str(fixtures/'compaction_transport.mjs'),str(root/'app/openai_agent_worker.mjs')],input=json.dumps(payload),text=True,capture_output=True,env=env,timeout=20)
        assert result.returncode==0,result.stdout[-2500:]+result.stderr
        assert 'secret-configuration' not in result.stdout
        return [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    events=run()
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert len([c for c in calls if c['url'].endswith('/compact')])==expected
    charged=[e for e in events if e['type']=='usage' and e.get('stage')=='compaction']
    assert len(charged)==(1 if expected and not failure else 0)
    if charged: assert charged[0]['reservationId']=='compact-budget'
    if charged:
        assert any(e['type']=='context_manifest' and e['manifest']['stage']=='compaction' and e['manifest']['id']==charged[0]['manifestId'] for e in events)
    store=AgentSessionStore(workspace)
    raw=store.dispatch('one','current',{'action':'archive'})['items']
    assert '重要需求' in json.dumps(raw,ensure_ascii=False)
    if expected and failure:
        payload['recovery']=next(event['recovery'] for event in reversed(events) if event['type']=='checkpoint')
        env['FIXTURE_RUN_ID']='resumed'
        resumed=run()
        calls=[json.loads(line) for line in log.read_text().splitlines()]
        assert len([c for c in calls if c['url'].endswith('/compact')]) == 1
        assert not any(event['type']=='usage' and event.get('stage')=='compaction' for event in resumed)
        assert payload['recovery']['compactionDisabled'] is True
    if expected and not failure:
        stored=store.dispatch('one','current',{'action':'get'})
        assert any(i.get('type')=='compaction' for i in stored['items'])
        assert stored['compactionSignature']
        # A different vendor receives the original replay, not opaque OpenAI state.
        with workspace._connect() as db: db.execute("UPDATE tasks SET status='succeeded' WHERE id='current'")
        add_turn(workspace,'switch','继续',status='running')
        payload.update(baseUrl='https://closeai.fixture/v1',memorySettings={'compactionEnabled':False})
        payload['toolGateway']['taskId']='switch';payload['context'].update(taskId='switch',brief='继续')
        env['FIXTURE_RUN_ID']='switch'
        run()
        calls=[json.loads(line) for line in log.read_text().splitlines()]
        assert 'opaque-openai-fixture' not in json.dumps([c for c in calls if 'closeai.fixture' in c['url']])
        assert not any(i.get('type')=='compaction' for i in store.dispatch('one','switch',{'action':'get'})['items'])


def test_web_body_can_support_parameters_but_model_answer_and_search_cannot(workspace):
    from app.content_facts import fact_sources
    add_turn(workspace,'research','船舶资料',answer='模型猜测 900 米')
    add_turn(workspace,'current','整理报告',status='running')
    ExecutionStore(workspace).save('research',{'toolOutputs':[
        {'name':'web_search','output':{'sources':[{'url':'https://example.com/summary','snippet':'999 米'}]}},
        {'name':'web_read','output':{'sourceId':'body','url':'https://example.com/body','text':'已查阅正文：长度 75 米'}}]})
    values=set().union(*(set(s['values']) for s in fact_sources(workspace,'one','current')))
    assert '75米' in values and '900米' not in values and '999米' not in values


def test_review_notes_belong_to_artifact_version_and_diagnostics_exclude_secrets(workspace):
    from app.delivery import DeliveryService
    canvas=CanvasStore(workspace);delivery=DeliveryService(workspace)
    node=canvas.create_node('one',kind='html',title='报告',data={'html':'<p>需核实的内容</p>'})
    add_turn(workspace,'report','汇总报告',output={'structured_data':{'deliveryStatus':'needs_review',
        'delivery':{'artifacts':[{'nodeId':node['id'],'fingerprint':delivery.fingerprint(node)}]},
        'review':{'issues':['需要正文证据']}}})
    from app.delivery_findings import annotate_delivery
    data = {'delivery':delivery.inspect('one','report'),'review':{'issues':['需要正文证据']}}
    assert annotate_delivery(data) == []
    assert 'review' not in data
    store=AgentSessionStore(workspace)
    store.manifest('report',{'id':'call','stage':'design','evidenceIds':['source'],'apiKey':'secret','reasoning':'private','prompt':'raw'})
    store.record_cost('report','call',3,'ledger')
    with workspace._connect() as db:
        value=json.loads(db.execute("SELECT payload FROM sdk_context_manifests WHERE id='call'").fetchone()[0])
    assert value=={'id':'call','stage':'design','evidenceIds':['source'],'actualPoints':3,'ledgerId':'ledger'}


def test_explicit_reference_does_not_inherit_unrelated_recent_research(workspace):
    add_turn(workspace,'research','研究船舶趋势',output={'structured_data':{'sources':[{'url':'https://example.com/unrelated','snippet':'另一份报告'}]}})
    add_turn(workspace,'current','修改这张插图',status='running',extra={'referencedAssets':[{'id':'specific-image'}]})
    assert ProjectContextResolver(workspace).evidence('one','current','修改这张插图')==[]
