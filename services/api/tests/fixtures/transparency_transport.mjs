import assert from 'node:assert/strict';
let calls = 0;
globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/generate_image')) {
    assert.equal(body.background, 'transparent');
    assert.equal(body.params.background, 'transparent');
    assert.equal(body.params.output_format, 'png');
    const opaque = process.env.FIXTURE_ALPHA_OPAQUE === '1';
    return Response.json({ assetId: 'fixture', imageOutput: { verified: true, hasTransparency: !opaque }, warnings: opaque ? ['返回图片没有透明像素'] : [] });
  }
  const tool = body.tools.find(t => t.function.name === 'generate_image').function;
  assert.ok(JSON.stringify(tool.parameters.properties.background).includes('transparent'));
  const first = calls++ === 0;
  const delta = first ? { role: 'assistant', tool_calls: [{ index: 0, id: 'alpha-call', type: 'function', function: { name: 'generate_image', arguments: JSON.stringify({ prompt: 'A dryer', background: 'transparent' }) } }] } : { role: 'assistant', content: '图像已保存。' };
  const chunk = (delta, finish_reason = null) => ({ id: 'fixture', object: 'chat.completion.chunk', created: 1, model: body.model, choices: [{ index: 0, delta, finish_reason }] });
  return new Response([chunk(delta), chunk({}, first ? 'tool_calls' : 'stop')].map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } });
};
