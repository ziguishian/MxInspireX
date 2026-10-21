import { sessionResponse } from './session_transport.mjs';
import assert from 'node:assert/strict';
let requests = 0;
globalThis.fetch = async (url, options) => {
  const session = sessionResponse(url,options); if(session) return session;
  assert.ok(String(url).endsWith('/responses'), 'Greeting must not call a tool or another API');
  assert.equal(++requests, 1, 'Greeting should require only one model request');
  const body = JSON.parse(options.body);
  const instructions = body.instructions;
  assert.ok(instructions.includes('你叫MxinspireX'));
  assert.ok(instructions.includes('灵矩绘境研发'));
  assert.ok(!instructions.includes('你是朗居设计'));
  assert.equal(body.model, 'openai/gpt-6-luna');
  assert.equal((body.tools || []).length, 0);
  assert.ok(!body.reasoning?.effort || body.reasoning.effort === 'none');
  assert.ok(!JSON.stringify(body).includes('研究 Agent 已完成的简报'));
  const output = [{ type: 'message', id: 'msg_greeting', role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: '你好！很高兴见到你。', annotations: [] }] }];
  const response = { id: 'resp_greeting', object: 'response', created_at: 1, model: body.model, status: 'completed', output, usage: { input_tokens: 30, output_tokens: 12, total_tokens: 42 } };
  const events = [
    { type: 'response.created', response: { ...response, status: 'in_progress', output: [] } },
    { type: 'response.output_item.added', output_index: 0, item: output[0] },
    { type: 'response.output_text.delta', item_id: 'msg_greeting', output_index: 0, content_index: 0, delta: output[0].content[0].text },
    { type: 'response.output_item.done', output_index: 0, item: output[0] },
    { type: 'response.completed', response },
  ];
  return new Response(events.map(event => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'content-type': 'text/event-stream' } });
};
