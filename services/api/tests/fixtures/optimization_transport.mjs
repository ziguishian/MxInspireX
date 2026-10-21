import {memoryHandshake} from './memory_handshake.mjs';
import { sessionResponse } from './session_transport.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';
let generation = 0;
globalThis.fetch = async (url, options) => {
  const session = sessionResponse(url,options); if(session) return session;
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    const name=String(url).split('/').at(-1);
    const result=spawnSync(process.env.FIXTURE_PYTHON,[process.env.FIXTURE_TOOL_SCRIPT,name],{input:JSON.stringify(body),encoding:'utf8',env:process.env});
    if(result.status!==0 && result.stderr.includes('ProviderError:')) return Response.json({detail:result.stderr.split('ProviderError:').at(-1).trim()},{status:402});
    assert.equal(result.status,0,result.stderr);
    return Response.json(JSON.parse(result.stdout));
  }
  assert.ok(String(url).endsWith('/responses'));
  const instructions=String(body.instructions||'');
  const research=instructions.includes('专职职责是研究') || instructions.includes('你是 MxinspireX 的研究 Agent'),review=instructions.includes('你是独立审查者'),repair=instructions.includes('只修复指定原节点');
  if (process.env.FIXTURE_MODEL_LOG) appendFileSync(process.env.FIXTURE_MODEL_LOG,JSON.stringify({model:body.model,stage:research?'research':review?'review':repair?'repair':'design'})+'\n');
  if(!research && !review && !repair) { const handshake=memoryHandshake(body);if(handshake)return handshake; }
  const id='optimization-'+Math.random();
  let item;
  if (!research && !review && generation++ === 0) {
    item={type:'function_call',id,call_id:id,name:'canvas_create_html',arguments:JSON.stringify({html:process.env.FIXTURE_BROKEN_HTML && !repair?'<h1>网页</h1><button onclick="missingFunction()">试用</button>':'<h1>网页</h1><button onclick="this.textContent=\'完成\'">试用</button>',...(repair?{canvas_node_id:process.env.FIXTURE_REPAIR_TARGET}:{})}),status:'completed'};
  } else item={type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text:review?JSON.stringify({passed:true,issues:[],summary:'检查完成'}):research?'研究已完成':'网页已保存',annotations:[]}]};
  const response={id,object:'response',created_at:1,model:body.model,status:'completed',output:[item],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
