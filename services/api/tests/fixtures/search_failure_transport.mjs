import assert from 'node:assert/strict';
const mode = process.env.SEARCH_FAILURE_FIXTURE || 'permanent';
let round = 0;
let searches = 0;
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
globalThis.fetch = async (url, init) => {
  const address = String(url);
  if (address.includes('/agent-tools/web_search')) {
    searches++;
    const args = JSON.parse(init.body);
    assert.equal(args._search_context.model, 'fixture', 'inherit the actual Agent model');
    assert.ok(args._search_context.timeoutSeconds <= 60);
    assert.ok(searches <= (mode === 'transient' ? 2 : 1), 'must stop queued searches');
    if (mode === 'hang_headers') return new Promise((_,reject) => init.signal.addEventListener('abort',()=>reject(new Error('deadline')), {once:true}));
    if (mode === 'hang_body') return new Response(new ReadableStream({start(controller) {
      init.signal.addEventListener('abort',()=>controller.error(new Error('deadline')), {once:true});
    }}));
    if (mode === 'bad_body') return new Response('<html>upstream unavailable</html>');
    return json({ detail: 'Search fixture unavailable', stopTool: mode !== 'transient' }, mode === 'transient' ? 502 : 422);
  }
  if (address.includes('/agent-tools/delivery_verify')) return json({ passed: true, status: 'passed', issues: [] });
  assert.ok(address.endsWith('/chat/completions'), address);
  const body = JSON.parse(init.body);
  round++;
  let delta;
  if (round === 1 && mode !== 'recovery') {
    delta = { role: 'assistant', tool_calls: Array.from({ length: 8 }, (_, index) => ({
      index, id: `search-${index}`, type: 'function', function: { name: 'web_search', arguments: JSON.stringify({ query: `source ${index}` }) },
    })) };
  } else {
    assert.ok(!body.tools?.some(t => t.function?.name === 'web_search'), 'blocked search tool must be removed');
    assert.equal(searches, mode === 'recovery' ? 0 : mode === 'transient' ? 2 : 1);
    delta = { role: 'assistant', content: '联网搜索不可用，无法核验最新标准。' };
  }
  const chunk = (d, reason) => ({ id: `response-${round}`, object: 'chat.completion.chunk', created: 1, model: body.model, choices: [{ index: 0, delta: d, finish_reason: reason }] });
  return new Response([chunk(delta, null), chunk({}, delta.tool_calls ? 'tool_calls' : 'stop')].map(c => `data: ${JSON.stringify(c)}\n\n`).join('') + 'data: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } });
};
