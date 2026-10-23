// Offline provider fixtures + real Electron/SQLite flows. Never calls paid models.
import { spawn, execFileSync } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdirSync, openSync, closeSync, writeFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(root, '.tmp', `agent-release-${Date.now()}`);
mkdirSync(output, { recursive: true });
const python = process.env.AICS_TEST_PYTHON || path.join(root, 'services/api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const npm = process.env.npm_execpath;
if (!existsSync(python) || !npm) throw new Error('Run npm run verify:agent-release with services/api/.venv installed (or set AICS_TEST_PYTHON).');
const env = { ...process.env, AICS_TEST_MODE: '1', AICS_WORKSPACE_ROOT: path.join(output, 'workspace'), PYTHONUTF8: '1' };
const report = { passed: false, providerMode: 'fixtures', steps: [] };
let api;
const stopApi = () => {
  if (!api || api.exitCode !== null) return;
  if (process.platform === 'win32') {
    try { execFileSync('taskkill', ['/pid', String(api.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' }); } catch { /* Already exited. */ }
  } else api.kill('SIGTERM');
};
async function run(name, command, args, cwd = root) {
  console.log(`\n[release check] ${name}`);
  const started = Date.now();
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: 'inherit', windowsHide: true });
    child.once('error', reject);
    child.once('exit', code => {
      report.steps.push({ name, passed: code === 0, durationMs: Date.now() - started });
      code === 0 ? resolve() : reject(new Error(`${name} failed (${code})`));
    });
  });
}
const npmRun = name => run(name, process.execPath, [npm, 'run', name]);
try {
  await npmRun('typecheck');
  await npmRun('test');
  await run('backend recovery and canvas', python, ['-X', 'utf8', '-m', 'pytest', '-q', '--basetemp', path.join(output, 'pytest'),
    'tests/test_canvas_placement.py', 'tests/test_canvas_node_tasks.py', 'tests/test_task_interaction_upgrade.py', 'tests/test_cad_worker_exit.py'], path.join(root, 'services/api'));
  const port = await new Promise((resolve, reject) => {
    const socket = createServer();
    socket.once('error', reject);
    socket.listen(0, '127.0.0.1', () => { const value = socket.address().port; socket.close(() => resolve(value)); });
  });
  env.AICS_TEST_API_URL = `http://127.0.0.1:${port}`;
  const log = openSync(path.join(output, 'api.log'), 'a');
  try {
    api = spawn(python, ['-X', 'utf8', '-m', 'app.server', '--host', '127.0.0.1', '--port', String(port)],
      { cwd: path.join(root, 'services/api'), env, stdio: ['ignore', log, log], windowsHide: true });
  } finally { closeSync(log); }
  let startupError;
  api.once('error', error => { startupError = error; });
  const deadline = Date.now() + 60000;
  while (true) {
    if (startupError) throw startupError;
    if (api.exitCode !== null) throw new Error('Isolated API exited; see api.log');
    try { if ((await fetch(`${env.AICS_TEST_API_URL}/health`, { signal: AbortSignal.timeout(1500) })).ok) break; } catch { /* Wait for startup. */ }
    if (Date.now() > deadline) throw new Error('Isolated API did not start; see api.log');
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  await npmRun('test:canvas-edge-persistence');
  await npmRun('test:node-composer');
  await npmRun('test:task-recovery');
  await npmRun('test:canvas-workspace');
  report.passed = true;
} catch (error) {
  report.error = String(error);
  console.error(error);
  process.exitCode = 1;
} finally {
  stopApi();
  writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(`Release check report: ${output}`);
}
