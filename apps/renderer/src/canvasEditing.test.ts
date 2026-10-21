import { describe, expect, it } from 'vitest';
import { boardChanges, cleanBoard, savedBoardEdit } from './canvasEditing';

describe('canvas history changes', () => {
  const node = { id: 'a', position: { x: 0, y: 10 }, data: { text: 'initial', apiBaseUrl: 'local', selected: true } };
  it('sends position-only edits, so an Agent result arriving during a drag is preserved', () => {
    const before = cleanBoard({ nodes: [node], edges: [] });
    const after = cleanBoard(before); after.nodes[0].position.x = 60;
    expect(boardChanges(before, after).upsertNodes).toEqual([{ id: 'a', position: { x: 60, y: 10 } }]);
    expect(before.nodes[0].data).toEqual({ text: 'initial' });
  });
  it('keeps deletion and restoration as deltas, without including unrelated output', () => {
    const before = cleanBoard({ nodes: [node], edges: [{ id: 'edge', source: 'a', target: 'b' }] });
    const after = { nodes: [], edges: [] };
    expect(boardChanges(before, after)).toMatchObject({ removeNodeIds: ['a'], removeEdgeIds: ['edge'], upsertNodes: [] });
    expect(boardChanges(after, before).upsertNodes[0].id).toBe('a');
  });
  it('undoes the position actually saved after automatic layout, then redoes from the saved undo result', () => {
    const before = cleanBoard({ nodes: [node], edges: [] });
    const requested = cleanBoard(before); requested.nodes[0].position.x = 40;
    const saved = cleanBoard(requested); saved.nodes[0].position.x = 48;
    const after = savedBoardEdit(before, requested, saved);
    expect(boardChanges(after, before).expectedNodes.a).toEqual({ position: { x: 48, y: 10 } });

    const undoResult = cleanBoard(before); undoResult.nodes[0].position.x = 4;
    const restored = savedBoardEdit(after, before, undoResult);
    expect(boardChanges(restored, after)).toMatchObject({
      upsertNodes: [{ id: 'a', position: { x: 48, y: 10 } }],
      expectedNodes: { a: { position: { x: 4, y: 10 } } },
    });
    expect(before.nodes[0].position.x).toBe(0);
  });
  it('does not undo Agent output that arrives while a user edit is being saved', () => {
    const before = cleanBoard({ nodes: [node], edges: [] });
    const requested = cleanBoard(before); requested.nodes[0].position.x = 40;
    const saved = cleanBoard(requested);
    saved.nodes[0].data.text = 'new Agent output';
    saved.nodes.push({ ...node, id: 'agent-output' });
    const undo = boardChanges(savedBoardEdit(before, requested, saved), before);
    expect(undo.upsertNodes).toEqual([{ id: 'a', position: { x: 0, y: 10 } }]);
    expect(undo.removeNodeIds).toEqual([]);
    expect(undo.expectedNodes.a).toEqual({ position: { x: 40, y: 10 } });
  });
  it('records canonical additions and links so uploaded nodes can be removed and restored', () => {
    const empty = { nodes: [], edges: [] };
    const requested = cleanBoard({ nodes: [node, { ...node, id: 'b' }], edges: [{ id: 'e', source: 'a', target: 'b', label: 'link' }] });
    const saved = cleanBoard(requested);
    saved.nodes[0].data.assetId = 'uploaded-asset';
    saved.edges[0].label = 'saved link';
    const added = savedBoardEdit(empty, requested, saved);
    expect(boardChanges(added, empty)).toMatchObject({ removeNodeIds: ['a', 'b'], removeEdgeIds: ['e'] });
    const removed = savedBoardEdit(added, empty, empty);
    expect(boardChanges(removed, added)).toMatchObject({
      upsertNodes: [expect.objectContaining({ data: { text: 'initial', assetId: 'uploaded-asset' } }), expect.any(Object)],
      upsertEdges: [expect.objectContaining({ label: 'saved link' })],
    });
  });
});
