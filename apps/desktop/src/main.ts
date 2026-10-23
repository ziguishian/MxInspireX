import { app, BrowserWindow, dialog, ipcMain, nativeTheme, Notification, shell } from 'electron';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import path from 'node:path';
import { format } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isHtmlExportWindow, registerHtmlExport } from './htmlExport.js';
import { recordDesktopLog, registerTestingLogExport, setTestingLogDirectory } from './testingLogs.js';
import { chooseApiPort } from './apiPort.js';
import { RuntimeComponentManager } from './runtimeComponents.js';
import { copyWorkspace, validateWorkspaceDestination, type WorkspaceChangeMode } from './workspaceStorage.js';
import updaterPackage from 'electron-updater';
import { AppUpdates, updateDisabledReason, trustedUpdateSender } from './appUpdates.js';

registerHtmlExport();

const currentDir = path.dirname(fileURLToPath(import.meta.url));
// The macOS development launcher runs from a copied Electron.app shell. That
// shell can report `app.isPackaged === true` even though the renderer should
// come from Vite. Keep an explicit launcher flag so `npm run dev` remains a
// real hot-reload development session while Finder-launched bundles retain
// their packaged behaviour.
const isDev = process.env.AICS_DEV_MODE === '1' || !app.isPackaged;
const ownsAppInstance = isDev || app.requestSingleInstanceLock();
if (!ownsAppInstance) app.quit();
app.on('second-instance', () => {
  const window = visibleWindows()[0];
  if (window?.isMinimized()) window.restore();
  window?.show(); window?.focus();
});
const APP_NAME = 'MxinspireX';
// The desktop entry is compiled to dist/desktop in development and is kept
// under the app root in a packaged build. In both cases two levels up is the
// project root that contains services/api and dist/renderer.
const projectRoot = path.resolve(process.env.AICS_PROJECT_ROOT?.trim() || path.resolve(currentDir, '../..'));

/**
 * Electron can outlive the terminal that started it (especially when the
 * development launcher is stopped or its PTY is closed).  A later
 * `console.error` to that closed descriptor raises an uncaught EPIPE in the
 * main process.  Keep the process alive when an output descriptor disappears
 * and stop writing to that descriptor afterwards.
 */
let stdoutWritable = true;
let stderrWritable = true;

function isOutputError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const code = (error as { code?: unknown }).code;
  return code === 'EPIPE' || code === 'ERR_STREAM_DESTROYED' || code === 'EBADF';
}

function installOutputGuards() {
  const guard = (stream: NodeJS.WriteStream, markUnavailable: () => void) => {
    // An error listener is required on Node writable streams.  Without one,
    // a closed inherited stdout/stderr descriptor becomes an uncaught error.
    stream.on('error', (error) => {
      if (isOutputError(error)) markUnavailable();
    });
  };
  guard(process.stdout, () => {
    stdoutWritable = false;
  });
  guard(process.stderr, () => {
    stderrWritable = false;
  });
}

installOutputGuards();

function safeLog(level: 'info' | 'warn' | 'error', ...args: unknown[]) {
  recordDesktopLog(level, format(...args));
  const stream = level === 'error' ? process.stderr : process.stdout;
  const available = level === 'error' ? stderrWritable : stdoutWritable;
  if (!available || stream.destroyed || stream.writable === false) return;

  const line = `${format(...args)}\n`;
  const markUnavailable = () => {
    if (level === 'error') stderrWritable = false;
    else stdoutWritable = false;
  };
  try {
    stream.write(line, (error?: Error | null) => {
      if (error && isOutputError(error)) markUnavailable();
    });
  } catch (error) {
    if (isOutputError(error)) markUnavailable();
  }
}

type AppAppearance = 'dark' | 'light';
type AppAppearancePreference = 'system' | AppAppearance;

// The renderer owns the user-facing theme preference.  Keep a small mirror in
// the main process so the native Dock/window icon follows a manually selected
// theme as well as the macOS system setting.  Until the renderer reports its
// preference, `system` is the safe launch-time default.
let appAppearancePreference: AppAppearancePreference = 'system';
let lastNativeIconPath = '';

