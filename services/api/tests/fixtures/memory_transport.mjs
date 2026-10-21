import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {sessionResponse} from './session_transport.mjs';
const mode=process.env.FIXTURE_MEMORY_MODE;
const logo=process.env.FIXTURE_LOGO;
const brooch=process.env.FIXTURE_BROOCH;
const visualPrompt='白色陶瓷水杯，杯身为蓝色图形、简洁平面构成，标识居中，柔和侧光。';
let round=0,lastMemory,lastTool,generated=0;
const referenceAnalysis = (assetId, referenceMode='identity') => ({images:[{asset_id:assetId,mode:referenceMode,
  visual_prompt:'蓝色图形，简洁平面构成',use:'提取蓝色和平面语言用于水杯',avoid:'无关文字和场景',preserve:'用户要求保留的标识形状与比例'}],
  synthesis:'根据用户的水杯需求，融合蓝色视觉语言，重新适配杯身版式'});
function reply(api, operation, index, textOverride) {
  const id=`${mode}-${index}`;
  const content=textOverride ?? ((mode==='create_retry' && index===0 || mode==='create_stalled') ? 'PREMATURE 已创建' : '已完成技能操作和本轮要求。');
  if(api==='responses') {
    const item=operation ? {type:'function_call',id:`fc-${id}`,call_id:id,name:operation.name,arguments:JSON.stringify(operation.arguments),status:'completed'}
      : {type:'message',id:`msg-${id}`,role:'assistant',status:'completed',content:[{type:'output_text',text:content,annotations:[]}]};
    const response={id:`res-${id}`,object:'response',model:'fixture',status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},
      {type:'response.output_item.added',output_index:0,item},
      {type:'response.output_item.done',output_index:0,item}, {type:'response.completed',response}];
    return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk=(delta,finish_reason=null)=>'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\n\n';
  const delta=operation ? {role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:operation.name,arguments:JSON.stringify(operation.arguments)}}]} : {role:'assistant',content};
  return new Response(chunk(delta)+chunk({},operation?'tool_calls':'stop')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
}
globalThis.fetch=async(input,options={})=>{
  const url=String(typeof input==='string'?input:input.url);
  const session=sessionResponse(url,options);if(session)return session;
  const body=JSON.parse(options.body || await input.text());
  if(url.includes('/agent-tools/')) {
    const name=decodeURIComponent(url.split('/').at(-1));
    if(name==='generate_image')generated++;
    const result=spawnSync(process.env.FIXTURE_PYTHON,[fileURLToPath(new URL('./memory_tool_fixture.py',import.meta.url))],{
      input:JSON.stringify({name,projectId:'one',taskId:options.headers['x-aics-task-id'],callId:options.headers['x-aics-tool-call-id'],role:options.headers['x-aics-agent-role'],arguments:body}),encoding:'utf8',env:process.env});
    assert.equal(result.status,0,result.stderr);
    const response=JSON.parse(result.stdout);
    lastTool=response.body;
    if(response.body.memoryContext)lastMemory=response.body.memoryContext;
    return Response.json(response.body,{status:response.status});
  }
  assert.match(url,/^http:\/\/memory-fixture.invalid\/v1\/(responses|chat\/completions)$/,'Live network is forbidden');
  const index=round++, api=url.endsWith('/responses')?'responses':'chat_completions';
  const text=JSON.stringify(body.input||body.messages);
  let operation;
  if(mode==='fast_image') {
    assert.ok(index<3,'one creation, one answer and one review are sufficient');
    if(index===0) {
      assert.ok(text.includes('empty_catalog'));
      assert.ok(!(body.tools || []).some(t=>(t.name || t.function?.name)==='skill_create'));
      return reply(api,{name:'generate_image',arguments:{prompt:'蓝白青花陶瓷杯，现代简洁杯型，干净产品摄影'}},index);
    }
    if(index===1)return reply(api,null,index,'陶瓷杯已生成，请查看画布。');
    assert.equal((body.tools || []).length,0,'review has no mutation tools');
    return reply(api,null,index,JSON.stringify({passed:true,summary:'杯型完整，蓝白纹样清晰',checks:[]}));
  }
  if (mode==='invalid_references') {
    assert.ok(index<3,'repeated invalid references must stop after two correction attempts');
    return reply(api,{name:'generate_image',arguments:{prompt:'杯子包装',source_asset_id:'asset:unrelated-image',output_mode:'create'}},index);
  }
  if (mode==='reference_stalled') {
    assert.ok(index<4,'repeated reference mismatches must stop after two correction attempts');
    if(index===0)operation={name:'conversation_memory_read',arguments:{}};
    else {
      if(index>1)assert.equal(lastTool.status,'reference_mismatch');
      operation={name:'generate_image',arguments:{prompt:'杯子包装',source_asset_id:brooch,output_mode:'create'}};
    }
    return reply(api,operation,index);
  }
  if (['intro','followup','clarify'].includes(mode)) {
    if (mode==='intro') {
      assert.equal(index,0,'self-introduction must finish in one response');
      assert.equal((body.tools || []).length,0);
    } else if (mode==='clarify') {
      assert.equal(index,0,'a clarification card ends the turn immediately');
      operation={name:'request_clarification',arguments:{intro:'先确认产品和用途。',questions:[
        {id:'product',question:'是什么类型的杯子？',options:['陶瓷杯','玻璃杯']},
        {id:'usage',question:'包装用于什么场景？',options:['零售','礼赠']}]}};
    } else {
      // Several completed SDK runs in one stage used to re-import live
      // history under the same legacy operation ID and fail on the third run.
      assert.ok(index<5,'memory follow-up must complete');
      if(index===2)operation={name:'conversation_memory_read',arguments:{}};
      if(index===3)operation={name:'conversation_memory_update',arguments:{expected_revision:lastMemory.revision,changes:[],selected_ids:[]}};
    }
    return reply(api,operation,index);
  }
  if (mode==='source_repair' || mode==='source_stalled') {
    assert.ok(text.includes('sourceEvidence') && text.includes('这是原 Logo，标准色为蓝色，做水杯'));
    const changes=quote=>[{key:'asset:'+logo,content:'博览会原 Logo',role:'logo',status:'confirmed',source:{taskId:'current',quote}}];
    if(index===0) operation={name:'conversation_memory_read',arguments:{}};
    else if(index===1 || mode==='source_stalled') {
      if(index>1) {
        assert.equal(lastTool.status,'memory_invalid');
        assert.ok(text.includes('source.quote') && text.includes('图片附件 @1：logo.png'),'failed args and correction evidence survive context preparation');
      }
      assert.ok(index<5,'repeated memory rejection must stop before another model call');
      operation={name:'conversation_memory_update',arguments:{expected_revision:lastMemory.revision,changes:changes('图片附件 @1：logo.png'),selected_ids:['asset:'+logo]}};
    } else if(index===2) {
      assert.equal(lastTool.validation.field,'source.quote');
      assert.equal(lastTool.validation.sourceEvidence.userText,'这是原 Logo，标准色为蓝色，做水杯');
      assert.ok(text.includes('图片附件 @1：logo.png') && text.includes('source.quote'));
      operation={name:'conversation_memory_update',arguments:{expected_revision:lastMemory.revision,changes:changes('这是原 Logo'),selected_ids:['asset:'+logo]}};
    } else if(index===3) {
      assert.equal(lastMemory.analyzed,true);
      assert.ok(text.includes('本轮参考资料'));
      operation={name:'generate_image',arguments:{prompt:'水杯',model:'gpt-image-1',source_asset_id:logo,output_mode:'create',reference_analysis:referenceAnalysis(logo)}};
    } else { assert.equal(index,4);assert.equal(generated,1); }
    return reply(api,operation,index);
  }
  if(mode==='resume') {
    assert.ok(text.includes('记忆蓝色') && text.includes('本轮参考资料') && text.includes(logo));
    assert.equal(generated,0);
    return reply(api,undefined,index);
  }
  if(index===0)operation={name:'conversation_memory_read',arguments:{}};
  if(index===1)operation={name:'conversation_memory_update',arguments:{expected_revision:lastMemory.revision,changes:[
    {key:'brand.color',content:'记忆蓝色',category:'preference',status:'confirmed',scope:'conversation',source:{quote:'标准色为蓝色'}},
    {key:'asset:'+logo,content:'博览会原 Logo',role:'logo',status:'confirmed',source:{quote:'这是原 Logo'}}],selected_ids:['brand.color','asset:'+logo]}};
  if(index>=2) {
    assert.ok(text.includes('记忆蓝色') && text.includes('本轮参考资料'));
    assert.ok(text.includes('data:image/jpeg;base64,'),'reference pixels must be in the actual SDK request');
  }
  if(index>=3 && ['analysis_repair','analysis_stalled'].includes(mode)) {
    if(index>3) assert.equal(lastTool.status,index===5 && mode==='analysis_repair'?'succeeded':'reference_analysis_required');
    if(index===3 || mode==='analysis_stalled' || index===4) operation={name:'generate_image',arguments:{prompt:visualPrompt,model:'gpt-image-1',source_asset_id:logo,output_mode:'create',
      ...(index===4 && mode==='analysis_repair'?{reference_analysis:referenceAnalysis(logo,'inspiration')}:{})}};
    assert.ok(index<6,'unresolved analysis must stop after bounded correction');
    return reply(api,operation,index);
  }
  if(index===2)operation={name:'generate_batch',arguments:{items:[
    {tool:'generate_image',arguments:{prompt:'水杯 A',source_asset_id:logo,output_mode:'create',reference_analysis:referenceAnalysis(logo)}},
    {tool:'generate_image',arguments:{prompt:'水杯 B',source_asset_id:brooch,output_mode:'create'}}]}};
  if(index===3) {
    assert.ok(text.includes('reference_mismatch'));
    assert.equal(generated,0,'whole batch rejected before any provider invocation');
    operation={name:'generate_image',arguments:{prompt:visualPrompt,model:'gpt-image-1',source_asset_id:logo,output_mode:'create',quality:'draft',params:{size:'1024x1536'},reference_analysis:referenceAnalysis(logo,mode==='inspiration'?'inspiration':'identity')}};
  }
  if(index===4 && mode==='interrupt')throw new Error('SIMULATED_DISCONNECT_AFTER_SAVED_IMAGE');
  if(index===4)assert.equal(generated,1);
  assert.ok(index<8,'unexpected model loop');
  return reply(api,operation,index);
};
