import { describe, expect, it } from 'vitest';
import { canvasNodeKind, nodePreviewSize, requestedMediaRatio } from './nodeSizing';
import { boardChanges, cleanBoard } from './canvasEditing';

describe('canvas preview sizing', () => {
  it('gives new media a larger readable frame while preserving a saved media width', () => {
    expect(nodePreviewSize({ kind: 'image', previewSizingVersion: 2 })).toEqual({ width: 720, height: 405 });
    expect(nodePreviewSize({ kind: 'image', previewSizingVersion: 2 }, 2 / 3)).toEqual({ width: 720, height: 1080 });
    expect(nodePreviewSize({ kind: 'video', previewSizingVersion: 2, params: { aspectRatio: '9:16' } })).toEqual({ width: 608, height: 1080 });
    expect(nodePreviewSize({ kind: 'upload', previewSizingVersion: 2, asset: { mime: 'image/png' } }, 1)).toEqual({ width: 720, height: 720 });
    expect(nodePreviewSize({ kind: 'image' })).toEqual({ width: 300, height: 169 });
    expect(nodePreviewSize({ kind: 'image', previewSizingVersion: 2, previewSize: { width: 500, height: 320 } })).toEqual({ width: 500, height: 281 });
  });
  it.each([
    [{ size: '1024x1536', aspectRatio: '16:9' }, 1024, 1536, 720, 1080],
    [{ size: '1536X864' }, 1536, 864, 720, 405],
    [{ aspect_ratio: '9:16' }, 864, 1536, 608, 1080],
    [{ aspectRatio: '1:1' }, 1024, 1024, 720, 720],
    [{ aspect: '3:1' }, 3072, 1024, 720, 240],
    [{ width: 1024, height: 3072 }, 1024, 3072, 360, 1080],
  ])('keeps a %j placeholder the same size when its image arrives', (params, width, height, frameWidth, frameHeight) => {
    const data = { kind: 'image', previewSizingVersion: 2, params };
    const loading = nodePreviewSize({ ...data, generating: true });
    const finished = nodePreviewSize({ ...data, generating: false, asset: { metadata: { imageOutput: { width, height } } } });
    expect(loading).toEqual({ width: frameWidth, height: frameHeight });
    expect(finished).toEqual(loading);
    expect(nodePreviewSize(data, width / height)).toEqual(loading);
  });
  it('uses new generation dimensions over the original image when editing a node', () => {
    const data = { kind: 'image', previewSizingVersion: 2, generating: true, params: { size: '864x1536' }, asset: { metadata: { imageOutput: { width: 1024, height: 1024 } } } };
    expect(nodePreviewSize(data, 1)).toEqual({ width: 608, height: 1080 });
    expect(nodePreviewSize({ ...data, previewSize: { width: 500, height: 320 } }, 1)).toEqual({ width: 500, height: 889 });
  });
  it('uses asset parameters as a fallback and actual output dimensions for automatic sizes', () => {
    expect(nodePreviewSize({ kind: 'image', previewSizingVersion: 2, asset: { metadata: { params: { size: '1024x1024' } } } })).toEqual({ width: 720, height: 720 });
    expect(nodePreviewSize({ kind: 'image', previewSizingVersion: 2, params: { size: 'auto' } }, 9 / 16)).toEqual({ width: 608, height: 1080 });
  });
  it.each([{ size: 'auto' }, { size: '0x1024' }, { aspect_ratio: '0:9' }, { aspectRatio: 'invalid' }, { width: Infinity, height: 1 }, {}])('ignores invalid or unknown dimensions %j', params => {
    expect(requestedMediaRatio(params)).toBeNull();
  });
  it('uses recorded image dimensions before loading so placement and final frames agree', () => {
    const data = { kind: 'image', params: { aspectRatio: '16:9' }, asset: { mime: 'image/png', metadata: { imageOutput: { width: 600, height: 1200 } } } };
    expect(nodePreviewSize(data)).toEqual({ width: 300, height: 600 });
    expect(nodePreviewSize(data, .5)).toEqual(nodePreviewSize(data));
    expect(nodePreviewSize({ ...data, previewSize: { width: 500, height: 320 } })).toEqual({ width: 500, height: 1000 });
  });
  it('keeps media proportions before and after resizing or replacing an asset', () => {
    expect(nodePreviewSize({ kind: 'image' }, 2)).toEqual({ width: 300, height: 150 });
    expect(nodePreviewSize({ kind: 'video', params: { aspectRatio: '9:16' } })).toEqual({ width: 300, height: 533 });
    const data = { kind: 'image', previewSize: { width: 600, height: 350 } };
    expect(nodePreviewSize(data, 1 / 2)).toEqual({ width: 600, height: 1200 });
    expect(nodePreviewSize(data, 3)).toEqual({ width: 600, height: 200 });
  });
  it.each(['audio', 'text', 'html', 'upload', '3d', 'document'])('restores custom %s dimensions', kind => {
    expect(nodePreviewSize({ kind, previewSize: { width: 640, height: 480 } })).toEqual({ width: 640, height: 480 });
    expect(nodePreviewSize({ kind, previewSize: { width: Infinity, height: NaN } })).toEqual(nodePreviewSize({ kind }));
    expect(nodePreviewSize({ kind, previewSize: { width: 9999, height: 9999 } })).toEqual({ width: 1920, height: 1440 });
  });
  it.each(['image', 'video'])('keeps custom %s widths but derives heights from the media', kind => {
    expect(nodePreviewSize({ kind, previewSize: { width: 640, height: 480 } })).toEqual({ width: 640, height: 360 });
    expect(nodePreviewSize({ kind, previewSize: { width: Infinity, height: NaN } })).toEqual(nodePreviewSize({ kind }));
    expect(nodePreviewSize({ kind, previewSize: { width: 9999, height: 9999 } })).toEqual({ width: 1920, height: 1080 });
  });
  it('keeps controls usable at minimum size', () => {
    const minimum = (kind: string) => nodePreviewSize({ kind, previewSize: { width: -1, height: -1 } });
    expect(minimum('image')).toEqual({ width: 160, height: 90 });
    expect(minimum('audio')).toEqual({ width: 220, height: 90 });
    expect(minimum('text')).toEqual({ width: 180, height: 120 });
    expect(minimum('3d')).toEqual({ width: 180, height: 150 });
    expect(minimum('html')).toEqual({ width: 320, height: 240 });
  });
  it('honors legacy HTML sizes until a new size is saved', () => {
    const data = { kind: 'html', htmlPreviewSize: { width: 1200, height: 800 } };
    expect(nodePreviewSize(data)).toEqual(data.htmlPreviewSize);
    expect(nodePreviewSize({ ...data, previewSize: { width: 400, height: 300 } })).toEqual({ width: 400, height: 300 });
  });
  it('detects uploaded asset types for the same sizing and rendering rules', () => {
    expect(canvasNodeKind({ kind: 'upload', asset: { mime: 'audio/mpeg' } })).toBe('audio');
    expect(canvasNodeKind({ kind: 'upload', asset: { pathRelative: 'models/ship.GLB' } })).toBe('3d');
    expect(nodePreviewSize({ kind: 'upload', asset: { mime: 'audio/mpeg' } }).width).toBe(220);
  });
  it('records sizing as an undoable data edit without modifying position, asset or text style', () => {
    const before = cleanBoard({ nodes: [{ id: 'a', position: { x: 70, y: 90 }, data: { kind: 'text', text: 'hello', textStyle: { fontSize: 18 } } }], edges: [] });
    const after = cleanBoard(before);
    after.nodes[0].data.previewSize = { width: 520, height: 300 };
    const change = boardChanges(before, after);
    expect(change.upsertNodes[0].position).toBeUndefined();
    expect(change.upsertNodes[0].data.textStyle).toEqual({ fontSize: 18 });
    expect(change.expectedNodes.a.data).toEqual(before.nodes[0].data);
    expect(boardChanges(after, before).upsertNodes[0].data.previewSize).toBeUndefined();
  });
});
