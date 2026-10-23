import {it, expect} from 'vitest';
import {directSingleArtifact, readyPlanExecution, singleDeliveryComplete, receiptView, nestedTextAllowed, selectRules} from '../app/execution_efficiency.mjs';
import {singleImageToolAllowed,singleImageFrame} from '../app/execution_efficiency.mjs';
import {completionDecision} from '../app/delivery_execution.mjs';

it('keeps read and clarification fallbacks while omitting unused write schemas',()=>{
  const memory={analysisMode:'explicit_single_image'};
  expect(singleImageToolAllowed('generate_image',memory)).toBe(true);
  expect(singleImageToolAllowed('request_clarification',memory)).toBe(true);
  expect(singleImageToolAllowed('conversation_memory_update',memory)).toBe(false);
  expect(singleImageToolAllowed('conversation_memory_update',memory,[{name:'conversation_memory_read'}])).toBe(true);
  expect(singleImageToolAllowed('conversation_memory_update',{})).toBe(true);
});
it('projects a small frame without dropping visual constraints or editing scope',()=>{
  const frame={requirements:{currentRequest:'repeated request',earlierUserExcerpts:['preserve the logo']},
    generationConstraints:{canvasParams:{size:'1024x1024'},imageStyle:'neutral'},scope:{mode:'edit',nodeIds:['original']},
    attachments:[{assetId:'a',filename:'photo.jpg',mime:'image/jpeg',data:'x'.repeat(10000)}],
    evidence:{preserve:['real product']},notice:'current corrective instruction',outcomes:{body:'x'.repeat(10000)}};
  const original=structuredClone(frame),view=singleImageFrame(frame);
  expect(view.requirements.earlierUserExcerpts).toEqual(['preserve the logo']);
  expect(view.generationConstraints).toEqual(frame.generationConstraints);
  expect(view.scope.nodeIds).toEqual(['original']);
  expect(view.notice).toBe(frame.notice);
  expect(JSON.stringify(view).length).toBeLessThan(1000);
  expect(frame).toEqual(original);
});

