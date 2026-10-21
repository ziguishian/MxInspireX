import type { Project } from '../../../../packages/contracts/project';

/** A background response must not undo a newer rename, delete or creation. */
export function mergeProjectTitles(current: Project[], loaded: Project[], before: Project[]): Project[] {
  const previous = new Map(before.map((project) => [project.id, project]));
  const updates = new Map(loaded.map((project) => [project.id, project]));
  return current.map((project) => {
    const old = previous.get(project.id);
    const update = updates.get(project.id);
    if (!old || !update || old.name !== project.name || old.titleMode !== project.titleMode || old.updatedAt !== project.updatedAt) return project;
    return { ...project, name: update.name, titleMode: update.titleMode,
      titleGeneratedAt: update.titleGeneratedAt, titlePending: update.titlePending,
      latestTaskId: update.latestTaskId, latestTaskStatus: update.latestTaskStatus, summary: update.summary,
      activityAt: update.activityAt, previewRevision: update.previewRevision };
  });
}
