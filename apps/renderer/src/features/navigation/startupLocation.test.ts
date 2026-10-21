import { describe, expect, it } from 'vitest';
import { desktopStartupPath, legacyHashDestination } from './startupLocation';
const web = { protocol: 'http:', pathname: '/', search: '', hash: '' };
describe('clean page URLs', () => {
  it('keeps the homepage and clean deep links independent of last-opened projects', () => {
    expect(desktopStartupPath(web, '/assets', 'old-project')).toBeNull();
    expect(desktopStartupPath({ ...web, pathname: '/knowledge' }, '/projects', 'old-project')).toBeNull();
    expect(legacyHashDestination(web)).toBeNull();
    expect(legacyHashDestination({ ...web, pathname: '/assets', hash: '#/projects/old' })).toBeNull();
  });
  it('migrates old hash bookmarks, preserving query values and anchors', () => {
    expect(legacyHashDestination({ ...web, hash: '#/' })).toBe('/');
    expect(legacyHashDestination({ ...web, search: '?source=old&page=1', hash: '#/projects/p-1?page=2#details' })).toBe('/projects/p-1?page=2&source=old#details');
    expect(legacyHashDestination({ ...web, pathname: '/studio/', hash: '#/assets' }, '/studio/')).toBe('/assets');
    expect(legacyHashDestination({ ...web, hash: '#section' })).toBeNull();
  });
  it('never turns a legacy route into an external navigation', () => {
    for (const hash of ['#//outside.test', '#/\\outside.test', '#/\noutside.test']) expect(legacyHashDestination({ ...web, hash })).toBeNull();
  });
  it('restores desktop internal pages and handles old file bookmarks without a hash router', () => {
    const file = { ...web, protocol: 'file:', pathname: '/Applications/Studio/index.html' };
    expect(desktopStartupPath(file, '/', 'old-project')).toBe('/');
    expect(desktopStartupPath(file, '/assets', 'old-project')).toBe('/assets');
    expect(desktopStartupPath(file, null, 'design / 1')).toBe('/projects/design%20%2F%201');
    expect(desktopStartupPath({ ...file, hash: '#/knowledge' }, '/assets', 'old-project')).toBe('/knowledge');
    expect(desktopStartupPath(file, '//outside.test', null)).toBe('/');
  });
});
