import { existsSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function devWorkspace(root, env = process.env) {
  if (env.AICS_WORKSPACE_ROOT?.trim()) return path.resolve(root, env.AICS_WORKSPACE_ROOT.trim());
  const config = path.join(root, '.local', 'dev-api.json');
  if (!existsSync(config)) return path.join(root, 'services', 'api', 'workspace-data');
  const { workspaceRoot } = JSON.parse(readFileSync(config, 'utf8'));
  if (typeof workspaceRoot !== 'string' || !workspaceRoot.trim()) throw Error('本机开发配置缺少 workspaceRoot，请检查 .local/dev-api.json');
  const workspace = path.resolve(root, workspaceRoot);
  if (!existsSync(path.join(workspace, 'catalog.sqlite'))) throw Error(`已保存的工作区不可用：${workspace}。请恢复该目录或修正 .local/dev-api.json；不会自动切换到空工作区。`);
  return workspace;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const workspaceRoot = devWorkspace(root);
  if (process.argv.includes('--print-workspace')) console.log(workspaceRoot);
  else {
    console.log(`[api] 工作区：${workspaceRoot}`);
    const child = spawn('uv', ['run', '--directory', path.join(root, 'services', 'api'), 'python', '-m', 'app.server', '--reload', '--host', '127.0.0.1', '--port', '8765'], {
      cwd: root, stdio: 'inherit', env: { ...process.env, AICS_WORKSPACE_ROOT: workspaceRoot, UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(root, '.tmp', 'uv-cache') },
    });
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
    child.on('error', error => { console.error(error.message); process.exitCode = 1; });
    child.on('exit', code => { process.exitCode = code ?? 0; });
  }
}
