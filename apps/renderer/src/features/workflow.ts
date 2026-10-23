export type WorkflowNode = { id: string; position: { x: number; y: number }; data: Record<string, any>; type?: string };
export type WorkflowEdge = { id: string; source: string; target: string; [key: string]: any };
export function workflowOrder(nodes: WorkflowNode[], edges: WorkflowEdge[]) {
  const ids = new Set(nodes.map(n => n.id));
  if (ids.size !== nodes.length) throw new Error('节点 ID 重复');
  if (edges.some(e => !ids.has(e.source) || !ids.has(e.target))) throw new Error('连线引用了不存在的节点');
  const remaining = new Set(ids), ordered: WorkflowNode[] = [];
  while (remaining.size) {
    const ready = nodes.filter(n => remaining.has(n.id) && !edges.some(e => e.target === n.id && remaining.has(e.source)));
    if (!ready.length) throw new Error('工作流存在循环连线，请断开循环后运行');
    ready.forEach(n => { remaining.delete(n.id); ordered.push(n); });
  }
  return ordered;
}
export function workflowOperations(nodes: WorkflowNode[], edges: WorkflowEdge[]) {
  const ordered = workflowOrder(nodes.filter(n => !n.data.workflowRunId), edges.filter(e => nodes.some(n => n.id === e.source && !n.data.workflowRunId) && nodes.some(n => n.id === e.target && !n.data.workflowRunId)));
  const operations = ordered.filter(n => n.data.prompt?.trim() || n.data.workflowOperation);
  if (!operations.length) throw new Error('请先给生成节点填写提示词，或指定节点操作');
  for (const node of operations) {
    if (!['image','video','audio','text','html','cad'].includes(node.data.kind)) throw new Error(`暂不支持运行「${node.data.title || node.id}」类型`);
  }
  return operations;
}
export function cloneWorkflowStep(node: WorkflowNode, runId: string, round: number, x: number): WorkflowNode {
  const data = JSON.parse(JSON.stringify(node.data));
  for (const key of ['asset','assetId','text','html','summary','localFile','taskId','error','status','delivery','deliveryFindings','previewValidation','generating','vectorSource','vectorSourceNode']) delete data[key];
  return { id: crypto.randomUUID(), type: 'creative', position: { x: node.position.x + x, y: node.position.y }, data: { ...data, draft: true, workflowRunId: runId, workflowSourceNode: node.id, workflowRound: round, title: `${node.data.title || '生成结果'} · 第 ${round} 次` } };
}
