import { mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('electron-builder', () => ({ build: vi.fn(async () => []), Platform: { WINDOWS: { createTarget: () => 'nsis-x64' } }, Arch: { x64: 1 } }));
import { build } from 'electron-builder';
import { buildWindowsUpdateInstaller } from './windows-update-installer.mjs';
let fixture;
afterEach(() => { if (fixture) rmSync(fixture, { recursive: true, force: true }); vi.unstubAllEnvs(); vi.clearAllMocks(); });
function input(profile) {
  fixture = mkdtempSync(path.join(tmpdir(), 'mx-update-config-'));
  mkdirSync(path.join(fixture, 'resources'));
  vi.stubEnv('WIN_CSC_LINK', ''); vi.stubEnv('CSC_LINK', ''); vi.stubEnv('WIN_PUBLISHER_NAME', '');
  return { root: process.cwd(), appDir: fixture, output: fixture, prefix: 'test-only', profile };
}
describe('Windows update packaging', () => {
  it.each([['full', 'latest'], ['lite', 'lite']])('keeps %s feed isolated and never publishes', async (profile, channel) => {
    await buildWindowsUpdateInstaller(input(profile));
    const feed = JSON.parse(readFileSync(path.join(fixture, 'resources/app-update.yml'), 'utf8'));
    expect(feed).toMatchObject({ provider: 'github', owner: 'ziguishian', repo: 'MxInspireX', channel });
    expect(feed).not.toHaveProperty('token');
    const options = build.mock.calls[0][0];
    expect(options.publish).toBe('never');
    expect(options.config.publish[0].channel).toBe(channel);
    expect(options.config.appId).toBe('com.aicreativestudio.desktop');
  });
  it('requires a publisher for signed builds and preserves signature identity', async () => {
    const options = input('full');
    vi.stubEnv('WIN_CSC_LINK', 'test-certificate.pfx');
    await expect(buildWindowsUpdateInstaller(options)).rejects.toThrow('WIN_PUBLISHER_NAME');
    expect(build).not.toHaveBeenCalled();
    vi.stubEnv('WIN_PUBLISHER_NAME', 'Example Publisher');
    await buildWindowsUpdateInstaller(options);
    const feed = JSON.parse(readFileSync(path.join(fixture, 'resources/app-update.yml'), 'utf8'));
    expect(feed.publisherName).toEqual(['Example Publisher']);
    expect(build.mock.calls[0][0].config.win.signtoolOptions.publisherName).toBe('Example Publisher');
  });
});
