import { contextBridge, ipcRenderer } from 'electron';

const portArgument = process.argv.find((argument) => argument.startsWith('--aics-api-port='));
const port = Number(portArgument?.split('=')[1] || 8765);
const apiPort = Number.isInteger(port) && port > 0 && port <= 65535 ? port : 8765;

contextBridge.exposeInMainWorld('studio', {
  apiBaseUrl: `http://127.0.0.1:${apiPort}`,
  isDesktop: true,
  exportTestingLogs: () => ipcRenderer.invoke('testing:export-logs') as Promise<string | null>,
  exportHtmlPdf: (input: { html: string; width: number }) => ipcRenderer.invoke('canvas:export-html-pdf', input) as Promise<Uint8Array>,
  onScheduleNotification: (listener: (projectId: string | null) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, projectId: unknown) => listener(typeof projectId === 'string' ? projectId : null);
    ipcRenderer.on('schedule:open', handler);
    return () => ipcRenderer.removeListener('schedule:open', handler);
  },
  chooseWorkspaceFolder: () => ipcRenderer.invoke('workspace:choose-folder') as Promise<string | null>,
  runtimeComponents: () => ipcRenderer.invoke('runtime-components:status') as Promise<Array<{ id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' }>>,
  installRuntimeComponent: (id: string) => ipcRenderer.invoke('runtime-components:install', id) as Promise<{ cancelled: boolean; components: Array<{ id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' }> }>,
  setTitleBarTheme: (theme: 'dark' | 'light') => ipcRenderer.invoke('window:set-titlebar-theme', theme) as Promise<void>,
  setAppIconAppearance: (preference: 'system' | 'dark' | 'light') => ipcRenderer.invoke('app:set-icon-appearance', preference) as Promise<void>,
});
