import { app, dialog, ipcMain } from 'electron';
import { appendFileSync, existsSync, mkdirSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';

let logDirectory = '';
export function setTestingLogDirectory(workspace: string) { logDirectory = path.join(workspace, 'logs'); }

export function recordDesktopLog(level: string, message: string) {
  if (!logDirectory) return;
  try {
    mkdirSync(logDirectory, { recursive: true });
    const file = path.join(logDirectory, 'desktop.log');
    if (existsSync(file) && statSync(file).size > 2 * 1024 * 1024) {
      rmSync(file + '.2', { force: true });
      if (existsSync(file + '.1')) renameSync(file + '.1', file + '.2');
      renameSync(file, file + '.1');
    }
    const safe = message.replace(/\bsk-[A-Za-z0-9_-]{8,}/g, '[REDACTED]')
      .replace(/\bBearer\s+[^\s"',;]+/gi, 'Bearer [REDACTED]')
      .replace(/((?:api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token|cookie)["']?\s*[:=]\s*["']?)[^\s"',;}]+/gi, '$1[REDACTED]')
      .replace(/(https?:\/\/[^\s?"<>]+)\?[^\s"<>]*/g, '$1?[REDACTED]');
    appendFileSync(file, `${new Date().toISOString()} ${level} ${safe.slice(0, 24000)}\n`, 'utf8');
  } catch { /* Log collection must not interrupt an Agent task. */ }
}

export function registerTestingLogExport(apiPort: () => number) {
  let exporting = false;
  ipcMain.handle('testing:export-logs', async () => {
    if (exporting) throw new Error('日志正在导出，请稍候');
    exporting = true;
    try {
      const filename = `LangjuAgent-beta-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.zip`;
      const result = await dialog.showSaveDialog({ title: '导出内部测试日志', defaultPath: path.join(app.getPath('downloads'), filename), filters: [{ name: '日志压缩包', extensions: ['zip'] }] });
      if (result.canceled || !result.filePath) return null;
      const response = await fetch(`http://127.0.0.1:${apiPort()}/api/testing/export`);
      if (!response.ok) throw new Error('日志导出失败，请确认本地服务已连接');
      if (!response.headers.get('content-type')?.includes('application/zip')) throw new Error('日志文件格式异常');
      const bytes = Buffer.from(await response.arrayBuffer());
      writeFileSync(result.filePath, bytes);
      return result.filePath;
    } finally { exporting = false; }
  });
}
