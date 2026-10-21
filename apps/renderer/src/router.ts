import { createRouter, createMemoryHistory, createWebHistory } from 'vue-router';
import { studioRoutes } from './features/navigation/routes';
import { desktopStartupPath, legacyHashDestination } from './features/navigation/startupLocation';

const filePage = window.location.protocol === 'file:';
const webBase = import.meta.env.BASE_URL.startsWith('/') ? import.meta.env.BASE_URL : '/';
const desktopRouteKey = 'langjuart.desktopRoute';
function stored(storage: Storage, key: string) { try { return storage.getItem(key); } catch { return null; } }
// Capture before router initialization. A browser's / is always the homepage;
// only the packaged desktop entry restores its previous internal destination.
export const initialDesktopPath = desktopStartupPath(window.location,
  filePage ? stored(sessionStorage, desktopRouteKey) : null,
  filePage ? stored(localStorage, 'langjuart.activeProjectId') : null);
const legacyPath = legacyHashDestination(window.location, webBase);
if (!filePage && legacyPath) window.history.replaceState(window.history.state, '', `${webBase.replace(/\/$/, '')}${legacyPath}`);
if (filePage && legacyPath) window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}`);

export const router = createRouter({ history: filePage ? createMemoryHistory() : createWebHistory(webBase), routes: studioRoutes, scrollBehavior: () => ({ top: 0 }) });
router.afterEach(to => {
  document.title = `${String(to.meta.title || '工作台')} · MxinspireX`;
  if (filePage) { try { sessionStorage.setItem(desktopRouteKey, to.fullPath); } catch { /* Navigation works without storage. */ } }
});
