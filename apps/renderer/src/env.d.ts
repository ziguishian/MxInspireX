/// <reference types="vite/client" />

interface Window {
  studio: {
    apiBaseUrl: string;
    isDesktop?: boolean;
    exportTestingLogs?: () => Promise<string | null>;
    exportHtmlPdf?: (input: { html: string; width: number }) => Promise<Uint8Array>;
    onScheduleNotification?: (listener: (projectId: string | null) => void) => () => void;
    chooseWorkspaceFolder: () => Promise<string | null>;
    runtimeComponents?: () => Promise<Array<{ id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' }>>;
    installRuntimeComponent?: (id: string) => Promise<{ cancelled: boolean; components: Array<{ id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' }> }>;
    setTitleBarTheme?: (theme: 'dark' | 'light') => Promise<void>;
    setAppIconAppearance?: (preference: 'system' | 'dark' | 'light') => Promise<void>;
  };
}