function currentAppAppearance(): AppAppearance {
  if (appAppearancePreference !== 'system') return appAppearancePreference;
  return nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
}

function appIconPath(appearance: AppAppearance = currentAppAppearance()) {
  // BrowserWindow/nativeImage accepts PNG consistently across Electron
  // versions. The ICNS remains declared in the bundle's Info.plist for
  // Finder/Stage Manager; the Dock API receives the matching PNG variant.
  const variant = `langju-agent-icon-${appearance}-1024.png`;
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, variant)]
    : [
        path.join(projectRoot, 'apps', 'renderer', 'public', 'assets', 'mxinspirex-robot.png'),
        path.join(projectRoot, 'apps', 'desktop', 'assets', variant),
      ];
  return candidates.find((candidate) => existsSync(candidate)) ?? candidates[candidates.length - 1];
}

function dockIconPath() {
  return appIconPath(currentAppAppearance());
}

function setDockIcon(iconPath: string) {
  if (process.platform !== 'darwin' || !app.dock || !existsSync(iconPath)) return;
  try {
    // Electron's declared type is void, but some macOS builds return a
    // Promise when decoding the image. Consume that promise so a decode error
    // cannot become an unhandled-rejection dialog in the main process.
    const result = app.dock.setIcon(iconPath) as unknown;
    if (result && typeof (result as { catch?: unknown }).catch === 'function') {
      void (result as Promise<unknown>).catch((error) => {
        safeLog('warn', '[app] dock icon unavailable: %s', error instanceof Error ? error.message : String(error));
      });
    }
  } catch (error) {
    safeLog('warn', '[app] dock icon unavailable: %s', error instanceof Error ? error.message : String(error));
  }
}

function syncNativeAppIcon() {
  const iconPath = appIconPath(currentAppAppearance());
  if (iconPath !== lastNativeIconPath) {
    lastNativeIconPath = iconPath;
    safeLog('info', '[app] native icon (%s): %s', currentAppAppearance(), iconPath);
  }
  setDockIcon(iconPath);
  // Electron documents BrowserWindow#setIcon primarily for Linux.  Call it
  // opportunistically on macOS builds that expose transient preview artwork;
  // the Dock API remains the authoritative running-app icon on macOS. Keeping
  // every open window in sync avoids a stale preview when appearance changes.
  for (const window of BrowserWindow.getAllWindows()) {
    try {
      window.setIcon(iconPath);
    } catch (error) {
      safeLog('warn', '[app] window icon unavailable: %s', error instanceof Error ? error.message : String(error));
    }
  }
}

function isAppAppearancePreference(value: unknown): value is AppAppearancePreference {
  return value === 'system' || value === 'dark' || value === 'light';
}

let apiProcess: ChildProcessWithoutNullStreams | undefined;
let apiRestartTimer: ReturnType<typeof setTimeout> | undefined;
let apiStopping = false;
let appIsQuitting = false;
let workspaceRoot = '';
let changingWorkspace = false;
let apiPort = 8765;
let runtimeComponentManager: RuntimeComponentManager;
registerTestingLogExport(() => apiPort);

function workspaceConfigPath() {
  return path.join(app.getPath('userData'), 'workspace.json');
}

function loadWorkspaceRoot() {
  const override = process.env.AICS_WORKSPACE_ROOT?.trim();
  if (override) return path.resolve(override);
  try {
    const saved = JSON.parse(readFileSync(workspaceConfigPath(), 'utf8')) as { root?: string };
    if (saved.root?.trim()) return path.resolve(saved.root);
  } catch {
    // First launch or an unreadable config falls back to Documents.
  }
  // Existing workspaces stay discoverable when upgrading the app.
  const previousWorkspace = path.join(app.getPath('documents'), 'AI Creative Studio');
  if (existsSync(path.join(previousWorkspace, 'catalog.sqlite'))) return previousWorkspace;
  return path.join(app.getPath('documents'), 'Langju Design Studio');
}

