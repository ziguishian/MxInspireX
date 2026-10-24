import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

export const workerName = 'openai_agent_worker.mjs';
export const runtimeManifestName = 'agent-runtime-build.json';
export const runtimeDataDirectories = ['builtin_skills', 'print_fonts', 'web_frameworks'];

export function fileDigest(filename) {
  return createHash('sha256').update(readFileSync(filename)).digest('hex');
}

export function runtimeSourceDigest(root) {
  const files = ['scripts/build-sidecar.mjs', 'scripts/agent-runtime-build.mjs', 'services/api/sidecar_entry.py', 'services/api/pyproject.toml', 'services/api/uv.lock', 'package-lock.json', `services/api/app/${workerName}`];
  const visit = (relativeDir) => {
    for (const entry of readdirSync(path.join(root, relativeDir), { withFileTypes: true })) {
      if (entry.name.startsWith('.') || entry.name === '__pycache__') continue;
      const relativePath = path.join(relativeDir, entry.name);
      if (entry.isDirectory()) visit(relativePath);
      else if (runtimeDataDirectories.some(dir => relativePath.startsWith(path.join('services/api/app', dir) + path.sep))
        || entry.name.endsWith('.py') || entry.name.endsWith('.mjs') && entry.name !== workerName) files.push(relativePath);
    }
  };
  visit('services/api/app');
  const hash = createHash('sha256');
  for (const filename of files.filter((file) => existsSync(path.join(root, file))).sort()) {
    hash.update(filename).update('\0').update(readFileSync(path.join(root, filename))).update('\0');
  }
  return hash.digest('hex');
}

export async function bundleAgentWorker(root, outfile) {
  await build({
    entryPoints: [path.join(root, 'services/api/app', workerName)],
    outfile,
    bundle: true, platform: 'node', format: 'esm', target: 'node22',
    banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);" },
  });
  verifyStandaloneWorker(outfile);
}

export function verifyStandaloneWorker(workerPath) {
  // Resolve dependencies from a fresh directory outside the checkout. The
  // intercepted transport completes a real SDK run without a key or network.
  const smokeDir = mkdtempSync(path.join(tmpdir(), 'langju-worker-check-'));
  try {
    const isolatedWorker = path.join(smokeDir, workerName);
    cpSync(workerPath, isolatedWorker);
    const preload = `
      globalThis.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url ?? String(input);
        if (url.endsWith('/agent-tools/delivery_snapshot')) return Response.json({mode:'canvas_preview_once',nodes:[],images:[]});
        if (url !== 'https://worker-smoke.invalid/v1/chat/completions') throw new Error('Unexpected smoke transport: ' + url);
        const request = JSON.parse(init?.body ?? await input.text());
        const identity = request.messages.filter(item => ['system', 'developer'].includes(item.role)).map(item => item.content).join(' ');
        if (!identity.includes('MxinspireX') || !identity.includes('灵矩绘境') || identity.includes('你叫小居')) {
          throw new Error('Packaged worker contains an outdated Agent identity');
        }
        const content = 'packaged-agent-ready';
        const chunk = (delta, finish_reason) => 'data: ' + JSON.stringify({
          id: 'worker-smoke', object: 'chat.completion.chunk', created: 0, model: 'worker-smoke',
          choices: [{ index: 0, delta, finish_reason }]
        }) + '\\n\\n';
        return new Response(chunk({ role: 'assistant', content }, null) + chunk({}, 'stop') + 'data: [DONE]\\n\\n', {
          status: 200, headers: { 'content-type': 'text/event-stream' }
        });
      };
      await import(${JSON.stringify(pathToFileURL(isolatedWorker).href)});
    `;
    const result = spawnSync(process.execPath, ['--input-type=module', '--eval', preload], {
      cwd: smokeDir, encoding: 'utf8', timeout: 30000,
      env: { ...process.env, NODE_PATH: '', NODE_OPTIONS: '' },
      input: JSON.stringify({
        apiKey: 'worker-smoke-only', model: 'worker-smoke', baseUrl: 'https://worker-smoke.invalid/v1',
        context: { brief: '检查运行环境', constraints: { executionPolicyVersion: 2 } },
      }),
    });
    const events = (result.stdout || '').split('\n').filter((line) => line.startsWith('{')).map((line) => JSON.parse(line));
    const final = events.find((event) => event.type === 'result')?.result;
    if (result.error || result.status !== 0 || final?.status !== 'succeeded'
      || final?.structured_data?.answer !== 'packaged-agent-ready'
      || final?.structured_data?.review != null
      || !final?.provenance?.stages?.includes('design')
      || final?.provenance?.stages?.includes('review')
      || final?.provenance?.runtime !== 'openai-agents-sdk') {
      throw new Error(`Agent worker 独立运行检查失败：${result.error?.message || result.stderr || result.stdout}`);
    }
  } finally {
    rmSync(smokeDir, { recursive: true, force: true });
  }
}

export function verifySidecarBuild(root, sidecarDirectory, expectedProfile = undefined) {
  const manifestPath = path.join(sidecarDirectory, runtimeManifestName);
  if (!existsSync(manifestPath)) throw new Error('Sidecar 缺少构建记录，请先运行 npm run build:sidecar。');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  if (expectedProfile && (manifest.profile || 'full') !== expectedProfile) {
    throw new Error(`Sidecar profile 不匹配：需要 ${expectedProfile}，实际 ${manifest.profile || 'full'}。`);
  }
  if (manifest.sourceDigest !== runtimeSourceDigest(root)) {
    throw new Error('Sidecar 与当前源码不一致，请先运行 npm run build:sidecar，避免打包旧版 Agent。');
  }
  const worker = path.join(sidecarDirectory, '_internal', 'app', workerName);
  if (!existsSync(worker) || manifest.workerDigest !== fileDigest(worker)) {
    throw new Error('Sidecar 的 Agent worker 缺失或不完整，请重新运行 npm run build:sidecar。');
  }
  verifyRuntimeData(root, sidecarDirectory);
  return { manifest, worker };
}

export function verifyRuntimeData(root, sidecarDirectory) {
  const verify = relative => {
    const source = path.join(root, 'services/api/app', relative);
    for (const entry of readdirSync(source, {withFileTypes:true})) {
      const child = path.join(relative, entry.name);
      if (entry.isDirectory()) verify(child);
      else {
        const frozen = path.join(sidecarDirectory, '_internal/app', child);
        if (!existsSync(frozen) || fileDigest(frozen) !== fileDigest(path.join(source, entry.name))) {
          throw new Error(`Sidecar 内置技能或印刷字体缺失/不一致：${child}，请重新构建。`);
        }
      }
    }
  };
  runtimeDataDirectories.forEach(verify);
}
