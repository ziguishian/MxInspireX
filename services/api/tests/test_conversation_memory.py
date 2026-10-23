import io
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.conversation_memory import ConversationMemoryService, MemoryError
from app.design_tools import DesignToolRegistry
from test_conversation_context import workspace, add_turn


def turn(store, name, text, project='one', **extra):
    add_turn(store,name,text,project=project,status='running',extra={'memoryProtocol':1,**extra})
    with store._connect() as db:
        db.execute('UPDATE tasks SET created_at=? WHERE id=?',(datetime.now(timezone.utc).isoformat(),name))
    return name


def picture(store, name='logo', project='one', **metadata):
    buffer=io.BytesIO();Image.new('RGB',(30,24),'#113377').save(buffer,format='PNG')
    assets=AssetStore(store)
    saved=assets.add_bytes(project_id=project,kind='image',filename=name+'.png',content=buffer.getvalue(),metadata=metadata)
    return assets.get_asset(project_id=project,asset_id=saved['id'])


def update(service, task, changes=None, selected=None, project='one', **kwargs):
    args={'expected_revision':service.read(project,task)['revision'],**kwargs}
    if changes is not None:args['changes']=changes
    if selected is not None:args['selected_ids']=selected
    return service.update(project,task,args,'op:'+json.dumps(args,sort_keys=True))


def fact(value, quote, **kwargs):
    return {'key':'brand.color','content':value,'category':'preference','status':'confirmed','source':{'quote':quote},**kwargs}


@pytest.mark.parametrize('guard',['none','history','skill','unresolved','multi','no_pixels','selected'])
def test_local_single_image_selection_is_only_a_first_turn_candidate(workspace,guard):
    service=ConversationMemoryService(workspace)
    asset=picture(workspace,source='input-reference')
    if guard=='history': turn(workspace,'old','Earlier request')
    constraints={'executionPolicyVersion':2,'singleDeliveryTarget':{'kind':'image','count':1},'referencedAssets':[{'id':asset['id']}]}
    if guard=='skill': constraints['referencedSkills']=[{'id':'required'}]
    if guard=='unresolved': constraints['focusContext']={'selectionRequired':True}
    turn(workspace,'new','Make one poster',**constraints)
    images=[{'assetId':asset['id'],'mime':'image/png','data':'normalized-preview'}]
    if guard=='multi': images=images*2
    if guard=='no_pixels': images[0].pop('data')
    service.prepare_empty_selection('one','new')
    if guard=='selected': update(service,'new',selected=['asset:'+asset['id']])
    before=service.runtime('one','new')
    service.prepare_single_image_selection('one','new',images,constraints)
    after=service.runtime('one','new')
    if guard!='none':
        assert after==before
        return
    assert after['analysisMode']=='explicit_single_image'
    assert after['analyzed'] and len(after['selected'])==1
    assert after['selected'][0]['assetId']==asset['id']
    assert all(s['bindingPolicy']=='candidates' for s in after['referenceSnapshots'])
    assert len(after['catalog'])==1
    service.prepare_single_image_selection('one','new',images,constraints)
    assert service.runtime('one','new')==after


def test_independent_node_can_select_connected_generated_assets_without_importing_other_history(workspace):
    turn(workspace, 'source-task', 'original task', taskSurface='canvas_node', canvasNodeId='source')
    first=picture(workspace, 'first', taskId='source-task')
    second=picture(workspace, 'second', taskId='source-task')
    unrelated=picture(workspace, 'unrelated', taskId='source-task')
    turn(workspace, 'target-task', 'combine references into one image', taskSurface='canvas_node', canvasNodeId='target',
         referencedAssets=[{'id':first['id']},{'id':second['id']}])
    service=ConversationMemoryService(workspace)
    records=service.read('one','target-task')['records']
    assert {r['assetId'] for r in records} == {first['id'],second['id']}
    assert all(r['source']['taskId']=='source-task' for r in records)
    update(service,'target-task',selected=[r['id'] for r in records])
    snapshot=service.validate_generation('one','target-task',{'source_asset_ids':[first['id'],second['id']]})
    assert {r['assetId'] for r in snapshot['references']} == {first['id'],second['id']}
    with pytest.raises(MemoryError):
        service.validate_generation('one','target-task',{'source_asset_ids':[unrelated['id']]})


