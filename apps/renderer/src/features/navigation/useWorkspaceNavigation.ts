import { watch, type Ref } from 'vue';
import { useRouter, type Router } from 'vue-router';
import { pathForWorkspace, sectionForWorkspace, type WorkspaceView, type SidebarSection } from './routes';

type NavigationState = {
  workspaceView: Ref<WorkspaceView>; sidebarSection: Ref<SidebarSection>; activeProjectId: Ref<string | null>;
  projects: Readonly<Ref<{ id: string }[]>>; catalogReady: Readonly<Ref<boolean>>;
  selectProject: (id: string) => void; startNewIntake: () => void; loadLibraries: () => void;
  missingProject: () => void;
};
// Accept the router explicitly so races between a delayed catalogue, task
// commands and browser Back can be tested without mounting a canvas or an API.
export function bindWorkspaceNavigation(router: Router, state: NavigationState) {
  const stateKey = () => `${state.workspaceView.value}:${state.activeProjectId.value || ''}`;
  let routeState = '';
  let lastLibraryPath = '';
  function applyRoute() {
    const route = router.currentRoute.value;
    const view = route.meta.view as WorkspaceView | undefined;
    if (!view) { routeState = stateKey(); return; }
    const id = typeof route.params.projectId === 'string' ? route.params.projectId : null;
    if (id && state.catalogReady.value) {
      if (!state.projects.value.some(project => project.id === id)) {
        state.missingProject();
        routeState = stateKey();
        void router.replace('/projects');
        return;
      }
      if (state.activeProjectId.value !== id) state.selectProject(id);
    }
    // Returning to an existing home draft from a library is navigation, not a
    // new-task command. Only the explicit Home/New command clears that draft.
    if (view === 'intake' && state.activeProjectId.value) state.startNewIntake();
    state.workspaceView.value = view;
    state.sidebarSection.value = sectionForWorkspace(view);
    routeState = stateKey();
    if (['asset-library', 'knowledge-library', 'projects-library'].includes(view) && lastLibraryPath !== route.path) {
      lastLibraryPath = route.path;
      state.loadLibraries();
    } else if (!['asset-library', 'knowledge-library', 'projects-library'].includes(view)) lastLibraryPath = '';
  }
  watch([() => router.currentRoute.value.fullPath, state.catalogReady], applyRoute, { immediate: true });
  watch([state.workspaceView, state.activeProjectId], () => {
    if (stateKey() === routeState) return;
    const path = pathForWorkspace(state.workspaceView.value, state.activeProjectId.value);
    if (path && path !== router.currentRoute.value.path) void router.push(path);
  }, { flush: 'post' });
}
export function useWorkspaceNavigation(state: NavigationState) {
  const router = useRouter();
  bindWorkspaceNavigation(router, state);
  return { router };
}
