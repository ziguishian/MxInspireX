import { describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import { createTaskQueue, type QueueTask } from './taskQueue';

const task = (id: string, projectId: string, status = 'running'): QueueTask => ({ id, projectId, status, agentKey: 'design', userMessage: `需求 ${id}` });
describe('task queue destinations', () => {
  it('notifies once for new terminal transitions, not historical results or cancellations', () => {
    const notify = vi.fn();
    const queue = createTaskQueue(ref([{ id: 'a', name: 'A' }]), vi.fn(), undefined, notify);
    queue.replace('a', [task('old', 'a', 'succeeded')]);
    expect(notify).not.toHaveBeenCalled();
    queue.update('a', task('new', 'a'));
    queue.update('a', task('new', 'a', 'succeeded'));
    queue.update('a', task('new', 'a', 'succeeded'));
    expect(notify).toHaveBeenCalledTimes(1);
    queue.update('a', task('failed', 'a'));
    queue.update('a', task('failed', 'a', 'failed'));
    expect(notify).toHaveBeenCalledTimes(2);
    queue.update('a', task('cancel', 'a'));
    queue.update('a', task('cancel', 'a', 'cancelled'));
    expect(notify).toHaveBeenCalledTimes(2);
  });
  it('discovers canvas work and attention states in unopened projects', async () => {
    const queue = createTaskQueue(ref([{ id: 'a', name: '项目 A' }, { id: 'b', name: '项目 B' }]), vi.fn(), async () => [
      { ...task('node', 'a'), taskSurface: 'canvas_node', canvasNodeId: 'node-1' },
      { ...task('unverified', 'b', 'succeeded'), output: { structured_data: { deliveryStatus: 'needs_review', review: { status: 'timed_out' } } } },
    ]);
    await queue.refresh();
    expect(queue.activeTasks.value[0].canvasNodeId).toBe('node-1');
    expect(queue.attentionTasks.value[0].reason).toContain('待处理');
  });
  it('finds running tasks before a project is opened and retains each destination', async () => {
    const projects = ref([{ id: 'a', name: '项目 A', latestTaskId: 'one', latestTaskStatus: 'running' }, { id: 'b', name: '项目 B', latestTaskId: 'two', latestTaskStatus: 'queued' }]);
    const fetchTasks = vi.fn(async (id: string) => id === 'a' ? [task('one', 'a')] : [task('two', 'b', 'queued')]);
    const queue = createTaskQueue(projects, fetchTasks);
    expect(queue.activeTasks.value.map(task => [task.id, task.projectId])).toEqual([['one', 'a'], ['two', 'b']]);
    await queue.refresh();
    expect(queue.activeTasks.value.map(task => task.userMessage)).toEqual(['需求 one', '需求 two']);
    queue.update('a', task('one', 'a', 'succeeded'));
    expect(queue.activeTasks.value.map(task => task.id)).toEqual(['two']);
  });
  it('does not resurrect a task when a stale snapshot arrives after completion', async () => {
    let resolve!: (tasks: QueueTask[]) => void;
    const queue = createTaskQueue(ref([{ id: 'a', name: '项目 A' }]), () => new Promise(done => { resolve = done; }));
    queue.update('a', task('one', 'a'));
    const refresh = queue.refresh();
    queue.update('a', task('one', 'a', 'succeeded'));
    resolve([task('one', 'a')]);
    await refresh;
    expect(queue.activeTasks.value).toEqual([]);
  });
  it('retains known tasks during disconnection and stops polling after completion', async () => {
    const fetchTasks = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([task('one', 'a', 'succeeded')]);
    const queue = createTaskQueue(ref([{ id: 'a', name: '项目 A' }]), fetchTasks);
    queue.update('a', task('one', 'a'));
    await queue.refresh();
    expect(queue.activeTasks.value).toHaveLength(1);
    await queue.refresh();
    await queue.refresh();
    expect(queue.activeTasks.value).toEqual([]);
    expect(fetchTasks).toHaveBeenCalledTimes(2);
  });
  it('removes deleted projects and lists multiple tasks within one project', () => {
    const projects = ref([{ id: 'a', name: '项目 A' }, { id: 'b', name: '项目 B' }]);
    const queue = createTaskQueue(projects, vi.fn());
    queue.replace('a', [task('one', 'a'), task('two', 'a', 'queued'), task('done', 'a', 'succeeded')]);
    queue.update('b', task('three', 'b'));
    projects.value = projects.value.filter(project => project.id === 'a');
    expect(queue.activeTasks.value.map(task => [task.id, task.projectId])).toEqual([['one', 'a'], ['two', 'a']]);
  });
  it('includes independent canvas tasks in the global work list', () => {
    const queue = createTaskQueue(ref([{ id: 'a', name: '项目 A' }]), vi.fn());
    queue.replace('a', [task('chat', 'a'), { ...task('node', 'a'), taskSurface: 'canvas_node', canvasNodeId: 'image-1' }]);
    expect(queue.activeTasks.value.map(item => item.id)).toEqual(['chat', 'node']);
  });
});
