export const MAX_CANVAS_ZOOM = 8;

export function parseViewport(raw: string | null): { x: number; y: number; zoom: number } | null {
  try {
    const value = JSON.parse(raw || 'null');
    return value && [value.x, value.y, value.zoom].every(Number.isFinite) && value.zoom > 0 && value.zoom <= MAX_CANVAS_ZOOM ? { x: value.x, y: value.y, zoom: value.zoom } : null;
  } catch { return null; }
}
// Only visible content changes trigger a new overview. Poll timestamps, locks,
// prompt settings, node positions and selection must not reset a user's view.
export function canvasContentRevision(node: { data?: Record<string, any> }) {
  const data = node.data || {};
  return JSON.stringify([data.kind, data.assetId || data.asset?.id, data.localFile,
    data.text, data.html, data.summary, Boolean(data.generating), data.error,
    data.asset?.metadata?.imageOutput, data.job?.status]);
}

export type FocusRect = { x: number; y: number; width: number; height: number };
// x/y attach to a node's bottom center in canvas coordinates; width/height
// stay in screen pixels. Fitting also reserves a ten-pixel gap above them.
export type CanvasControlsRect = FocusRect;
export function fitCanvasContents(rects: FocusRect[], region: FocusRect, controls: CanvasControlsRect[] = [], maxZoom = 1) {
  const valid = rects.filter(rect => [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) && rect.width > 0 && rect.height > 0);
  if (!valid.length || region.width <= 0 || region.height <= 0) return null;
  const left = Math.min(...valid.map(rect => rect.x)), top = Math.min(...valid.map(rect => rect.y));
  const right = Math.max(...valid.map(rect => rect.x + rect.width)), bottom = Math.max(...valid.map(rect => rect.y + rect.height));
  // Fit even a large or widely spread board; a fixed 20% minimum clips it.
  let zoom = Math.min(maxZoom, region.width / (right - left + 40), region.height / (bottom - top + 40));
  if (!controls.length) return { x: region.x + region.width / 2 - (left + right) / 2 * zoom,
    y: region.y + region.height / 2 - (top + bottom) / 2 * zoom, zoom };
  const boundsAt = (scale: number) => ({
    left: Math.min((left - 20) * scale, ...controls.map(panel => panel.x * scale - panel.width / 2)),
    right: Math.max((right + 20) * scale, ...controls.map(panel => panel.x * scale + panel.width / 2)),
    top: Math.min((top - 20) * scale, ...controls.map(panel => panel.y * scale + 10)),
    bottom: Math.max((bottom + 20) * scale, ...controls.map(panel => panel.y * scale + 10 + panel.height)),
  });
  const fits = (bounds: ReturnType<typeof boundsAt>) => bounds.right - bounds.left <= region.width && bounds.bottom - bounds.top <= region.height;
  // A smaller canvas cannot shrink these controls; choose another free region
  // instead of repeatedly zooming toward zero when a region is too small.
  if (!fits(boundsAt(0))) return null;
  if (!fits(boundsAt(zoom))) {
    let lower = 0, upper = zoom;
    for (let i = 0; i < 40; i++) {
      const middle = (lower + upper) / 2;
      if (fits(boundsAt(middle))) lower = middle; else upper = middle;
    }
    zoom = lower;
  }
  if (zoom <= 0) return null;
  const bounds = boundsAt(zoom);
  return { x: region.x + region.width / 2 - (bounds.left + bounds.right) / 2,
    y: region.y + region.height / 2 - (bounds.top + bounds.bottom) / 2, zoom };
}