function persistWorkspaceRoot(root: string) {
  const configPath = workspaceConfigPath();
  mkdirSync(path.dirname(configPath), { recursive: true });
  const temporary = `${configPath}.tmp`;
  writeFileSync(temporary, JSON.stringify({ root, updatedAt: new Date().toISOString() }, null, 2), 'utf8');
  renameSync(temporary, configPath);
}

function startApiSidecar() {
  if (process.env.AICS_SKIP_SIDECAR === '1' || apiProcess || appIsQuitting) return;
  const apiDir = path.join(projectRoot, 'services/api');
  const bundledPython = process.platform === 'win32'
    ? path.join(apiDir, 'python', 'python.exe')
    : path.join(apiDir, '.venv', 'bin', 'python');
  const bundledSidecar = path.join(
    apiDir,
    'sidecar',
    'aics-api',
    process.platform === 'win32' ? 'aics-api.exe' : 'aics-api',
  );
  const python = process.env.AICS_PYTHON ?? (existsSync(bundledPython) ? bundledPython : 'python3');
  const usePortableSidecar = !isDev && existsSync(bundledSidecar) && process.env.AICS_USE_PYTHON_SIDECAR !== '1';
  const command = usePortableSidecar ? bundledSidecar : python;
  const args = usePortableSidecar
    ? []
    : ['-X', 'utf8', '-B', '-m', 'app.server', '--host', '127.0.0.1', '--port', String(apiPort)];
  const child = spawn(command, args, {
    cwd: apiDir,
    env: {
      ...process.env, AICS_WORKSPACE_ROOT: workspaceRoot,
      AICS_API_PORT: String(apiPort),
      AICS_AGENT_TOOL_GATEWAY_URL: `http://127.0.0.1:${apiPort}`,
      AICS_NODE: process.execPath,
      AICS_NODE_RUN_AS_NODE: '1',
      AICS_AGENT_WORKER: path.join(apiDir, 'app', 'openai_agent_worker.mjs'),
      ...(runtimeComponentManager?.status().length ? { AICS_LITE_RUNTIME: '1' } : {}),
      ...runtimeComponentManager?.environment(),
      PYTHONUTF8: '1',
      PYTHONDONTWRITEBYTECODE: '1',
    },
    stdio: 'pipe',
    windowsHide: true,
  });
  apiProcess = child;
  safeLog('info', '[api] %s: %s', usePortableSidecar ? 'portable sidecar' : 'python sidecar', command);

  // Always drain both pipes.  Uvicorn normally logs to stderr, while a
  // frozen sidecar or a Python warning can write to stdout; leaving stdout
  // unread can eventually block the child process.
  const forwardSidecarOutput = (stream: NodeJS.ReadableStream, level: 'info' | 'error') => {
    stream.setEncoding?.('utf8');
    stream.on('data', (chunk: unknown) => {
      const message = String(chunk).trim();
      if (message) safeLog(level, '[api] %s', message);
    });
    stream.on('error', (error) => {
      safeLog('error', '[api] sidecar %s stream failed: %s', level, error instanceof Error ? error.message : String(error));
    });
  };
  forwardSidecarOutput(child.stdout, 'info');
  forwardSidecarOutput(child.stderr, 'error');
  child.on('error', (error) => safeLog('error', '[api] sidecar failed: %s', error instanceof Error ? error.message : String(error)));
  child.on('exit', (code, signal) => {
    const wasCurrentProcess = apiProcess === child;
    if (wasCurrentProcess) apiProcess = undefined;
    if (wasCurrentProcess && !apiStopping && !appIsQuitting && !apiRestartTimer) {
      safeLog('error', '[api] sidecar exited (code=%s, signal=%s); restarting', code ?? 'null', signal ?? 'null');
      apiRestartTimer = setTimeout(() => {
        apiRestartTimer = undefined;
        startApiSidecar();
      }, 1000);
    }
  });
}

