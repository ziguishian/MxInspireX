import { expect, it } from 'vitest';
import { canvasTaskTerminalPatch, canvasTextModel, createCanvasSubmissionGate } from './canvasGeneration';

it.each(['text', 'html', 'cad'])('routes the chosen %s text model', kind => {
  expect(canvasTextModel(kind, 'chosen', 'default')).toBe('chosen');
  expect(canvasTextModel(kind, '', 'default')).toBe('default');
});
it.each(['image', 'video', 'audio'])('keeps %s media model out of text routing', kind => {
  expect(canvasTextModel(kind, 'media', 'text')).toBe('text');
});
it.each(['queued', 'running'])('does not terminate a %s task', status => {
  expect(canvasTaskTerminalPatch({ id: 't', status }, { generating: true })).toBeNull();
});
it.each(['assetId', 'localFile', 'html', 'text', 'cad', 'job'])('preserves saved or asynchronous %s results', field => {
  expect(canvasTaskTerminalPatch({ id: 't', status: 'failed' }, { generating: true, [field]: 'saved' })).toBeNull();
});
it('preserves a newer run and a settled node', () => {
  expect(canvasTaskTerminalPatch({ id: 'old', status: 'failed' }, { generating: true, taskId: 'new' })).toBeNull();
  expect(canvasTaskTerminalPatch({ id: 't', status: 'failed' }, { generating: false })).toBeNull();
});
it.each(['failed', 'succeeded', 'cancelled'])('clears unfinished placeholders after %s without claiming success', status => {
  const patch = canvasTaskTerminalPatch({ id: 't', status }, { generating: true, taskId: 't' });
  expect(patch?.generating).toBe(false);
  expect(patch?.error).toBeTruthy();
});
it('blocks duplicates but allows independent nodes, and releases after failure', async () => {
  const gate = createCanvasSubmissionGate();
  let finish!: () => void;
  const first = gate('p', 'n', () => new Promise<void>(resolve => { finish = resolve; }));
  expect(await gate('p', 'n', async () => true)).toBe(false);
  expect(await gate('q', 'n', async () => true)).toBe(true);
  expect(await gate('p', 'm', async () => true)).toBe(true);
  finish(); await first;
  await expect(gate('p', 'n', async () => { throw new Error('failure'); })).rejects.toThrow('failure');
  expect(await gate('p', 'n', async () => true)).toBe(true);
});
