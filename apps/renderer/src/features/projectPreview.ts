import type { CanvasDocument, LibraryAsset } from './pageServices';
import { assetPreviewKind } from './assetPreview';

type CanvasNode = Record<string, any>;

function previewAsset(node: CanvasNode, projectId: string, revision?: string): LibraryAsset | null {
  const data = node.data || {};
  const asset = data.asset || {};
  const assetId = data.assetId || asset.id;
  const htmlNodeId = data.kind === 'html' && data.htmlNodeId ? data.htmlNodeId : undefined;
  if (!assetId && !htmlNodeId) return null;
  const candidate: LibraryAsset = {
    id: assetId || node.id,
    projectId: asset.projectId || projectId,
    kind: data.kind || asset.kind || 'image',
    pathRelative: asset.pathRelative || '',
    mime: asset.mime,
    byteSize: 0,
    htmlNodeId,
    createdAt: asset.createdAt,
    revision,
  };
  return assetPreviewKind(candidate) ? candidate : null;
}

function isCompletedGeneratedNode(node: CanvasNode): boolean {
  const data = node.data || {};
  const source = data.asset?.metadata?.source;
  if (data.kind === 'upload' || data.draft || data.generating || data.error) return false;
  if (source === 'user-upload' || source === 'system-easter-egg') return false;
  return true;
}

function generatedAt(node: CanvasNode): number | null {
  const data = node.data || {};
  const value = data.generatedAt || data.asset?.createdAt || node.meta?.createdAt;
  const timestamp = typeof value === 'string' ? Date.parse(value) : Number.NaN;
  return Number.isFinite(timestamp) ? timestamp : null;
}

/** Returns the first completed generated asset, never a user-uploaded reference. */
export function firstGeneratedProjectAsset(board: CanvasDocument | undefined, projectId: string): LibraryAsset | null {
  const candidates = (board?.nodes || [])
    .map((node, index) => ({ node, index, asset: previewAsset(node, projectId, board?.schemaVersion) }))
    .filter((item): item is { node: CanvasNode; index: number; asset: LibraryAsset } => Boolean(item.asset) && isCompletedGeneratedNode(item.node));
  if (!candidates.length) return null;

  const timestamps = candidates.map(item => generatedAt(item.node));
  if (timestamps.every((timestamp): timestamp is number => timestamp !== null)) {
    candidates.sort((left, right) => generatedAt(left.node)! - generatedAt(right.node)! || left.index - right.index);
  }
  return candidates[0].asset;
}
