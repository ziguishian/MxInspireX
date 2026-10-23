import { describe, expect, it } from 'vitest';
import { canvasReferenceParams, connectedReferences, referenceImageIds, referenceProblem } from './canvasReferences';

const nodes: { id: string; data: Record<string, any> }[] = [
  { id: 'a', data: { kind: 'image', title: '主体', assetId: 'asset-a' } },
  { id: 'b', data: { kind: 'upload', title: '风格', asset: { id: 'asset-b', mime: 'image/png' } } },
  { id: 'c', data: { kind: 'text', title: '要求', text: '保持主体，使用蓝色' } },
  { id: 'target', data: { kind: 'image' } },
];
const edges = nodes.slice(0, 3).map(node => ({ id: `edge-${node.id}`, source: node.id, target: 'target' }));
const resolve = (links = edges, board = nodes) => connectedReferences('target', board, links, 'http://localhost:8765', 'project');

describe('canvas reference inputs', () => {
  it('resolves images and text in connection order, including embedded asset IDs', () => {
    const refs = resolve();
    expect(refs.map(ref => [ref.nodeId, ref.kind, ref.status])).toEqual([['a', 'image', 'ready'], ['b', 'image', 'ready'], ['c', 'text', 'ready']]);
    expect(refs[1].previewUrl).toContain('/assets/asset-b/content');
    expect(refs[2].text).toBe('保持主体，使用蓝色');
    expect(canvasReferenceParams(refs, { source_asset_id: 'manual' }, 'target', 'image')).toMatchObject({
      canvasNodeId: 'target', source_asset_ids: ['manual', 'asset-a', 'asset-b'], reference_node_ids: ['a', 'b', 'c'], reference_asset_ids: ['manual', 'asset-a', 'asset-b'],
    });
  });
  it('deduplicates repeated sources and image IDs without traversing ancestors or cycles', () => {
    const refs = resolve([...edges, { id: 'again', source: 'a', target: 'target' }, { id: 'cycle', source: 'target', target: 'a' }]);
    expect(refs).toHaveLength(3);
    expect(refs[0].edgeIds).toEqual(['edge-a', 'again']);
    expect(referenceImageIds(refs, 'asset-a')).toEqual(['asset-a', 'asset-b']);
  });
  it('removes disconnected inputs and re-resolves changed output IDs from a restored board', () => {
    const refs = resolve(edges.slice(1), nodes.map(node => node.id === 'b' ? { ...node, data: { kind: 'image', assetId: 'new-output' } } : node));
    expect(canvasReferenceParams(refs, {}, 'target', 'image').source_asset_ids).toEqual(['new-output']);
    expect(resolve([])).toEqual([]);
    expect(referenceImageIds([], undefined)).toEqual([]);
  });
  it('drops legacy manual modes so image purpose is detected automatically', () => {
    const result = canvasReferenceParams(resolve(), { referenceMode: 'edit', referenceModes: { 'asset-a': 'edit', 'asset-b': 'auto', stale: 'layout' } }, 'target', 'image');
    expect(result).not.toHaveProperty('referenceModes');
    expect(result).not.toHaveProperty('referenceMode');
  });
  it('blocks empty, missing and still-generating inputs instead of silently omitting them', () => {
    for (const data of [{ kind: 'image' }, { kind: 'image', assetId: 'old', generating: true }]) {
      const refs = connectedReferences('target', [{ id: 'a', data }], [edges[0]], '', 'project');
      expect(() => canvasReferenceParams(refs, {}, 'target', 'image')).toThrow();
    }
    expect(resolve(edges, nodes.filter(node => node.id !== 'b'))[1].status).toBe('missing');
  });
  it('maps two video inputs to ordered first and last frames, rejecting excess inputs', () => {
    expect(referenceProblem('video', resolve(), ['asset-a', 'asset-b'])).toBe('');
    expect(referenceProblem('video', resolve(), ['asset-a', 'asset-b', 'asset-c'])).toContain('最多支持两张');
    expect(referenceProblem('video', resolve(), ['asset-a'])).toBe('');
    expect(canvasReferenceParams(resolve(), {}, 'target', 'video')).toMatchObject({ source_asset_id: 'asset-a', last_frame_asset_id: 'asset-b', source_asset_ids: ['asset-a', 'asset-b'] });
    expect(canvasReferenceParams(resolve([...edges].reverse()), {}, 'target', 'video')).toMatchObject({ source_asset_id: 'asset-b', last_frame_asset_id: 'asset-a' });
    expect(canvasReferenceParams(resolve([edges[0]]), {last_frame_asset_id: 'stale'}, 'target', 'video').last_frame_asset_id).toBeUndefined();
  });
});
