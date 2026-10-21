import { computed, ref, type Ref } from 'vue';
import { queuePauseReason, queueTaskResult } from './messageQueue';

export type QueueTask = { id: string; projectId: string; status: string; userMessage?: string; agentKey: string; replacesTaskId?: string; taskSurface?: 'conversation' | 'canvas_node'; canvasNodeId?: string; updates?: Array<{ appliedAt?: string | null }>; output?: { structured_data?: Record<string, any> } | null };
type QueueRecord = Omit<QueueTask, 'projectId'>;
type QueueProject = { id: string; name: string; latestTaskId?: string | null; latestTaskStatus?: string | null };
const active = (status: string) => ['queued', 'pending', 'running'].includes(status);

// Keep task destinations independent of the project currently on screen.
export function createTaskQueue(projects: Readonly<Ref<QueueProject[]>>, fetchTasks: (projectId: string) => Promise<QueueRecord[]>, fetchActivity?: () => Promise<QueueTask[]>) {
  const records = ref<Record<string, QueueRecord[]>>({});
  const revisions = new Map<string, number>();
  const refreshing = new Set<string>();
  const activeTasks = computed(() => projects.value.flatMap(project => {
    const known = records.value[project.id] || [];
    const tasks = known.filter(task => active(task.status));
    if (project.latestTaskId && active(project.latestTaskStatus || '') && !known.some(task => task.id === project.latestTaskId)) {
      tasks.push({ id: project.latestTaskId, status: project.latestTaskStatus!, agentKey: 'design' });
    }
    return tasks.map(task => ({ ...task, projectId: project.id, projectName: project.name }));
  }));
  const attentionTasks = computed(() => projects.value.flatMap(project => {
    const seen = new Set<string>();
    return (records.value[project.id] || []).flatMap(task => {
      const key = task.taskSurface === 'canvas_node' ? `node:${task.canvasNodeId}` : 'conversation';
      if (seen.has(key)) return [];
      seen.add(key);
      if (active(task.status)) return [];
      const reason = queuePauseReason(queueTaskResult(task));
      return reason ? [{ ...task, projectId: project.id, projectName: project.name, reason }] : [];
    });
  }));
  let activityRefreshing = false;
  function replace(projectId: string, tasks: QueueRecord[]) {
    revisions.set(projectId, (revisions.get(projectId) || 0) + 1);
    records.value = { ...records.value, [projectId]: tasks };
  }
  function update(projectId: string, task: QueueRecord) {
    replace(projectId, [task, ...(records.value[projectId] || []).filter(item => item.id !== task.id && item.id !== task.replacesTaskId)]);
  }
  async function refresh() {
    if (fetchActivity) {
      if (activityRefreshing) return;
      activityRefreshing = true;
      const before = new Map(revisions);
      try {
        const tasks = await fetchActivity();
        for (const project of projects.value) if (revisions.get(project.id) === before.get(project.id)) {
          replace(project.id, tasks.filter(task => task.projectId === project.id));
        }
      } finally { activityRefreshing = false; }
      return;
    }
    await Promise.allSettled([...new Set(activeTasks.value.map(task => task.projectId))].map(async projectId => {
      if (refreshing.has(projectId)) return;
      refreshing.add(projectId);
      const revision = revisions.get(projectId);
      try {
        const tasks = await fetchTasks(projectId);
        // A delayed snapshot must not overwrite a newer streamed status.
        if (revisions.get(projectId) === revision) replace(projectId, tasks);
      } finally { refreshing.delete(projectId); }
    }));
  }
  return { activeTasks, attentionTasks, replace, update, refresh };
}
