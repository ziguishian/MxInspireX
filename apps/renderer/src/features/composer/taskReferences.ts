import { referencedKeys, type InlineReference } from './references';

type Asset = { id: string; projectId?: string; nodeId?: string };
type Document = { id: string; title: string; pathRelative: string };
type FileInput = { filename: string; mime: string; byteSize: number; result?: Record<string, unknown> };

/** Snapshot only the references still present when this message is submitted. */
export function taskReferences(input: { message: string; projectId: string; references: InlineReference[]; assets: Asset[]; documents: Document[]; files: FileInput[] }) {
  const { message, projectId } = input;
  const keys = referencedKeys(message, input.references);
  const tokens = (kind: string) => Array.from(message.matchAll(new RegExp(`@${kind}:([A-Za-z0-9_-]+)`, 'g')), match => match[1]);
  const selectedAssetReferences = input.references.filter(reference => keys.has(reference.key) && reference.assetId);
  const assetIds = new Set([...tokens('asset'), ...Array.from(keys).filter(key => key.startsWith('asset:')).map(key => key.slice(6)), ...selectedAssetReferences.map(reference => reference.assetId!)]);
  const assets = [...assetIds].map(id => {
    const asset = input.assets.find(asset => asset.id === id);
    const reference = input.references.find(reference => keys.has(reference.key) && reference.assetId === id)
      || input.references.find(reference => reference.key === `asset:${id}`);
    return { id, projectId: reference?.projectId || asset?.projectId || projectId, nodeId: reference?.nodeId || asset?.nodeId, mention: reference?.token || `@asset:${id}`, filename: reference?.label };
  });
  const nodes = new Set([...tokens('node'), ...assets.filter(asset => asset.projectId === projectId && asset.nodeId).map(asset => asset.nodeId!)]);
  const selectedFiles = new Set([...keys].filter(key => key.startsWith('file:')).map(key => Number(key.slice(5))));
  const files = input.files.flatMap((file, index) => selectedFiles.size && !selectedFiles.has(index) ? [] : [{
    ...file.result, filename: file.filename, mime: file.mime, byteSize: file.byteSize, projectId, index: index + 1,
  }]);
  const documentIds = new Set([...tokens('knowledge'), ...Array.from(keys).filter(key => key.startsWith('knowledge:')).map(key => key.slice(10))]);
  const documents = [...documentIds].map(id => {
    const document = input.documents.find(document => document.id === id);
    return { documentId: id, filename: document?.title, pathRelative: document?.pathRelative, scope: 'global' };
  });
  return { referencedAssets: assets, referencedNodes: [...nodes].map(id => ({id,projectId})), referencedFiles: [...files,...documents] };
}
