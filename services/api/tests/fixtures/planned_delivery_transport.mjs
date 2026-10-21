// Actual SDK + Python tool registry, with only model responses simulated.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { sessionResponse } from './session_transport.mjs';
let calls = 0;
const nodes = {};
const mode = process.env.FIXTURE_COMPLETION_MODE;
globalThis.fetch = async (url, options) => {
  const session = sessionResponse(url,options); if(session) return session;
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    const name = String(url).split('/').at(-1);
    assert.ok(!['generate_video','canvas_create_svg','repair_control'].includes(name));
    if (name === 'generate_image') assert.equal(body.provider,'local-placeholder','Only the offline PNG fixture may generate images');
    const result = spawnSync(process.env.FIXTURE_PYTHON,[process.env.FIXTURE_TOOL_SCRIPT,name],{input:JSON.stringify(body),encoding:'utf8',env:process.env});
    assert.equal(result.status,0,result.stderr);
    const output = JSON.parse(result.stdout);
    if (name === 'generate_image') nodes[body.deliverable_ids[0]] = output.node.id;
    return Response.json(output);
  }
  assert.ok(String(url).endsWith('/responses'));
  const review = String(body.instructions).includes('你是独立审查者');
  const n = calls++, id = `planned-${n}`;
  let action, text;
  if (review) {
    assert.notEqual(mode,'clarify','New clarification from completion must pause review');
    assert.equal(Object.keys(nodes).length,2,'Both missing and original outputs must exist before review');
    text = JSON.stringify({passed:true,summary:'已核对实际 PNG 内容',checks:mode === 'unverified' ? [] : Object.entries(nodes).map(([planItemId,artifactId])=>({planItemId,artifactId,category:'content',status:'passed',message:'对应概念图已保存'}))});
  } else if(n === 0) action = {name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_DESIGN_PLAN)}};
  else if(n === 1) action = {name:'generate_image',args:{provider:'local-placeholder',prompt:'外盒概念',deliverable_ids:['outer']}};
  else if(n === 2) text = '外盒概念图已保存。';
  else if(n === 3) {
    assert.ok(JSON.stringify(body.input).includes('尚未交付'),'Missing item must go through completion stage');
    action = mode === 'clarify' ? {name:'request_clarification',args:{questions:[{id:'material',question:'内托材质是否已确定？',options:['纸浆托','海绵托']}]}} : {name:'generate_image',args:{provider:'local-placeholder',prompt:'内装概念',deliverable_ids:['inner']}};
  } else { assert.equal(n,4); text = mode === 'clarify' ? '请补充内托材质，已有外盒图已保留。' : '两张概念图已保存。'; }
  const output = action ? {type:'function_call',id,call_id:id,name:action.name,arguments:JSON.stringify(action.args),status:'completed'} : {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]};
  const response = {id,object:'response',created_at:1,model:body.model,status:'completed',output:[output],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item:output},{type:'response.output_item.done',output_index:0,item:output},{type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
