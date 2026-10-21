import { describe, expect, it } from 'vitest';
import { missingDeliverables, latestClarification, completionDecision } from '../app/delivery_execution.mjs';

it('shares completion decisions without resubmitting unknown or pending media',()=>{
  const constraints={executionPolicyVersion:2,singleDeliveryTarget:{kind:'image',count:1}};
  const image={name:'generate_image',output:{status:'succeeded',assetId:'a',node:{id:'n',data:{kind:'image',assetId:'a'}}}};
  expect(completionDecision(constraints,[image]).finish).toBe(true);
  expect(completionDecision(constraints,[image],{updatePending:true})).toMatchObject({finish:false,reason:'user_update',missing:[]});
  for(const output of [{status:'generation_unconfirmed'},{stopTool:true},{node:{data:{generating:true}}},{job:{id:'paid'}}]) {
    expect(completionDecision(constraints,[{name:'generate_image',output}],{delivery:{deliverables:[{id:'a',status:'pending'}]}})).toMatchObject({finish:false,missing:[]});
  }
  expect(completionDecision({},[],{delivery:{pendingMedia:['n'],deliverables:[{id:'a',status:'pending'}]}}).missing).toEqual([]);
  expect(completionDecision({},[],{delivery:{deliverables:[{id:'a',status:'pending'},{id:'b',status:'blocked'}]}}).missing.map(x=>x.id)).toEqual(['a']);
});

describe('deliverable execution decisions', () => {
  it('hands an accepted single video to the poller without another model round', () => {
    const output = {name:'generate_video',output:{status:'processing',job:{id:'job',metadata:{canvasNodeId:'video'}}}};
    const constraints = {deliveryContract:[{kind:'video',count:1}]};
    expect(completionDecision(constraints,[output])).toMatchObject({finish:true,reason:'video_submitted'});
    expect(completionDecision({canvasParams:{kind:'video',canvasNodeId:'video'}},[output]).finish).toBe(true);
    expect(completionDecision(constraints,[output],{updatePending:true}).finish).toBe(false);
    expect(completionDecision({deliveryContract:[{kind:'video',count:2}]},[output]).finish).toBe(false);
    expect(completionDecision({deliveryContract:[{kind:'video'},{kind:'image'}]},[output]).finish).toBe(false);
    expect(completionDecision({canvasParams:{kind:'video',canvasNodeId:'other'}},[output]).finish).toBe(false);
    expect(completionDecision(constraints,[{name:'generate_video',output:{status:'generation_unconfirmed'}}]).finish).toBe(false);
  });
  it('continues only missing outputs and does not repair missing media with text tools', () => {
    const delivery = { artifacts: [{nodeId:'copy',kind:'text',ready:true},{nodeId:'hero',kind:'image',ready:true}], deliverables: [{id:'a',status:'ready'},{id:'b',status:'pending'},{id:'c',status:'blocked'}] };
    expect(missingDeliverables(delivery).map(d=>d.id)).toEqual(['b']);
  });
  it('uses the latest clarification result after the completion stage', () => {
    const calls = [{name:'request_clarification',output:{awaitingUser:true,questions:[{id:'q'}]}}];
    expect(latestClarification(calls).questions[0].id).toBe('q');
    calls.push({name:'request_clarification',output:{awaitingUser:false,questions:[],answered:[{field:'quantity',value:'300套'}]}});
    expect(latestClarification(calls)).toBeNull();
  });
  it('stops on unresolved plan questions without requiring another model tool call', () => {
    const calls = [{name:'design_plan',output:{status:'needs_clarification',plan:{openQuestions:['品牌正式名称是什么？']}}}];
    expect(latestClarification(calls)).toMatchObject({awaitingUser:true,source:'design_plan'});
    expect(latestClarification(calls).questions[0]).toMatchObject({question:'品牌正式名称是什么？',options:[]});
  });
});
