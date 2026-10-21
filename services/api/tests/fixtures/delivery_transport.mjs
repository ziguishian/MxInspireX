import {memoryHandshake} from './memory_handshake.mjs';
import { sessionResponse } from './session_transport.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
let calls = 0;
globalThis.fetch = async (url, options) => {
  const session = sessionResponse(url,options); if(session) return session;
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    const name = String(url).split('/').at(-1);
    if (process.env.FIXTURE_REVIEW_ONLY) assert.ok(!/generate_|canvas_create|canvas_update/.test(name), 'Final review must not regenerate artifacts');
    const result = spawnSync(process.env.FIXTURE_PYTHON, [process.env.FIXTURE_TOOL_SCRIPT, name], { input: JSON.stringify(body), encoding: 'utf8', env: process.env });
    assert.equal(result.status, 0, result.stderr);
    return Response.json(JSON.parse(result.stdout));
  }
  const handshake=memoryHandshake(body);if(handshake)return handshake;
  assert.ok(String(url).endsWith('/responses'));
  const review = String(body.instructions).includes('你是独立审查者');
  if (process.env.FIXTURE_REVIEW_ONLY) assert.ok(review);
  const n = calls++, id = `${review ? 'review' : 'design'}-delivery-${n}`;
  const failed = Boolean(process.env.FIXTURE_REVIEW_FAIL);
  const output = review ? {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text:JSON.stringify({passed:!failed,issues:failed?['设计仍不符合要求']:[],summary:'已读取预览检查'}),annotations:[]}]} : n === 0 ? {type:'function_call',id,call_id:id,name:'canvas_create_html',arguments:JSON.stringify({html:'<h1>页面</h1><button onclick="this.textContent=\'成功\'">体验</button>'}),status:'completed'} : {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text:'网页已保存',annotations:[]}]};
  const response = {id,object:'response',created_at:1,model:body.model,status:'completed',output:[output],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}}, {type:'response.output_item.added',output_index:0,item:output}, {type:'response.output_item.done',output_index:0,item:output}, {type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
