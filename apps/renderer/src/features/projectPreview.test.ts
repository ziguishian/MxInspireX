import { describe, expect, it } from 'vitest';
import { firstGeneratedProjectAsset } from './projectPreview';

const board = (nodes: Record<string, any>[]) => ({ schemaVersion: 'test', nodes, edges: [] });
const generated = (id: string, createdAt: string) => ({ id, data: { kind: 'image', assetId: id, asset: { id, kind: 'image', pathRelative: `${id}.png`, createdAt, metadata: { source: 'design-agent-tool' } } } });

describe('firstGeneratedProjectAsset', () => {
  it('skips user-uploaded references before the first generated asset', () => {
    const result = firstGeneratedProjectAsset(board([
      { id: 'reference', data: { kind: 'image', assetId: 'reference', asset: { id: 'reference', kind: 'image', pathRelative: 'reference.png', createdAt: '2026-10-12T08:00:00Z', metadata: { source: 'user-upload' } } } },
      generated('first-output', '2026-10-12T09:00:00Z'),
    ]), 'project');
    expect(result?.id).toBe('first-output');
  });

  it('uses generation time instead of an unstable saved-node order', () => {
    const result = firstGeneratedProjectAsset(board([
      generated('second-output', '2026-10-12T10:00:00Z'),
      generated('first-output', '2026-10-12T09:00:00Z'),
    ]), 'project');
    expect(result?.id).toBe('first-output');
  });

  it('keeps legacy boards in their original node order when timestamps are absent', () => {
    const result = firstGeneratedProjectAsset(board([
      { id: 'first-output', data: { kind: 'image', assetId: 'first-output', asset: { id: 'first-output', kind: 'image', pathRelative: 'first.png' } } },
      { id: 'second-output', data: { kind: 'image', assetId: 'second-output', asset: { id: 'second-output', kind: 'image', pathRelative: 'second.png' } } },
    ]), 'project');
    expect(result?.id).toBe('first-output');
  });
});
