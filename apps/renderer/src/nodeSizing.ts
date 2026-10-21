import { htmlPreviewSize } from './htmlPreview';

export type NodePreviewSize = { width: number; height: number };

export function requestedMediaRatio(params: Record<string, any> = {}): number | null {
  const ratio = (width: unknown, height: unknown) => {
    const w = Number(width), h = Number(height);
    return w > 0 && h > 0 && Number.isFinite(w / h) ? w / h : null;
  };
  // Use the normalized provider size before an inherited composer ratio.
  const size = /^\s*(\d+)\s*[x×]\s*(\d+)\s*$/i.exec(String(params.size || ''));
  if (size) { const value = ratio(size[1], size[2]); if (value) return value; }
  if (typeof params.width === 'number' && typeof params.height === 'number') {
    const value = ratio(params.width, params.height); if (value) return value;
  }
  for (const hint of [params.aspectRatio, params.aspect_ratio, params.aspect]) {
    const parts = /^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$/.exec(String(hint || ''));
    if (parts) { const value = ratio(parts[1], parts[2]); if (value) return value; }
  }
  return null;
}

export function canvasNodeKind(data: Record<string, any> = {}): string {
  if (data.kind === 'cad') return 'cad';
  const mime = String(data.asset?.mime || '');
  for (const kind of ['image', 'video', 'audio']) if (mime.startsWith(`${kind}/`)) return kind;
  const extension = String(data.asset?.pathRelative || '').split('.').pop()?.toLowerCase();
  if (extension && ['glb', 'gltf', 'obj', 'fbx', 'stl'].includes(extension)) return '3d';
  return data.kind || 'text';
}

// Store a preview width, not source media dimensions or canvas zoom. Image and
// video frames always derive their height from the real content ratio so an old
// manually sized frame can never add letterboxing around a replacement asset.
// Legacy HTML sizes remain readable because an HTML document is its own artboard.
export function nodePreviewSize(data: Record<string, any> = {}, naturalRatio?: number | null): NodePreviewSize {
  const kind = canvasNodeKind(data);
  const saved = data.previewSize || (kind === 'html' ? data.htmlPreviewSize : undefined);
  if (kind === 'html') return htmlPreviewSize(saved);
  // New nodes opt into larger frames. Unversioned saved boards retain their
  // original footprint, so opening a project never overlaps its old layout.
  const largeMedia = data.previewSizingVersion === 2 && ['image', 'video', 'upload'].includes(kind);
  let defaultWidth = largeMedia ? 720 : kind === 'text' ? 360 : kind === 'audio' ? 220 : 300;
  const requestedRatio = requestedMediaRatio(data.params || data.asset?.metadata?.params || {});
  const imageOutput = data.asset?.metadata?.imageOutput;
  const sourceWidth = imageOutput?.width ?? data.asset?.metadata?.width;
  const sourceHeight = imageOutput?.height ?? data.asset?.metadata?.height;
  const sourceRatio = ['image', 'video'].includes(kind) && Number.isFinite(sourceWidth) && Number.isFinite(sourceHeight) && sourceWidth > 0 && sourceHeight > 0 ? sourceWidth / sourceHeight : null;
  const ratio = data.generating && requestedRatio ? requestedRatio
    : naturalRatio && Number.isFinite(naturalRatio) && naturalRatio > 0 ? naturalRatio
    : sourceRatio && Number.isFinite(sourceRatio) ? sourceRatio
    : requestedRatio || (kind === 'text' ? 6 / 5 : kind === 'audio' ? 8 / 5 : kind === '3d' ? 1 : 16 / 9);
  // Fit tall media within the height limit by scaling both axes together.
  if (largeMedia) defaultWidth = Math.min(defaultWidth, 1080 * ratio);
  const [minWidth, minHeight] = kind === 'audio' ? [220, 90] : kind === '3d' ? [180, 150]
    : kind === 'text' ? [180, 120] : ['image', 'video', 'upload'].includes(kind) ? [160, 90] : [180, 120];
  const clamp = (value: unknown, fallback: number, min: number, max: number) =>
    Math.round(Math.min(max, Math.max(min, typeof value === 'number' && Number.isFinite(value) ? value : fallback)));
  const isAspectLockedMedia = ['image', 'video'].includes(kind);
  if (isAspectLockedMedia) {
    // Fit both axes together. For unusually wide/tall assets, respecting the
    // real aspect ratio is more important than forcing the generic minimum.
    const hasSavedWidth = typeof saved?.width === 'number' && Number.isFinite(saved.width);
    const maxHeight = largeMedia && !hasSavedWidth ? 1080 : 1440;
    const maxWidth = Math.min(1920, maxHeight * ratio);
    const minWidthForRatio = Math.max(minWidth, minHeight * ratio);
    let width = maxWidth < minWidthForRatio
      ? Math.round(maxWidth)
      : clamp(saved?.width, defaultWidth, minWidthForRatio, maxWidth);
    let height = Math.round(width / ratio);
    if (height > maxHeight) { height = maxHeight; width = Math.round(height * ratio); }
    return { width, height };
  }
  return {
    width: clamp(saved?.width, defaultWidth, minWidth, 1920),
    height: clamp(saved?.height, Math.min(largeMedia ? 1080 : 440, Math.max(120, defaultWidth / ratio)), minHeight, 1440),
  };
}
