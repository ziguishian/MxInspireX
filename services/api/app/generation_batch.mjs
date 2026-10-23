import { generationTools } from './tool_scheduler.mjs';
import { ToolInputNormalizationError } from './tool_input_validation.mjs';

const kindFor = name => name === 'canvas_create_svg' ? 'image' : name.replace(/^(generate_|canvas_create_)/, '');
const available = new Set(['ready', 'passed', 'needs_review']);

// A future identity source must be seen before the dependent prompt is written.
// Execute the ready subset now; keep deferred items for the next Agent turn.
export function partitionIdentityBatch(operations, plan) {
  const produced = new Set(operations.flatMap(op => op.arguments.deliverable_ids || []));
  const deferredIds = new Set((plan?.deliverables || []).filter(item =>
    item.inputs?.some(ref => ref.role === 'identity' && ref.source === 'deliverable' && produced.has(ref.id)))
    .map(item => item.id));
  let changed = true;
  while (changed) {
    changed = false;
    for (const item of plan?.deliverables || []) {
      if (!deferredIds.has(item.id) && item.dependsOn?.some(id => deferredIds.has(id))) {
        deferredIds.add(item.id); changed = true;
      }
    }
  }
  const deferred = [], ready = [];
  for (const op of operations) (op.arguments.deliverable_ids?.some(id => deferredIds.has(id)) ? deferred : ready).push(op);
  return {ready, deferred};
}

export function identityPreviewAssets(plan, name, result) {
  const parents = new Set((plan?.deliverables || []).flatMap(item => (item.inputs || [])
    .filter(ref => ref.role === 'identity' && ref.source === 'deliverable').map(ref => ref.id)));
  const rows = name === 'generate_batch' ? result?.results || []
    : [{...result, deliverable_ids:result?.node?.data?.deliveryBinding?.itemIds}];
  return [...new Set(rows.filter(row => row.status === 'succeeded' && row.assetId
    && row.deliverable_ids?.some(id => parents.has(id))).map(row => row.assetId))];
}

// All selected items must have an actual usable result or a non-retryable
// generation outcome. A plan, parameter error or progress sentence is no proof.
export function generationAttemptComplete(constraints = {}, outputs = []) {
  const plan = [...outputs].reverse().find(item=>item.name==='design_plan' && item.output?.plan)?.output.plan || constraints.designPlan;
  if (!plan?.ready || constraints.deliveryRepairOnly) return false;
  const {batch,progress} = currentBatchContext(constraints,outputs);
  if (batch?.status==='needs_plan') return false;
  const items = plan.deliverables.filter(item=>!batch || batch.itemIds.includes(item.id));
  const done = new Set(progress.filter(item=>available.has(item.status)).map(item=>item.id));
  for (const {name,args,output} of outputs) {
    if (!(generationTools.includes(name) || name === 'image_edit' && args?.operation === 'inpaint') || !output) continue;
    const usable = output.status==='succeeded' && !output.node?.data?.generating && !output.node?.data?.error
      && Boolean(output.assetId || output.node?.data?.text || output.node?.data?.html || output.node?.data?.cad);
    if (usable || output.status==='generation_unconfirmed' || output.status==='failed' && output.stopTool) {
      const binding = output.node?.data?.deliveryBinding;
      if (binding && binding.scopeId !== plan.scopeId) continue;
      for (const id of binding?.itemIds || args?.deliverable_ids || []) done.add(id);
    }
  }
  return items.length>0 && items.every(item=>done.has(item.id));
}

/** Accept the two shapes produced by supported model gateways.
 *
 * The canonical generator argument remains arguments.deliverable_ids. Some
 * models mirror the batch result envelope and put deliverable_ids beside
 * `tool` and `arguments`; normalize that harmless variation before any
 * delivery/reference validation so it cannot create a protocol loop.
 */
export function normalizeBatchItems(items = [], plan) {
  return items.map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)
      || !item.arguments || typeof item.arguments !== 'object' || Array.isArray(item.arguments)) return item;
    const argumentsValue = {...(item.arguments || {})};
    const outer = item.deliverable_ids;
    const inner = argumentsValue.deliverable_ids;
    if (outer?.length && inner?.length && JSON.stringify(outer) !== JSON.stringify(inner)) {
      throw new ToolInputNormalizationError(['items',index,'deliverable_ids'], '批次条目内外的 deliverable_ids 不一致');
    }
    if (outer?.length && !inner?.length) argumentsValue.deliverable_ids = outer;
    const ids = argumentsValue.deliverable_ids;
    // A missing name is deterministic only for explicit image bindings in a
    // saved ready plan. Never guess from a prompt, an unknown ID or mixed kinds.
    const imageBinding = plan?.ready && Array.isArray(ids) && ids.length > 0
      && ids.every(id => plan.deliverables?.some(d => d.id === id && d.kind === 'image' && d.representation !== 'vector'));
    return {tool:item.tool === undefined && imageBinding ? 'generate_image' : item.tool,arguments:argumentsValue};
  });
}

export function currentBatchContext(constraints = {}, outputs = []) {
  const latest = [...outputs].reverse().find(({output}) => output?.batchContext?.batch || output?.batch || output?.designBatch)?.output;
  return {batch:latest?.batchContext?.batch || latest?.batch || latest?.designBatch || constraints.designBatch,
    progress:latest?.batchContext?.progress || latest?.progress || latest?.deliverables || constraints.deliveryProgress || []};
}

