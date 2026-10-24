import { describe, it, expect } from 'vitest';
import { generationBatchRequired, normalizeBatchItems, readyGenerationItems, runGenerationBatch, generationAttemptComplete, partitionIdentityBatch, identityPreviewAssets } from '../app/generation_batch.mjs';

const item = (id, kind='image', dependsOn=[]) => ({id,kind,title:id,acceptance:'可独立使用',dependsOn});
const context = items => ({designPlan:{ready:true,scopeId:'scope',deliverables:items}});
const request = (id, tool='generate_image') => ({tool,arguments:{prompt:id,deliverable_ids:[id]}});
const output = (id, kind='image') => ({name:`generate_${kind}`,output:{status:'succeeded',node:{id,data:{deliveryBinding:{scopeId:'scope',itemIds:[id]}}}}});

describe('same-product stages',()=>{
  const plan={deliverables:[item('product'),{...item('scene','image',['product']),inputs:[{source:'deliverable',id:'product',role:'identity'}]},
    item('copy','text'),item('page','html',['scene'])]};
  it('defers unseen scene inputs and their consumers, keeping independent work',()=>{
    const split=partitionIdentityBatch([request('scene'),request('copy','canvas_create_text'),request('page','canvas_create_html'),request('product')],plan);
    expect(split.ready.map(op=>op.arguments.deliverable_ids[0])).toEqual(['copy','product']);
    expect(split.deferred.map(op=>op.arguments.deliverable_ids[0])).toEqual(['scene','page']);
    expect(partitionIdentityBatch([request('scene')],plan).deferred).toEqual([]);
    const existing={deliverables:[{...item('scene'),inputs:[{source:'asset',id:'existing',role:'identity'}]},item('product')]};
    expect(partitionIdentityBatch([request('scene'),request('product')],existing).deferred).toEqual([]);
  });
  it('exposes only saved identity parents for a local pixel read; failed/unknown outputs are not previews',()=>{
    const result={results:[{status:'succeeded',assetId:'base',deliverable_ids:['product']},
      {status:'succeeded',assetId:'copy',deliverable_ids:['copy']},
      {status:'generation_unconfirmed',assetId:'unknown',deliverable_ids:['product']}]};
    expect(identityPreviewAssets(plan,'generate_batch',result)).toEqual(['base']);
    expect(identityPreviewAssets(plan,'generate_image',{status:'succeeded',assetId:'base',node:{data:{deliveryBinding:{itemIds:['product']}}}})).toEqual(['base']);
    expect(identityPreviewAssets(plan,'generate_image',{status:'failed'})).toEqual([]);
  });
});

