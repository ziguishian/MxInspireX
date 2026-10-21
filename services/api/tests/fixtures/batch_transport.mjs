import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {sessionResponse} from './session_transport.mjs';

let round=0, last;
const plan = JSON.parse(process.env.FIXTURE_BATCH_PLAN);
const gen = id => ({prompt:`第二批新物料 ${id}`,model:'gpt-image-1',provider:'local-placeholder',output_mode:'create',deliverable_ids:[id]});
const operation = (name,args) => ({name,arguments:args});
function reply(api, op) {
  const id='batch-'+round;
  if(api==='responses') {
    const item=op ? {type:'function_call',id:'fc-'+id,call_id:id,name:op.name,arguments:JSON.stringify(op.arguments),status:'completed'}
      : {type:'message',id:'msg-'+id,role:'assistant',status:'completed',content:[{type:'output_text',text:'第二批两项已完成，累计四项。',annotations:[]}]};
    const response={id:'res-'+id,object:'response',model:'fixture',status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}}, {type:'response.output_item.added',output_index:0,item}, {type:'response.output_item.done',output_index:0,item}, {type:'response.completed',response}];
    return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk=(delta,finish_reason=null)=>'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\n\n';
  const delta=op ? {role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:op.name,arguments:JSON.stringify(op.arguments)}}]} : {role:'assistant',content:'第二批两项已完成，累计四项。'};
  return new Response(chunk(delta)+chunk({},op?'tool_calls':'stop')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
}

globalThis.fetch=async(input,options={})=>{
  const url=String(typeof input==='string'?input:input.url);
  const session=sessionResponse(url,options);if(session)return session;
  const body=JSON.parse(options.body || await input.text());
  if(url.includes('/agent-tools/')) {
    const name=decodeURIComponent(url.split('/').at(-1));
    const result=spawnSync(process.env.FIXTURE_PYTHON,[fileURLToPath(new URL('./memory_tool_fixture.py',import.meta.url))],{
      input:JSON.stringify({name,projectId:process.env.FIXTURE_PROJECT,taskId:options.headers['x-aics-task-id'],callId:options.headers['x-aics-tool-call-id'],role:options.headers['x-aics-agent-role'],arguments:body}),encoding:'utf8',env:process.env});
    assert.equal(result.status,0,result.stderr);
    const response=JSON.parse(result.stdout);last=response.body;
    return Response.json(last,{status:response.status});
  }
  assert.match(url,/^http:\/\/batch-fixture.invalid\/v1\/(responses|chat\/completions)$/,'No live network allowed');
  const text=JSON.stringify(body);
  const index=round++;
  assert.ok(text.includes('designBatch') && text.includes('next_batch'),'batch state must reach every model call');
  let op;
  if(index===0) {
    assert.ok(text.includes('needs_plan'));
    op=operation('generate_image',gen('B2-0'));
  } else if(index===1) {
    assert.equal(last.status,'planning_required');
    op=operation('design_plan',{});
  } else if(index===2) {
    assert.equal(last.batch.status,'needs_plan');assert.equal(last.progress.filter(r=>r.status==='passed').length,2);
    op=operation('design_plan',{plan});
  } else if(index===3) {
    assert.equal(last.status,'ready');assert.equal(last.plan.deliverables.length,4);
    assert.deepEqual(last.batch.itemIds,['B2-0','B2-1']);
    assert.ok(text.includes('B2-0') && text.includes('B1-0'));
    op=operation('generate_batch',{items:['B2-0','B2-1'].map(id=>({tool:'generate_image',arguments:gen(id)}))});
  } else {assert.equal(index,4);assert.ok(text.includes('第二批新物料'));}
  return reply(url.endsWith('/responses')?'responses':'chat_completions',op);
};
