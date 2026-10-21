import {it,expect} from 'vitest';
import {executionFrame} from '../app/execution_frame.mjs';
import {prepareModelInput} from '../app/sdk_context.mjs';

it('retains six real assets and one unknown operation through aggressive context trimming',()=>{
  const ids=['box','display','notebook','pillow','tea','cup','silk'];
  const constraints={designPlan:{ready:true,scopeId:'gift',revision:3,deliverables:ids.map(id=>({id,kind:'image',dependsOn:[]}))}};
  const outputs=ids.map((id,i)=>({name:'generate_image',args:{deliverable_ids:[id]},output:i===4
    ? {status:'generation_unconfirmed',retryable:false}
    : {status:'succeeded',assetId:'asset-'+id,node:{id:'node-'+id,data:{deliveryBinding:{scopeId:'gift',itemIds:[id]}}}}}));
  const execution=executionFrame(constraints,outputs);
  expect(execution.items.filter(i=>i.action==='reuse')).toHaveLength(6);
  expect(execution.items.find(i=>i.id==='tea')).toMatchObject({status:'unconfirmed',action:'reconcile_only'});
  expect(execution.next).toBe('deliver');
  const prepared=prepareModelInput({instructions:'设计',input:[{role:'user',content:'继续'}]},
    {frame:{execution,designPlan:constraints.designPlan,requirements:{earlierUserExcerpts:[{user:'历史'.repeat(10000)}]}},contextLength:32000,toolSchemaChars:20000});
  const text=JSON.stringify(prepared.modelData);
  for(const id of ids.filter(id=>id!=='tea'))expect(text).toContain('asset-'+id);
  expect(text).toContain('reconcile_only');expect(text).toContain('planRevision');
});

it('keeps dependency-blocked items out of the generation action',()=>{
  const constraints={designPlan:{ready:true,scopeId:'scope',revision:1,deliverables:[{id:'master',kind:'image'},{id:'child',kind:'image',dependsOn:['master']}]}};
  const frame=executionFrame(constraints,[]);
  expect(frame.items.map(i=>i.action)).toEqual(['generate','wait']);
  expect(frame.next).toBe('execute_pending');
});
