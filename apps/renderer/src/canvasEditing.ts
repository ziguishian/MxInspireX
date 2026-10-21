export type Board = { nodes: any[]; edges: any[] };
export function cleanBoard(board: Board): Board {
  return JSON.parse(JSON.stringify({ nodes: board.nodes.map(({ id, position, data, meta }) => ({ id, type: 'creative', position: { x: position.x, y: position.y }, data: Object.fromEntries(Object.entries(data || {}).filter(([key]) => !['apiBaseUrl', 'projectId', 'modelOptions', 'videoModelOptions', 'textModelOptions', 'audioModelOptions', 'selected', 'deliveryReview'].includes(key))), ...(meta ? { meta } : {}) })), edges: board.edges.map(({ id, source, target, sourceHandle, targetHandle, label, type }) => ({ id, source, target, sourceHandle, targetHandle, label, type, animated: false })) }));
}
export function boardChanges(before: Board, after: Board) {
  const changed = (key: 'nodes' | 'edges') => after[key].flatMap(item => {
    const previous = before[key].find(old => old.id === item.id);
    if (!previous) return [item];
    const fields = Object.entries(item).filter(([field, value]) => JSON.stringify(previous[field]) !== JSON.stringify(value));
    return fields.length ? [{ id: item.id, ...Object.fromEntries(fields) }] : [];
  });
  const removed = (key: 'nodes' | 'edges') => before[key].filter(item => !after[key].some(next => next.id === item.id)).map(item => item.id);
  const expected = (key: 'nodes' | 'edges') => Object.fromEntries([
    ...changed(key).map(item => {
      const previous = before[key].find(old => old.id === item.id);
      return [item.id, previous ? Object.fromEntries(Object.keys(item).filter(field => field !== 'id').map(field => [field, previous[field] ?? null])) : null];
    }),
    ...removed(key).map(id => [id, { ...before[key].find(item => item.id === id) }]),
  ]);
  return { upsertNodes: changed('nodes'), upsertEdges: changed('edges'), removeNodeIds: removed('nodes'), removeEdgeIds: removed('edges'), expectedNodes: expected('nodes'), expectedEdges: expected('edges') };
}

/** Record the saved values of this edit, without capturing concurrent Agent output. */
export function savedBoardEdit(before: Board, requested: Board, saved: Board): Board {
  const result = cleanBoard(before), canonical = cleanBoard(saved);
  const changes = boardChanges(before, requested);
  for (const key of ['nodes', 'edges'] as const) {
    const removed = key === 'nodes' ? changes.removeNodeIds : changes.removeEdgeIds;
    const upserts = key === 'nodes' ? changes.upsertNodes : changes.upsertEdges;
    result[key] = result[key].filter(item => !removed.includes(item.id) || canonical[key].some(current => current.id === item.id));
    for (const patch of upserts) {
      const actual = canonical[key].find(item => item.id === patch.id);
      if (!actual) continue;
      const previous = result[key].find(item => item.id === patch.id);
      if (!previous) { result[key].push(actual); continue; }
      for (const field of Object.keys(patch).filter(field => field !== 'id')) {
        if (field in actual) previous[field] = actual[field];
        else delete previous[field];
      }
    }
  }
  return result;
}
