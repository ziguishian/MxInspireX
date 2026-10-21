// Deterministic execution decisions based on saved artifacts, not prose grades.
import { generationTools } from './tool_scheduler.mjs';
import { generationAttemptComplete, readyGenerationItems } from './generation_batch.mjs';
import { singleDeliveryComplete } from './execution_efficiency.mjs';
import { currentDesignPlan } from './tool_input_validation.mjs';

const artifactTools = new Set([...generationTools, 'canvas_create_media', 'canvas_create_node', 'canvas_create_svg', 'canvas_update_node', 'image_edit', 'media_edit', 'export_deliverable']);

export function artifactToolOutputs(toolOutputs) {
  return toolOutputs.filter(item => artifactTools.has(item.name) && item.output?.status !== 'failed');
}

/** Inspecting a reference never makes it a deliverable, including after resume. */
export function collectArtifactRefs(toolOutputs) {
  return [...new Map(artifactToolOutputs(toolOutputs).flatMap(item => {
    const output = item.output || {}, refs = [];
    if (output.assetId) refs.push({entity_type:'asset',entity_id:output.assetId});
    if (output.node?.id) refs.push({entity_type:'canvas_node',entity_id:output.node.id,label:output.node.data?.title});
    return refs;
  }).map(ref => [`${ref.entity_type}:${ref.entity_id}`, ref])).values()];
}

export function hasPendingDelivery(delivery) {
  return Boolean(delivery?.pendingMedia?.length || delivery?.pendingPreview?.length);
}

export function missingDeliverables(delivery) {
  return (delivery?.deliverables || []).filter(item => item.status === 'pending');
}

// Shared by tool completion and final inspection; unknown paid results are
// never an invitation to generate again.
export function completionDecision(constraints, outputs, {delivery, awaitingInput = false, updatePending = false} = {}) {
  if (awaitingInput || latestClarification(outputs)) return {finish:false,missing:[],reason:'user_input'};
  if (updatePending) return {finish:false,missing:[],reason:'user_update'};
  // Accepted asynchronous video jobs are polled by Python. Do not ask the
  // model to generate again while the original paid operation is pending.
  const contract = constraints?.deliveryContract || [];
  const canvas = constraints?.canvasParams || {};
  const videoOnly = canvas.kind === 'video' && canvas.canvasNodeId
    || contract.length === 1 && contract[0].kind === 'video' && (contract[0].count ?? 1) === 1;
  const jobs = outputs.filter(item => item.name === 'generate_video' && item.output?.job?.id);
  if (videoOnly && !currentDesignPlan(constraints,outputs) && jobs.length === 1
    && !outputs.some(item => item.name === 'request_reference_selection')
    && (!canvas.canvasNodeId || jobs[0].output.job.metadata?.canvasNodeId === canvas.canvasNodeId)) {
    return {finish:true,missing:[],reason:'video_submitted'};
  }
  const settled = generationAttemptComplete(constraints,outputs) || singleDeliveryComplete(constraints,outputs);
  if (settled) return {finish:true,missing:[],reason:'attempt_complete'};
  if (hasPendingDelivery(delivery)) return {finish:false,missing:[],reason:'pending_result'};
  if (delivery?.passed) return {finish:true,missing:[],reason:'delivered'};
  if (outputs.some(({output={}})=>output.status==='generation_unconfirmed' || output.stopTool
    || output.node?.data?.generating || output.job && output.status !== 'succeeded')) {
    return {finish:false,missing:[],reason:'reconcile_only'};
  }
  const ready = new Set(readyGenerationItems(constraints,outputs).map(item=>item.id));
  const plan = currentDesignPlan(constraints,outputs);
  return {finish:false,reason:'incomplete',missing:missingDeliverables(delivery).filter(item=>!plan || ready.has(item.id))};
}

export function latestClarification(toolOutputs) {
  const output = [...toolOutputs].reverse().find(item => item.name === 'request_clarification')?.output;
  if (output?.awaitingUser && output.questions?.length) return output;
  // A saved plan with unresolved questions is already a durable request for
  // user input. Treat it like an explicit clarification tool result so the
  // runner stops after the first plan instead of rewriting it until maxTurns.
  const plan = [...toolOutputs].reverse().find(item => item.name === 'design_plan'
    && item.output?.status === 'needs_clarification' && item.output?.plan?.openQuestions?.length)?.output;
  if (!plan) return null;
  return {
    intro: '继续当前设计前，请补充以下关键信息。',
    questions: plan.plan.openQuestions.map((question, index) => ({id:`design-plan-${index + 1}`,question,options:[],multi:false})),
    awaitingUser: true,
    source: 'design_plan',
  };
}

