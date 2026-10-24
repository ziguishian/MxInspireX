import {expect, it} from 'vitest';
import {webMediaAllowed, directWeb, webTools, supportingWebMedia, waitForWebMedia} from '../app/web_generation.mjs';
import {directSingleArtifact} from '../app/execution_efficiency.mjs';

it('opens page media composition only for conversation HTML', () => {
  for (const kind of ['image','video','audio','text']) {
    expect(webMediaAllowed({}, new Set(['html']), kind)).toBe(true);
    expect(webMediaAllowed({taskSurface:'canvas_node'}, new Set(['html']), kind)).toBe(false);
    expect(webMediaAllowed({}, new Set(['image']), kind)).toBe(false);
  }
  expect(webMediaAllowed({}, new Set(['html']), 'cad')).toBe(false);
  expect(directSingleArtifact({executionPolicyVersion:3,singleDeliveryTarget:{kind:'html',count:1}})).toBe(false);
});

const plan = {ready:true,deliverables:[{id:'hero',kind:'image',supporting:true},{id:'page',kind:'html',dependsOn:['hero'],
  inputs:[{source:'deliverable',id:'hero',role:'content'}]}]};
it('keeps a small page path with a media/planning escape hatch and restores complex work', () => {
  const constraints={executionPolicyVersion:3,singleDeliveryTarget:{kind:'html',count:1}};
  expect(directWeb(constraints,{},0)).toBe(true);
  expect(directWeb({...constraints,referencedAssets:['photo']},{},0,[{assetId:'photo',mime:'image/png'}])).toBe(true);
  for (const extra of [{taskSurface:'canvas_node'},{designPlan:plan},{continuation:{}},{referencedFiles:['doc']}])
    expect(directWeb({...constraints,...extra},{},0)).toBe(false);
  expect(directWeb(constraints,{active:[{}]},0)).toBe(false);
  expect(directWeb(constraints,{},1)).toBe(false);
  expect(webTools.has('design_plan') && webTools.has('generate_batch')).toBe(true);
  expect(webTools.has('generate_text')).toBe(false);
});
it('overlaps only explicit supporting content, never future visual identity', () => {
  const args={deliverable_ids:['hero']};
  expect(supportingWebMedia({},plan,'generate_image',args)).toBe(true);
  expect(supportingWebMedia({taskSurface:'canvas_node'},plan,'generate_image',args)).toBe(false);
  expect(supportingWebMedia({},plan,'generate_image',{deliverable_ids:['unknown']})).toBe(false);
  const identity=structuredClone(plan); identity.deliverables[1].inputs[0].role='identity';
  expect(supportingWebMedia({},identity,'generate_image',args)).toBe(false);
});
it.each(['image','audio'])('queries only the accepted %s operation after checkpoint restoration',async kind => {
  const urls=[];
  const output=await waitForWebMedia({record:JSON.parse(JSON.stringify({name:`generate_${kind}`,args:{prompt:'exact'},output:{operationId:'accepted'}})),
    baseUrl:'http://fixture',projectId:'p',taskId:'t',fetchResult:async(url,options)=>{
      urls.push(url); expect(options.method).toBe('GET');
      return Response.json({state:'completed',output:{status:'succeeded',assetId:'saved'}});
    }});
  expect(urls).toEqual([`http://fixture/api/projects/p/tasks/t/${kind}-operations/accepted`]);
  expect(output.assetId).toBe('saved');
});
it.each(['cancelled','unconfirmed'])('never resubmits %s media',async state => {
  const output=await waitForWebMedia({record:{name:'generate_image',output:{operationId:'accepted'}},baseUrl:'http://fixture',projectId:'p',taskId:'t',
    fetchResult:async(_url,options)=>{expect(options.method).toBe('GET');return Response.json({state});}});
  expect(output.status).toBe(state==='cancelled'?'cancelled':'generation_unconfirmed');
  expect(output.retryable).toBe(false);
});
it('preserves persisted async HTTP rejection as a terminal failure',async()=>{
  const result=await waitForWebMedia({record:{name:'generate_audio',output:{operationId:'accepted'}},baseUrl:'http://fixture',projectId:'p',taskId:'t',
    fetchResult:async()=>Response.json({state:'completed',httpStatus:422,output:{detail:'Unsupported voice',submitted:false}})});
  expect(result).toMatchObject({status:'failed',stopTool:true,retryable:false,submitted:false,message:'Unsupported voice'});
});
it('waits for a saved video using local GETs and honors task cancellation',async () => {
  const options={record:{name:'generate_video',output:{job:{id:'original'}}},baseUrl:'http://fixture',projectId:'p',taskId:'t'};
  const saved=await waitForWebMedia({...options,fetchResult:async(url,opts)=>{
    expect(opts.method).toBe('GET');
    return Response.json(url.endsWith('/tasks/t')?{status:'running'}:url.endsWith('/video/jobs')?
      [{id:'original',outputAssetId:'video',metadata:{taskId:'t',canvasSynced:true}}]:{nodes:[{id:'n',data:{assetId:'video'}}]});
  }});
  expect(saved).toMatchObject({status:'succeeded',assetId:'video'});
  const cancelled=await waitForWebMedia({...options,fetchResult:async()=>Response.json({status:'cancelled'})});
  expect(cancelled.status).toBe('cancelled');
});