def test_scopes_corrections_reopen_and_isolation(workspace):
    service=ConversationMemoryService(workspace)
    turn(workspace,'a','后面统一用蓝色')
    first=update(service,'a',[fact('蓝色','后面统一用蓝色')],['brand.color'])
    turn(workspace,'b','这次用绿色')
    second=update(service,'b',[fact('绿色','这次用绿色',key='task.color',scope='task')],['task.color'])
    turn(workspace,'c','接着来')
    records=ConversationMemoryService(workspace).read('one','c')['records']
    assert [r['content'] for r in records]==['蓝色']
    turn(workspace,'d','后面统一用绿色')
    update(service,'d',[fact('绿色','后面统一用绿色')],['brand.color'])
    assert service.runtime('one','a')['selected'][0]['content']=='蓝色'
    assert service.runtime('one','b')['selected'][0]['scope']=='task'
    turn(workspace,'e','继续');reopened=ConversationMemoryService(workspace)
    assert reopened.read('one','e')['records'][0]['content']=='绿色'
    assert reopened.read('one','e')['records'][0]['version']==2
    turn(workspace,'other','新聊天',project='two')
    assert reopened.read('two','other')['records']==[]
    with pytest.raises(MemoryError):reopened.read('two','e')
    assert first['state']['sessionId']=='project:one'
    assert second['state']['selected'][0]['source']['taskId']=='b'


def test_revision_conflict_replay_and_failed_update_rollback(workspace):
    service=ConversationMemoryService(workspace);turn(workspace,'a','统一蓝色')
    args={'expected_revision':0,'changes':[fact('蓝色','统一蓝色')],'selected_ids':['brand.color']}
    value=service.update('one','a',args,'once')
    assert service.update('one','a',args,'once')==value
    with pytest.raises(MemoryError,match='版本已更新'):service.update('one','a',args,'different')
    bad={'expected_revision':1,'changes':[fact('绿色','伪造原话')],'selected_ids':['brand.color']}
    with pytest.raises(MemoryError):service.update('one','a',bad,'bad')
    assert service.read('one','a')['revision']==1
    assert service.runtime('one','a')['selected'][0]['content']=='蓝色'
    with pytest.raises(MemoryError):service.update('one','a',{**args,'expected_revision':1},'once')


def test_original_assets_use_structured_attachment_proof_and_freeze_hash(workspace):
    logo=picture(workspace,source='input-reference',referenceDocumentId='uploaded-logo')
    turn(workspace,'a','这是原 Logo，主色蓝色',referencedFiles=[{'documentId':'uploaded-logo'}])
    service=ConversationMemoryService(workspace);record=service.read('one','a')['records'][0]
    assert record['role']=='input'
    change={'key':record['key'],'content':'原 Logo','role':'logo','status':'confirmed','source':{'quote':'这是原 Logo'}}
    selected=update(service,'a',[change],[record['key']])
    context=service.runtime('one','a',images=True)
    assert context['attachments'][0]['assetId']==logo['id']
    snapshot=service.validate_generation('one','a',{'source_asset_id':logo['id']})
    assert snapshot==selected['state']['referenceSnapshots'][0]
    Path(logo['absolutePath']).write_bytes(b'changed')
    with pytest.raises(MemoryError):service.validate_generation('one','a',{'source_asset_id':logo['id']})


