import { describe, expect, it } from 'vitest';
import { alignBoardNodes, boardChanges, cleanBoard, savedBoardEdit } from './canvasEditing';

describe('manual alignment ownership', () => {
  const rects = [{id:'a',x:0,y:26,width:300,height:200}, {id:'b',x:450,y:146,width:200,height:300}, {id:'c',x:900,y:286,width:400,height:150}];
  const board = {nodes:rects.map(r=>({id:r.id,type:'creative',position:{x:r.x,y:r.y-26},data:{autoPositioned:true,assetId:r.id}})),edges:[]};
  it.each(['left','right','top','bottom','center-x','center-y','distribute-x','distribute-y'] as const)('persists %s as manual positions, including unchanged anchors', mode => {
    const before = cleanBoard(board);
    const after = alignBoardNodes(before,rects,mode);
    expect(after.nodes.every(n=>n.data.autoPositioned===false)).toBe(true);
    expect(before).toEqual(board);
    const rendered = after.nodes.map((n,i)=>({...rects[i],x:n.position.x,y:n.position.y+26}));
    const horizontal = ['left','right','center-x','distribute-x'].includes(mode);
    const start = horizontal ? 'x' : 'y', size = horizontal ? 'width' : 'height';
    if (mode.startsWith('distribute')) {
      expect(rendered[1][start]-rendered[0][start]-rendered[0][size]).toBeCloseTo(rendered[2][start]-rendered[1][start]-rendered[1][size]);
    } else {
      const edge = (r:typeof rects[number])=>r[start]+(mode.startsWith('center') ? r[size]/2 : ['right','bottom'].includes(mode) ? r[size] : 0);
      expect(edge(rendered[0])).toBeCloseTo(edge(rendered[1]));
      expect(edge(rendered[1])).toBeCloseTo(edge(rendered[2]));
    }
    expect(boardChanges(before,after).upsertNodes.every(n=>n.data.autoPositioned===false)).toBe(true);
    const saved = savedBoardEdit(before,after,after);
    expect(boardChanges(saved,before).upsertNodes.every(n=>n.data.autoPositioned===true)).toBe(true);
  });
  it('leaves unselected nodes eligible for automatic placement', () => {
    const result=alignBoardNodes(board,rects.slice(0,2),'top');
    expect(result.nodes[2]).toEqual(board.nodes[2]);
    expect(result.nodes[0].position).toEqual(board.nodes[0].position);
    expect(result.nodes[0].data.autoPositioned).toBe(false);
  });
});

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
