import {sessionResponse} from './session_transport.mjs';
import assert from 'node:assert/strict';
import {appendFileSync} from 'node:fs';
let sequence=0;
globalThis.fetch=async (url,options)=>{
  url=String(url);
  const session=sessionResponse(url,options);if(session)return session;
  const body=JSON.parse(options.body);
  appendFileSync(process.env.FIXTURE_REQUEST_LOG,JSON.stringify({url,body})+'\n');
  if(url.includes('/agent-tools/budget_check'))return Response.json({reservationId:'compact-budget'});
  if(url.includes('/agent-tools/context_read'))return Response.json({results:[]});
  if(url.endsWith('/responses/compact')){
    assert.ok(body.input);assert.equal(body.previous_response_id,undefined);
    if(process.env.FIXTURE_COMPACTION_FAILURE)return Response.json({error:{message:'unsupported'}},{status:400});
    return Response.json({id:'compact-result',object:'response.compaction',output:[{id:'compacted',type:'compaction',encrypted_content:'opaque-openai-fixture'}],usage:{input_tokens:100,output_tokens:30,total_tokens:130}});
  }
  assert.ok(url.endsWith('/responses'));
  const id=`answer-${process.env.FIXTURE_RUN_ID||'first'}-${++sequence}`;
  const item={id,type:'message',role:'assistant',status:'completed',content:[{type:'output_text',text:'记得这份项目要求。',annotations:[]}]};
  const response={id,object:'response',model:body.model,status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
  const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
