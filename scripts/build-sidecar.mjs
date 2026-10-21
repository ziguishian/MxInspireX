import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { bundleAgentWorker, fileDigest, runtimeManifestName, runtimeSourceDigest, verifyRuntimeData, workerName } from './agent-runtime-build.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = path.join(root, 'services', 'api');
const entry = path.join(apiDir, 'sidecar_entry.py');
const profileArgument = process.argv.find(argument => argument.startsWith('--profile='))?.split('=')[1];
const profile = profileArgument || process.env.AICS_SIDECAR_PROFILE || 'full';
if (!['full', 'lite'].includes(profile)) throw new Error(`不支持的 sidecar profile: ${profile}`);
const bundledPython = path.join(apiDir, '.venv', 'bin', 'python');
const python = process.env.AICS_PYTHON ?? (existsSync(bundledPython) ? bundledPython : 'python3');
const outputRoot = path.join(root, 'dist', profile === 'lite' ? 'sidecar-lite' : 'sidecar');
const distPath = path.join(outputRoot, 'dist');
const workPath = path.join(outputRoot, 'work');
const specPath = path.join(outputRoot, 'spec');
const pyinstallerConfig = process.env.PYINSTALLER_CONFIG_DIR ?? path.join(outputRoot, 'pyinstaller-config');

if (!existsSync(entry)) throw new Error(`找不到 sidecar 入口: ${entry}`);
rmSync(outputRoot, { recursive: true, force: true });
mkdirSync(outputRoot, { recursive: true });
mkdirSync(pyinstallerConfig, { recursive: true });
const standaloneWorker = path.join(outputRoot, 'agent', workerName);
await bundleAgentWorker(root, standaloneWorker);
const sourceDigest = runtimeSourceDigest(root);

const cadLicenses = path.join(outputRoot, 'cad-licenses');
if (profile === 'full') execFileSync(python, [path.join(root, 'scripts/cad-licenses.py'), cadLicenses], { stdio: 'inherit' });
const pdfiumLicenses = path.join(outputRoot, 'pdfium-licenses');
execFileSync(python, [path.join(root, 'scripts/pdfium-licenses.py'), pdfiumLicenses], { stdio: 'inherit' });
const args = [
  '-m', 'PyInstaller',
  '--noconfirm', '--clean', '--onedir', '--name', 'aics-api',
  '--distpath', distPath, '--workpath', workPath, '--specpath', specPath,
  '--paths', apiDir,
  // Include the standalone SDK bundle as frozen package data. This also
  // supports launching the sidecar without Electron's path override.
  '--add-data', `${standaloneWorker}${path.delimiter}app`,
  '--add-data', `${path.join(apiDir, 'app', 'builtin_skills')}${path.delimiter}app/builtin_skills`,
  '--add-data', `${path.join(apiDir, 'app', 'print_fonts')}${path.delimiter}app/print_fonts`,
  '--add-data', `${path.join(apiDir, 'app', 'easter_egg_assets')}${path.delimiter}app/easter_egg_assets`,
  ...(profile === 'full' ? [
    '--collect-submodules', 'fontTools',
  ] : [
    '--hidden-import', 'fontTools.ttLib',
    '--hidden-import', 'fontTools.pens.svgPathPen',
    '--hidden-import', 'fontTools.pens.transformPen',
  ]),
  '--hidden-import', 'app.main',
  '--add-data', `${pdfiumLicenses}${path.delimiter}PDFIUM-LICENSES`,
  '--collect-submodules', 'app',
  '--collect-all', 'pypdfium2',
  '--collect-all', 'pypdfium2_raw',
  '--collect-submodules', 'uvicorn',
  '--collect-submodules', 'fastapi',
  ...(profile === 'full' ? [
    '--add-data', `${cadLicenses}${path.delimiter}CAD-LICENSES`,
    '--collect-all', 'imageio_ffmpeg',
    '--collect-all', 'cadquery',
    '--collect-all', 'OCP',
    '--collect-all', 'vtkmodules',
  ] : [
    '--exclude-module', 'imageio_ffmpeg',
    '--exclude-module', 'cadquery',
    '--exclude-module', 'OCP',
    '--exclude-module', 'vtkmodules',
    '--exclude-module', 'casadi',
    '--exclude-module', 'numba',
    '--exclude-module', 'llvmlite',
    '--exclude-module', 'scipy',
  ]),
  entry,
];

try {
  execFileSync(python, args, {
    cwd: apiDir,
    stdio: 'inherit',
    env: { ...process.env, PYINSTALLER_CONFIG_DIR: pyinstallerConfig },
  });
} catch (error) {
  throw new Error(`无法构建 portable sidecar，请确认 Python 环境已安装 PyInstaller（${python}）`, { cause: error });
}

const executable = path.join(distPath, 'aics-api', process.platform === 'win32' ? 'aics-api.exe' : 'aics-api');
if (!existsSync(executable)) throw new Error(`PyInstaller 未生成 sidecar 可执行文件: ${executable}`);
const frozenWorker = path.join(distPath, 'aics-api', '_internal', 'app', workerName);
if (!existsSync(frozenWorker) || fileDigest(frozenWorker) !== fileDigest(standaloneWorker)) {
  throw new Error('PyInstaller 未完整包含 OpenAI Agents SDK worker。');
}
verifyRuntimeData(root, path.join(distPath, 'aics-api'));
if (sourceDigest !== runtimeSourceDigest(root)) throw new Error('构建期间 API 源码发生变化，请重新运行 npm run build:sidecar。');
writeFileSync(path.join(distPath, 'aics-api', runtimeManifestName), `${JSON.stringify({
  generatedAt: new Date().toISOString(), profile, sourceDigest, workerDigest: fileDigest(frozenWorker),
}, null, 2)}\n`);
console.log(`Built ${profile} portable sidecar: ${executable}`);
