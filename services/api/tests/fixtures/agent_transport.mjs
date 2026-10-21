import {memoryHandshake} from './memory_handshake.mjs';
import { sessionResponse } from './session_transport.mjs';
// Network-free transport fixture. The production worker and installed SDK run
// unchanged; business tool calls execute the real Python registry/storage.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
let calls = 0;
let activeImages = 0, peakImages = 0, startedImages = 0, startImages;
const imageCount = Number(process.env.FIXTURE_PARALLEL_COUNT || 2);
const imageBarrier = new Promise(resolve => { startImages = resolve; });
const transport = async (url, options) => {
  if (process.env.FIXTURE_STEERING && String(url).includes('/updates')) return Response.json(calls ? [{id:'steer',text:'不要蓝色，改用绿色',revision:1}] : []);
  const session = sessionResponse(url,options); if(session) return session;
  url = String(url);
  const body = JSON.parse(options.body);
  if (url.includes('/agent-tools/')) {
    if (process.env.FIXTURE_PARALLEL && url.endsWith('/generate_image')) {
      activeImages++; startedImages++; peakImages = Math.max(peakImages, activeImages);
      if (activeImages === imageCount) startImages();
      let timer;
      try { await Promise.race([imageBarrier, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('image requests were serialized')), 5000); })]); }
      finally { clearTimeout(timer); activeImages--; }
      const id = body.prompt;
      if (process.env.FIXTURE_BATCH_FAILURE && id === 'image-1') return Response.json({detail:'OpenRouter 图像接口 HTTP 400: Gemini could not generate an image (STOP)'},{status:400});
      return Response.json({ tool:'generate_image',status:'succeeded',assetId:id,node:{id,position:{x:0,y:0},data:{kind:'image',assetId:id,deliveryBinding:{scopeId:'batch-scope',itemIds:body.deliverable_ids || []}}} });
    }
    const result = spawnSync(process.env.FIXTURE_PYTHON, [process.env.FIXTURE_TOOL_SCRIPT, url.split('/').at(-1)], {
      input: JSON.stringify(body), encoding: 'utf8', env: {...process.env,FIXTURE_TASK:new Headers(options.headers).get('x-aics-task-id') || process.env.FIXTURE_TASK || 'sdk-fixture'},
    });
    assert.equal(result.status, 0, result.stderr);
    return new Response(result.stdout, { headers: { 'content-type': 'application/json' } });
  }
  const handshake=memoryHandshake(body);if(handshake)return handshake;
  const responses = process.env.FIXTURE_API === 'responses';
  assert.ok(url.endsWith(responses ? '/responses' : '/chat/completions'), url);
  assert.equal(new Headers(options.headers).get('authorization'), 'Bearer test-only-never-saved');
  assert.ok(body.stream);
  if (process.env.FIXTURE_ERROR === 'socket') {
    assert.equal(++calls, 1, 'A disconnected submitted stream must not be sent again');
    const event = responses
      ? 'event: response.created\ndata: '+JSON.stringify({type:'response.created',response:{id:'socket-fixture',object:'response',status:'in_progress',output:[]}})+'\n\n'
      : 'data: '+JSON.stringify({id:'socket-fixture',object:'chat.completion.chunk',choices:[{index:0,delta:{role:'assistant',content:'正在处理'},finish_reason:null}]})+'\n\n';
    return new Response(new ReadableStream({start(controller) {
      controller.enqueue(new TextEncoder().encode(event));
      setTimeout(() => controller.error(new TypeError('terminated', {cause:Object.assign(new Error('other side closed'), {code:'UND_ERR_SOCKET'})})), 20);
    }}), {headers:{'content-type':'text/event-stream'}});
  }
  const identityInstructions = responses ? body.instructions : body.messages.filter(item => ['system', 'developer'].includes(item.role)).map(item => item.content).join('\n');
  assert.ok(identityInstructions.includes('你叫MxinspireX'));
  assert.ok(identityInstructions.includes('灵矩绘境研发'));
  assert.ok(!identityInstructions.includes('你是朗居设计'));
  const toolDefinitions = body.tools.map((entry) => responses ? entry : entry.function);
  const exposed = new Set(toolDefinitions.map(entry=>entry.name));
  assert.ok(['generate_batch','list_models','canvas_link_nodes','request_clarification'].every(name=>exposed.has(name)));
  const plannedText = Boolean(process.env.FIXTURE_DESIGN_PLAN) && calls >= 2;
  const plannedImages = Boolean(process.env.FIXTURE_BATCH);
  if (plannedText) {
    assert.ok(exposed.has('canvas_create_text') && exposed.has('generate_text'));
    assert.ok(!exposed.has('generate_image') && !exposed.has('generate_video') && !exposed.has('generate_audio'));
  } else if (plannedImages) {
    assert.ok(exposed.has('generate_image') && exposed.has('canvas_create_media'));
    assert.ok(!exposed.has('generate_video') && !exposed.has('generate_audio') && !exposed.has('generate_text'));
  } else {
    assert.ok(['generate_image','generate_video','generate_audio','canvas_create_text','canvas_create_media'].every(name=>exposed.has(name)));
  }
  if (process.env.FIXTURE_NETWORK !== undefined) assert.equal(toolDefinitions.some((entry) => entry.name === 'web_search'), process.env.FIXTURE_NETWORK === '1');
  assert.equal(responses ? body.reasoning?.effort : body.reasoning_effort, process.env.FIXTURE_EFFORT === 'omit' ? undefined : process.env.FIXTURE_EFFORT || 'low');
  assert.equal(body.parallel_tool_calls, true);
  assert.ok(toolDefinitions.every((entry) => entry.parameters.type === 'object'));
  const imageTool = toolDefinitions.find((entry) => entry.name === 'generate_image');
  if (imageTool) assert.equal(imageTool.strict, false);
  // History is hydrated on entry; later requests can replace that snapshot
  // with current tool results under the production context budget.
  if (calls === 0) assert.ok(JSON.stringify(responses ? body.input : body.messages).includes('之前的设计约束'));
  if (process.env.FIXTURE_ERROR) return new Response(JSON.stringify({ error: { message: '测试模型不可用', type: 'invalid_request_error' } }), { status: 400 });
  if (process.env.FIXTURE_STEERING && calls > 0) assert.ok(JSON.stringify(responses ? body.input : body.messages).includes('不要蓝色，改用绿色'), 'running supplement reaches every subsequent model judgment');
  const turn = calls++;
  const actions = process.env.FIXTURE_DESIGN_BRIEF ? [
    {name:'design_state',args:{brief:JSON.parse(process.env.FIXTURE_DESIGN_BRIEF),decisions:[{field:'scope',label:'范围',value:'一套品牌视觉',status:'confirmed',quote:'设计一套品牌视觉'}]}},
    {name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_DESIGN_PLAN)}},
    {name:'canvas_create_text',args:{text:'品牌使用手册：定位、识别、应用和使用规范'}},
  ] : process.env.FIXTURE_DESIGN_PLAN ? [
    {name:'canvas_create_text',args:{text:'保留用户要求的设计说明'}},
    {name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_DESIGN_PLAN)}},
    {name:'canvas_create_text',args:{text:'保留用户要求的设计说明'}},
  ] : [{name:'canvas_create_media',args:{asset_id:process.env.FIXTURE_ASSET,title:'船舶设计图'}},{name:'canvas_create_text',args:{text:'保留用户要求的设计说明'}}];
  const action = actions[turn];
  if (process.env.FIXTURE_DESIGN_BRIEF) {
    assert.ok(identityInstructions.includes('需求整理：'));
    assert.ok(toolDefinitions.find(entry=>entry.name==='design_state').parameters.properties.brief);
    if (turn > 0) {
      assert.ok(JSON.stringify(responses ? body.input : body.messages).includes('designBrief'));
      assert.ok(JSON.stringify(responses ? body.input : body.messages).includes('采用简洁现代风格'));
      assert.ok(JSON.stringify(responses ? body.input : body.messages).includes('derived'));
    }
  }
  const imageActions = Array.from({length:imageCount},(_,i)=>({name:'generate_image',args:{prompt:`image-${i}`,deliverable_ids:[`item-${i}`]}}));
  const batch = process.env.FIXTURE_BATCH ? turn === 0 ? [imageActions[0]] : turn === 1 ? [{name:'generate_batch',args:{items:imageActions.map(item=>({tool:item.name,arguments:item.args}))}}] : []
    : process.env.FIXTURE_PARALLEL ? turn === 0 ? imageActions : [] : action ? [action] : [];
  if (process.env.FIXTURE_BATCH && turn === 1) {
    assert.equal(startedImages, 0, 'serial attempt is redirected before any provider request');
    assert.ok(JSON.stringify(responses ? body.input : body.messages).includes('batch_required'));
  }
  if (process.env.FIXTURE_PARALLEL && turn > (process.env.FIXTURE_BATCH ? 1 : 0)) assert.equal(peakImages, imageCount, 'all independent outputs start before any completes');
  if (process.env.FIXTURE_DESIGN_PLAN) {
    assert.ok(toolDefinitions.some(entry=>entry.name==='design_plan'));
    const modelInput = JSON.stringify(responses ? [body.instructions, body.input] : body.messages);
    assert.ok(modelInput.includes('designPlanning'));
    if (turn >= 2) assert.ok(modelInput.includes('品牌使用手册'));
  }
  if (responses) {
    if (turn > 0) assert.ok(body.input.some((item) => item.type === 'function_call_output'));
    const output = batch.length ? batch.map((item,index)=>({ type: 'function_call', id: `fc_${turn}_${index}`, call_id: `call_${turn}_${index}`, name: item.name, arguments: JSON.stringify(item.args), status: 'completed' }))
      : [{ type: 'message', id: `msg_${turn}`, role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: '设计资产已保存，可以继续修改。', annotations: [] }] }];
    const response = { id: `resp_${turn}`, object: 'response', created_at: 1, model: body.model, status: 'completed', output, usage: { input_tokens: 10, output_tokens: 8, total_tokens: 18, input_tokens_details: { cached_tokens: 2, cache_write_tokens:1 } } };
    const events = [{ type: 'response.created', response: { ...response, status: 'in_progress', output: [] } }, ...output.flatMap((item,index)=>[{ type: 'response.output_item.added', output_index: index, item }, { type: 'response.output_item.done', output_index: index, item }]), { type: 'response.completed', response }];
    return new Response(events.map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'content-type': 'text/event-stream' } });
  }
  const delta = batch.length ? { role:'assistant', tool_calls:batch.map((item,index)=>({index,id:`call_${turn}_${index}`,type:'function',function:{name:item.name,arguments:JSON.stringify(item.args)}})) } : {role:'assistant',content:'设计资产已保存，'};
  if (turn > 0) assert.ok(body.messages.some((item) => item.role === 'tool'));
  const chunk = (value, reason = null) => ({ id: `chat-${turn}`, object: 'chat.completion.chunk', created: 1, model: 'fixture-model', choices: [{ index: 0, delta: value, finish_reason: reason }] });
  const chunks = [chunk(delta)];
  if (!batch.length) chunks.push(chunk({ content: '可以继续修改。' }));
  chunks.push(chunk({}, batch.length ? 'tool_calls' : 'stop'));
  chunks.push({ ...chunk({}), choices: [], usage: { prompt_tokens: 10, completion_tokens: 8, total_tokens: 18, prompt_tokens_details: { cached_tokens: 2, cache_write_tokens:1 } } });
  return new Response(chunks.map((entry) => `data: ${JSON.stringify(entry)}\n\n`).join('') + 'data: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } });
};
globalThis.fetch = async (...args) => {
  try { return await transport(...args); }
  catch (error) { console.error('Fixture transport:', error.message); throw error; }
};
