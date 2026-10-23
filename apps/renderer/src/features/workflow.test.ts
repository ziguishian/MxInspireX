import { describe,it,expect } from 'vitest';
import { workflowOrder, workflowOperations, cloneWorkflowStep } from './workflow';
import { cutoutModel } from './designNodes';
const nodes=[{id:'input',position:{x:0,y:0},data:{kind:'image',assetId:'original'}},{id:'result',position:{x:500,y:0},data:{kind:'image',prompt:'edit',assetId:'old',taskId:'old-task',params:{model:'test'}}}];
const edges=[{id:'e',source:'input',target:'result'}];
describe('workflow planning',()=>{
  it('orders dependencies and does not run plain references',()=>{expect(workflowOrder([...nodes].reverse(),edges).map(n=>n.id)).toEqual(['input','result']);expect(workflowOperations(nodes,edges).map(n=>n.id)).toEqual(['result']);});
  it('rejects cycles and dangling edges',()=>{expect(()=>workflowOrder(nodes,[...edges,{id:'back',source:'result',target:'input'}])).toThrow('循环');expect(()=>workflowOrder(nodes,[{id:'bad',source:'missing',target:'result'}])).toThrow('不存在');});
  it('clones outputs without changing source data or reusing old receipts',()=>{const copy=cloneWorkflowStep(nodes[1],'run',2,1000);expect(copy.id).not.toBe('result');expect(copy.data.assetId).toBeUndefined();expect(copy.data.taskId).toBeUndefined();expect(copy.data.params.model).toBe('test');expect(nodes[1].data.assetId).toBe('old');expect(copy.position.x).toBe(1500);});
  it('does not recursively execute prior workflow results',()=>{expect(workflowOperations([...nodes,{...nodes[1],id:'past',data:{...nodes[1].data,workflowRunId:'past'}}],edges)).toHaveLength(1);});
  it('prefers flare even when sunburst is listed first',()=>{expect(cutoutModel(['gpt-image-2.5-sunburst','gpt-image-2.5-flare'])).toBe('gpt-image-2.5-flare');});
});
