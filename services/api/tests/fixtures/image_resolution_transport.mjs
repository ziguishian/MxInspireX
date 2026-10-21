import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { sessionResponse } from './session_transport.mjs';

let round = 0;
const args = JSON.parse(process.env.FIXTURE_IMAGE_ARGS);
globalThis.fetch = async (input, options = {}) => {
  const url = String(typeof input === 'string' ? input : input.url);
  const session = sessionResponse(url, options); if (session) return session;
  const body = JSON.parse(options.body || await input.text());
  if (url.includes('/agent-tools/')) {
    const name = decodeURIComponent(url.split('/').at(-1));
    assert.ok(['generate_image', 'generation_reference_check'].includes(name), name);
    const operations = name === 'generate_image' ? [{arguments:body}] : body.operations;
    for (const operation of operations) {
      assert.deepEqual(operation.arguments.source_asset_ids, args.source_asset_ids, 'Worker must not inject smart-reference candidates');
      assert.equal(operation.arguments.output_mode, undefined);
      assert.equal(operation.arguments.canvas_node_id, undefined, 'Backend owns the canvas destination');
    }
    const result = spawnSync(process.env.FIXTURE_PYTHON, [fileURLToPath(new URL('./memory_tool_fixture.py', import.meta.url))], {
      input: JSON.stringify({name, projectId:process.env.FIXTURE_PROJECT, taskId:'current', arguments:body}), encoding:'utf8', env:process.env,
    });
    assert.equal(result.status, 0, result.stderr);
    const response = JSON.parse(result.stdout);
    assert.ok(['ready', 'succeeded'].includes(response.body.status), JSON.stringify(response));
    return Response.json(response.body, {status:response.status});
  }
  assert.match(url, /^https:\/\/image-resolution-fixture.invalid\/v1\/responses$/, 'No live network');
  const id = `image-resolution-${++round}`;
  assert.ok(round <= 2, 'No parameter-repair model rounds');
  const name = process.env.FIXTURE_IMAGE_BATCH === '1' ? 'generate_batch' : 'generate_image';
  const argumentsValue = name === 'generate_batch' ? {items:[{tool:'generate_image',arguments:args}]} : args;
  const item = round === 1
    ? {type:'function_call', id, call_id:id, name, arguments:JSON.stringify(argumentsValue), status:'completed'}
    : {type:'message', id, role:'assistant', status:'completed', content:[{type:'output_text', text:'已生成新角色并保留原图。', annotations:[]}]};
  const response = {id, object:'response', model:'fixture', status:'completed', output:[item], usage:{input_tokens:10, output_tokens:10, total_tokens:20}};
  const events = [{type:'response.created', response:{...response,status:'in_progress',output:[]}},
    {type:'response.output_item.added',output_index:0,item}, {type:'response.output_item.done',output_index:0,item}, {type:'response.completed',response}];
  return new Response(events.map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''), {headers:{'content-type':'text/event-stream'}});
};