def test_invalid_attachment_quote_returns_exact_source_and_keeps_transaction_atomic(workspace):
    logo=picture(workspace,source='input-reference')
    turn(workspace,'a','用这个logo做一套视觉，主色蓝色',referencedAssets=[{'id':logo['id']}])
    service=ConversationMemoryService(workspace);revision=service.read('one','a')['revision']
    registry=DesignToolRegistry(workspace)
    result=registry.execute(project_id='one',task_id='a',name='conversation_memory_update',arguments={
        'expected_revision':revision,'changes':[fact('蓝色','主色蓝色'),{
            'key':'asset:'+logo['id'],'role':'logo','status':'confirmed','source':{'quote':'图片附件 @1：logo.png'}}]})
    assert result['status']=='memory_invalid' and result['revision']==revision
    assert result['validation']['key']=='asset:'+logo['id']
    assert result['validation']['field']=='source.quote'
    evidence=result['validation']['sourceEvidence']
    assert evidence['userText']=='用这个logo做一套视觉，主色蓝色'
    assert evidence['attachments']==[{'assetId':logo['id'],'kind':'attachment','origin':'user_upload'}]
    assert result['memoryContext']['sourceEvidence']==evidence
    assert len(service.read('one','a')['records'])==1
    assert not result['memoryContext']['analyzed']
    assert result['memoryContext']['selected']==[]
    assert result['memoryContext']['referenceSnapshots']==[]


def test_generated_brooch_cannot_be_promoted_and_wrong_reference_calls_zero(workspace):
    logo=picture(workspace,source='input-reference')
    turn(workspace,'a','这是原 Logo',referencedAssets=[{'id':logo['id']}])
    brooch=picture(workspace,'brooch',taskId='a',sourceAssetIds=[logo['id']])
    turn(workspace,'b','按原 Logo 做水杯')
    service=ConversationMemoryService(workspace)
    records=service.read('one','b')['records'];by_asset={r['assetId']:r for r in records}
    assert by_asset[brooch['id']]['role']=='artifact'
    with pytest.raises(MemoryError,match='母版'):
        update(service,'b',[{'key':'asset:'+brooch['id'],'role':'logo'}])
    update(service,'b',selected=['asset:'+logo['id']])
    service.execute('conversation_memory_read','one','b',{})
    calls=[]
    provider=SimpleNamespace(generate=lambda **kw:calls.append(kw))
    registry=DesignToolRegistry(workspace,asset_store=AssetStore(workspace),provider_registry=SimpleNamespace(image=lambda *a,**k:provider))
    result=registry.execute(project_id='one',task_id='b',name='generate_image',arguments={'prompt':'水杯','source_asset_id':brooch['id'],'output_mode':'create'})
    assert result['status']=='reference_mismatch' and not calls
    result=registry.execute(project_id='one',task_id='b',name='generation_reference_check',arguments={'operations':[
        {'tool':'generate_image','arguments':{'source_asset_id':logo['id'],'output_mode':'create',
            'reference_analysis':{'images':[{'asset_id':logo['id'],'mode':'identity','visual_prompt':'用户 Logo','use':'保持品牌身份','preserve':'Logo 比例'}], 'synthesis':'将用户 Logo 应用于水杯'}}},
        {'tool':'generate_image','arguments':{'source_asset_id':brooch['id'],'output_mode':'create'}}]})
    assert result['status']=='reference_mismatch' and not calls
    assert CanvasStore(workspace).load('one')['nodes']==[]


