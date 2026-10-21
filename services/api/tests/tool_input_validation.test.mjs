import {describe, expect, it} from 'vitest';
import {normalizeToolInput, bindPlanVersion, reusesReadyPlan, ToolInputNormalizationError} from '../app/tool_input_validation.mjs';
import {normalizeBatchItems} from '../app/generation_batch.mjs';
import {z} from 'zod';
import {validateBatchArguments,inputFailure} from '../app/tool_input_validation.mjs';

it('reports every invalid batch item before dispatch with exact item paths',()=>{
  const schemas=new Map([['generate_image',z.object({prompt:z.string().min(1),size:z.number().positive()})]]);
  const items=[{tool:'generate_image',arguments:{prompt:'',size:-1}},{tool:'generate_image',arguments:{prompt:42,size:0}}];
  let failure;
  try {validateBatchArguments(items,schemas);} catch(error) {failure=inputFailure('generate_batch',error);}
  expect(failure.submitted).toBe(false);
  expect(failure.fieldPath).toBe('items.*.arguments.prompt|items.*.arguments.size');
  expect(failure.errors.map(e=>e.path)).toEqual(['items.0.arguments.prompt','items.0.arguments.size','items.1.arguments.prompt','items.1.arguments.size']);
  expect(validateBatchArguments([{tool:'generate_image',arguments:{prompt:'blue cup',size:1024}}],schemas)).toHaveLength(1);
});

const constraints={designPlanning:{areas:[{id:'visuals',title:'关键设计表达',aliases:['关键视觉']}]}};
const plan={ready:true,deliverables:[{id:'a',kind:'image'},{id:'b',kind:'image'},{id:'c',kind:'text'}]};
describe('local correction without model or provider calls',()=>{
  it('binds plan writes to the observed plan version, not model-generated state revisions',()=>{
    const input={plan:{goal:'首次计划'},expected_revision:2,expected_scope_id:'unrelated-state'};
    expect(bindPlanVersion(input,{revision:0})).toEqual({...input,expected_revision:0,expected_scope_id:undefined});
    expect(bindPlanVersion(input,{revision:7,scopeId:'actual-plan'}).expected_revision).toBe(7);
    expect(input.expected_revision).toBe(2);
    const flat=normalizeToolInput('design_plan',{goal:'首次计划',expected_revision:2});
    expect(bindPlanVersion(flat,{revision:0}).expected_revision).toBe(0);
  });
  it('moves only supplied plan fields, resolves known labels, preserves the original payload',()=>{
    const input={plan:{goal:'完整设计',preserve:['用户要求']},deliverables:[{id:'a'}],coverage:[{area:'七项关键视觉',status:'included',detail:'七图'}],research:'已有资料'};
    const normalized=normalizeToolInput('design_plan',input,constraints);
    expect(normalized.plan).toEqual({...input.plan,deliverables:input.deliverables,coverage:[{...input.coverage[0],area:'visuals'}],research:'已有资料'});
    expect(input.plan.deliverables).toBeUndefined();
    expect(input.coverage[0].area).toBe('七项关键视觉');
    expect(normalizeToolInput('design_plan',{plan:{coverage:[{area:'不明确的自定义范围'}]}},constraints).plan.coverage[0].area).toBe('不明确的自定义范围');
    expect(normalizeToolInput('design_plan',{plan:{}})).toEqual({});
    expect(()=>normalizeToolInput('design_plan',{plan:{goal:'a'},goal:'b'})).toThrow(ToolInputNormalizationError);
  });
  it('reuses ready plans before interpreting replacement fields but validates explicit changes',()=>{
    expect(reusesReadyPlan({plan:{goal:'重复改写'}},plan,{status:'ready'})).toBe(true);
    expect(reusesReadyPlan({plan:{},deliverables:[{id:'a'}]},plan,{status:'ready'})).toBe(true);
    for(const args of [{plan:{}},{}, {plan:{goal:'新信息'},change_reason:'用户新增要求'}, {plan:{},change_reason:3}])expect(reusesReadyPlan(args,plan,{status:'ready'})).toBe(false);
    expect(reusesReadyPlan({plan:{goal:'x'}},plan,{status:'needs_plan'})).toBe(false);
  });
  it('infers the image tool only from explicit ready plan bindings and never changes paid arguments',()=>{
    const input={deliverable_ids:['a'],arguments:{prompt:'具体设计',source_asset_ids:['original'],params:{aspect_ratio:'4:3'}}};
    expect(normalizeBatchItems([input],plan)).toEqual([{tool:'generate_image',arguments:{...input.arguments,deliverable_ids:['a']}}]);
    expect(input.tool).toBeUndefined();expect(input.arguments.deliverable_ids).toBeUndefined();
    for(const ids of [[],['unknown'],['a','c'],['c']])expect(normalizeBatchItems([{arguments:{prompt:'x',deliverable_ids:ids}}],plan)[0].tool).toBeUndefined();
    expect(normalizeBatchItems([input],{...plan,ready:false})[0].tool).toBeUndefined();
    expect(normalizeBatchItems([{...input,tool:'incorrect'}],plan)[0].tool).toBe('incorrect');
  });
  it('rejects conflicting bindings locally before any generation',()=>{
    expect(()=>normalizeBatchItems([{tool:'generate_image',deliverable_ids:['a'],arguments:{deliverable_ids:['b'],prompt:'x'}}],plan)).toThrow(ToolInputNormalizationError);
    expect(normalizeBatchItems([null,{arguments:'invalid'}],plan)).toEqual([null,{arguments:'invalid'}]);
  });
});
