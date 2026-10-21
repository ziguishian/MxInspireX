import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from test_delivery_contract import workspace, task
from app.agent_contracts import AgentResult
from app.design_tools import DesignToolRegistry, DesignToolError
from app.knowledge import KnowledgeStore
from app.task_focus import TaskFocus, whole_canvas_requested
from app.task_runtime import TaskRuntime


def asset(workspace, color='red'):
    raw = io.BytesIO()
    Image.new('RGB',(16,16),color).save(raw,format='PNG')
    return workspace[2].add_bytes(project_id=workspace[1],kind='image',filename=color+'.png',content=raw.getvalue())


def test_reference_uses_current_node_and_exact_placement_not_all_canvas(workspace):
    store, project, assets, canvas = workspace
    image = asset(workspace)
    first = canvas.create_node(project,kind='image',title='目标',asset_id=image['id'])
    other = canvas.create_node(project,kind='image',title='其他位置',asset_id=image['id'])
    canvas.create_node(project,kind='html',title='无关',data={'html':'UNRELATED_HTML'*10000})
    context = {'userMessage':'修改引用配色','referencedNodes':[{'id':first['id'],'data':{'title':'STALE_CLIENT'}}],
               'referencedAssets':[{'id':image['id'],'projectId':project,'nodeId':first['id']}]}
    task(store,project,context=context)
    focus = TaskFocus(store,canvas).resolve(project,'task',context)
    assert focus['nodeIds']==[first['id']]
    assert focus['assetReferences']==[{'assetId':image['id'],'projectId':project}]
    tools = DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    read = tools.execute(project_id=project,task_id='task',name='canvas_read',arguments={})
    assert [node['id'] for node in read['canvas']['nodes']]==[first['id']]
    assert not any(value in json.dumps(read) for value in ('UNRELATED_HTML','STALE_CLIENT',other['id']))
    with pytest.raises((ValueError,DesignToolError),match='已有明确引用'):
        tools.execute(project_id=project,task_id='task',name='canvas_read',arguments={'scope':'discover'})


def test_missing_reference_never_substitutes_an_unrelated_node(workspace):
    store, project, _, canvas = workspace
    unrelated = canvas.create_node(project,kind='text',title='其他文案',data={'text':'不得误改'})
    context = {'userMessage':'修改 @node:missing-node'}
    task(store,project,context=context)
    focus = TaskFocus(store,canvas).resolve(project,'task',context)
    assert focus['hasReferences'] and focus['missingNodeIds']==['missing-node']
    assert focus['nodeIds']==[]
    assert TaskFocus(store,canvas).read(project,'task',context)['canvas']['nodes']==[]
    assert canvas.load(project)['nodes'][0]==unrelated


@pytest.mark.parametrize('image_node', [False, True])
def test_html_from_image_reference_defaults_to_new_page(workspace, image_node):
    store, project, assets, canvas = workspace
    image = asset(workspace)
    node = canvas.create_node(project, kind='image', title='商品图', asset_id=image['id']) if image_node else None
    context = {'userMessage':'用这张图片创建一个HTML详情页', 'referencedAssets':[{'id':image['id'],'projectId':project}]}
    if node: context['referencedNodes'] = [{'id':node['id']}]
    task(store, project, context=context)
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    args = tools._focused_arguments(project, 'task', 'canvas_create_html', {'html':'<h1>商品详情</h1>'})
    assert args['output_mode'] == 'create' and 'canvas_node_id' not in args


def test_html_reference_still_requires_explicit_edit_or_create(workspace):
    store, project, assets, canvas = workspace
    node = canvas.create_node(project, kind='html', title='已有网页', data={'html':'<p>保留</p>'})
    task(store, project, context={'userMessage':'修改这个网页','referencedNodes':[{'id':node['id']}]})
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    with pytest.raises(DesignToolError, match='区分修改对象'):
        tools._focused_arguments(project, 'task', 'canvas_create_html', {'html':'<h1>不能猜目标</h1>'})