@pytest.mark.parametrize('legacy', [False, True])
def test_explicit_empty_references_allow_preflight_and_generation(workspace, legacy):
    turn(workspace, 'skip', '跳过参考，继续原设计任务。')
    service = ConversationMemoryService(workspace)
    recorded = update(service, 'skip', selected=[], references=[])
    snapshot = recorded['state']['referenceSnapshots'][0]
    assert snapshot['deliverableId'] == '*' and snapshot['references'] == []
    if legacy:
        # Reproduce the persisted state from the failed skip-reference task.
        with workspace._connect() as db:
            _, data, _ = service._task(db, 'one', 'skip')
            state = data['conversationMemory']
            state['referenceSnapshots'] = []
            service._publish(db, 'skip', data, state)
            db.execute('DELETE FROM conversation_reference_snapshots WHERE task_id=?', ('skip',))
    calls = []
    buffer = io.BytesIO(); Image.new('RGB', (32, 32), 'blue').save(buffer, format='PNG')
    def generate(**args):
        calls.append(args)
        assert not args.get('source_asset_path') and not args.get('source_asset_paths')
        return buffer.getvalue()
    registry = DesignToolRegistry(workspace, asset_store=AssetStore(workspace),
        provider_registry=SimpleNamespace(image=lambda *a, **kw: SimpleNamespace(generate=generate)))
    operations = [{'tool': 'generate_image', 'arguments': {'prompt': title, 'output_mode': 'create',
                   'deliverable_ids': [identity]}} for identity, title in
                  [('ship_ext', '游船外观'), ('ship_plan', '甲板布置'), ('ship_section', '横剖面'), ('ship_interior', '开放式舱内')]]
    checked = registry.execute(project_id='one', task_id='skip', name='generation_reference_check',
                               arguments={'operations': operations})
    assert checked['status'] == 'ready' and len(checked['snapshots']) == 4
    assert all(s['references'] == [] for s in checked['snapshots'])
    assert calls == [] and CanvasStore(workspace).load('one')['nodes'] == []
    if legacy:
        with workspace._connect() as db:
            assert not db.execute("SELECT 1 FROM conversation_reference_snapshots WHERE task_id=? AND COALESCE(json_extract(body,'$.kind'),'')!='image-preflight'", ('skip',)).fetchone()
    for operation in operations:
        result = registry.execute(project_id='one', task_id='skip', name=operation['tool'], arguments=operation['arguments'])
        replay = registry.execute(project_id='one', task_id='skip', name=operation['tool'], arguments=operation['arguments'])
        assert result['status'] == 'succeeded' and result['assetId'] == replay['assetId']
        assert result['asset']['metadata']['referenceSnapshot']['references'] == []
    assert len(calls) == 4 and len(CanvasStore(workspace).load('one')['nodes']) == 4


def test_empty_references_do_not_infer_pixels_from_selected_images(workspace):
    asset = picture(workspace, source='input-reference')
    turn(workspace, 'empty', '仅作为资料，本轮不使用图片', referencedAssets=[{'id': asset['id']}])
    service = ConversationMemoryService(workspace)
    result = update(service, 'empty', selected=['asset:' + asset['id']], references=[])
    assert result['state']['selected'][0]['assetId'] == asset['id']
    assert service.validate_generation('one', 'empty', {})['references'] == []
    with pytest.raises(MemoryError, match='实际参考图'):
        service.validate_generation('one', 'empty', {'source_asset_id': asset['id']})
    # A legacy empty state with selected images is ambiguous, not an implicit
    # decision to drop those references.
    with workspace._connect() as db:
        _, data, _ = service._task(db, 'one', 'empty')
        data['conversationMemory']['referenceSnapshots'] = []
        service._publish(db, 'empty', data, data['conversationMemory'])
    with pytest.raises(MemoryError, match='conversation_memory_update'):
        service.validate_generation('one', 'empty', {})
    with pytest.raises(MemoryError):
        service.validate_generation('one', 'empty', {'source_asset_id': asset['id']})


def test_empty_reference_recovery_keeps_analysis_and_item_scope_guards(workspace):
    turn(workspace, 'new', '从零设计')
    service = ConversationMemoryService(workspace)
    with pytest.raises(MemoryError) as error:
        service.validate_generation('one', 'new', {})
    assert error.value.code == 'memory_required'
    update(service, 'new', selected=[], references=[{'deliverable_id': 'front', 'memory_ids': []}])
    with pytest.raises(MemoryError):
        service.validate_generation('one', 'new', {'deliverable_ids': ['back']})
    with pytest.raises(MemoryError):
        service.validate_generation('one', 'new', {'reference_snapshot_id': 'other-task-snapshot'})


def test_original_promotion_review_snapshot_and_user_adoption(workspace):
    turn(workspace,'a','生成一个图案');artifact=picture(workspace,'pattern',taskId='a')
    turn(workspace,'b','采用这张作为主视觉',referencedAssets=[{'id':artifact['id']}])
    service=ConversationMemoryService(workspace)
    update(service,'b',[{'key':'asset:'+artifact['id'],'role':'key_visual','status':'confirmed','source':{'quote':'采用这张作为主视觉'}}],['asset:'+artifact['id']])
    turn(workspace,'c','停用这张');update(service,'c',[{'key':'asset:'+artifact['id'],'active':False,'source':{'quote':'停用这张'}}],[])
    readonly=service.execute('conversation_memory_read','one','b',{},role='review')
    assert readonly['records'][0]['role']=='key_visual' and readonly['records'][0]['active']
    assert readonly['memoryContext']['catalog'][0]['active']
    for role in ['review','repair','research']:
        with pytest.raises(MemoryError):service.execute('conversation_memory_update','one','b',{},role=role)
    assert service.runtime('one','b',images=True)['attachments'][0]['assetId']==artifact['id']


