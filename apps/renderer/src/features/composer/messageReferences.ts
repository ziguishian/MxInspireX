import { referenceSegments, type InlineReference } from './references';
import { skillReferences, type SkillMention } from './skillMentions';
import type { ImageReferenceMode } from '../imageReferenceModes';

export type MessageReference = InlineReference & { url?: string; attached?: boolean; nodeId?: string };
type Asset = { id: string; projectId?: string; pathRelative: string; kind: string; mime?: string };
type Document = { id: string; title: string; pathRelative: string };
type Node = { id?: string; data?: Record<string, any> };
export type TaskReferenceSnapshot = {
  referencedSkills?: SkillMention[];
  referencedAssets?: { id?: string; assetId?: string; projectId?: string; nodeId?: string; filename?: string; referenceMode?: ImageReferenceMode }[];
  referencedFiles?: { documentId?: string; filename?: string; mime?: string; scope?: string; projectId?: string; index?: number; referenceMode?: ImageReferenceMode }[];
  referencedNodes?: { id?: string; nodeId?: string; projectId?: string }[];
};
const basename = (path: string) => path.split(/[\\/]/).pop() || path;
function fileKind(name: string, mime = '', kind = '') {
  if (mime.startsWith('image/') || kind === 'image' || /\.(png|jpe?g|webp|gif|avif|svg)$/i.test(name)) return '图像';
  if (mime.startsWith('video/') || kind === 'video') return '视频';
  if (mime.startsWith('audio/') || kind === 'audio') return '音频';
  return name.match(/\.([a-z0-9]{1,8})$/i)?.[1].toUpperCase() || (kind === 'html' ? '网页' : '文件');
}

/** Reconstruct a message's own references, never the current composer's @1. */
export function messageReferences(input: { text: string; projectId: string; apiBaseUrl: string; snapshot?: TaskReferenceSnapshot; assets: Asset[]; documents: Document[]; nodes: Node[] }): MessageReference[] {
  const { snapshot = {}, projectId, apiBaseUrl: base, text } = input;
  const path = (value: string) => encodeURIComponent(value);
  const result: MessageReference[] = skillReferences(snapshot.referencedSkills || []);
  function assetReference(id: string, scope = projectId, filename?: string, nodeId?: string, referenceMode?: ImageReferenceMode) {
    const asset = input.assets.find(item => item.id === id && (!item.projectId || item.projectId === scope));
    const label = filename || (asset ? basename(asset.pathRelative) : '引用素材');
    const kind = fileKind(label, asset?.mime, asset?.kind);
    const url = `${base}/api/projects/${path(scope)}/assets/${path(id)}/content`;
    return { key: `asset:${id}`, token: `@asset:${id}`, aliases: [`@${label}`], label, kind, badge: '@', url, assetId: id, projectId: scope, nodeId, referenceMode, preview: kind === '图像' ? url : undefined };
  }
  for (const ref of snapshot.referencedAssets || []) {
    const id = ref.id || ref.assetId;
    if (id) result.push(assetReference(id, ref.projectId || projectId, ref.filename, ref.nodeId, ref.referenceMode));
  }
  for (const ref of snapshot.referencedFiles || []) {
    const global = ref.scope === 'global';
    const doc = global ? input.documents.find(item => item.id === ref.documentId) : undefined;
    const label = ref.filename || doc?.title || '引用文件', kind = fileKind(doc?.pathRelative || label, ref.mime);
    const url = ref.documentId ? `${base}/api/${global ? '' : `projects/${path(ref.projectId || projectId)}/`}knowledge/documents/${path(ref.documentId)}/content` : undefined;
    const token = global && ref.documentId ? `@knowledge:${ref.documentId}` : ref.index ? `@${ref.index}` : `@${label}`;
    result.push({ key: global ? `knowledge:${ref.documentId}` : `file:${ref.documentId || ref.index || label}`, token, aliases: [`@${label}`], label, kind, badge: ref.index ? `@${ref.index}` : '@', preview: kind === '图像' ? url : undefined, url, attached: !global, referenceMode: ref.referenceMode });
  }
  // Stable IDs and unique legacy filenames also work for older task records.
  for (const asset of input.assets.filter(item => item.projectId === projectId)) {
    if (!result.some(item => item.key === `asset:${asset.id}`)) result.push(assetReference(asset.id, projectId));
  }
  for (const match of text.matchAll(/@asset:([\w-]+)/g)) if (!result.some(item => item.key === `asset:${match[1]}`)) result.push(assetReference(match[1]));
  for (const doc of input.documents) if (!result.some(item => item.key === `knowledge:${doc.id}`)) {
    const kind = fileKind(doc.pathRelative);
    const url = `${base}/api/knowledge/documents/${path(doc.id)}/content`;
    result.push({ key: `knowledge:${doc.id}`, token: `@knowledge:${doc.id}`, aliases: [`@${doc.title}`], label: doc.title, kind, badge: '@', url, preview: kind === '图像' ? url : undefined });
  }
  const nodeIds = new Set([...(snapshot.referencedNodes || []).map(ref => ref.id || ref.nodeId), ...Array.from(text.matchAll(/@node:([\w-]+)/g), match => match[1])]);
  for (const id of nodeIds) if (id) {
    const node = input.nodes.find(item => item.id === id), data = node?.data || {};
    const assetId = data.assetId || data.asset?.id;
    const media = assetId ? assetReference(assetId) : undefined;
    const textContent = [data.text, data.summary].find(value => typeof value === 'string' && value.trim());
    result.push({ key: `node:${id}`, token: `@node:${id}`, label: data.title || '引用节点', kind: media?.kind || (data.kind === 'html' ? '网页' : '文本'), badge: '@', url: media?.url, preview: media?.preview, textContent, assetId, projectId, nodeId: id });
  }
  // Do not guess between different same-named files; stable IDs still match.
  const aliases = new Map<string, Set<string>>();
  for (const ref of result) for (const alias of ref.aliases || []) { if (!aliases.has(alias)) aliases.set(alias, new Set()); aliases.get(alias)!.add(ref.key); }
  for (const ref of result) ref.aliases = ref.aliases?.filter(alias => aliases.get(alias)?.size === 1);
  const used = new Set(referenceSegments(text, result).flatMap(segment => segment.reference ? [segment.reference.key] : []));
  return result.filter(ref => ref.attached || used.has(ref.key));
}
