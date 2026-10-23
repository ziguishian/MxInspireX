import type { RouteRecordRaw } from 'vue-router';
export type WorkspaceView = 'intake' | 'design-agent' | 'asset-library' | 'knowledge-library' | 'projects-library' | 'user-center' | 'settings' | 'help' | 'schedules' | 'skills';
export type SidebarSection = 'home' | 'new' | 'projects' | 'assets' | 'knowledge' | 'schedules' | 'skills';
export const pageLocations = {
  intake: '/', 'projects-library': '/projects', 'asset-library': '/assets',
  'knowledge-library': '/references', skills: '/skills', schedules: '/schedules', 'user-center': '/settings/account', settings: '/settings/account', help: '/settings/help',
} as const;
export function pathForWorkspace(view: WorkspaceView, projectId: string | null): string | null {
  if (view in pageLocations) return pageLocations[view as keyof typeof pageLocations];
  if (!projectId) return null;
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return base;
}
export function sectionForWorkspace(view: WorkspaceView): SidebarSection {
  return view === 'skills' ? 'skills' : view === 'asset-library' ? 'assets' : view === 'knowledge-library' ? 'knowledge'
    : view === 'schedules' ? 'schedules' : view === 'projects-library' || view === 'design-agent' ? 'projects' : 'home';
}
// Settings are addressable pages; old account links keep their destination.
export const studioRoutes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: () => import('../../pages/HomePage.vue'), meta: { view: 'intake', title: '首页' } },
  { path: '/projects', name: 'projects', component: () => import('../../pages/ProjectsPage.vue'), meta: { view: 'projects-library', title: '我的项目' } },
  { path: '/projects/:projectId', name: 'project', component: () => import('../../pages/ProjectWorkspacePage.vue'), meta: { view: 'design-agent', title: '设计工作区' } },
  { path: '/assets', name: 'assets', component: () => import('../../pages/AssetsPage.vue'), meta: { view: 'asset-library', title: '资产库' } },
  { path: '/knowledge', redirect: '/references' },
  { path: '/references', name: 'references', component: () => import('../../pages/ReferencesPage.vue'), meta: { view: 'knowledge-library', title: '参考库' } },
  { path: '/references/legacy', name: 'knowledge', component: () => import('../../pages/KnowledgePage.vue'), meta: { view: 'knowledge-library', title: '历史资料' } },
  { path: '/skills', name: 'skills', component: () => import('../../pages/SkillsPage.vue'), meta: { view: 'skills', title: '技能库' } },
  { path: '/schedules', name: 'schedules', component: () => import('../../pages/SchedulesPage.vue'), meta: { view: 'schedules', title: '定时任务' } },
  { path: '/account', redirect: '/settings/account' },
  { path: '/settings', redirect: '/settings/account' },
  { path: '/settings/:section(account|general|text|routing|appearance|components|about|help)', name: 'settings', component: () => import('../../pages/SettingsPage.vue'), meta: { view: 'settings', title: '设置' } },
  { path: '/help', name: 'help', redirect: '/settings/help' },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../../pages/NotFoundPage.vue'), meta: { title: '页面不存在' } },
];
