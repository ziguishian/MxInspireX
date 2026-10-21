import type { LibraryAsset } from './pageServices';

export function assetPreviewKind(asset: LibraryAsset): 'image' | 'video' | 'html' | '3d' | 'cad' | null {
  if (!asset.projectId) return null;
  if (asset.kind === 'cad' && asset.pathRelative.endsWith('.cad.json')) return 'cad';
  if (asset.kind === '3d' || /\.(glb|gltf|obj|fbx|stl)$/i.test(asset.pathRelative)) return '3d';
  if (asset.htmlNodeId || asset.kind === 'html' || /^(text\/html|application\/xhtml\+xml)(;|$)/i.test(asset.mime || '') || /\.html?$/i.test(asset.pathRelative)) return 'html';
  if (asset.kind === 'video' || asset.mime?.startsWith('video/') || /\.(mp4|webm|mov|m4v|ogv)$/i.test(asset.pathRelative)) return 'video';
  if (asset.kind === 'image' || asset.mime?.startsWith('image/') || /\.(png|jpe?g|webp|gif|avif|svg|bmp)$/i.test(asset.pathRelative)) return 'image';
  return null;
}
export const libraryAssetKey = (asset: LibraryAsset) => `${asset.projectId}/${asset.id}/${asset.revision || asset.updatedAt || ''}`;
export const libraryAssetUrl = (api: string, asset: LibraryAsset) => `${api}/api/projects/${encodeURIComponent(asset.projectId!)}/assets/${encodeURIComponent(asset.id)}/content`;
export async function loadAssetHtml(api: string, asset: LibraryAsset, signal: AbortSignal): Promise<string> {
  const url = asset.htmlNodeId
    ? `${api}/api/projects/${encodeURIComponent(asset.projectId!)}/canvas/html/${encodeURIComponent(asset.htmlNodeId)}`
    : libraryAssetUrl(api, asset);
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error('HTML 产物暂时无法读取');
  const html = asset.htmlNodeId ? (await response.json()).html : await response.text();
  if (typeof html !== 'string' || !html.trim()) throw new Error('HTML 产物内容为空');
  return html;
}
export function videoDuration(value: number) {
  return Number.isFinite(value) && value > 0 ? `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}` : '';
}