def test_generation_saves_quality_original_bytes_progress_and_replays(workspace):
    logo=picture(workspace,source='input-reference')
    turn(workspace,'a','测试一下做水杯',referencedAssets=[{'id':logo['id']}])
    service=ConversationMemoryService(workspace);update(service,'a',selected=['asset:'+logo['id']])
    calls=[]
    def generate(**params):
        calls.append(params)
        assert Path(params['source_asset_paths'][0]).read_bytes()==Path(logo['absolutePath']).read_bytes()
        return Path(logo['absolutePath']).read_bytes()
    registry=DesignToolRegistry(workspace,asset_store=AssetStore(workspace),provider_registry=SimpleNamespace(image=lambda *a,**k:SimpleNamespace(generate=generate,api='images')))
    args={'prompt':'水杯','model':'gpt-image-1','quality':'draft','params':{'size':'1024x1536'},'source_asset_id':logo['id'],'output_mode':'create',
          'reference_analysis':{'images':[{'asset_id':logo['id'],'mode':'identity','visual_prompt':'蓝色图形','use':'作为杯身标识','preserve':'原标识形状和比例'}], 'synthesis':'以原标识设计蓝色水杯，适配杯身曲面'}}
    result=registry.execute(project_id='one',task_id='a',name='generate_image',arguments=args)
    assert calls[0]['quality']=='low' and calls[0]['input_fidelity']=='high'
    assert calls[0]['size']=='1024x1536'
    assert result['asset']['metadata']['imageQuality']['tier']=='draft'
    assert result['memoryContext']['progress'][0]['assetId']==result['assetId']
    repeated=registry.execute(project_id='one',task_id='a',name='generate_image',arguments=args)
    assert repeated['assetId']==result['assetId'] and len(calls)==1
    assert service.read('one','a',ids=['asset:'+result['assetId']])['records'][0]['role']=='artifact'


def test_large_selection_failure_keeps_existing_binding(workspace):
    assets=[picture(workspace,str(i),source='input-reference') for i in range(9)]
    turn(workspace,'a','使用这些资料',referencedAssets=[{'id':a['id']} for a in assets])
    service=ConversationMemoryService(workspace)
    update(service,'a',selected=['asset:'+assets[0]['id']])
    before=service.runtime('one','a')
    with pytest.raises(MemoryError):
        update(service,'a',selected=['asset:'+a['id'] for a in assets],references=[{'deliverable_id':str(i),'memory_ids':['asset:'+a['id']]} for i,a in enumerate(assets)])
    assert service.runtime('one','a')==before


def test_cross_project_import_has_local_attachment_evidence(workspace):
    logo=picture(workspace,project='two',source='input-reference')
    imported=picture(workspace,source='input-reference',referenceOrigin={'assetId':logo['id'],'projectId':'two'})
    turn(workspace,'a','这张是 Logo',referencedAssets=[{'id':logo['id'],'projectId':'two'}])
    service=ConversationMemoryService(workspace)
    update(service,'a',[{'key':'asset:'+imported['id'],'status':'confirmed','role':'logo','source':{'quote':'这张是 Logo'}}],['asset:'+imported['id']])
    assert service.runtime('one','a')['selected'][0]['assetId']==imported['id']
    with pytest.raises(MemoryError):update(service,'a',[{'key':'foreign','category':'asset','content':'other','assetId':logo['id'],'role':'input'}])


