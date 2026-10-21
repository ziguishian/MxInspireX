import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {sessionResponse} from './session_transport.mjs';

let round=0;
const mode=process.env.FIXTURE_SKILL_MODE;
const skillId=process.env.FIXTURE_SKILL_ID;
const sentinel='莓红色_SKILL_RULE_V1';
function reply(api, operation, index) {
  const id=`${mode}-${index}`;
  const content=(mode==='create_retry' && index===0 || mode==='create_stalled') ? 'PREMATURE 已创建' : '已完成技能操作和本轮要求。';
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
globalThis.fetch=async (input, options={})=>{
  const url=String(typeof input==='string'?input:input.url);
  const session=sessionResponse(url,options);if(session) return session;
  const body=JSON.parse(options.body || await input.text());
  if(url.includes('/agent-tools/')) {
    const result=spawnSync(process.env.FIXTURE_PYTHON,[fileURLToPath(new URL('./skill_tool_fixture.py',import.meta.url))],{
      input:JSON.stringify({name:decodeURIComponent(url.split('/').at(-1)),projectId:decodeURIComponent(new URL(url).pathname.split('/')[3]),
        taskId:options.headers['x-aics-task-id'],callId:options.headers['x-aics-tool-call-id'],role:options.headers['x-aics-agent-role'],arguments:body}),
      encoding:'utf8',env:process.env,
    });
    assert.equal(result.status,0,result.stderr);
    const response=JSON.parse(result.stdout);
    return Response.json(response.body,{status:response.status});
  }
  assert.match(url,/^http:\/\/skill-fixture.invalid\/v1\/(responses|chat\/completions)$/,'No external requests permitted');
  const api=url.endsWith('/responses')?'responses':'chat_completions';
  const text=JSON.stringify(body.input || body.messages), index=round++;
  const exposed=(body.tools||[]).map(t=>t.name||t.function?.name);
  let operation;
  if(mode.startsWith('svg_')) {
    const allowed = false;
    assert.equal(exposed.includes('canvas_create_svg'), allowed);
    const batch = (body.tools || []).find(t => (t.name || t.function?.name) === 'generate_batch');
    assert.equal(JSON.stringify(batch).includes('canvas_create_svg'), allowed, 'batch enum follows the same permission');
    assert.ok(JSON.stringify(body).includes('SVG 绘图已全局禁用'), 'core policy must be present in model instructions');
    if (index === 0) operation = allowed
      ? {name:'canvas_create_svg',arguments:{svg:'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="green"/></svg>'}}
      : {name:'generate_batch',arguments:{items:[{tool:'canvas_create_text',arguments:{text:'MUST_NOT_SAVE'}},{tool:'canvas_create_html',arguments:{html:'<html><body><svg><rect width="10" height="10"/></svg></body></html>'}}]}};
    if (index === 1 && !allowed) {
      assert.ok(text.includes('SVG 绘图已全局禁用'));
      operation = {name:'canvas_create_text',arguments:{text:'可执行的排版说明'}};
    }
  } else if(mode.startsWith('create')) {
    if(mode==='create_retry' && index===2) assert.ok(text.includes('工具依赖不存在') && text.includes('nonexistent_tool'),'validation errors must reach the model for correction');
    assert.ok(exposed.includes('skill_create'));
    assert.ok(!exposed.includes('generate_image'),'authoring must not expose generators');
    if(mode==='create' && index===0 || mode==='create_retry' && index===2) operation={name:'skill_create',arguments:{name:'packaging-design',title:'包装设计',description:'包装设计方法',instructions:sentinel,required_tools:['export_deliverable','canvas_create_text']}};
    if(mode==='create_retry' && index===1) operation={name:'skill_create',arguments:{name:'packaging-design',description:'包装设计',instructions:sentinel,required_tools:['nonexistent_tool']}};
  } else if(mode.startsWith('builtin:')) {
    const name=mode.slice('builtin:'.length);
    if(index===0) {
      assert.ok(text.includes(name),'shipped catalogue must be supplied on first request');
      operation={name:'skill_load',arguments:{skill_id:skillId}};
    } else {
      assert.ok(text.includes('references/host-tools.md'),'full builtin workflow must reach the next request');
      assert.ok(exposed.includes('generate_image') && exposed.includes('generate_batch'),'image dependencies must be exposed');
      assert.ok(!exposed.includes('export_deliverable'),'design skills must not enable automatic download packages');
      if(index===1) operation={name:'skill_read',arguments:{skill_id:skillId,resource:'references/host-tools.md'}};
      if(index===2) {
        assert.ok(!exposed.includes('canvas_create_svg'));
        operation={name:'canvas_create_text',arguments:{title:name+' 交付验证',text:'实际加载内置流程后通过已有工具保存的测试产物。'}};
      }
    }
  } else if(mode==='mention' || mode==='mention_unloaded') {
    assert.equal(text.includes(sentinel), mode==='mention', 'explicit selection is applied before first request and unload survives restart');
    assert.equal(exposed.includes('export_deliverable'), mode==='mention');
  } else if(mode==='use') {
    if(index===0) {
      assert.ok(!text.includes(sentinel));assert.ok(!exposed.includes('export_deliverable'));
      operation={name:'skill_load',arguments:{skill_id:skillId}};
    } else {
      assert.ok(text.includes(sentinel),'loaded instructions must reach the next SDK request');
      assert.ok(exposed.includes('export_deliverable'),'dependency tools must become visible');
      if(index===1) operation={name:'canvas_create_text',arguments:{title:'包装说明',text:'莓红色包装设计说明'}};
    }
  } else if(mode==='unload') {
    if(index===0 || index===2) {assert.ok(!text.includes(sentinel));operation={name:'skill_load',arguments:{skill_id:skillId}};}
    if(index===1) {assert.ok(text.includes(sentinel));operation={name:'skill_unload',arguments:{skill_id:skillId}};}
    if(index===3) assert.ok(text.includes(sentinel));
  } else if(mode==='interrupt') {
    if(index===0) operation={name:'skill_load',arguments:{skill_id:skillId}};
    else if(index===1) operation={name:'canvas_create_text',arguments:{text:'已完成的包装产物',title:'恢复验证'}};
    else return Response.json({error:{message:'fixture connection interrupted'}},{status:503});
  } else if(mode==='resume') {
    assert.ok(text.includes(sentinel),'resume must retain original skill version');
    assert.ok(!text.includes('NEW_VERSION_ONLY'));
  }
  return reply(api,operation,index);
};
