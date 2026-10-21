// Actual Agents SDK; model and external gateway responses are offline fixtures.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { sessionResponse } from './session_transport.mjs';
let calls = 0, submissions = 0, checks = 0;
globalThis.fetch = async (url, options) => {
  const session = sessionResponse(url, options); if (session) return session;
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    const name = String(url).split('/').at(-1);
    assert.ok(!['repair_control','canvas_update_node','generate_image'].includes(name), 'Must wait without repair or extra generation');
    if (name === 'generate_video') {
      assert.equal(++submissions, 1);
      assert.equal(body.source_asset_id, 'closed-box');
      assert.equal(body.last_frame_asset_id, 'open-box');
      return Response.json({job:{id:'video-job',status:'pending'},status:'pending'});
    }
    if (name === 'delivery_verify') {
      const waiting = process.env.FIXTURE_WAIT_FOR;
      const finished = waiting === 'finished_during_check' && checks++ > 0;
      return Response.json({pendingMedia: !finished && waiting !== 'preview' ? ['video-job'] : [], pendingPreview:waiting === 'preview' ? ['video-node'] : [],
        issues:['另一交付项尚未完成'], artifacts:[{nodeId:'existing',kind:'text',ready:true}], artifact_refs:[],
        deliverables:[{id:'missing',kind:'image',title:'另一个交付项',status:'pending',nodeIds:[]}]});
    }
    const result = spawnSync(process.env.FIXTURE_PYTHON,[process.env.FIXTURE_TOOL_SCRIPT,name],{input:JSON.stringify(body),encoding:'utf8',env:process.env});
    assert.equal(result.status, 0, result.stderr);
    return Response.json(JSON.parse(result.stdout));
  }
  assert.ok(String(url).endsWith('/responses'));
  assert.ok(calls < 2, 'No completion/review/repair stage while delivery is pending');
  assert.ok(!String(body.instructions).includes('你是独立审查者'));
  const definition = body.tools.find(tool => tool.name === 'generate_video');
  assert.ok(definition.parameters.properties.last_frame_asset_id, 'Tail must be visible to the real SDK model');
  assert.ok(definition.parameters.properties.source_asset_ids);
  const n = calls++, id = `frames-${n}`;
  const output = n === 0 ? {type:'function_call',id,call_id:id,name:'generate_video',arguments:JSON.stringify({prompt:'开盒',source_asset_id:'closed-box',last_frame_asset_id:'open-box',params:{duration:8},output_mode:'create'}),status:'completed'}
    : {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text:'视频已提交，等待生成。',annotations:[]}]};
  const response = {id,object:'response',created_at:1,model:body.model,status:'completed',output:[output],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item:output},{type:'response.output_item.done',output_index:0,item:output},{type:'response.completed',response}];
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