def test_temporary_override_cannot_replace_long_term_key_and_versions_readable(workspace):
    service=ConversationMemoryService(workspace);turn(workspace,'a','统一蓝色')
    update(service,'a',[fact('蓝色','统一蓝色')],['brand.color'])
    turn(workspace,'b','这次绿色')
    with pytest.raises(MemoryError,match='独立 key'):
        update(service,'b',[fact('绿色','这次绿色',scope='task')])
    turn(workspace,'c','后面统一绿色')
    update(service,'c',[fact('绿色','后面统一绿色')],['brand.color'])
    assert service.read('one','c',ids=['brand.color'],version=1)['records'][0]['content']=='蓝色'


def test_select_clear_select_and_accepted_continuation_keep_snapshot(workspace):
    service=ConversationMemoryService(workspace);logo=picture(workspace,source='input-reference')
    turn(workspace,'a','Logo',referencedAssets=[{'id':logo['id']}])
    update(service,'a',selected=['asset:'+logo['id']])
    one=service.runtime('one','a')
    update(service,'a',selected=[])
    assert service.runtime('one','a')['selected']==[]
    update(service,'a',selected=['asset:'+logo['id']])
    assert service.runtime('one','a')['memoryRevision']>one['memoryRevision']
    turn(workspace,'continued','可以，继续',planAccepted=True,continuation={'taskId':'a'})
    state=service.bootstrap('one','continued')
    assert state['selected']==one['selected'] and not state['analyzed']
    assert state['referenceSnapshots'][0]['taskId']=='continued'
    turn(workspace,'new-topic','换一个主题')
    assert service.bootstrap('one','new-topic')['selected']==[]


def test_new_topic_can_explicitly_reuse_applicable_prior_topic_memory(workspace):
    service=ConversationMemoryService(workspace)
    turn(workspace,'lamp','设计一款便携台灯，奶油白机身')
    update(service,'lamp',[{'key':'lamp.body','content':'奶油白机身','category':'fact','scope':'topic',
        'topic':'portable-lamp','status':'confirmed','source':{'quote':'奶油白机身'}}],['lamp.body'],topic='portable-lamp')
    turn(workspace,'package','为这个台灯设计包装')
    result=update(service,'package',[{'key':'packaging.goal','content':'为台灯设计包装','category':'decision',
        'scope':'topic','topic':'portable-lamp-packaging','status':'confirmed','source':{'quote':'设计包装'}}],
        ['lamp.body','packaging.goal'],topic='portable-lamp-packaging')
    selected={record['key']:record for record in result['state']['selected']}
    assert selected['lamp.body']['topic']=='portable-lamp'
    assert selected['packaging.goal']['topic']=='portable-lamp-packaging'
    assert result['state']['topic']=='portable-lamp-packaging'


def test_reference_binding_alias_normalizes_to_single_current_plan_item(workspace):
    turn(workspace,'lamp','生成一张台灯外观概念图')
    lamp=picture(workspace,'lamp-render',taskId='lamp')
    stable_id='packaging-front-poster-01'
    plan={'ready':True,'scopeId':'packaging','currentItemIds':[stable_id],
          'deliverables':[{'id':stable_id,'title':'包装正面主视觉','kind':'image'}]}
    # The previous canvas outcome is contextual input selected by TaskFocus;
    # the user did not manually mention or attach it in this turn.
    turn(workspace,'package','为这个台灯设计包装',
         memoryContextAssets=[{'assetId':lamp['id'],'sha256':lamp['sha256']}],designPlan=plan)
    service=ConversationMemoryService(workspace)
    result=update(service,'package',selected=['asset:'+lamp['id']],references=[{
        'deliverable_id':'poster','memory_ids':['asset:'+lamp['id']]}])
    snapshot=result['state']['referenceSnapshots'][0]
    assert snapshot['deliverableId']==stable_id
    assert service.validate_generation('one','package',{
        'source_asset_id':lamp['id'],'deliverable_ids':[stable_id]})==snapshot
    # Existing tasks may already contain the pre-fix alias. They should resume
    # without another memory update when the mapping is still unambiguous.
    with workspace._connect() as db:
        data=json.loads(db.execute("SELECT input_json FROM tasks WHERE id='package'").fetchone()[0])
        data['conversationMemory']['referenceSnapshots'][0]['deliverableId']='poster'
        db.execute("UPDATE tasks SET input_json=? WHERE id='package'",(json.dumps(data),))
    legacy=service.validate_generation('one','package',{
        'source_asset_id':lamp['id'],'deliverable_ids':[stable_id]})
    assert legacy['deliverableId']=='poster'