describe('generic generation batches', () => {
  it('uses saved delivery bindings and never counts another scope as complete',()=>{
    const constraints=context([item('a')]);
    const saved={name:'generate_image',args:{},output:{status:'succeeded',assetId:'asset',node:{id:'node',
      data:{deliveryBinding:{scopeId:'scope',itemIds:['a']}}}}};
    expect(generationAttemptComplete(constraints,[saved])).toBe(true);
    saved.args.deliverable_ids=['a'];
    saved.output.node.data.deliveryBinding.scopeId='previous-scope';
    expect(generationAttemptComplete(constraints,[saved])).toBe(false);
  });
  it('hands off only settled selected items; invalid arguments and unsaved outputs still need work',()=>{
    const constraints=context([item('a'),item('b')]);
    const saved={name:'generate_image',args:{deliverable_ids:['a']},output:{status:'succeeded',assetId:'saved',node:{id:'n',data:{}}}};
    const failed={name:'generate_image',args:{deliverable_ids:['b']},output:{status:'invalid_arguments'}};
    expect(generationAttemptComplete(constraints,[saved,failed])).toBe(false);
    expect(generationAttemptComplete(constraints,[saved])).toBe(false);
    const unknown={...failed,output:{status:'generation_unconfirmed',retryable:false}};
    expect(generationAttemptComplete(constraints,[saved,unknown])).toBe(true);
    expect(generationAttemptComplete(constraints,[saved,{...failed,output:{status:'failed',stopTool:true,errorCode:'image_provider_access'}}])).toBe(true);
    expect(generationAttemptComplete(constraints,[{...saved,output:{status:'succeeded'}},unknown])).toBe(false);
    expect(generationAttemptComplete({...constraints,designBatch:{status:'needs_plan',itemIds:['a','b']}},[saved,unknown])).toBe(false);
    expect(generationAttemptComplete({...constraints,designBatch:{status:'ready',itemIds:['a']}},[saved])).toBe(true);
    expect(generationAttemptComplete({...constraints,deliveryRepairOnly:true},[saved,unknown])).toBe(false);
  });
  it('normalizes item-level delivery ids without losing canonical nested ids', () => {
    expect(normalizeBatchItems([{tool:'generate_image',deliverable_ids:['B1'],arguments:{prompt:'one'}}]))
      .toEqual([{tool:'generate_image',arguments:{prompt:'one',deliverable_ids:['B1']}}]);
    expect(normalizeBatchItems([{tool:'generate_image',arguments:{prompt:'one',deliverable_ids:['B1']}}]))
      .toEqual([{tool:'generate_image',arguments:{prompt:'one',deliverable_ids:['B1']}}]);
    expect(() => normalizeBatchItems([{tool:'generate_image',deliverable_ids:['B1'],arguments:{deliverable_ids:['B2']}}]))
      .toThrow('不一致');
  });
  it('schedules only the registered current batch and inherits real prerequisites', () => {
    const constraints=context([item('B1'),item('B2a','image',['B1']),item('B2b')]);
    constraints.designBatch={intent:'next_batch',status:'needs_plan',number:2,itemIds:[]};
    constraints.deliveryProgress=[{id:'B1',status:'passed'}];
    expect(readyGenerationItems(constraints)).toEqual([]);
    const outputs=[{name:'design_plan',output:{plan:constraints.designPlan,batch:{...constraints.designBatch,status:'ready',itemIds:['B2a','B2b']},progress:constraints.deliveryProgress}}];
    expect(readyGenerationItems(constraints,outputs).map(r=>r.id)).toEqual(['B2a','B2b']);
    expect(generationBatchRequired([request('B2a')],constraints,outputs).readyDeliverables.map(r=>r.id)).toEqual(['B2a','B2b']);
  });
  it('runs independent variants together and waits for them before a combined output', () => {
    const ids=['variant-a','variant-b','variant-c','variant-d'];
    const constraints=context([...ids.map(id=>item(id)),item('overview','image',ids)]);
    expect(readyGenerationItems(constraints).map(item=>item.id)).toEqual(ids);
    expect(generationBatchRequired([request(ids[0])],constraints).readyDeliverables.map(item=>item.id)).toEqual(ids);
    expect(readyGenerationItems(constraints,ids.slice(0,3).map(id=>output(id))).map(item=>item.id)).toEqual(['variant-d']);
    expect(readyGenerationItems(constraints,ids.map(id=>output(id))).map(item=>item.id)).toEqual(['overview']);
  });
  it('redirects one-at-a-time generation using the plan, regardless of subject or count', () => {
    for (const names of [['窄体客运','廊棚游览','市集货运','餐饮体验'], ['产品正面','包装外盒','活动主视觉','背景','配图','封面','海报']]) {
      const constraints = context(names.map(name=>item(name)));
      expect(generationBatchRequired([request(names[0])],constraints).readyDeliverables).toHaveLength(names.length);
      expect(generationBatchRequired(names.map(name=>request(name)),constraints)).toBeNull();
    }
  });
  it('groups mixed deliverables only after their real prerequisites are usable', () => {
    const constraints = context([item('copy','text'),item('visual'),item('web','html',['copy','visual']),item('voice','audio'),item('film','video')]);
    expect(readyGenerationItems(constraints).map(d=>d.id)).toEqual(['copy','visual','voice','film']);
    expect(readyGenerationItems(constraints,[output('copy','text'),output('visual')]).map(d=>d.id)).toEqual(['web','voice','film']);
    constraints.designPlan.deliverables[1].blockingFields=['style'];
    expect(readyGenerationItems(constraints).map(d=>d.id)).not.toContain('visual');
    expect(readyGenerationItems(constraints,[{name:'design_state',output:{state:{decisions:{style:{status:'confirmed'}}}}}]).map(d=>d.id)).toContain('visual');
  });
  it('allows a single dependent next step, explicit edits and completed-result reuse', () => {
    const constraints = context([item('base'),item('next','image',['base'])]);
    expect(generationBatchRequired([request('base')],constraints)).toBeNull();
    expect(generationBatchRequired([request('next')],constraints,[output('base')])).toBeNull();
    const independent=context([item('one'),item('two')]);
    expect(generationBatchRequired([{tool:'generate_image',arguments:{canvas_node_id:'existing'}}],independent)).toBeNull();
    expect(generationBatchRequired([request('one')],independent,[output('one')])).toBeNull();
  });
  it('preserves structured reference errors without losing other successful items', async () => {
    const errors=[{field:'reference_analysis',assetIds:['source'],message:'缺少参考分析'}];
    const result=await runGenerationBatch([request('one'),request('two')],async(_tool,args)=>
      args.prompt==='one' ? {status:'reference_analysis_required',instruction:'补充指定参考的分析',errors}
        : {status:'succeeded',assetId:'two',node:{id:'node-two'}});
    expect(result.results[0].errors).toEqual(errors);
    expect(result.results[0].instruction).toBe('补充指定参考的分析');
    expect(result.results[1].assetId).toBe('two');
  });
  it('starts every item and collects successes despite synchronous and async failures', async () => {
    const started=[]; let release;
    const allStarted=new Promise(resolve=>{release=resolve;});
    const operations=['a','b','c','d','e','f'].map(id=>request(id));
    const result=await runGenerationBatch(operations, (_tool,args)=>{
      started.push(args.prompt); if(started.length===operations.length)release();
      if(args.prompt==='b')throw new Error('invalid request');
      return allStarted.then(()=>{
        if(args.prompt==='d')throw new Error('response lost');
        return {status:'succeeded',assetId:args.prompt,node:{id:args.prompt}};
      });
    });
    expect(started).toHaveLength(6);
    expect(result.results.filter(item=>item.status==='succeeded').map(item=>item.assetId)).toEqual(['a','c','e','f']);
    expect(result.results.filter(item=>item.status==='failed')).toHaveLength(2);
  });
});


