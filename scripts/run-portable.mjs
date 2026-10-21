import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = path.join(root, 'services', 'api');
const python = path.join(apiDir, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const vite = path.join(root, 'node_modules/vite/bin/vite.js');
const stamp = path.join(root, '.local/portable-setup.json');
const { values } = parseArgs({ options: {
  'setup-only': { type: 'boolean' }, 'no-install': { type: 'boolean' },
  smoke: { type: 'boolean' }, workspace: { type: 'string' }, help: { type: 'boolean' },
} });
const children = [];
let stopping = false;
let smokeWorkspace;

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', ...options });
  if (result.error || result.status !== 0) {
    throw new Error(`执行失败：${command} ${args.join(' ')}。${result.error?.message || `退出码 ${result.status}`}`);
  }
}

function setup() {
  const hash = createHash('sha256').update(`${process.platform}/${process.arch}/${process.versions.node.split('.')[0]}`);
  for (const file of ['package.json', 'package-lock.json', 'services/api/pyproject.toml', 'services/api/uv.lock']) {
    hash.update(readFileSync(path.join(root, file)));
  }
  const fingerprint = hash.digest('hex');
  let installed;
  try { installed = JSON.parse(readFileSync(stamp, 'utf8')); } catch { /* First installation. */ }
  if (installed?.fingerprint === fingerprint && existsSync(python) && existsSync(vite)
    && existsSync(path.join(root, 'node_modules/@openai/agents/package.json')) && !values['setup-only']) return;
  const uv = process.env.AICS_UV || 'uv';
  const check = spawnSync(uv, ['--version'], { encoding: 'utf8' });
  if (check.error || check.status !== 0) {
    throw new Error('未找到 uv。请先安装 uv 并重新打开终端；给 Codex 的完整步骤见 RUN_IN_CODEX.md。可用 AICS_UV 指定 uv 可执行文件路径。');
  }
  mkdirSync(path.dirname(stamp), { recursive: true });
  console.log('[setup] 根据 package-lock.json 安装 JavaScript 依赖……');
  // Ignore optional Electron downloads for web development. npm.cmd needs the
  // Windows command interpreter; all arguments here are fixed literals.
  const npmArgs = ['ci', '--ignore-scripts', '--no-audit', '--no-fund'];
  if (process.env.npm_execpath?.endsWith('.js')) run(process.execPath, [process.env.npm_execpath, ...npmArgs]);
  else run(process.platform === 'win32' ? 'npm.cmd' : 'npm', npmArgs, { shell: process.platform === 'win32' });
  console.log('[setup] 安装 Python 3.12 与锁定依赖（含 CAD、媒体及开发工具）……');
  run(uv, ['sync', '--project', apiDir, '--locked', '--python', '3.12'], {
    env: { ...process.env, UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(root, '.tmp/uv-cache'),
      UV_PROJECT_ENVIRONMENT: path.join(apiDir, '.venv') },
  });
  writeFileSync(stamp, JSON.stringify({ fingerprint, installedAt: new Date().toISOString() }, null, 2));
  console.log('[setup] 依赖安装完成。');
}

async function freePort(preferred) {
  const listen = port => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => {
      const selected = server.address().port;
      server.close(error => error ? reject(error) : resolve(selected));
    });
  });
  try { return await listen(preferred); }
  catch (error) {
    if (error.code !== 'EADDRINUSE') throw error;
    return listen(0);
  }
}

async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  await Promise.all(children.map(({ child, done }) => {
    if (child.exitCode !== null || child.signalCode !== null) return done;
    child.kill('SIGTERM');
    const timeout = setTimeout(() => child.kill('SIGKILL'), 8000);
    return done.finally(() => clearTimeout(timeout));
  }));
  if (smokeWorkspace) rmSync(smokeWorkspace, { recursive: true, force: true });
}

function start(label, command, args, options) {
  const child = spawn(command, args, { cwd: root, stdio: 'inherit', ...options });
  const entry = { child, exited: false, error: undefined };
  entry.done = new Promise(resolve => {
    child.once('error', error => {
      entry.error = error;
      entry.exited = true;
      resolve();
      if (!stopping) { console.error(`[${label}] ${error.message}`); void stop(1); }
    });
    child.once('exit', (code, signal) => {
      entry.exited = true;
      resolve();
      if (!stopping) {
        console.error(`[${label}] 已退出 (${code ?? signal})`);
        void stop(code || 1);
      }
    });
  });
  children.push(entry);
  return entry;
}

