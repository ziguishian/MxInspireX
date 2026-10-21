// Real SDK and Python registry; only the model and network transport are fixtures.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { sessionResponse } from './session_transport.mjs';
let turn=0, releaseSlow;
let parentFinished=false;
const slowGate=new Promise(resolve=>{releaseSlow=resolve;});
const record=value=>appendFileSync(process.env.FIXTURE_CALL_LOG,JSON.stringify(value)+'\n');
globalThis.fetch=async(url,options)=>{
  const session=sessionResponse(url,options);if(session)return session;
  const body=JSON.parse(options.body);
  if(String(url).includes('/agent-tools/')){
    const name=String(url).split('/').at(-1),id=body.deliverable_ids?.[0];
    if(name==='generate_image'){
      assert.equal(body.provider,'local-placeholder');record({event:'start',id});
      if(id==='slow')await slowGate;
      if(id==='child')assert.ok(parentFinished,'Child must wait for its own completed input');
    }
    const child=spawn(process.env.FIXTURE_PYTHON,[process.env.FIXTURE_TOOL_SCRIPT,name],{env:process.env});
    let output='',error='';child.stdout.on('data',s=>{output+=s;});child.stderr.on('data',s=>{error+=s;});
    child.stdin.end(JSON.stringify(body));
    const code=await new Promise(resolve=>child.on('close',resolve));assert.equal(code,0,error);
    const result=JSON.parse(output);
    if(name==='generate_image'){
      assert.equal(result.status,'succeeded',JSON.stringify(result));
      if(id==='parent')parentFinished=true;
      // The fixture uses separate registry processes; release after persistence
      // so it does not invent cross-process canvas writes absent in the API.
      if(id==='child')releaseSlow();
      record({event:'finish',id,assetId:result.assetId});
    }
    return Response.json(result);
  }
  assert.ok(String(url).endsWith('/responses'));
  const n=turn++,id='dependency-'+n;
  let action,text;
  if(n===0)action={name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_DESIGN_PLAN)}};
  else if(n===1)action={name:'generate_batch',args:{items:['child','slow','parent'].map(id=>({tool:'generate_image',arguments:{output_mode:'create',deliverable_ids:[id],prompt:id,params:{size:'1024x1024'}}}))}};
  else {assert.equal(n,2);text='三个产物已按输入依赖保存。';}
  const output=action?{type:'function_call',id,call_id:id,name:action.name,arguments:JSON.stringify(action.args),status:'completed'}:{type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]};
  const response={id,object:'response',created_at:1,model:body.model,status:'completed',output:[output],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item:output},{type:'response.output_item.done',output_index:0,item:output},{type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