const context = {executionPolicyVersion:2,singleDeliveryTarget:{kind:'image',count:1}};
const image = {name:'generate_image',output:{status:'succeeded',assetId:'asset',node:{id:'node',data:{kind:'image',assetId:'asset'}}}};
it('stops a clarified single image after its saved receipt, but preserves steering and pending results',()=>{
  const clarified={...context,clarificationContinuation:true,clarificationTaskId:'source',continuation:{taskId:'source'}};
  const outputs=[{name:'asset_inspect',output:{}},{name:'design_state',output:{}},image];
  expect(completionDecision(clarified,outputs).finish).toBe(true);
  expect(completionDecision(clarified,outputs,{updatePending:true}).finish).toBe(false);
  expect(completionDecision(clarified,[{...image,output:{status:'generation_unconfirmed',stopTool:true}}]).finish).toBe(false);
});
it('reuses ready plans but reopens planning for steering, new batches or execution failures', () => {
  const plan = {ready:true,deliverables:[{id:'logo',kind:'image',acceptance:'保留品牌拼写'}]};
  expect(readyPlanExecution(context,plan,{status:'ready'})).toBe(true);
  expect(readyPlanExecution(context,plan,{status:'ready'},[{name:'generate_batch',output:{status:'invalid_arguments'}}])).toBe(true);
  expect(readyPlanExecution(context,plan,{status:'needs_plan'})).toBe(false);
  expect(readyPlanExecution(context,plan,{},[],1)).toBe(false);
  expect(readyPlanExecution(context,plan,{},[{name:'generate_image',output:{status:'failed'}}])).toBe(false);
  expect(readyPlanExecution(context,plan,{},[{name:'generate_image',output:{status:'design_spec_required',submitted:false}}])).toBe(false);
  expect(readyPlanExecution(context,{...plan,ready:false},{})).toBe(false);
  expect(readyPlanExecution(context,{...plan,openQuestions:['用途？']},{})).toBe(false);
  expect(plan.deliverables[0].acceptance).toBe('保留品牌拼写');
});
it('limits optional planning only for a new unambiguous artifact without references or skills', () => {
  expect(directSingleArtifact(context)).toBe(true);
  expect(directSingleArtifact(context,{},1)).toBe(false);
  expect(directSingleArtifact(context,{active:[{name:'required-skill'}]})).toBe(false);
  for (const extra of [{executionPolicyVersion:1},{designPlan:{ready:true}},{referenceWorkflow:{status:'required'}},
    {referencedAssets:[{id:'reference'}]},{referencedFiles:[{id:'document'}]},{deliveryRepairOnly:true}]) {
    expect(directSingleArtifact({...context,...extra})).toBe(false);
  }
});
it('completes only one real artifact under an unambiguous new contract', () => {
  expect(singleDeliveryComplete(context,[image])).toBe(true);
  for (const result of [{status:'generation_unconfirmed'}, {status:'failed'}, {status:'succeeded',job:{id:'job'}},
    {...image.output,node:{id:'node',data:{generating:true}}}]) {
    expect(singleDeliveryComplete(context,[{...image,output:result}])).toBe(false);
  }
  expect(singleDeliveryComplete(context,[image,image])).toBe(true);
  const inpaint={...image,name:'image_edit',args:{operation:'inpaint'}};
  expect(singleDeliveryComplete(context,[inpaint])).toBe(true);
  expect(singleDeliveryComplete(context,[inpaint,image])).toBe(true);
  expect(singleDeliveryComplete(context,[{name:'generate_image',output:{status:'reference_mismatch',submitted:false}},image])).toBe(true);
  expect(singleDeliveryComplete(context,[{name:'generate_image',output:{status:'generation_unconfirmed'}},image])).toBe(false);
  expect(singleDeliveryComplete(context,[image,{...image,output:{...image.output,node:{id:'second',data:{assetId:'second'}}}}])).toBe(false);
  expect(singleDeliveryComplete(context,[image,{name:'request_clarification'}])).toBe(false);
  expect(singleDeliveryComplete(context,[{name:'request_clarification',output:{awaitingUser:true}},
    {name:'request_clarification',output:{awaitingUser:false}},image])).toBe(true);
  expect(singleDeliveryComplete({...context,executionPolicyVersion:1},[image])).toBe(false);
  expect(singleDeliveryComplete({...context,singleDeliveryTarget:{kind:'image',count:1,nodeId:'different'}},[image])).toBe(false);
  for (const kind of ['text','html']) {
    expect(singleDeliveryComplete({...context,singleDeliveryTarget:{kind,count:1}},
      [{name:'canvas_create_'+kind,output:{node:{id:'n',data:{[kind]:'完整的内容'}}}}])).toBe(true);
  }
});
it('uses the single-image path with resolved images, while preserving complex inputs and steering', () => {
  const references = {...context,referencedFiles:[{pathRelative:'product.jpg'}],referenceWorkflow:{status:'provided'}};
  const images = [{assetId:'product',mime:'image/jpeg'}];
  expect(directSingleArtifact(references,{},0,images)).toBe(true);
  expect(directSingleArtifact(references,{},1,images)).toBe(false);
  expect(directSingleArtifact(references,{requested:['brand-skill']},0,images)).toBe(false);
  expect(directSingleArtifact(references,{},0,[...images,{mime:'application/pdf'}])).toBe(false);
  for (const focus of [{selectionRequired:true},{unattachedFileCount:1},{unattachedAssetReferences:[{id:'missing'}]},
    {nodes:[{data:{kind:'html'}}]}]) expect(directSingleArtifact({...references,focusContext:focus},{},0,images)).toBe(false);
});
it('keeps canonical content and exact failure IDs while shrinking successful write receipts', () => {
  const result = {status:'succeeded',node:{id:'n',data:{text:'正文'.repeat(5000),summary:'正文'.repeat(5000),deliveryBinding:{itemIds:['a']}}},canvas:{nodes:Array(30).fill(image.output.node)}};
  const before = structuredClone(result);
  const view = receiptView('canvas_create_text',result);
  expect(result).toEqual(before);
  expect(JSON.stringify(view).length).toBeLessThan(900);
  expect(view.node.data.deliveryBinding.itemIds).toEqual(['a']);
  expect(view.readMore.arguments.node_ids).toEqual(['n']);
  const failure = {...result,status:'reference_mismatch',errors:[{assetIds:['exact-long-id']}]};
  expect(receiptView('generate_image',failure)).toBe(failure);
});
it('retains explicit skill and legacy tool contracts and core quality rules', () => {
  expect(nestedTextAllowed({},{})).toBe(true);
  expect(nestedTextAllowed(context)).toBe(false);
  expect(nestedTextAllowed(context,{}, {active:[{requiredTools:['generate_text']}]})).toBe(true);
  const rules=['保留原始用户要求、imageSpec、验收和真实来源','网页默认按桌面设计','CAD 只使用合法语法'];
  expect(selectRules(rules,context,new Set(['image']))).toEqual([rules[0]]);
  expect(selectRules(rules,{},new Set(['image']))).toEqual(rules);
});
