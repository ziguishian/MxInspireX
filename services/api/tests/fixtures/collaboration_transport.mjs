import {sessionResponse} from './session_transport.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
const counts = { research: 0, design: 0, review: 0, revision: 0 };
let htmlNode, serial = 0;
globalThis.fetch = async (url, options) => {
  url = String(url);
  const session = sessionResponse(url, options); if (session) return session;
  const body = JSON.parse(options.body);
  if (url.includes('/agent-tools/')) {
    const name = url.split('/').at(-1);
    if (name === 'web_search') return Response.json({ sources: [{ title: 'Research result', url: 'https://example.com/research' }], answer: 'RESEARCH_READY' });
    const result = spawnSync(process.env.FIXTURE_PYTHON, [process.env.FIXTURE_TOOL_SCRIPT, name], { input: JSON.stringify(body), encoding: 'utf8', env: process.env });
    assert.equal(result.status, 0, result.stderr);
    const output = JSON.parse(result.stdout);
    if (name === 'canvas_create_html') htmlNode = output.node.id;
    return Response.json(output);
  }
  assert.ok(!process.env.FIXTURE_NO_MODEL_CALLS, 'Completed stages must not call the model again');
  const responses = url.endsWith('/responses');
  const messages = responses ? body.input : body.messages;
  const instructions = String(body.instructions || messages.find(m => ['system','developer'].includes(m.role))?.content || '');
  const serialized = JSON.stringify(messages);
  const stage = instructions.includes('你是独立审查者') ? 'review' : instructions.includes('你的专职职责') ? 'research' : instructions.includes('本轮只做一次修复') ? 'revision' : 'design';
  const definitions = (body.tools || []).map(t => responses ? t : t.function);
  if (stage === 'research' || stage === 'review') assert.ok(definitions.every(t => !/generate_|canvas_create|canvas_update|canvas_link/.test(t.name)));
  if (stage === 'design') assert.ok((serialized+instructions).includes('RESEARCH_READY'), 'Design must await research');
  if (stage !== 'review') assert.ok(serialized.includes('data:image/png;base64,aW1hZ2U='), 'Native image content must survive SDK transport');
  const parts = messages.flatMap(m => Array.isArray(m.content) ? m.content : []);
  if (stage !== 'review') assert.ok(parts.some(p => p.type === (responses ? 'input_image' : 'image_url')));
  const n = counts[stage]++;
  let call, text;
  if (stage === 'research') { if (!n) call = ['web_search', { query: '页面设计依据' }]; else if (n === 1) call = ['asset_inspect', { asset_id: process.env.FIXTURE_INSPECT_ASSET }]; else { assert.ok(serialized.includes('data:image/jpeg;base64,'), 'asset_inspect must return the bounded visual preview'); text = 'RESEARCH_READY'; } }
  if (stage === 'design') { if (!n) call = ['canvas_create_html', { title: '示例页面', html: '<h1>Draft</h1>' }]; else text = '网页初稿已保存'; }
  if (stage === 'review') {
    assert.equal(definitions.length, 0);
    assert.equal(n, 0, 'Review must run exactly once');
    text = JSON.stringify({ passed: false, checks:[{category:'content',status:'error',artifactId:htmlNode,message:'缺少用户要求的按钮交互'}], summary:'缺少按钮交互，保留产物供后续修改' });
  }
  if (stage === 'revision') { if (!n) call = ['canvas_create_html', { title: '示例页面', canvas_node_id: htmlNode, html: '<h1>Ready</h1><button onclick="this.textContent=\'完成\'">体验</button>' }]; else text = '网页已生成到画布'; }
  const id = `fixture-${++serial}`;
  if (responses) {
    const output = call ? { type: 'function_call', id, call_id: id, name: call[0], arguments: JSON.stringify(call[1]), status: 'completed' } : { type: 'message', id, role: 'assistant', status: 'completed', content: [{ type: 'output_text', text, annotations: [] }] };
    const response = { id, object: 'response', created_at: 1, model: body.model, status: 'completed', output: [output], usage: { input_tokens: 10, output_tokens: 8, total_tokens: 18 } };
    const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}}, {type:'response.output_item.added',output_index:0,item:output}, {type:'response.output_item.done',output_index:0,item:output}, {type:'response.completed',response}];
    return new Response(events.map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''), {headers:{'content-type':'text/event-stream'}});
  }
  const delta = call ? {role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:call[0],arguments:JSON.stringify(call[1])}}]} : {role:'assistant',content:text};
  const chunk = (delta,reason=null) => ({id,object:'chat.completion.chunk',created:1,model:body.model,choices:[{index:0,delta,finish_reason:reason}]});
  const events = [chunk(delta),chunk({},call?'tool_calls':'stop'), {...chunk({}),choices:[],usage:{prompt_tokens:10,completion_tokens:8,total_tokens:18}}];
  return new Response(events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
};
