type StartupLocation = Pick<Location, 'protocol' | 'pathname' | 'search' | 'hash'>;
const routeOrigin = 'https://studio.invalid';

function localRoute(value: string | null): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\r\n]/.test(value)) return null;
  try {
    const url = new URL(value, routeOrigin);
    return url.origin === routeOrigin ? `${url.pathname}${url.search}${url.hash}` : null;
  } catch { return null; }
}

/** Old bookmarks use /#/projects/id. Explicit clean paths always take priority. */
export function legacyHashDestination(location: StartupLocation, base = '/'): string | null {
  const root = base.endsWith('/') ? base : `${base}/`;
  const entry = location.protocol === 'file:' || [root, `${root}index.html`].includes(location.pathname);
  if (!entry || !location.hash.startsWith('#/')) return null;
  const route = localRoute(location.hash.slice(1));
  if (!route) return null;
  const url = new URL(route, routeOrigin);
  // Preserve entry query parameters; the bookmarked route's values win.
  for (const [key, value] of new URLSearchParams(location.search)) if (!url.searchParams.has(key)) url.searchParams.append(key, value);
  return `${url.pathname}${url.search}${url.hash}`;
}

/** file:// cannot serve history paths. Keep desktop navigation in Vue Router. */
export function desktopStartupPath(location: StartupLocation, remembered: string | null, projectId: string | null): string | null {
  if (location.protocol !== 'file:') return null;
  return legacyHashDestination(location) || localRoute(remembered) || (projectId ? `/projects/${encodeURIComponent(projectId)}` : '/');
}