def test_no_reference_uses_latest_edit_receipt_before_discovery(workspace):
    store, project, assets, canvas = workspace
    task(store,project,context={'userMessage':'第一轮生成文案'})
    node = canvas.create_node(project,kind='text',title='品牌文案',data={'text':'原文'})
    tools = DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    tools.execute(project_id=project,task_id='task',name='canvas_update_node',arguments={'node_id':node['id'],'patch':{'data':{'text':'上一轮改好的文案'}}})
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded' WHERE id='task'")
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','running',?,'now','now')",('followup',project,json.dumps({'userMessage':'修改刚才的内容'})))
    context = {'userMessage':'修改刚才的内容'}
    focus = TaskFocus(store,canvas).resolve(project,'followup',context)
    assert focus['mode']=='context' and focus['nodeIds']==[node['id']]
    assert focus['nodes'][0]['data']['text']=='上一轮改好的文案'


def test_discovery_returns_small_directory_and_scoped_reads_page_bodies(workspace):
    store, project, _, canvas = workspace
    nodes = [canvas.create_node(project,kind='html',title=f'网页{i}',data={'html':'BODY'*4000}) for i in range(11)]
    task(store,project)
    service = TaskFocus(store,canvas)
    assert service.read(project,'task',{})['canvas']['nodes']==[]
    directory = service.read(project,'task',{},query='网页')
    assert directory['scope']=='discover' and len(directory['canvas']['nodes'])==6
    assert directory['nextOffset'] is None and 'BODY' not in json.dumps(directory)
    with pytest.raises(ValueError,match='逐页'):
        service.read(project,'task',{},query='网页',offset=6)
    first = service.read(project,'task',{},node_ids=[nodes[9]['id']])
    assert len(first['canvas']['nodes'][0]['data']['html'])==12000
    assert first['canvas']['nodes'][0]['nextTextOffset']==12000
    second = service.read(project,'task',{},node_ids=[nodes[9]['id']],text_offset=12000)
    assert second['canvas']['nodes'][0]['data']['html']=='BODY'*1000


def test_mutations_and_recovery_never_return_unrelated_canvas_to_agent(workspace):
    store, project, assets, canvas = workspace
    task(store,project)
    canvas.create_node(project,kind='text',title='不相关',data={'text':'UNRELATED_CONTENT'})
    tools = DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    args = {'text':'本轮文案'}
    first = tools.execute(project_id=project,task_id='task',name='canvas_create_text',arguments=args)
    recovered = tools.execute(project_id=project,task_id='task',name='canvas_create_text',arguments=args)
    assert first==recovered and 'canvas' not in first
    assert 'UNRELATED_CONTENT' not in json.dumps(first)
    read = tools.execute(project_id=project,task_id='task',name='canvas_read',arguments={'scope':'outputs'})
    assert [n['id'] for n in read['canvas']['nodes']]==[first['node']['id']]
    ui = tools.execute(project_id=project,task_id=None,name='canvas_create_text',arguments={'text':'UI操作'})
    assert len(ui['canvas']['nodes'])==3


def test_asset_search_without_query_only_returns_references(workspace):
    store, project, assets, canvas = workspace
    selected, unrelated = asset(workspace), asset(workspace,'blue')
    task(store,project,context={'referencedAssets':[{'id':selected['id']}]})
    tools = DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    result = tools.execute(project_id=project,task_id='task',name='asset_search',arguments={})
    assert [a['id'] for a in result['results']]==[selected['id']]
    assert unrelated['id'] not in json.dumps(result)


