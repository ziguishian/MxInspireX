import assert from 'node:assert/strict';
import { appendFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

let reviews = 0;
globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    const name = String(url).split('/').at(-1);
    appendFileSync(process.env.FIXTURE_CALL_LOG, JSON.stringify({name, args:body}) + '\n');
    assert.ok(!/generate_|canvas_create|canvas_update/.test(name), 'Review must never regenerate or modify saved assets');
    if (name === 'delivery_snapshot' && process.env.FIXTURE_REVIEW_ERROR === 'inspection') {
      return Response.json({detail:'目标不在本轮引用、对话相关内容或本轮产物中。'}, {status:400});
    }
    const result = spawnSync(process.env.FIXTURE_PYTHON, [process.env.FIXTURE_TOOL_SCRIPT, name], {input:JSON.stringify(body), encoding:'utf8', env:process.env});
    assert.equal(result.status, 0, result.stderr);
    return Response.json(JSON.parse(result.stdout));
  }
  assert.ok(String(url).endsWith('/responses'));
  assert.ok(String(body.instructions).includes('你是独立审查者'), 'Only review should run');
  assert.equal((body.tools || []).length, 0, 'Single-pass review exposes no read or repair tools');
  const images = body.input.flatMap(item=>item.content || []).filter(part=>part.type==='input_image');
  assert.equal(images.length, 2, 'One contact sheet and one low-resolution detail sheet, no originals');
  assert.ok(images[0].image_url.startsWith('data:image/jpeg;base64,'));
  appendFileSync(process.env.FIXTURE_CALL_LOG, JSON.stringify({name:'review_model'}) + '\n');
  if (process.env.FIXTURE_REVIEW_ERROR === 'model') return Response.json({error:{message:'review service unavailable'}}, {status:503});
  if (process.env.FIXTURE_REVIEW_ERROR === 'timeout') {
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => resolve(Response.json({error:{message:'late review'}}, {status:503})), 1000);
      options.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(options.signal.reason || new Error('aborted')); }, {once:true});
    });
  }
  const id = `review-${++reviews}`;
  const review = {passed:true, summary:'纸杯图内容检查通过', checks:[{category:'content',status:'passed',artifactId:process.env.FIXTURE_NODE,message:'纸杯内容符合要求'}]};
  const output = {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text:JSON.stringify(review),annotations:[]}]};
  const response = {id,object:'response',created_at:1,model:body.model,status:'completed',output:[output],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}}, {type:'response.output_item.added',output_index:0,item:output}, {type:'response.output_item.done',output_index:0,item:output}, {type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''), {headers:{'content-type':'text/event-stream'}});
};
