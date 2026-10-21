import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const electron = vi.hoisted(() => ({ handle: vi.fn(), showSaveDialog: vi.fn(), getPath: vi.fn(() => '/Downloads') }));
vi.mock('electron', () => ({ app: { getPath: electron.getPath }, dialog: { showSaveDialog: electron.showSaveDialog }, ipcMain: { handle: electron.handle } }));
import { recordDesktopLog, registerTestingLogExport, setTestingLogDirectory } from '../apps/desktop/src/testingLogs';

const folders: string[] = [];
function tempFolder() { const folder = mkdtempSync(path.join(tmpdir(), 'langju-log-export-')); folders.push(folder); return folder; }
function exportHandler() {
  registerTestingLogExport(() => 9876);
  expect(electron.handle).toHaveBeenLastCalledWith('testing:export-logs', expect.any(Function));
  return electron.handle.mock.calls.at(-1)![1] as () => Promise<string | null>;
}
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); setTestingLogDirectory(''); for (const folder of folders.splice(0)) rmSync(folder, { recursive: true, force: true }); });

describe('desktop beta log export', () => {
  it('saves the exact ZIP bytes to the path selected in the native dialog', async () => {
    const file = path.join(tempFolder(), '员工测试日志.zip');
    electron.showSaveDialog.mockResolvedValue({ canceled: false, filePath: file });
    const bytes = new Uint8Array([80, 75, 3, 4, 0, 255, 128]);
    const fetch = vi.fn().mockResolvedValue(new Response(bytes, { headers: { 'content-type': 'application/zip' } }));
    vi.stubGlobal('fetch', fetch);
    expect(await exportHandler()()).toBe(file);
    expect(fetch).toHaveBeenCalledExactlyOnceWith('http://127.0.0.1:9876/api/testing/export');
    expect(readFileSync(file)).toEqual(Buffer.from(bytes));
  });

  it('cancels without exporting and preserves an existing file when the response is invalid', async () => {
    const file = path.join(tempFolder(), 'logs.zip');
    writeFileSync(file, 'existing log bundle');
    const fetch = vi.fn().mockResolvedValue(new Response('unavailable', { headers: { 'content-type': 'text/html' } }));
    vi.stubGlobal('fetch', fetch);
    const run = exportHandler();
    electron.showSaveDialog.mockResolvedValueOnce({ canceled: true });
    expect(await run()).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
    electron.showSaveDialog.mockResolvedValue({ canceled: false, filePath: file });
    await expect(run()).rejects.toThrow('日志文件格式异常');
    expect(readFileSync(file, 'utf8')).toBe('existing log bundle');
    // A failed export releases the in-progress guard for a retry.
    fetch.mockResolvedValueOnce(new Response(new Uint8Array([80, 75]), { headers: { 'content-type': 'application/zip' } }));
    expect(await run()).toBe(file);
  });

  it('records desktop diagnostics without retaining common credentials', () => {
    const folder = tempFolder();
    setTestingLogDirectory(folder);
    recordDesktopLog('error', 'provider failed api_key=sample-secret-value Bearer sample-token https://example.com/media?token=sample-query');
    const log = readFileSync(path.join(folder, 'logs/desktop.log'), 'utf8');
    expect(log).toContain('provider failed');
    for (const secret of ['sample-secret-value', 'sample-token', 'sample-query']) expect(log).not.toContain(secret);
  });
});
