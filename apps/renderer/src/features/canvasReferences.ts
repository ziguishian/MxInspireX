import { canvasNodeKind } from '../nodeSizing';

type ReferenceNode = { id: string; data?: Record<string, any> };
type ReferenceEdge = { id: string; source: string; target: string };
export type CanvasReference = {
  nodeId: string; edgeIds: string[]; title: string; kind: string;
  assetId?: string; previewUrl?: string; text: string;
  status: 'ready' | 'empty' | 'generating' | 'missing';
};

// Only direct inputs: an upstream output already represents its own workflow.
// Derive from the live board so reconnect, undo and new outputs cannot leave stale references.
export function connectedReferences(nodeId: string, nodes: ReferenceNode[], edges: ReferenceEdge[], apiBaseUrl: string, projectId: string): CanvasReference[] {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const references = new Map<string, CanvasReference>();
  for (const edge of edges) {
    if (edge.target !== nodeId || edge.source === nodeId) continue;
    const previous = references.get(edge.source);
    if (previous) { previous.edgeIds.push(edge.id); continue; }
    const node = byId.get(edge.source), data = node?.data || {};
    const assetId = data.assetId || data.asset?.id;
    const kind = canvasNodeKind(data);
    const text = String(data.html || data.text || data.summary || '');
    references.set(edge.source, {
      nodeId: edge.source, edgeIds: [edge.id], title: data.title || '连接的节点', kind, assetId,
      previewUrl: assetId ? `${apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/content` : undefined,
      text, status: !node ? 'missing' : data.generating ? 'generating' : assetId || text.trim() ? 'ready' : 'empty',
    });
  }
  return [...references.values()];
}

export function referenceImageIds(references: CanvasReference[], manualAssetId?: string): string[] {
  const ids = [manualAssetId, ...references.filter(ref => ref.kind === 'image' || ref.kind === 'upload').map(ref => ref.assetId)].filter(Boolean) as string[];
  return [...new Set(ids)];
}

export function referenceProblem(kind: string, references: CanvasReference[], imageIds: string[]): string {
  const unready = references.find(ref => ref.status !== 'ready');
  if (unready) return `「${unready.title}」${unready.status === 'generating' ? '正在生成' : unready.status === 'missing' ? '已不存在' : '还没有内容'}，请等待素材就绪或断开连线。`;
  if (references.some(ref => ['video', 'audio'].includes(ref.kind))) return '音视频尚不能直接作为生成参考，请先转换为图像或文字节点再连接。';
  if (kind === 'video' && imageIds.length > 2) return '视频最多支持两张图像：第一张为首帧，第二张为尾帧，请断开多余的图像。';
  if (kind === 'audio' && imageIds.length) return '语音生成需要文字参考，请连接文字节点。';
  return '';
}

export function canvasReferenceParams(references: CanvasReference[], params: Record<string, any>, nodeId: string, kind: string) {
  const imageIds = referenceImageIds(references, params.source_asset_id);
  const problem = referenceProblem(kind, references, imageIds);
  if (problem) throw new Error(problem);
  const automaticParams = { ...params };
  delete automaticParams.referenceModes;
  delete automaticParams.referenceMode;
  return { ...automaticParams, canvasNodeId: nodeId, kind, source_asset_id: imageIds[0], source_asset_ids: imageIds,
    ...(kind === 'video' ? { last_frame_asset_id: imageIds[1] } : {}),
    reference_node_ids: references.map(ref => ref.nodeId),
    reference_asset_ids: [...new Set([...imageIds, ...references.map(ref => ref.assetId).filter(Boolean)])] as string[],
  };
}