def test_auxiliary_master_adoption_requires_real_accepted_dependency(workspace):
    turn(workspace,'proposal','提出图案与水杯计划');generated=picture(workspace,taskId='proposal')
    CanvasStore(workspace).ensure_asset_node('one',generated,task_id='proposal',data={'deliveryBinding':{'scopeId':'scope','itemIds':['pattern']}})
    baseline={'ready':True,'scopeId':'scope','deliverables':[{'id':'pattern'},{'id':'cup','dependsOn':['pattern']}]}
    turn(workspace,'accepted','按计划继续',planAccepted=True,planBaselineTaskId='proposal',planBaseline=baseline)
    service=ConversationMemoryService(workspace)
    change={'key':'asset:'+generated['id'],'content':'采用计划中的辅助图形','status':'confirmed','role':'style','source':{'planTaskId':'proposal','deliverableId':'pattern'}}
    update(service,'accepted',[change],['asset:'+generated['id']])
    assert service.runtime('one','accepted')['selected'][0]['role']=='style'
    with pytest.raises(MemoryError):update(service,'accepted',[{**change,'role':'logo'}])
    turn(workspace,'unconfirmed','研究其他方向')
    with pytest.raises(MemoryError):update(service,'unconfirmed',[change])


def test_runtime_node_reference_proves_adoption_and_survives_node_edit(workspace):
    from app.task_runtime import TaskRuntime
    from app.agent_contracts import AgentResult
    asset=picture(workspace,source='input-reference')
    canvas=CanvasStore(workspace);node=canvas.ensure_asset_node('one',asset)
    seen=[]
    def run(**kwargs):
        seen.append(kwargs)
        return AgentResult(status='succeeded',structured_data={'answer':'已整理资料'})
    runtime=TaskRuntime(workspace,asset_store=AssetStore(workspace),design_runtime=SimpleNamespace(run=run),provider_registry=SimpleNamespace(catalog=None,text=lambda *a,**k:SimpleNamespace(model='fixture')))
    result=runtime.enqueue(project_id='one',task_id='node-ref',agent_key='design',workflow_step='design',brief='这张是原 Logo，用于品牌延展',input_data={'textProvider':{'key':'fixture'},'referencedNodes':[{'id':node['id'],'projectId':'one'}], 'memoryInputAssets':[{'assetId':'forged'}]})
    assert result['status']=='succeeded'
    service=ConversationMemoryService(workspace)
    update(service,'node-ref',[{'key':'asset:'+asset['id'],'content':'原 Logo','role':'logo','status':'confirmed','source':{'quote':'这张是原 Logo'}}],['asset:'+asset['id']])
    changed=picture(workspace,'replacement',taskId='node-ref')
    canvas.update_node('one',node['id'],{'data':{'assetId':changed['id'],'asset':changed}})
    runtime.run('node-ref',brief='这张是原 Logo，用于品牌延展')
    assert seen[0]['attachments'][0]['assetId']==asset['id']
    assert seen[1]['attachments'][0]['assetId']==asset['id']
    with workspace._connect() as db:
        data=json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?',('node-ref',)).fetchone()[0])
    assert data['memoryInputAssets']==[{'assetId':asset['id'],'sha256':asset['sha256']}]


def test_delivery_cache_changes_when_selected_color_memory_changes(workspace):
    from app.delivery import DeliveryService
    service=ConversationMemoryService(workspace);turn(workspace,'a','用蓝色，然后更正为绿色',executionPolicyVersion=2)
    update(service,'a',[fact('蓝色','用蓝色')],['brand.color'])
    before=DeliveryService(workspace).inspect_task('one','a')['inspectionVersion']
    update(service,'a',[fact('绿色','更正为绿色')],['brand.color'])
    after=DeliveryService(workspace).inspect_task('one','a')['inspectionVersion']
    assert before!=after
