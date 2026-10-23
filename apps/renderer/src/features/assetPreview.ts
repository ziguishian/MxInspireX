import type { LibraryAsset } from './pageServices';

export function assetModelFormat(asset: LibraryAsset): string {
  const extension = asset.pathRelative.split('.').pop()?.toLowerCase() || '';
  if (['glb', 'gltf', 'obj', 'fbx', 'stl'].includes(extension)) return extension;
  return ({ 'model/gltf-binary': 'glb', 'model/gltf+json': 'gltf', 'model/obj': 'obj', 'model/stl': 'stl', 'application/sla': 'stl' } as Record<string, string>)[(asset.mime || '').split(';')[0]] || 'glb';
}
export function assetPreviewKind(asset: LibraryAsset): 'image' | 'video' | 'audio' | 'html' | '3d' | 'cad' | null {
  if (!asset.projectId) return null;
  if (asset.kind === 'cad' && asset.pathRelative.endsWith('.cad.json')) return 'cad';
  if (asset.kind === '3d' || /^model\//i.test(asset.mime || '') || /\.(glb|gltf|obj|fbx|stl)$/i.test(asset.pathRelative)) return '3d';
  if (asset.kind === 'audio' || asset.mime?.startsWith('audio/') || /\.(mp3|wav|m4a|aac|ogg|flac|opus)$/i.test(asset.pathRelative)) return 'audio';
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