// Use the current plan and real outputs, never task-specific words or counts.
export function readyGenerationItems(constraints = {}, outputs = []) {
  const plan = [...outputs].reverse().find(item => item.name === 'design_plan' && item.output?.plan)?.output.plan || constraints.designPlan;
  if (!plan?.ready) return [];
  const { batch, progress: batchProgress } = currentBatchContext(constraints, outputs);
  if (batch?.status === 'needs_plan') return [];
  const progress = batch ? batchProgress : [...outputs].reverse().find(item => item.name === 'delivery_verify')?.output?.deliverables || constraints.deliveryProgress || [];
  const ready = new Set(progress.filter(item => available.has(item.status)).map(item => item.id));
  const started = new Set(progress.filter(item => item.status === 'generating').map(item => item.id));
  for (const { args = {}, output = {} } of outputs) {
    if (output.status === 'generation_unconfirmed' || output.stopTool && output.retryable === false) {
      for (const id of args.deliverable_ids || []) started.add(id);
    }
    const binding = output.node?.data?.deliveryBinding;
    if (binding?.scopeId !== plan.scopeId) continue;
    const usable = !output.node?.data?.generating && !output.node?.data?.error && output.status === 'succeeded';
    const target = usable ? ready : started;
    if (usable || output.node?.data?.generating || output.job) for (const id of binding.itemIds || []) target.add(id);
  }
  const decisions = [...outputs].reverse().find(item => item.name === 'design_state')?.output?.state?.decisions || constraints.designState?.decisions || {};
  return plan.deliverables.filter(item => (!batch || batch.itemIds.includes(item.id)) && !ready.has(item.id) && !started.has(item.id)
    && !(item.dependsOn || []).some(id => !ready.has(id))
    && !(item.blockingFields || []).some(field => decisions[field]?.status !== 'confirmed'));
}

export function generationBatchRequired(operations, constraints = {}, outputs = []) {
  if (operations.length !== 1 || constraints.deliveryRepairOnly || constraints.canvasParams?.canvasNodeId) return null;
  const { tool, arguments: args } = operations[0];
  if (!generationTools.includes(tool) || args.canvas_node_id || args.output_mode === 'edit') return null;
  const pending = readyGenerationItems(constraints, outputs);
  if (pending.length < 2 || !pending.some(item => args.deliverable_ids?.length
    ? args.deliverable_ids.includes(item.id) : item.kind === kindFor(tool))) return null;
  return { status: 'batch_required', instruction: '当前计划有多项输入已就绪且互不依赖的产物。请为各项准备独立参数，一次调用 generate_batch 提交这些产物，不要先逐项等待。需要前置结果的项目留到下一组；不要重复提交已有产物。',
    readyDeliverables: pending.map(({ id, title, kind, acceptance, representation }) => ({ id, title, kind, acceptance, representation })) };
}

export async function runGenerationBatch(operations, dispatch, dependenciesFor = () => []) {
  const producers = new Map();
  operations.forEach((operation, index) => {
    for (const id of operation.arguments.deliverable_ids || []) {
      if (producers.has(id)) throw new Error('同一批次的交付项不能由多个操作重复生成：' + id);
      producers.set(id, index);
    }
  });
  const parents = operations.map(operation => [...new Set(dependenciesFor(operation).map(id => producers.get(id)).filter(index => index !== undefined))]);
  const visiting = new Set(), visited = new Set();
  const validate = index => {
    if (visiting.has(index)) throw new Error('生成批次存在循环依赖，请先修正计划');
    if (visited.has(index)) return;
    visiting.add(index); parents[index].forEach(validate); visiting.delete(index); visited.add(index);
  };
  operations.forEach((_, index) => validate(index));
  const usable = value => value && !['failed','dependency_required','reference_mismatch','planning_required'].includes(value.status)
    && !value.node?.data?.generating && !value.node?.data?.error
    && Boolean(value.assetId || value.node?.data?.text || value.node?.data?.html || value.node?.data?.assetId || value.node?.data?.cad);
  const jobs = new Map();
  const start = index => {
    if (jobs.has(index)) return jobs.get(index);
    const job = Promise.resolve().then(async () => {
      const completed = await Promise.allSettled(parents[index].map(start));
      const unavailable = parents[index].filter((_, i) => completed[i].status !== 'fulfilled' || !usable(completed[i].value));
      if (unavailable.length) return {status:'dependency_required',dependencies:unavailable.flatMap(i => operations[i].arguments.deliverable_ids || []),instruction:'前置产物未完成或未成功，已保留其他结果；等待可用输入，不重复生成整组。'};
      const {tool, arguments:args} = operations[index];
      return dispatch(tool, args);
    });
    jobs.set(index, job); return job;
  };
  // Each branch starts as soon as its own prerequisites finish, even while an
  // unrelated branch is still running. Array order never defines dependency.
  const results = await Promise.allSettled(operations.map((_, index) => start(index)));
  return { tool: 'generate_batch', results: results.map((result, index) => {
    const item = operations[index];
    if (result.status === 'rejected') return { tool: item.tool, deliverable_ids: item.arguments.deliverable_ids,
      status: 'failed', message: String(result.reason?.message || result.reason) };
    const { status, assetId, node, job, warnings, dependencies, instruction, reused, errors, errorCode, retryable, billingCertainty } = result.value;
    return { tool: item.tool, deliverable_ids: item.arguments.deliverable_ids, status, assetId, nodeId: node?.id,
      job: job ? { id: job.id, status: job.status } : undefined, warnings, dependencies, instruction, reused,
      errorCode, retryable, billingCertainty, ...(errors ? {errors} : {}) };
  }), instruction: '按每项真实状态报告结果。保留成功项；异步任务等待完成，有依赖的后续项读取真实资产后再提交。不得因一项失败重新生成整组。' };
}
