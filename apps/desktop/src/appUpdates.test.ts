import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import { AppUpdates, trustedUpdateSender, updateDisabledReason } from './appUpdates.js';

function setup(reason?: string) {
  const driver = Object.assign(new EventEmitter(), {
    autoDownload: true, autoInstallOnAppQuit: true, allowPrerelease: true, allowDowngrade: true,
    checkForUpdates: vi.fn(async () => { driver.emit('update-available', { version: '0.3.0', releaseNotes: '改进更新流程' }); }),
    downloadUpdate: vi.fn(async () => { driver.emit('download-progress', { percent: 46.7 }); driver.emit('update-downloaded'); }),
    quitAndInstall: vi.fn(),
  });
  const publish = vi.fn();
  const updates = new AppUpdates(driver, '0.2.0', reason, publish);
  return { driver, updates, publish };
}
describe('manual application updates', () => {
  it('enables only packaged Windows installers', () => {
    expect(updateDisabledReason(false, 'win32', true)).toBeUndefined();
    expect(updateDisabledReason(true, 'win32', true)).toContain('开发模式');
    expect(updateDisabledReason(false, 'darwin', true)).toContain('此平台');
    expect(updateDisabledReason(false, 'win32', false)).toContain('便携版');
  });
  it('rejects frames, workers and navigated/untrusted URLs', () => {
    const file = 'file:///D:/app/index.html';
    expect(trustedUpdateSender(file + '#/settings', file, false, true, true)).toBe(true);
    expect(trustedUpdateSender(file, file, false, false, true)).toBe(false);
    expect(trustedUpdateSender(file, file, false, true, false)).toBe(false);
    expect(trustedUpdateSender(file + '.evil', file, false, true, true)).toBe(false);
    expect(trustedUpdateSender('https://example.com', file, false, true, true)).toBe(false);
    expect(trustedUpdateSender('invalid', 'http://localhost:5173', true, true, true)).toBe(false);
  });
  it('disables development / unsupported packages without making requests', async () => {
    const { driver, updates } = setup('开发模式');
    await updates.check(); await updates.download(); updates.install();
    expect(updates.snapshot().status).toBe('disabled');
    expect(driver.checkForUpdates).not.toHaveBeenCalled();
    expect(driver.downloadUpdate).not.toHaveBeenCalled();
    expect(driver.quitAndInstall).not.toHaveBeenCalled();
  });
  it('finds releases but never downloads or installs on check or dismissal', async () => {
    const { driver, updates } = setup();
    await updates.check();
    expect(updates.snapshot()).toMatchObject({ status: 'available', currentVersion: '0.2.0', latestVersion: '0.3.0', notes: '改进更新流程' });
    expect(driver.autoDownload).toBe(false);
    expect(driver.autoInstallOnAppQuit).toBe(false);
    expect(driver.allowDowngrade).toBe(false);
    expect(driver.allowPrerelease).toBe(false);
    updates.snapshot(); updates.install(); await updates.check();
    expect(driver.downloadUpdate).not.toHaveBeenCalled();
    expect(driver.quitAndInstall).not.toHaveBeenCalled();
    expect(driver.checkForUpdates).toHaveBeenCalledTimes(1);
  });
  it('handles no newer version without announcing an update', async () => {
    const { driver, updates } = setup();
    driver.checkForUpdates.mockImplementation(async () => { driver.emit('update-not-available'); });
    await updates.check();
    expect(updates.snapshot().status).toBe('idle');
    expect(updates.snapshot().latestVersion).toBeUndefined();
  });
  it('requires download then a separate install click, reports progress and installs once', async () => {
    const { driver, updates, publish } = setup();
    await updates.download();
    expect(driver.downloadUpdate).not.toHaveBeenCalled();
    await updates.check(); await updates.download();
    expect(publish.mock.calls.some(([state]) => state.status === 'downloading' && state.percent === 46.7)).toBe(true);
    expect(updates.snapshot().status).toBe('downloaded');
    expect(driver.quitAndInstall).not.toHaveBeenCalled();
    await updates.download(); updates.install(); updates.install();
    expect(driver.downloadUpdate).toHaveBeenCalledTimes(1);
    expect(driver.quitAndInstall).toHaveBeenCalledExactlyOnceWith(false, true);
  });
  it('deduplicates in-flight checks and downloads', async () => {
    const { driver, updates } = setup();
    let resolve!: () => void;
    driver.checkForUpdates.mockImplementation(() => new Promise<void>(done => { resolve = done; }));
    const check = updates.check(); await updates.check();
    expect(driver.checkForUpdates).toHaveBeenCalledTimes(1);
    driver.emit('update-available', { version: '0.3.0' }); resolve(); await check;
    driver.downloadUpdate.mockImplementation(() => new Promise<void>(done => { resolve = done; }));
    const download = updates.download(); await updates.download(); updates.install();
    expect(driver.downloadUpdate).toHaveBeenCalledTimes(1);
    expect(driver.quitAndInstall).not.toHaveBeenCalled();
    driver.emit('update-downloaded'); resolve(); await download;
  });
  it.each(['network timeout', 'HTTP 429', 'HTTP 403', 'HTTP 404'])('handles check failure %s and manual retry', async error => {
    const { driver, updates } = setup();
    driver.checkForUpdates.mockRejectedValueOnce(new Error(error));
    await updates.check();
    expect(updates.snapshot()).toMatchObject({ status: 'error', retry: 'check' });
    await updates.check();
    expect(updates.snapshot().status).toBe('available');
  });
  it('retains version after a failed download and retries only on click', async () => {
    const { driver, updates } = setup();
    await updates.check();
    driver.downloadUpdate.mockImplementationOnce(async () => { driver.emit('error', new Error('sha512 mismatch')); throw new Error('sha512 mismatch'); });
    await updates.download();
    expect(updates.snapshot()).toMatchObject({ status: 'error', latestVersion: '0.3.0', retry: 'download' });
    expect(updates.snapshot().error).toContain('校验失败');
    updates.install(); await updates.check();
    expect(driver.quitAndInstall).not.toHaveBeenCalled();
    expect(driver.checkForUpdates).toHaveBeenCalledTimes(1);
    await updates.download();
    expect(updates.snapshot().status).toBe('downloaded');
  });
  it('does not start a second installer after an installation error', async () => {
    const { driver, updates } = setup();
    await updates.check(); await updates.download();
    driver.quitAndInstall.mockImplementation(() => { driver.emit('error', new Error('spawn failed')); });
    updates.install(); updates.install(); await updates.check(); await updates.download();
    expect(updates.snapshot()).toMatchObject({ status: 'error', retry: 'restart' });
    expect(driver.quitAndInstall).toHaveBeenCalledTimes(1);
    expect(driver.downloadUpdate).toHaveBeenCalledTimes(1);
  });
});
