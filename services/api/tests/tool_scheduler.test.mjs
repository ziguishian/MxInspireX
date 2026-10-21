import { describe, expect, it } from 'vitest';
import { createToolScheduler } from '../app/tool_scheduler.mjs';
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = () => new Promise(resolve => setImmediate(resolve));

describe('dependency-aware image scheduling', () => {
  it.each([1, 4, 7, 12])('starts all %i independent images without a configured cap', async count => {
    const scheduler = createToolScheduler(1), pending = Array.from({length:count}, deferred), started = [];
    const jobs = pending.map((wait, i) => scheduler.run('generate_image', { prompt: String(i) }, () => { started.push(i); return wait.promise; }));
    await flush(); expect(started).toEqual(pending.map((_,i)=>i));
    pending.forEach((wait,i)=>wait.resolve(i)); expect(await Promise.all(jobs)).toEqual(started);
  });
  it('preserves plan/write barriers and explicit upstream dependencies', async () => {
    const scheduler = createToolScheduler(3), plan = deferred(), base = deferred(), independent = deferred(), started = [];
    const jobs = [scheduler.run('design_plan', {}, () => { started.push('plan'); return plan.promise; }),
      scheduler.run('generate_image', { prompt: 'base', deliverable_ids: ['base'] }, () => { started.push('base'); return base.promise; }),
      scheduler.run('generate_image', { prompt: 'independent', deliverable_ids: ['other'] }, () => { started.push('other'); return independent.promise; }),
      scheduler.run('generate_image', { prompt: 'detail', deliverable_ids: ['detail'] }, () => { started.push('detail'); }, ['base']),
      scheduler.run('canvas_update_node', {}, () => { started.push('web'); })];
    await flush(); expect(started).toEqual(['plan']); plan.resolve(); await flush(); expect(started).toEqual(['plan', 'base', 'other']);
    base.resolve(); await flush(); expect(started).toEqual(['plan', 'base', 'other', 'detail']);
    independent.resolve(); await Promise.all(jobs); expect(started.at(-1)).toBe('web');
  });
  it('serializes edits to the same node and keeps independent successes after failure', async () => {
    const scheduler = createToolScheduler(2), wait = deferred(), other = deferred(), started = [];
    const first = scheduler.run('generate_image', { canvas_node_id: 'one', prompt: 'first' }, () => { started.push('first'); return wait.promise; });
    const second = scheduler.run('generate_image', { canvas_node_id: 'one', prompt: 'second' }, () => { started.push('second'); return 'changed'; });
    const third = scheduler.run('generate_image', { canvas_node_id: 'two' }, () => { started.push('other'); return other.promise; });
    const results = Promise.allSettled([first, second, third]); await flush(); expect(started).toEqual(['first', 'other']);
    wait.reject(new Error('upstream rejected')); other.resolve('saved');
    const completed = await results; expect(completed.map(r => r.status)).toEqual(['rejected', 'fulfilled', 'fulfilled']);
    expect(completed[2].value).toBe('saved'); expect(started.at(-1)).toBe('second');
  });
  it('uses the same rule for independent work of different kinds', async () => {
    const scheduler = createToolScheduler(1), wait = deferred(), started = [];
    const kinds = ['generate_image','generate_video','generate_audio','generate_3d','generate_text','canvas_create_html'];
    const jobs = kinds.map(name=>scheduler.run(name, {}, () => { started.push(name); return wait.promise; }));
    await flush(); expect(started).toEqual(kinds); wait.resolve(); await Promise.all(jobs);
  });
});
