import { afterEach, describe, expect, it, vi } from 'vitest';
import { effectScope, nextTick, ref } from 'vue';
import { createMemoryHistory, createRouter, type RouteRecordRaw } from 'vue-router';
import { studioRoutes, pathForWorkspace, type SidebarSection, type WorkspaceView } from './routes';
import { bindWorkspaceNavigation } from './useWorkspaceNavigation';

const scopes: ReturnType<typeof effectScope>[] = [];
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); });
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick(); }
async function setup(path: string, ready = true) {
  const router = createRouter({ history: createMemoryHistory(), routes: studioRoutes.map((route): RouteRecordRaw => 'redirect' in route && route.redirect ? route : ({ path: route.path, name: route.name, meta: route.meta, component: { render: () => null } })) });
  await router.push(path);
  const state = {
    workspaceView: ref<WorkspaceView>('intake'), sidebarSection: ref<SidebarSection>('home'), activeProjectId: ref<string | null>(null),
    projects: ref([{ id: 'first' }, { id: 'second' }]), catalogReady: ref(ready),
    selectProject: vi.fn((id: string) => { state.activeProjectId.value = id; state.workspaceView.value = 'design-agent'; }),
    startNewIntake: vi.fn(() => { state.activeProjectId.value = null; state.workspaceView.value = 'intake'; }),
    loadLibraries: vi.fn(), missingProject: vi.fn(),
  };
  const scope = effectScope(); scopes.push(scope);
  scope.run(() => bindWorkspaceNavigation(router, state));
  await settle();
  return { router, state };
}
describe('workspace page navigation', () => {
  it('preserves an explicit library URL while the catalogue loads', async () => {
    const { router, state } = await setup('/assets', false);
    state.catalogReady.value = true; await settle();
    expect(router.currentRoute.value.path).toBe('/assets');
    expect(state.workspaceView.value).toBe('asset-library');
    expect(state.selectProject).not.toHaveBeenCalled();
  });
  it('hydrates a project deep link after delayed API startup, once', async () => {
    const { router, state } = await setup('/projects/second', false);
    expect(state.selectProject).not.toHaveBeenCalled();
    state.catalogReady.value = true; await settle();
    expect(state.selectProject).toHaveBeenCalledExactlyOnceWith('second');
    expect(router.currentRoute.value.path).toBe('/projects/second');
  });
  it('does not redirect an unknown project until the catalogue is authoritative', async () => {
    const { router, state } = await setup('/projects/missing', false);
    expect(router.currentRoute.value.path).toBe('/projects/missing');
    state.catalogReady.value = true; await settle();
    expect(router.currentRoute.value.path).toBe('/projects');
    expect(state.selectProject).not.toHaveBeenCalled();
    expect(state.missingProject).toHaveBeenCalledTimes(1);
  });
  it('keeps browser Back/Forward and workspace commands in one history', async () => {
    const { router, state } = await setup('/projects');
    state.selectProject('first'); await settle();
    expect(router.currentRoute.value.path).toBe('/projects/first');
    await router.push('/references'); await settle();
    router.back(); await settle();
    expect(state.workspaceView.value).toBe('design-agent');
    expect(state.activeProjectId.value).toBe('first');
    expect(state.selectProject).toHaveBeenCalledTimes(1);
    router.forward(); await settle();
    expect(state.workspaceView.value).toBe('knowledge-library');
    expect(router.currentRoute.value.path).toBe('/references');
  });
  it('selecting another project creates one entry, without intermediate state URLs', async () => {
    const { router, state } = await setup('/projects/first');
    state.selectProject('second'); await settle();
    expect(router.currentRoute.value.path).toBe('/projects/second');
    router.back(); await settle();
    expect(router.currentRoute.value.path).toBe('/projects/first');
    expect(state.activeProjectId.value).toBe('first');
  });
  it('returning from a library preserves the existing home draft', async () => {
    const { router, state } = await setup('/');
    await router.push('/assets'); await settle();
    router.back(); await settle();
    expect(state.workspaceView.value).toBe('intake');
    expect(state.startNewIntake).not.toHaveBeenCalled();
  });
  it('invalid destinations render 404 instead of returning to the previous workspace', async () => {
    const { router } = await setup('/projects/first');
    await router.push('/missing-page'); await settle();
    expect(router.currentRoute.value.name).toBe('not-found');
  });
  it('redirects legacy account links to the first settings page', async () => {
    const { router, state } = await setup('/account');
    expect(router.currentRoute.value.path).toBe('/settings/account');
    expect(state.workspaceView.value).toBe('settings');
  });
  it('keeps settings deep links while loading and restores the project on Back', async () => {
    const { router, state } = await setup('/projects/first');
    await router.push('/settings/text'); await settle();
    state.catalogReady.value = false; await settle();
    state.catalogReady.value = true; await settle();
    expect(router.currentRoute.value.path).toBe('/settings/text');
    expect(state.activeProjectId.value).toBe('first');
    await router.push('/settings/account'); await settle();
    router.back(); await settle();
    expect(router.currentRoute.value.path).toBe('/settings/text');
    router.back(); await settle();
    expect(state.workspaceView.value).toBe('design-agent');
    expect(state.startNewIntake).not.toHaveBeenCalled();
  });
  it('has independently loaded core pages, while queue and prompt controls stay local', () => {
    expect(studioRoutes.filter(route => 'component' in route).every(route => typeof route.component === 'function')).toBe(true);
    expect(pathForWorkspace('design-agent', null)).toBeNull();
    expect(pathForWorkspace('knowledge-library', 'first')).toBe('/references');
    expect(studioRoutes.some(route => /queue|prompt/.test(route.path))).toBe(false);
    expect(pathForWorkspace('settings', null)).toBe('/settings/account');
  });
});