def test_runtime_native_reference_keeps_ids_and_skips_automatic_research(workspace, monkeypatch):
    monkeypatch.delenv('AICS_TEST_MODE',raising=False)
    store, project, assets, canvas = workspace
    selected = asset(workspace)
    node = canvas.create_node(project,kind='image',title='参考图',asset_id=selected['id'])
    knowledge = KnowledgeStore(store)
    monkeypatch.setattr(knowledge,'vector_search_for_project',lambda **kw: pytest.fail('引用明确时不应自动检索'))
    captured = []
    def run(**kwargs):
        captured.append(kwargs)
        return AgentResult(status='succeeded',structured_data={'answer':'已处理引用内容'})
    providers = SimpleNamespace(catalog=None,text=lambda *a,**kw:SimpleNamespace(model='fixture'))
    runtime = TaskRuntime(store,asset_store=assets,knowledge_store=knowledge,provider_registry=providers,design_runtime=SimpleNamespace(run=run))
    result = runtime.enqueue(project_id=project,agent_key='design',workflow_step='design',brief='修改引用图像',input_data={
        'textProvider':{'key':'fixture'},'referencedNodes':[{'id':node['id']}],
        'focusContext':{'nodeIds':['UNTRUSTED_CLIENT']}})
    assert result['status']=='succeeded',result
    params = captured[0]
    assert params['attachments'][0]['assetId']==selected['id']
    assert params['attachments'][0]['data'] and params['constraints']['focusContext']['nodeIds']==[node['id']]
    assert 'UNTRUSTED_CLIENT' not in json.dumps(params['constraints'])


def test_uploaded_image_can_be_edited_and_is_reused_after_restart(workspace):
    store, project, assets, canvas = workspace
    root = Path(store.get_project(project)['rootPath'])
    root.mkdir(parents=True,exist_ok=True)
    Image.new('RGB',(8,8),'green').save(root/'reference.png')
    refs = [{'pathRelative':'reference.png','index':1}]
    def resolve():
        return TaskRuntime(store,asset_store=assets,knowledge_store=KnowledgeStore(store))._resolve_file_attachments(project,refs)
    first, second = resolve()[0], resolve()[0]
    assert first['assetId']==second['assetId'] and first['projectId']==project
    assert first['mention']=='@1' and first['data']
    assert len(assets.list_assets(project))==1 and canvas.load(project)['nodes']==[]


@pytest.mark.parametrize('legacy_checkpoint',[False,True])
def test_real_sdk_edits_original_and_reviewer_only_reads_current_output(workspace,legacy_checkpoint):
    store, project, _, canvas = workspace
    selected = canvas.create_node(project,kind='text',title='引用文案',data={'text':'待修改的文案'})
    unrelated = [canvas.create_node(project,kind='html',title=f'其他{i}',data={'html':'UNRELATED_CONTENT'*500}) for i in range(12)]
    context = {'userMessage':'修改引用的文案','referencedNodes':[{'id':selected['id']}]}
    task(store,project,context=context)
    focus = TaskFocus(store,canvas).resolve(project,'task',context)
    root = Path(__file__).resolve().parents[1]
    payload = {'api':'responses','model':'fixture','apiKey':'fixture','baseUrl':'http://fixture.invalid/v1',
               'context':{'projectId':project,'taskId':'task','brief':context['userMessage'],
                          'constraints':{'executionFlow':'design_review','focusContext':focus}}}
    if legacy_checkpoint:
        snapshot={'canvas':canvas.load(project)}
        payload['recovery']={'toolOutputs':[{'name':'canvas_read','args':{},'output':snapshot}],
            'sessions':{'design':[{'type':'function_call','id':'old','callId':'old','name':'canvas_read','arguments':'{}'},
                                  {'type':'function_call_result','callId':'old','name':'canvas_read','status':'completed','output':json.dumps(snapshot)}]}}
    env = {**os.environ,'PYTHONPATH':str(root),'FIXTURE_PYTHON':sys.executable,'FIXTURE_TOOL_SCRIPT':str(root/'tests/fixtures/agent_tool_fixture.py'),
           'FIXTURE_WORKSPACE':str(store.workspace_root),'FIXTURE_PROJECT':project,'FIXTURE_TASK':'task','FIXTURE_TARGET':selected['id']}
    result = subprocess.run([shutil.which('node'),'--import',str(root/'tests/fixtures/focus_transport.mjs'),str(root/'app/openai_agent_worker.mjs')],input=json.dumps(payload),text=True,capture_output=True,timeout=30,env=env)
    assert result.returncode==0,result.stderr+result.stdout[-5000:]
    nodes = canvas.load(project)['nodes']
    assert len(nodes)==13 and nodes[0]['id']==selected['id']
    assert nodes[0]['data']['text']=='已按要求修改引用文案'
    assert nodes[1:]==unrelated