async function stopApiSidecar() {
  const child = apiProcess;
  if (apiRestartTimer) {
    clearTimeout(apiRestartTimer);
    apiRestartTimer = undefined;
  }
  if (!child || child.killed) return;
  apiStopping = true;
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    child.once('close', finish);
    child.kill('SIGTERM');
    setTimeout(finish, 1500);
  });
  apiProcess = undefined;
  apiStopping = false;
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 720,
    minHeight: 560,
    title: APP_NAME,
    backgroundColor: '#0d0f10',
    icon: appIconPath(),
    ...(process.platform === 'darwin'
      ? {
          titleBarStyle: 'hiddenInset' as const,
          trafficLightPosition: { x: 16, y: 10 },
        }
      : {
          titleBarStyle: 'hidden' as const,
          titleBarOverlay: {
            color: '#0d0f10',
            symbolColor: '#d6ff4b',
            height: 34,
          },
        }),
    webPreferences: {
      additionalArguments: [`--aics-api-port=${apiPort}`],
      preload: path.join(currentDir, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // Keep the renderer sandboxed. The preload is compiled as CommonJS so
      // Electron can execute it in this sandbox without dropping the bridge.
      sandbox: true,
    },
  });

  if (isDev) window.loadURL('http://localhost:5173');
  else window.loadFile(path.join(projectRoot, 'dist/renderer/index.html'));
  window.on('closed', () => {
    // The invisible delivery window must not keep the Windows app alive
    // after its last visible window closes.
    if (process.platform !== 'darwin' && visibleWindows().length === 0) app.quit();
  });
}

let deliveryWindow: BrowserWindow | undefined;
function visibleWindows() { return BrowserWindow.getAllWindows().filter(window => window !== deliveryWindow && !isHtmlExportWindow(window)); }
let appUpdates: AppUpdates | undefined;
let updateTimer: ReturnType<typeof setTimeout> | undefined;
function registerAppUpdates() {
  const reason = updateDisabledReason(isDev, process.platform, existsSync(path.join(process.resourcesPath, 'app-update.yml')));
  appUpdates = new AppUpdates(updaterPackage.autoUpdater, app.getVersion(), reason, state => {
    for (const window of visibleWindows()) window.webContents.send('app-update:state', state);
  });
  for (const action of ['state', 'check', 'download', 'install'] as const) {
    ipcMain.handle(`app-update:${action}`, event => {
      const expected = isDev ? 'http://localhost:5173' : pathToFileURL(path.join(projectRoot, 'dist/renderer/index.html')).href;
      const url = event.senderFrame?.url || '';
      if (!trustedUpdateSender(url, expected, isDev, event.senderFrame === event.sender.mainFrame, visibleWindows().some(window => window.webContents === event.sender))) throw new Error('Unauthorized update request');
      return action === 'state' ? appUpdates!.snapshot() : appUpdates![action]();
    });
  }
  if (!reason) updateTimer = setTimeout(() => { void appUpdates?.check(); }, 12000);
}
function createDeliveryWindow() {
  if (appIsQuitting || deliveryWindow && !deliveryWindow.isDestroyed()) return;
  const window = new BrowserWindow({ show: false, webPreferences: {
    additionalArguments: [`--aics-api-port=${apiPort}`], preload: path.join(currentDir, 'preload.js'),
    contextIsolation: true, nodeIntegration: false, sandbox: true, backgroundThrottling: false,
  } });
  deliveryWindow = window;
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('render-process-gone', () => { window.destroy(); });
  window.webContents.on('did-fail-load', () => { if (!appIsQuitting) setTimeout(() => { if (!window.isDestroyed()) window.reload(); },3000); });
  window.on('closed', () => { deliveryWindow = undefined; if (!appIsQuitting) setTimeout(createDeliveryWindow, 3000); });
  if (isDev) void window.loadURL('http://localhost:5173/?deliveryWorker=1');
  else void window.loadFile(path.join(projectRoot, 'dist/renderer/index.html'), { query: { deliveryWorker: '1' } });
}

ipcMain.handle('window:set-titlebar-theme', (event, theme: 'dark' | 'light') => {
  if (process.platform === 'darwin') return;
  const target = BrowserWindow.fromWebContents(event.sender);
  target?.setTitleBarOverlay({
    color: theme === 'light' ? '#eef1ec' : '#0d0f10',
    symbolColor: theme === 'light' ? '#38523d' : '#d6ff4b',
    height: 34,
  });
});

