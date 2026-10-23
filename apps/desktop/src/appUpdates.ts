export function updateDisabledReason(isDev: boolean, platform: string, hasInstallerFeed: boolean) {
  return isDev ? '开发模式不检查更新。' : platform !== 'win32' ? '此平台暂未启用自动更新，请使用发布页安装包。'
    : !hasInstallerFeed ? '便携版不支持安装更新，请使用发布页安装包。' : undefined;
}

export function trustedUpdateSender(url: string, expected: string, isDev: boolean, isMainFrame: boolean, isAppWindow: boolean) {
  if (!isMainFrame || !isAppWindow) return false;
  try { return isDev ? new URL(url).origin === expected : url.split(/[?#]/)[0] === expected; }
  catch { return false; }
}

export interface UpdateState {
  status: 'disabled' | 'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'installing' | 'error';
  currentVersion: string;
  latestVersion?: string;
  notes?: string;
  percent: number;
  error?: string;
  retry?: 'check' | 'download' | 'restart';
  reason?: string;
  revision: number;
}

export interface UpdateDriver {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  allowPrerelease: boolean;
  allowDowngrade: boolean;
  on(event: string, listener: (...args: any[]) => void): unknown;
  checkForUpdates(): Promise<unknown>;
  downloadUpdate(): Promise<unknown>;
  quitAndInstall(isSilent?: boolean, isForceRunAfter?: boolean): void;
}

// One controller per main process; neither UI remounts nor repeated clicks add listeners.
export class AppUpdates {
  private state: UpdateState;
  private pending = false;
  constructor(private driver: UpdateDriver, version: string, reason: string | undefined,
    private publish: (state: UpdateState) => void) {
    this.state = { status: reason ? 'disabled' : 'idle', currentVersion: version, percent: 0, reason, revision: 0 };
    driver.autoDownload = false;
    driver.autoInstallOnAppQuit = false;
    driver.allowPrerelease = false;
    driver.allowDowngrade = false;
    driver.on('update-available', info => {
      if (this.state.status !== 'checking') return;
      const notes = typeof info.releaseNotes === 'string' ? info.releaseNotes
        : Array.isArray(info.releaseNotes) ? info.releaseNotes.map((item: { note?: string }) => item.note || '').join('\n') : '';
      this.set({ status: 'available', latestVersion: info.version, notes: notes.slice(0, 30000) });
    });
    driver.on('update-not-available', () => {
      if (this.state.status === 'checking') this.set({ status: 'idle', latestVersion: undefined, notes: undefined });
    });
    driver.on('download-progress', progress => {
      if (this.state.status === 'downloading') this.set({ percent: Math.max(0, Math.min(100, Number(progress.percent) || 0)) });
    });
    driver.on('update-downloaded', () => {
      if (this.state.status === 'downloading') this.set({ status: 'downloaded', percent: 100 });
    });
    driver.on('error', error => this.fail(error));
  }
  snapshot() { return { ...this.state }; }
  private set(patch: Partial<UpdateState>) {
    this.state = { ...this.state, ...patch, revision: this.state.revision + 1 };
    this.publish(this.snapshot());
  }
  private fail(error: unknown) {
    if (!['checking', 'downloading', 'installing'].includes(this.state.status)) return;
    const retry = this.state.status === 'checking' ? 'check' : this.state.status === 'installing' ? 'restart' : 'download';
    const detail = String(error);
    const message = retry === 'restart' ? '安装程序启动失败，请关闭软件后重新打开，再尝试更新。'
      : /403|429|rate.?limit/i.test(detail) ? '更新服务暂时限流，请稍后重试。'
      : /404|no published|latest.*yml/i.test(detail) ? '尚未找到当前平台的正式更新包，请稍后重试。'
      : /sha512|checksum|signature/i.test(detail) ? '更新包校验失败，请重新下载；仍失败时请联系发布者。'
      : '检查或下载更新失败，请检查网络后重试。';
    this.set({ status: 'error', error: message, retry });
  }
  async check() {
    if (this.pending || !['idle', 'error'].includes(this.state.status) || this.state.retry && this.state.retry !== 'check') return this.snapshot();
    this.pending = true;
    this.set({ status: 'checking', error: undefined, retry: undefined });
    try { await this.driver.checkForUpdates(); } catch (error) { this.fail(error); }
    finally { this.pending = false; }
    return this.snapshot();
  }
  async download() {
    if (this.pending || !(this.state.status === 'available' || this.state.status === 'error' && this.state.retry === 'download')) return this.snapshot();
    this.pending = true;
    this.set({ status: 'downloading', percent: 0, error: undefined, retry: undefined });
    try { await this.driver.downloadUpdate(); } catch (error) { this.fail(error); }
    finally { this.pending = false; }
    return this.snapshot();
  }
  install() {
    if (this.pending || this.state.status !== 'downloaded') return this.snapshot();
    this.set({ status: 'installing' });
    try { this.driver.quitAndInstall(false, true); } catch (error) { this.fail(error); }
    return this.snapshot();
  }
}
