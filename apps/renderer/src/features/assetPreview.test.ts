import { describe, expect, it } from 'vitest';
import { assetPreviewKind, libraryAssetUrl, videoDuration } from './assetPreview';
const asset = { id: 'a', projectId: 'p', pathRelative: 'file', kind: 'document', byteSize: 1 };
describe('library previews', () => {
  it('recognizes generated pages, uploaded HTML, videos and images', () => {
    expect(assetPreviewKind({ ...asset, htmlNodeId: 'page' })).toBe('html');
    expect(assetPreviewKind({ ...asset, mime: 'text/html;charset=utf-8' })).toBe('html');
    expect(assetPreviewKind({ ...asset, pathRelative: 'index.HTM' })).toBe('html');
    expect(assetPreviewKind({ ...asset, pathRelative: 'movie.MP4' })).toBe('video');
    expect(assetPreviewKind({ ...asset, mime: 'video/webm' })).toBe('video');
    expect(assetPreviewKind({ ...asset, kind: 'image' })).toBe('image');
    expect(assetPreviewKind({ ...asset, kind: '3d', pathRelative: 'model.glb' })).toBe('3d');
    expect(assetPreviewKind({ ...asset, mime: 'application/pdf' })).toBeNull();
  });
  it('keeps media in the owning project and encodes IDs', () => {
    expect(libraryAssetUrl('http://fixture.invalid', { ...asset, projectId: 'project /1', id: 'a/b' })).toContain('/projects/project%20%2F1/assets/a%2Fb/content');
    expect(assetPreviewKind({ ...asset, projectId: undefined, kind: 'image' })).toBeNull();
  });
  it('formats short and long video durations without showing invalid metadata', () => {
    expect(videoDuration(65.9)).toBe('1:05');
    expect(videoDuration(5)).toBe('0:05');
    expect(videoDuration(Infinity)).toBe('');
  });
});