ipcMain.handle('app:set-icon-appearance', (_event, preference: unknown) => {
  // IPC payloads are untrusted even with context isolation enabled. Ignore an
  // invalid value instead of allowing a renderer mistake to select a missing
  // file or alter the native app state.
  if (!isAppAppearancePreference(preference)) return;
  appAppearancePreference = preference;
  syncNativeAppIcon();
});

ipcMain.handle('workspace:open-folder', async () => {
  if (!workspaceRoot) throw new Error('Workspace is not ready');
  const error = await shell.openPath(workspaceRoot);
  if (error) throw new Error(error);
});
ipcMain.handle('workspace:clear-cache', async event => {
  await event.sender.session.clearCache();
});
async function changeWorkspaceLocation(mode: WorkspaceChangeMode) {
  if (mode !== 'migrate' && mode !== 'existing') throw new Error('无效的存储位置操作。');
  if (changingWorkspace) throw new Error('正在更改存储位置，请稍候。');
  if (process.env.AICS_SKIP_SIDECAR === '1' || process.env.AICS_WORKSPACE_ROOT?.trim()) {
    throw new Error('当前工作区由启动配置指定，请移除 AICS_WORKSPACE_ROOT 或外部服务配置后再使用此功能。');
  }
  changingWorkspace = true;
  const previousRoot = workspaceRoot;
  let stopped = false;
  let migrationChild: ChildProcessWithoutNullStreams | undefined;
  try {
    const result = await dialog.showOpenDialog({ title: mode === 'migrate' ? '选择空文件夹存放当前数据' : '选择已有 MxinspireX 工作区', properties: ['openDirectory', 'createDirectory'] });
    if (result.canceled || !result.filePaths[0]) return null;
    const { to } = await validateWorkspaceDestination(previousRoot, result.filePaths[0], mode);
    const confirmation = await dialog.showMessageBox({ type: 'question', title: '更改数据存储位置',
      message: mode === 'migrate' ? '复制当前工作区到新位置并重启？' : '切换到所选工作区并重启？',
      detail: `${previousRoot}\n→ ${to}\n\n${mode === 'migrate' ? '原目录会保留，不覆盖目标文件。' : '不会合并或搬迁当前数据，原目录会保留。'}请先保存正在编辑的内容。`,
      buttons: ['取消', '继续并重启'], defaultId: 0, cancelId: 0 });
    if (confirmation.response !== 1) return null;
    const activity = await fetch(`http://127.0.0.1:${apiPort}/api/tasks/activity`, { signal: AbortSignal.timeout(5000) });
    const mascot = await fetch(`http://127.0.0.1:${apiPort}/api/mascot`, { signal: AbortSignal.timeout(5000) });
    if (!activity.ok || !mascot.ok) throw new Error('无法确认任务状态，请待本地服务恢复后重试。');
    const tasks = await activity.json() as Array<{ status: string }>;
    const appearance = await mascot.json() as { latest?: { status: string } };
    if (tasks.some(task => ['queued', 'pending', 'running'].includes(task.status)) || ['queued', 'running'].includes(appearance.latest?.status || '')) {
      throw new Error('仍有任务运行或排队，请等待完成或停止后再更改存储位置。');
    }
    const child = apiProcess;
    if (!child) throw new Error('本地服务未就绪，请稍后重试。');
    migrationChild = child;
    await stopApiSidecar();
    stopped = true;
    // stopApiSidecar has a short UI timeout; migration must wait for real exit.
    if (child.exitCode === null && child.signalCode === null) {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('本地服务尚未退出，未开始迁移，请重启应用后重试。')), 15000);
        child.once('close', () => { clearTimeout(timeout); resolve(); });
      });
    }
    if (mode === 'migrate') await copyWorkspace(previousRoot, to);
    else await validateWorkspaceDestination(previousRoot, to, mode);
    persistWorkspaceRoot(to);
    workspaceRoot = to;
    app.relaunch();
    app.quit();
    return to;
  } catch (error) {
    workspaceRoot = previousRoot;
    if (stopped) {
      if (migrationChild && migrationChild.exitCode === null && migrationChild.signalCode === null) apiProcess = migrationChild;
      else startApiSidecar();
    }
    throw error;
  } finally { changingWorkspace = false; }
}
ipcMain.handle('workspace:change-location', (_event, mode: WorkspaceChangeMode) => changeWorkspaceLocation(mode));
// Retain the old bridge, but route it through the same guarded switch.
ipcMain.handle('workspace:choose-folder', () => changeWorkspaceLocation('existing'));

