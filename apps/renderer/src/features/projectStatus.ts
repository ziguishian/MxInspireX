import type { Project } from '../../../../packages/contracts/project';
export function projectStatusLabel(project: Project) {
  if (project.status === 'archived') return '已归档';
  return ({ empty: '尚未开始', queued: '等待执行', running: '生成中', succeeded: '本轮完成', awaiting_input: '等待补充', failed: '执行失败', cancelled: '已停止' })[project.latestTaskStatus || 'empty'];
}
export const projectActivity = (project: Project) => project.activityAt || project.updatedAt;
export const projectCompleted = (project: Project) => project.latestTaskStatus === 'succeeded';