@pytest.mark.parametrize('text', ['不要遍历整个画布','不需要你读取整个画布','其他所有节点保持不变','避免读取所有节点','只修改引用，不要遍历所有画布内容','do not scan the whole canvas'])
def test_negative_overview_instruction_does_not_expand_scope(text):
    assert not whole_canvas_requested(text)


def test_reference_scope_cannot_be_bypassed_with_ids_outputs_or_asset_search(workspace):
    store,project,assets,canvas=workspace
    selected,other=asset(workspace),asset(workspace,'blue')
    target=canvas.create_node(project,kind='image',title='引用',asset_id=selected['id'])
    unrelated=canvas.create_node(project,kind='image',title='无关',asset_id=other['id'])
    context={'userMessage':'改这个，不要遍历整个画布','referencedNodes':[{'id':target['id']}]}
    task(store,project,context=context)
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    for name,args in [('canvas_read',{'node_ids':[unrelated['id']]}),('canvas_read',{'scope':'outputs','node_ids':[unrelated['id']]}),
                      ('asset_inspect',{'asset_id':other['id']}),('canvas_update_node',{'node_id':unrelated['id'],'patch':{'data':{'title':'错误修改'}}})]:
        with pytest.raises(ValueError,match='无关画布'):
            tools.execute(project_id=project,task_id='task',name=name,arguments=args)
    assert tools.execute(project_id=project,task_id='task',name='asset_search',arguments={'query':other['id']})['results']==[]
    assert canvas.load(project)['nodes'][1]==unrelated


def test_model_must_choose_target_and_can_create_from_reference_without_overwrite(workspace):
    store,project,assets,canvas=workspace
    reference=canvas.create_node(project,kind='text',title='资料',data={'text':'参考资料'})
    target=canvas.create_node(project,kind='text',title='待修改文案',data={'text':'原文'})
    task(store,project,context={'userMessage':'根据引用资料修改文案','referencedNodes':[{'id':reference['id']},{'id':target['id']}]})
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    for args in [{'text':'误新建'}, {'text':'误覆盖','output_mode':'edit'}]:
        with pytest.raises(DesignToolError,match='明确'):
            tools.execute(project_id=project,task_id='task',name='canvas_create_text',arguments=args)
    result=tools.execute(project_id=project,task_id='task',name='canvas_create_text',arguments={'text':'修改后的文案','canvas_node_id':target['id'],'output_mode':'edit'})
    assert result['node']['id']==target['id']
    created=tools.execute(project_id=project,task_id='task',name='canvas_create_text',arguments={'text':'参考派生文案','output_mode':'create'})
    assert created['node']['id'] not in {reference['id'],target['id']}
    assert canvas.load(project)['nodes'][0]==reference


@pytest.mark.parametrize('previous_status',['succeeded','failed','cancelled'])
def test_context_without_edit_keyword_remembers_previously_discussed_reference(workspace,previous_status):
    store,project,_,canvas=workspace
    selected=canvas.create_node(project,kind='text',title='文案',data={'text':'上一版'})
    task(store,project,context={'userMessage':'看看这个','referencedNodes':[{'id':selected['id']}]})
    with store._connect() as db:
        db.execute("UPDATE tasks SET status=? WHERE id='task'",(previous_status,))
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','running',?,'now','now')",('next',project,json.dumps({'userMessage':'再简洁一点'})))
    focus=TaskFocus(store,canvas).resolve(project,'next',{'userMessage':'再简洁一点'})
    assert focus['mode']=='context' and focus['nodeIds']==[selected['id']]
    assert focus['contextTaskStatus']==previous_status


