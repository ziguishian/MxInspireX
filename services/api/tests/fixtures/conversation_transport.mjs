import assert from 'node:assert/strict';
globalThis.fetch = async (url, options) => {
  assert.ok(!String(url).includes('/agent-tools/'), 'Remembering a name must not generate an artifact');
  const body = JSON.parse(options.body), responses = String(url).endsWith('/responses');
  const items = responses ? body.input : body.messages;
  const serialized = JSON.stringify(items);
  for (const phrase of ['我叫 Alexi，品牌 PawJoy', '品牌改为 PawDays', '会沿用透明背景']) assert.ok(serialized.includes(phrase), phrase);
  assert.equal(serialized.split('我叫什么，品牌改成什么了？').length - 1, 1, 'Current input should occur only once');
  assert.ok(!serialized.includes('来自另一项目'));
  const tools = body.tools.map(t => responses ? t : t.function);
  assert.ok(tools.some(t => t.name === 'conversation_read'));
  const text = '你叫 Alexi，品牌已改为 PawDays。';
  if (responses) {
    const output = { type: 'message', id: 'message', role: 'assistant', status: 'completed', content: [{ type: 'output_text', text, annotations: [] }] };
    const response = { id: 'response', object: 'response', created_at: 1, model: body.model, status: 'completed', output: [output], usage: { input_tokens: 10, output_tokens: 8, total_tokens: 18 } };
    const events = [{ type: 'response.created', response: { ...response, status: 'in_progress', output: [] } }, { type: 'response.output_item.added', output_index: 0, item: output }, { type: 'response.output_item.done', output_index: 0, item: output }, { type: 'response.completed', response }];
    return new Response(events.map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''), { headers: { 'content-type': 'text/event-stream' } });
  }
  const chunk = (delta, reason=null) => ({ id: 'fixture', object: 'chat.completion.chunk', created: 1, model: body.model, choices: [{ index: 0, delta, finish_reason: reason }] });
  return new Response([chunk({role:'assistant', content:text}), chunk({},'stop')].map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } });
};