const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return{promise,resolve};};
const success=id=>({status:'succeeded',assetId:id,node:{id,data:{assetId:id}}});

it.each(['succeeded','generation_unconfirmed','cancelled'])('binds a prepared page only after original media is %s',async status=>{
  const calls=[],gate=deferred();
  const running=runGenerationBatch([request('hero'),{tool:'canvas_create_html',arguments:{deliverable_ids:['page'],html:'<img src="deliverable://hero">'}}],
    async(tool,args)=>{calls.push(tool);return tool==='canvas_create_html'?success('page'):{status:'processing',webMediaPending:true,operationId:'original'};},
    op=>op.tool==='canvas_create_html'?['hero']:[],async(_op,result)=>{expect(result.operationId).toBe('original');await gate.promise;return status==='succeeded'?success('hero'):{status,assetId:'stale'};});
  await new Promise(resolve=>setTimeout(resolve,0));
  expect(calls).toEqual(['generate_image']);
  gate.resolve();const result=await running;
  expect(calls.filter(t=>t==='generate_image')).toHaveLength(1);
  expect(result.results[1].status).toBe(status==='succeeded'?'succeeded':'dependency_required');
});

describe('execution follows actual input dependencies',()=>{
  it('starts a ready child before an unrelated slow branch finishes, regardless of array order',async()=>{
    const gates=Object.fromEntries(['a','b','c','join'].map(id=>[id,deferred()]));
    const started=Object.fromEntries(['a','b','c','join'].map(id=>[id,deferred()]));
    const events=[],dependencies={a:[],b:[],c:['a'],join:['b','c']};
    const running=runGenerationBatch(['join','c','b','a'].map(id=>request(id)),async(_tool,args)=>{
      const id=args.prompt;events.push(id);started[id].resolve();
      await gates[id].promise;return success(id);
    },op=>dependencies[op.arguments.prompt]);
    await Promise.all([started.a.promise,started.b.promise]);
    expect(events).toHaveLength(2);
    gates.a.resolve();await started.c.promise;
    expect(events).toEqual(['b','a','c']);
    gates.c.resolve();expect(events).not.toContain('join');
    gates.b.resolve();await started.join.promise;gates.join.resolve();
    expect((await running).results.map(r=>r.status)).toEqual(['succeeded','succeeded','succeeded','succeeded']);
  });
  it('waits through a full serial chain and passes each child only after its own parent',async()=>{
    const events=[],dependencies={a:[],b:['a'],c:['b'],d:['c']};
    const result=await runGenerationBatch(['d','c','b','a'].map(id=>request(id)),async(_tool,args)=>{
      events.push(args.prompt);return success(args.prompt);
    },op=>dependencies[op.arguments.prompt]);
    expect(events).toEqual(['a','b','c','d']);expect(result.results.every(r=>r.status==='succeeded')).toBe(true);
  });
  it.each(['failed','pending'])('blocks descendants of a %s input and preserves independent outputs',async state=>{
    const started=[],dependencies={a:[],b:[],c:['a'],d:['c'],e:['b']};
    const result=await runGenerationBatch(['d','c','e','a','b'].map(id=>request(id)),async(_tool,args)=>{
      const id=args.prompt;started.push(id);
      if(id==='a'){
        if(state==='failed')throw new Error('provider failed');
        return {status:'pending',job:{id:'job',status:'running'},node:{id:'a',data:{generating:true}}};
      }
      return success(id);
    },op=>dependencies[op.arguments.prompt]);
    expect(started.sort()).toEqual(['a','b','e']);
    expect(result.results.filter(r=>r.status==='dependency_required').map(r=>r.deliverable_ids[0]).sort()).toEqual(['c','d']);
    expect(result.results.filter(r=>r.status==='succeeded').map(r=>r.assetId).sort()).toEqual(['b','e']);
  });
  it('rejects cycles and duplicate producers before any dispatch',async()=>{
    let calls=0;const dispatch=()=>{calls++;return success('x');};
    await expect(runGenerationBatch([request('a'),request('b')],dispatch,op=>op.arguments.prompt==='a'?['b']:['a'])).rejects.toThrow('循环');
    await expect(runGenerationBatch([request('a'),request('a')],dispatch)).rejects.toThrow('重复');
    expect(calls).toBe(0);
  });
});
