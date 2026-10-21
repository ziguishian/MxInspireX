import { execFileSync } from 'node:child_process';
import path from 'node:path';

export function runningReleaseProcesses(releaseRoot, processList) {
  // This guard reads macOS `ps` paths, including when tested on Windows.
  const prefix = path.posix.resolve(releaseRoot) + '/';
  return processList.split('\n').flatMap(line => {
    const match = line.trim().match(/^(\d+)\s+(.+)$/);
    return match && match[2].startsWith(prefix) ? [{ pid: Number(match[1]), command: match[2] }] : [];
  });
}

export function assertReleaseNotRunning(releaseRoot, readProcesses = () => execFileSync('/bin/ps', ['-axo', 'pid=,command='], { encoding: 'utf8' })) {
  let processes;
  try { processes = runningReleaseProcesses(releaseRoot, readProcesses()); }
  catch { throw new Error('无法确认应用是否已退出，已停止覆盖现有安装包。请确认本地进程状态后重新打包。'); }
  if (processes.length) throw new Error(`发布目录中的应用或后台服务仍在运行（PID ${processes.map(process => process.pid).join(', ')}）。请先退出应用并等待后台服务结束，再重新打包；不能删除正在使用的运行目录。`);
}
