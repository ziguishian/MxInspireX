export type LayoutRect = { id: string; x: number; y: number; width: number; height: number };
export type Guide = { axis: 'x' | 'y'; value: number; from: number; to: number };
export type Alignment = 'left' | 'right' | 'top' | 'bottom' | 'center-x' | 'center-y' | 'distribute-x' | 'distribute-y';

export function snapRect(moving: LayoutRect, others: LayoutRect[], threshold = 8) {
  let dx = 0, dy = 0, bestX = threshold + .0001, bestY = threshold + .0001;
  let vertical: Guide | undefined, horizontal: Guide | undefined;
  for (const other of others) {
    for (const source of [moving.x, moving.x + moving.width / 2, moving.x + moving.width]) {
      for (const target of [other.x, other.x + other.width / 2, other.x + other.width]) {
        const difference = target - source;
        if (Math.abs(difference) < bestX) { bestX = Math.abs(difference); dx = difference; vertical = { axis: 'x', value: target, from: Math.min(moving.y, other.y) - 20, to: Math.max(moving.y + moving.height, other.y + other.height) + 20 }; }
      }
    }
    for (const source of [moving.y, moving.y + moving.height / 2, moving.y + moving.height]) {
      for (const target of [other.y, other.y + other.height / 2, other.y + other.height]) {
        const difference = target - source;
        if (Math.abs(difference) < bestY) { bestY = Math.abs(difference); dy = difference; horizontal = { axis: 'y', value: target, from: Math.min(moving.x, other.x) - 20, to: Math.max(moving.x + moving.width, other.x + other.width) + 20 }; }
      }
    }
  }
  return { x: moving.x + dx, y: moving.y + dy, guides: [vertical, horizontal].filter(Boolean) as Guide[] };
}

export function rectsOverlap(left: LayoutRect, right: LayoutRect, gap = 48) {
  return left.x < right.x + right.width + gap
    && left.x + left.width + gap > right.x
    && left.y < right.y + right.height + gap
    && left.y + left.height + gap > right.y;
}

// A node may receive its final image ratio or Markdown height after its
// placeholder has already been placed. Build candidates from every occupied
// edge so the measured, rendered footprint is always moved to a free slot.
export function nearestOpenPosition(target: LayoutRect, occupied: LayoutRect[], gap = 48) {
  const preferred = { x: target.x, y: target.y };
  const available = (position: { x: number; y: number }) => !occupied.some(rect => rectsOverlap({ ...target, ...position }, rect, gap));
  if (available(preferred)) return preferred;
  const xs = new Set([preferred.x]), ys = new Set([preferred.y]);
  for (const rect of occupied) {
    xs.add(rect.x);
    xs.add(rect.x + rect.width + gap);
    ys.add(rect.y);
    ys.add(rect.y + rect.height + gap);
  }
  const candidates = [...ys].flatMap(y => [...xs].map(x => ({ x, y }))).filter(available);
  if (candidates.length) return candidates.sort((a, b) =>
    Math.abs(a.x - preferred.x) + Math.abs(a.y - preferred.y) - Math.abs(b.x - preferred.x) - Math.abs(b.y - preferred.y)
    || a.y - b.y || a.x - b.x,
  )[0];
  // The right edge of every finite rectangle is a guaranteed open column.
  return { x: Math.max(...occupied.map(rect => rect.x + rect.width + gap), preferred.x), y: preferred.y };
}

export function arrangeRects(rects: LayoutRect[], columns = 3, gap = 48) {
  if (!rects.length) return [];
  const normalized = rects.map(rect => ({ ...rect,
    x: Number.isFinite(rect.x) ? rect.x : 0,
    y: Number.isFinite(rect.y) ? rect.y : 0,
    width: Math.max(1, Number.isFinite(rect.width) ? rect.width : 1),
    height: Math.max(1, Number.isFinite(rect.height) ? rect.height : 1),
  }));
  const originX = Math.min(...normalized.map(r => r.x)), originY = Math.min(...normalized.map(r => r.y));
  let x = originX, y = originY, rowHeight = 0;
  return normalized.map((rect, index) => {
    if (index && index % Math.max(1, columns) === 0) { x = originX; y += rowHeight + gap; rowHeight = 0; }
    const position = { id: rect.id, x, y };
    x += rect.width + gap; rowHeight = Math.max(rowHeight, rect.height);
    return position;
  });
}

export function alignRects(rects: LayoutRect[], mode: Alignment) {
  if (rects.length < 2) return rects.map(({ id, x, y }) => ({ id, x, y }));
  const minX = Math.min(...rects.map(r => r.x)), minY = Math.min(...rects.map(r => r.y));
  const maxX = Math.max(...rects.map(r => r.x + r.width)), maxY = Math.max(...rects.map(r => r.y + r.height));
  if (mode.startsWith('distribute')) {
    const horizontal = mode === 'distribute-x';
    const sorted = [...rects].sort((a, b) => horizontal ? a.x - b.x : a.y - b.y);
    const start = horizontal ? minX : minY, end = horizontal ? maxX : maxY;
    const gap = (end - start - rects.reduce((sum, r) => sum + (horizontal ? r.width : r.height), 0)) / (rects.length - 1);
    let cursor = start;
    return sorted.map(rect => { const result = { id: rect.id, x: horizontal ? cursor : rect.x, y: horizontal ? rect.y : cursor }; cursor += (horizontal ? rect.width : rect.height) + gap; return result; });
  }
  return rects.map(rect => ({ id: rect.id,
    x: mode === 'left' ? minX : mode === 'right' ? maxX - rect.width : mode === 'center-x' ? (minX + maxX - rect.width) / 2 : rect.x,
    y: mode === 'top' ? minY : mode === 'bottom' ? maxY - rect.height : mode === 'center-y' ? (minY + maxY - rect.height) / 2 : rect.y,
  }));
}