def test_multiple_context_candidates_are_not_read_as_full_bodies(workspace):
    store,project,_,canvas=workspace
    nodes=[canvas.create_node(project,kind='html',title=f'版本{i}',data={'html':'PRIVATE_BODY'*100}) for i in range(2)]
    context={'userMessage':'再简洁一点'}
    task(store,project,context=context)
    history={'recentOutcomes':[{'status':'succeeded','artifacts':[{'nodeId':n['id']} for n in nodes]}]}
    focus=TaskFocus(store,canvas).resolve(project,'task',context,history)
    assert focus['selectionRequired'] and 'PRIVATE_BODY' not in json.dumps(focus)


def test_global_document_is_read_by_id_and_image_is_editable(workspace):
    store,project,assets,canvas=workspace
    knowledge=KnowledgeStore(store)
    doc=knowledge.ingest_global_file(filename='brief.txt',content='把按钮改为绿色'.encode())
    data=io.BytesIO();Image.new('RGB',(8,8),'purple').save(data,format='PNG')
    image=knowledge.ingest_global_file(filename='reference.png',content=data.getvalue())
    refs=[{'scope':'global','documentId':d['documentId'],'pathRelative':'untrusted/path'} for d in (doc,image)]
    runtime=TaskRuntime(store,asset_store=assets,knowledge_store=knowledge)
    attachments=runtime._resolve_file_attachments(project,refs)
    assert attachments[0]['text']=='把按钮改为绿色'
    assert attachments[0]['mention']==f"@knowledge:{doc['documentId']}"
    assert attachments[1]['data'] and attachments[1]['assetId']
    task(store,project,context={'referencedFiles':refs})
    TaskFocus(store,canvas).validate_ids(project,'task',{'referencedFiles':refs},asset_ids=[attachments[1]['assetId']])
    assert runtime._resolve_file_attachments(project,[{'scope':'global','documentId':'missing','pathRelative':doc['pathRelative']}])==[]


def test_image_edit_uses_selected_original_and_retry_reuses_receipt(workspace,monkeypatch):
    monkeypatch.delenv('AICS_TEST_MODE',raising=False)
    store,project,assets,canvas=workspace
    original,style=asset(workspace),asset(workspace,'blue')
    target=canvas.create_node(project,kind='image',title='目标',asset_id=original['id'])
    reference=canvas.create_node(project,kind='image',title='风格参考',asset_id=style['id'])
    task(store,project,context={'userMessage':'参考蓝色图的风格，把目标改成紫色','referencedNodes':[{'id':target['id']},{'id':reference['id']}]})
    data=io.BytesIO();Image.new('RGB',(16,16),'purple').save(data,format='PNG')
    calls=[]
    def generate(**kwargs): calls.append(kwargs); return data.getvalue()
    providers=SimpleNamespace(catalog=None,image=lambda *a,**kw:SimpleNamespace(generate=generate,last_response={}))
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas,provider_registry=providers)
    args={'prompt':'把主体改为紫色，保留构图','canvas_node_id':target['id']}
    first=tools.execute(project_id=project,task_id='task',name='generate_image',arguments=args)
    reopened=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas,provider_registry=providers)
    assert reopened.execute(project_id=project,task_id='task',name='generate_image',arguments=args)==first
    assert len(calls)==1 and calls[0]['source_asset_path']==assets.get_asset(project_id=project,asset_id=original['id'])['absolutePath']
    assert first['node']['id']!=target['id'] and first['assetId']!=original['id']
    board={node['id']:node for node in canvas.load(project)['nodes']}
    assert board[target['id']]['data']['assetId']==original['id']
    assert board[reference['id']]==reference and len(board)==3


