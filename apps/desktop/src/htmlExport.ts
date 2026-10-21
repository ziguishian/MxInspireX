import { BrowserWindow, ipcMain, session } from 'electron';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';

const exportWindows = new Set<BrowserWindow>();
export function isHtmlExportWindow(window: BrowserWindow) { return exportWindows.has(window); }

export async function renderHtmlPdf(input: unknown): Promise<Buffer> {
  const { html, width } = (input || {}) as { html?: unknown; width?: unknown };
  if (typeof html !== 'string' || !html.trim() || html.length > 100 * 1024 * 1024 || typeof width !== 'number' || !Number.isFinite(width) || width < 480 || width > 2880) {
    throw new Error('网页导出参数无效。');
  }
  const directory = await mkdtemp(path.join(tmpdir(), 'aics-html-pdf-'));
  let window: BrowserWindow | undefined;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const isolatedSession = session.fromPartition(`html-export-${randomUUID()}`);
  try {
    const filename = path.join(directory, 'page.html');
    const url = pathToFileURL(filename).href;
    // Enforce the preview boundary in the main process as well. The generated
    // page receives no preload, workspace files, credentials, or network access.
    const csp = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
    await writeFile(filename, `<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><style>html{-webkit-print-color-adjust:exact;print-color-adjust:exact}</style>${html}`);
    isolatedSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    isolatedSession.setPermissionCheckHandler(() => false);
    isolatedSession.on('will-download', event => event.preventDefault());
    isolatedSession.webRequest.onBeforeRequest((details, callback) => callback({ cancel: details.url !== url && !/^(data|blob):/.test(details.url) }));
    window = new BrowserWindow({ show: false, width: Math.round(width), height: 1000, useContentSize: true, webPreferences: {
      session: isolatedSession, sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false,
    } });
    const target = window;
    exportWindows.add(target);
    target.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    target.webContents.on('will-navigate', event => event.preventDefault());
    target.webContents.on('will-frame-navigate', event => event.preventDefault());
    target.webContents.on('will-attach-webview', event => event.preventDefault());
    const render = async () => {
      await target.loadURL(url);
      await target.webContents.executeJavaScript(`(async () => {
        for (const image of document.images) image.loading = 'eager';
        await Promise.all([document.fonts.ready, ...Array.from(document.images, image => image.decode())]);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      })()`);
      return target.webContents.printToPDF({
        printBackground: true, displayHeaderFooter: false, margins: { top: 0, bottom: 0, left: 0, right: 0 },
        pageSize: { width: width / 96, height: width / 96 * Math.SQRT2 }, preferCSSPageSize: true,
      });
    };
    return await Promise.race([render(), new Promise<never>((_resolve, reject) => {
      timeout = setTimeout(() => reject(new Error('网页 PDF 导出超时，请重试。')), 30_000);
    })]);
  } finally {
    clearTimeout(timeout);
    if (window) { if (!window.isDestroyed()) window.destroy(); exportWindows.delete(window); }
    isolatedSession.webRequest.onBeforeRequest(null);
    await rm(directory, { recursive: true, force: true });
  }
}

export function registerHtmlExport() {
  const pending = new Set<number>();
  ipcMain.handle('canvas:export-html-pdf', async (event, input: unknown) => {
    if (event.senderFrame !== event.sender.mainFrame || !BrowserWindow.fromWebContents(event.sender)) throw new Error('无效的导出请求。');
    if (pending.has(event.sender.id)) throw new Error('请等待当前 PDF 导出完成。');
    pending.add(event.sender.id);
    try { return await renderHtmlPdf(input); }
    finally { pending.delete(event.sender.id); }
  });
}
