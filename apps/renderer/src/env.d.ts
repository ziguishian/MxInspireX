/// <reference types="vite/client" />

interface Window {
  studio: {
    apiBaseUrl: string;
    isDesktop?: boolean;
    showAppMenu?: (menu: string) => Promise<string | null>;
    updates?: {
      state: () => Promise<import('../../desktop/src/appUpdates').UpdateState>;
      check: () => Promise<import('../../desktop/src/appUpdates').UpdateState>;
      download: () => Promise<import('../../desktop/src/appUpdates').UpdateState>;
      install: () => Promise<import('../../desktop/src/appUpdates').UpdateState>;
      subscribe: (listener: (state: import('../../desktop/src/appUpdates').UpdateState) => void) => () => void;
    };
    openWorkspaceFolder?: () => Promise<void>;
    clearAppCache?: () => Promise<void>;
    changeWorkspaceLocation?: (mode: 'migrate' | 'existing') => Promise<string | null>;
    exportTestingLogs?: () => Promise<string | null>;
    exportHtmlPdf?: (input: { html: string; width: number }) => Promise<Uint8Array>;
    onScheduleNotification?: (listener: (projectId: string | null) => void) => () => void;
    chooseWorkspaceFolder: () => Promise<string | null>;
    runtimeComponents?: () => Promise<Array<{ id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' }>>;
    installRuntimeComponent?: (id: string) => Promise<{ cancelled: boolean; components: Array<{ id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' }> }>;
    setTitleBarTheme?: (theme: { background: string; foreground: string }) => Promise<void>;
    setAppIconAppearance?: (preference: 'system' | 'dark' | 'light') => Promise<void>;
  };
}