def test_cross_project_reference_has_local_editable_id_and_preserves_original(workspace,tmp_path):
    from app.main import new_project
    store,project,assets,canvas=workspace
    foreign=store.create_project(new_project(name='素材来源',slug='foreign',brief='',budget_minor=None,currency='CNY',root_path=str(tmp_path/'foreign')))['id']
    data=io.BytesIO();Image.new('RGB',(8,8),'gold').save(data,format='PNG')
    source=assets.add_bytes(project_id=foreign,kind='image',filename='shared.png',content=data.getvalue())
    refs=[{'id':source['id'],'projectId':foreign}]
    runtime=TaskRuntime(store,asset_store=assets)
    first=runtime._resolve_attachments(project,refs)[0]
    second=runtime._resolve_attachments(project,refs)[0]
    assert first['projectId']==project and first['assetId']==second['assetId']!=source['id']
    assert first['reference']=={'projectId':foreign,'assetId':source['id']} and first['data']
    context={'referencedAssets':refs,'userMessage':f"修改 @asset:{source['id']}"}
    task(store,project,context=context)
    assert TaskFocus(store,canvas).resolve(project,'task',context)['assetReferences']==[{'assetId':source['id'],'projectId':foreign}]
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    prepared=tools._focused_arguments(project,'task','generate_image',{'output_mode':'edit','prompt':'改颜色','source_asset_id':first['assetId']})
    assert prepared['source_asset_id']==first['assetId']
    assert Path(assets.get_asset(project_id=foreign,asset_id=source['id'])['absolutePath']).read_bytes()==data.getvalue()


def test_explicit_overview_is_allowed_but_outputs_stays_current_task_only(workspace):
    store,project,assets,canvas=workspace
    old=canvas.create_node(project,kind='text',title='旧节点',data={'text':'旧内容'})
    current=canvas.create_node(project,kind='text',title='本轮节点',task_id='task',data={'text':'新内容'})
    context={'userMessage':'请整理整个画布的所有节点'}
    task(store,project,context=context)
    service=TaskFocus(store,canvas)
    assert service.read(project,'task',context,scope='discover')['total']==2
    assert service.read(project,'task',context,scope='outputs',node_ids=[old['id']])['canvas']['nodes']==[]
    assert [n['id'] for n in service.read(project,'task',context,scope='outputs')['canvas']['nodes']]==[current['id']]


def test_recalled_older_target_can_be_used_with_new_reference(workspace):
    store,project,assets,canvas=workspace
    old=canvas.create_node(project,kind='text',title='最初的文案',data={'text':'保留的初稿'})
    task(store,project,context={'userMessage':'讨论最初的文案','referencedNodes':[{'id':old['id']}]})
    with store._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded' WHERE id='task'")
        for i in range(7):
            db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','succeeded',?,'now','now')",(f'chat{i}',project,json.dumps({'userMessage':f'别的交流{i}'})))
        context={'userMessage':'根据这份资料修改最初的文案','referencedFiles':[{'pathRelative':'new-brief.txt'}]}
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','running',?,'now','now')",('current',project,json.dumps(context)))
    tools=DesignToolRegistry(store,asset_store=assets,canvas_store=canvas)
    with pytest.raises(ValueError): tools.execute(project_id=project,task_id='current',name='canvas_read',arguments={'node_ids':[old['id']]})
    recalled=tools.execute(project_id=project,task_id='current',name='conversation_read',arguments={'query':'最初的文案'})
    assert recalled['results'][0]['taskId']=='task'
    read=tools.execute(project_id=project,task_id='current',name='canvas_read',arguments={'node_ids':[old['id']]})
    assert read['canvas']['nodes'][0]['data']['text']=='保留的初稿'
