import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

let designCalls = 0, reviewCalls = 0;
globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    const name = String(url).split('/').at(-1);
    if (name === 'canvas_create_text') assert.equal(body.canvas_node_id,process.env.FIXTURE_TARGET);
    else if (name === 'delivery_snapshot') assert.ok(Array.isArray(body.refs));
    else assert.fail(`Unneeded tool: ${name}`);
    const result = spawnSync(process.env.FIXTURE_PYTHON,[process.env.FIXTURE_TOOL_SCRIPT,name],{input:JSON.stringify(body),encoding:'utf8',env:process.env});
    assert.equal(result.status,0,result.stderr);
    const output = JSON.parse(result.stdout);
    assert.ok(!JSON.stringify(output).includes('UNRELATED_CONTENT'));
    if (name === 'delivery_snapshot') assert.ok(JSON.stringify(output).includes(process.env.FIXTURE_TARGET));
    return Response.json(output);
  }
  assert.ok(!JSON.stringify(body).includes('UNRELATED_CONTENT'),'Unrelated canvas bodies must not enter model context');
  for (const name of ['generate_image','generate_video','canvas_create_text','canvas_create_html']) {
    const schema=body.tools.find(t=>t.name===name)?.parameters;
    if (schema) assert.ok(schema.properties.canvas_node_id && schema.properties.output_mode, `${name} must expose the model's target selection`);
  }
  const review = String(body.instructions).includes('你是独立审查者');
  if (review) { reviewCalls++; assert.equal(body.tools.length, 0); }
  const first = !review && designCalls++ === 0;
  const id = `focus-${review}-${review?reviewCalls:designCalls}`;
  const item = first
    ? {type:'function_call',id,call_id:id,name:review?'canvas_read':'canvas_create_text',arguments:JSON.stringify(review?{}:{text:'已按要求修改引用文案',title:'引用文案',canvas_node_id:process.env.FIXTURE_TARGET,output_mode:'edit'}),status:'completed'}
    : {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text:review?JSON.stringify({passed:true,issues:[],summary:'已检查本轮节点'}):'已修改引用文案。',annotations:[]}]};
  const response = {id,object:'response',created_at:1,model:body.model,status:'completed',output:[item],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
