import { currentDesignPlan } from './tool_input_validation.mjs';
import { currentBatchContext, generationAttemptComplete, readyGenerationItems } from './generation_batch.mjs';

// A deterministic projection of persisted plans/receipts, never an LLM summary.
export function executionFrame(constraints = {}, outputs = []) {
  const plan = currentDesignPlan(constraints,outputs);
  if (!plan) return undefined;
  const {batch,progress} = currentBatchContext(constraints,outputs);
  const selected = plan.deliverables.filter(d=>!batch || batch.itemIds.includes(d.id));
  const ready = new Set(readyGenerationItems(constraints,outputs).map(d=>d.id));
  const items = selected.map(item=>{
    const saved = progress.find(p=>p.id===item.id);
    const receipt = [...outputs].reverse().find(r=>r.args?.deliverable_ids?.includes(item.id)
      && (!r.output?.node?.data?.deliveryBinding?.scopeId || r.output.node.data.deliveryBinding.scopeId===plan.scopeId)
      && ['succeeded','generation_unconfirmed'].includes(r.output?.status));
    const output = receipt?.output;
    const status = output?.status==='generation_unconfirmed' ? 'unconfirmed'
      : output?.status==='succeeded' && (output.assetId || output.node?.data?.assetId) ? 'saved' : saved?.status || 'pending';
    return {id:item.id,status,dependsOn:item.dependsOn || [],
      ...(output?.assetId ? {assetId:output.assetId} : {}),
      ...(output?.node?.id ? {nodeIds:[output.node.id]} : saved?.nodeIds ? {nodeIds:saved.nodeIds} : {}),
      action:status==='unconfirmed' ? 'reconcile_only' : ['saved','ready','passed','needs_review'].includes(status) ? 'reuse'
        : ready.has(item.id) ? 'generate' : 'wait',
    };
  });
  return {version:1,scopeId:plan.scopeId,planRevision:plan.revision,batchId:batch?.id,
    ready:plan.ready,items,next:generationAttemptComplete(constraints,outputs) ? 'deliver' : plan.ready ? 'execute_pending' : 'clarify',
    instruction:'以真实回执决定进度；reuse 不重新生成，reconcile_only 只核对原请求，保留全部资产。设计与验收要求仍按有效计划执行。'};
}