async function waitReady(url, entry, validate) {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    if (stopping || entry.exited) throw entry.error || new Error(`服务提前退出：${url}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (response.ok && await validate(response)) return;
    } catch { /* Startup is still in progress. */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`等待服务就绪超时：${url}`);
}

async function main() {
  if (values.help) {
    console.log('node scripts/run-portable.mjs [--setup-only | --smoke] [--no-install] [--workspace <path>]\n默认安装依赖并启动网页开发版；--smoke 使用临时空工作区检查后退出，不调用模型。');
    return;
  }
  if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('需要 Node.js 22 或更高版本（建议 22 / 24）。');
  if (values.smoke && values.workspace) throw new Error('--smoke 固定使用临时空工作区，不能指定 --workspace。');
  if (!values['no-install']) setup();
  if (!existsSync(python) || !existsSync(vite)) throw new Error('依赖不完整，请先运行 npm run setup:portable。');
  if (values['setup-only']) return;

  // Never read another computer's saved desktop or development workspace.
  const workspace = values.smoke
    ? (smokeWorkspace = mkdtempSync(path.join(tmpdir(), 'langju-portable-smoke-')))
    : path.resolve(root, values.workspace || '.local/portable-workspace');
  const apiPort = await freePort(values.smoke ? 0 : 8765);
  let webPort = await freePort(values.smoke ? 0 : 5173);
  while (webPort === apiPort) webPort = await freePort(0);
  const apiUrl = `http://127.0.0.1:${apiPort}`;
  const webUrl = `http://127.0.0.1:${webPort}`;
  const env = {
    ...process.env, AICS_WORKSPACE_ROOT: workspace, AICS_API_PORT: String(apiPort),
    AICS_DEV_WEB_ORIGIN: webUrl,
    AICS_AGENT_TOOL_GATEWAY_URL: apiUrl, AICS_AGENT_WORKER: path.join(apiDir, 'app/openai_agent_worker.mjs'),
    AICS_NODE: process.execPath, AICS_NODE_RUN_AS_NODE: '0',
    PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1',
    VITE_API_BASE_URL: apiUrl,
    // Smoke checks only read health, projects and local frontend modules.
    ...(values.smoke ? { AICS_TEST_MODE: '1' } : {}),
  };
  console.log(`[local] 工作区：${workspace}`);
  const api = start('api', python, ['-X', 'utf8', '-B', '-m', 'app.server', '--host', '127.0.0.1', '--port', String(apiPort)], { cwd: apiDir, env });
  await waitReady(`${apiUrl}/health`, api, async response => {
    const health = await response.json();
    return health.status === 'ok' && health.service === 'aics-api';
  });
  const web = start('web', process.execPath, [vite, '--config', path.join(root, 'apps/renderer/vite.config.ts'),
    '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'], { env });
  await waitReady(webUrl, web, async response => (await response.text()).includes('/src/main.ts'));
  if (values.smoke) {
    const projectResponse = await fetch(`${apiUrl}/api/projects`, { headers: { Origin: webUrl } });
    if (projectResponse.headers.get('access-control-allow-origin') !== webUrl) throw new Error('动态网页端口的跨域访问未放行。');
    const preflight = await fetch(`${apiUrl}/api/projects`, { method: 'OPTIONS', headers: {
      Origin: webUrl, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type',
    } });
    if (!preflight.ok || preflight.headers.get('access-control-allow-origin') !== webUrl) throw new Error('浏览器写请求的跨域预检失败。');
    const remoteOrigin = await fetch(`${apiUrl}/api/projects`, { headers: { Origin: 'https://untrusted.invalid' } });
    if (remoteOrigin.headers.has('access-control-allow-origin')) throw new Error('不应放行远程网页来源。');
    const projects = await projectResponse.json();
    if (!Array.isArray(projects) || projects.length !== 0) throw new Error('临时工作区不是空项目列表。');
    const module = await fetch(`${webUrl}/src/main.ts`);
    if (!module.ok || !(await module.text()).includes('createApp')) throw new Error('前端入口转换失败。');
    const viteEnv = await fetch(`${webUrl}/src/App.vue`);
    if (!viteEnv.ok || !(await viteEnv.text()).includes(apiUrl)) throw new Error('前端 API 地址未正确绑定。');
    console.log('PORTABLE_SMOKE_OK：API、空工作区、前端入口和 API 地址检查通过；未调用模型。');
    await stop();
  } else {
    console.log(`\nMxinspireX 已启动：${webUrl}\nAPI：${apiUrl}\n在浏览器打开以上地址，按 Ctrl+C 停止。首次生成前在设置中配置自己的 API Key。\n修改 Python 后端后请重启本命令。`);
  }
}

for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { void stop(); });
main().catch(async error => { console.error(error.message); await stop(1); });
