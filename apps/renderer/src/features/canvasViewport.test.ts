import { describe, expect, it } from 'vitest';
import { MAX_CANVAS_ZOOM, parseViewport, canvasContentRevision, fitCanvasContents, type FocusRect } from './canvasWorkspace';

describe('canvas content framing', () => {
  it('restores close-up views above the old 200% limit and rejects invalid zooms', () => {
    expect(parseViewport(JSON.stringify({ x: -1200, y: -700, zoom: 5 }))).toEqual({ x: -1200, y: -700, zoom: 5 });
    expect(parseViewport(JSON.stringify({ x: 0, y: 0, zoom: MAX_CANVAS_ZOOM }))?.zoom).toBe(8);
    expect(parseViewport(JSON.stringify({ x: 0, y: 0, zoom: 9 }))).toBeNull();
  });
  it('includes all widely separated outputs, including negative positions, without a 20% crop', () => {
    const region = { x: 490, y: 80, width: 760, height: 700 };
    const nodes = [{ x: -3000, y: -2000, width: 300, height: 500 }, { x: 6000, y: 5000, width: 1200, height: 900 }];
    const view = fitCanvasContents(nodes, region)!;
    expect(view.zoom).toBeLessThan(.2);
    for (const node of nodes) assertVisible(node, region, view);
  });
  it('fits portrait media and its wider prompt within the unobstructed area', () => {
    const region = { x: 24, y: 80, width: 342, height: 340 };
    const nodes = [{ x: 100, y: 10, width: 300, height: 500 }, { x: 10, y: 520, width: 480, height: 250 }];
    const view = fitCanvasContents(nodes, region)!;
    for (const node of nodes) assertVisible(node, region, view);
    expect(fitCanvasContents([], region)).toBeNull();
    expect(fitCanvasContents(nodes, { ...region, width: -100 })).toBeNull();
  });
  it('detects completion and replacement of the same node but ignores polling and dragging', () => {
    const pending = { data: { kind: 'image', generating: true } };
    const complete = { data: { kind: 'image', generating: false, assetId: 'one' } };
    expect(canvasContentRevision(pending)).not.toBe(canvasContentRevision(complete));
    expect(canvasContentRevision(complete)).not.toBe(canvasContentRevision({ data: { ...complete.data, assetId: 'two' } }));
    expect(canvasContentRevision(complete)).toBe(canvasContentRevision({ ...complete, data: { ...complete.data, selected: true, updatedAt: 'later', prompt: 'draft', params: { quality: 'high' } } }));
  });
  it('keeps screen-size controls below a portrait visible in a narrow free region', () => {
    const region = { x: 24, y: 80, width: 342, height: 340 };
    const node = { x: 100, y: 10, width: 608, height: 1080 };
    const controls = { x: 404, y: 1090, width: 342, height: 250 };
    const view = fitCanvasContents([node], region, [controls])!;
    expect(view.zoom).toBeGreaterThan(0);
    expect(view.zoom).toBeLessThan(.1);
    assertVisible(node, region, view);
    expect(controls.x * view.zoom + view.x - controls.width / 2).toBeGreaterThanOrEqual(region.x);
    expect(controls.x * view.zoom + view.x + controls.width / 2).toBeLessThanOrEqual(region.x + region.width);
    expect(controls.y * view.zoom + view.y + 10 + controls.height).toBeLessThanOrEqual(region.y + region.height);
  });
  it('rejects space smaller than the controls and preserves a manually zoomed-out view', () => {
    const node = { x: -3000, y: -2000, width: 720, height: 405 };
    const controls = { x: -2640, y: -1595, width: 480, height: 250 };
    expect(fitCanvasContents([node], { x: 0, y: 0, width: 400, height: 800 }, [controls])).toBeNull();
    const view = fitCanvasContents([node], { x: 20, y: 80, width: 800, height: 700 }, [controls], .05)!;
    expect(view.zoom).toBe(.05);
  });
});

function assertVisible(rect: FocusRect, region: FocusRect, view: { x: number; y: number; zoom: number }) {
  expect(rect.x * view.zoom + view.x).toBeGreaterThanOrEqual(region.x);
  expect(rect.y * view.zoom + view.y).toBeGreaterThanOrEqual(region.y);
  expect((rect.x + rect.width) * view.zoom + view.x).toBeLessThanOrEqual(region.x + region.width);
  expect((rect.y + rect.height) * view.zoom + view.y).toBeLessThanOrEqual(region.y + region.height);
}