ipcMain.handle('runtime-components:status', () => runtimeComponentManager?.status() || []);

ipcMain.handle('runtime-components:install', async (_event, id: unknown) => {
  if (typeof id !== 'string') throw new Error('能力组件 ID 无效。');
  const result = await runtimeComponentManager.install(id);
  if (!result.cancelled) {
    await stopApiSidecar();
    startApiSidecar();
  }
  return result;
});

let scheduleNotificationTimer: ReturnType<typeof setInterval> | undefined;
let scheduleNotificationPolling = false;
async function pollScheduleNotifications() {
  if (scheduleNotificationPolling || appIsQuitting || !Notification.isSupported()) return;
  scheduleNotificationPolling = true;
  try {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/schedule-notifications/desktop`, { method: 'POST', signal: AbortSignal.timeout(4000) });
    if (!response.ok) return;
    const notices = await response.json() as Array<{ id: string; title: string; body: string; projectId?: string | null }>;
    for (const notice of notices) {
      const notification = new Notification({ title: notice.title, body: notice.body.slice(0, 240) });
      notification.on('click', () => {
        let target = visibleWindows()[0];
        if (!target) { createWindow(); target = visibleWindows()[0]; }
        if (!target) return;
        if (target.isMinimized()) target.restore();
        target.show(); target.focus();
        const openResult = () => target?.webContents.send('schedule:open', notice.projectId || null);
        if (target.webContents.isLoading()) target.webContents.once('did-finish-load', openResult);
        else openResult();
        void fetch(`http://127.0.0.1:${apiPort}/api/schedule-notifications/${encodeURIComponent(notice.id)}/read`, { method: 'POST', signal: AbortSignal.timeout(4000) }).catch(() => {});
      });
      notification.show();
    }
  } catch { /* The sidecar may be starting or switching workspaces. */ }
  finally { scheduleNotificationPolling = false; }
}

app.whenReady().then(async () => {
  if (!ownsAppInstance) return;
  // Keep the development renderer opened in a regular browser and the
  // Electron renderer on the same local API. Browser pages cannot receive
  // Electron's dynamically injected port, so both modes share the canonical
  // 8765 endpoint when it is available.
  if (process.env.AICS_SKIP_SIDECAR !== '1') apiPort = await chooseApiPort(8765, !isDev);
  workspaceRoot = loadWorkspaceRoot();
  runtimeComponentManager = new RuntimeComponentManager(projectRoot, app.getPath('userData'));
  setTestingLogDirectory(workspaceRoot);
  app.setName(APP_NAME);
  nativeTheme.on('updated', syncNativeAppIcon);
  const icon = dockIconPath();
  setDockIcon(icon);
  startApiSidecar();
  registerAppUpdates();
  createWindow();
  createDeliveryWindow();
  scheduleNotificationTimer = setInterval(() => { void pollScheduleNotifications(); }, 5000);
  syncNativeAppIcon();
  app.on('activate', () => {
    if (visibleWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  appIsQuitting = true;
  if (updateTimer) clearTimeout(updateTimer);
  if (scheduleNotificationTimer) clearInterval(scheduleNotificationTimer);
  if (apiRestartTimer) {
    clearTimeout(apiRestartTimer);
    apiRestartTimer = undefined;
  }
  if (apiProcess && !apiProcess.killed) apiProcess.kill('SIGTERM');
});
