import { describe, expect, it } from 'vitest';
import { canvasEditHistory } from './canvasHistory';

describe('project canvas history', () => {
  it('retains create/undo/redo history when a project page is reopened', () => {
    const history = canvasEditHistory('local-api', 'reopened-project');
    const edit = { before: { nodes: [], edges: [] }, after: { nodes: [{ id: 'created' }], edges: [] } };
    history.undo.value.push(edit);
    const reopened = canvasEditHistory('local-api', 'reopened-project');
    expect(reopened.undo.value).toEqual([edit]);
    reopened.redo.value.push(reopened.undo.value.pop()!);
    expect(canvasEditHistory('local-api', 'reopened-project').redo.value).toEqual([edit]);
  });
  it('isolates different projects and API workspaces', () => {
    expect(canvasEditHistory('local-api', 'another-project').undo.value).toEqual([]);
    expect(canvasEditHistory('other-api', 'reopened-project').redo.value).toEqual([]);
  });
});
