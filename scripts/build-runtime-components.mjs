import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { fileDigest } from './agent-runtime-build.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = path.join(root, 'services', 'api');
const python = process.env.AICS_PYTHON || path.join(apiDir, '.venv', 'bin', 'python');
const platform = process.platform;
const arch = process.arch;
if (platform !== 'darwin') throw new Error('Mac 能力包构建必须在 macOS 上运行；Windows 能力包由 package-windows.mjs 交叉构建。');

const outputRoot = path.join(root, 'dist', 'runtime-components', `${platform}-${arch}`);
const buildRoot = path.join(root, 'dist', 'runtime-components', '.build', `${platform}-${arch}`);
const staging = path.join(buildRoot, 'staging');
const pyinstaller = path.join(buildRoot, 'pyinstaller');
rmSync(buildRoot, { recursive: true, force: true });
mkdirSync(staging, { recursive: true });
mkdirSync(outputRoot, { recursive: true });

const cadLicenses = path.join(buildRoot, 'cad-licenses');
execFileSync(python, [path.join(root, 'scripts/cad-licenses.py'), cadLicenses], { stdio: 'inherit' });
execFileSync(python, [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'aics-cad-worker',
  '--distpath', path.join(pyinstaller, 'dist'), '--workpath', path.join(pyinstaller, 'work'), '--specpath', path.join(pyinstaller, 'spec'),
  '--paths', apiDir,
  // Follow the modules imported by the trusted CAD worker instead of
  // collecting VTK's GUI, testing and scientific-visualisation surface.
  // CadQuery's geometry/export modules declare the exact VTK and OCP modules
  // needed for STEP/STL/GLB, keeping first-launch latency bounded.
  '--exclude-module', 'vtk',
  '--exclude-module', 'cadquery.vis',
  '--exclude-module', 'cadquery.fig',
  '--exclude-module', 'cadquery.occ_impl.jupyter_tools',
  '--exclude-module', 'matplotlib',
  '--exclude-module', 'trame',
  '--exclude-module', 'trame_vtk',
  '--hidden-import', 'cadquery',
  path.join(apiDir, 'cad_worker_entry.py'),
], { cwd: apiDir, stdio: 'inherit', env: { ...process.env, PYINSTALLER_CONFIG_DIR: path.join(pyinstaller, 'config') } });

const cadStage = path.join(staging, 'cad');
mkdirSync(cadStage, { recursive: true });
const cadWorker = path.join(pyinstaller, 'dist', 'aics-cad-worker');
if (!existsSync(path.join(cadWorker, 'aics-cad-worker'))) throw new Error('CAD 能力包未生成可执行文件。');
// PyInstaller uses relative links from _internal/ to package-local native
// libraries.  Node resolves those links by default while copying, which would
// bake this build machine's absolute path into the downloadable component.
cpSync(cadWorker, path.join(cadStage, 'aics-cad-worker'), { recursive: true, verbatimSymlinks: true });
cpSync(cadLicenses, path.join(cadStage, 'CAD-LICENSES'), { recursive: true });
execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', '--timestamp=none', path.join(cadStage, 'aics-cad-worker')]);

const ffmpeg = execFileSync(python, ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { encoding: 'utf8' }).trim();
if (!existsSync(ffmpeg)) throw new Error('找不到 imageio-ffmpeg 内置程序。');
const mediaStage = path.join(staging, 'media');
mkdirSync(mediaStage, { recursive: true });
cpSync(ffmpeg, path.join(mediaStage, 'ffmpeg'));
execFileSync('/bin/chmod', ['755', path.join(mediaStage, 'ffmpeg')]);
execFileSync('/usr/bin/codesign', ['--force', '--sign', '-', '--timestamp=none', path.join(mediaStage, 'ffmpeg')]);

const packageVersion = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')).version;
const componentBaseUrl = process.env.AICS_COMPONENT_BASE_URL?.replace(/\/$/, '') || '';
const definitions = [
  { id: 'cad', label: '本地 CAD 与三维几何', description: '参数化建模、STEP/STL/GLB 导出和本地几何检查。', environment: { AICS_CAD_WORKER: 'aics-cad-worker/aics-cad-worker' } },
  { id: 'media', label: '本地音视频处理', description: '视频裁剪、拼接、配音和字幕封装。', environment: { AICS_FFMPEG: 'ffmpeg' } },
];
const components = [];
for (const definition of definitions) {
  const archiveName = `LangjuAgent-${packageVersion}-${platform}-${arch}-${definition.id}-component.zip`;
  const archive = path.join(outputRoot, archiveName);
  rmSync(archive, { force: true });
  execFileSync('/usr/bin/ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', path.join(staging, definition.id), archive]);
  components.push({ ...definition, archiveName, sha256: fileDigest(archive), bytes: statSync(archive).size, downloadUrl: componentBaseUrl ? `${componentBaseUrl}/${archiveName}` : null });
}
const manifest = { schemaVersion: 1, version: packageVersion, profile: 'lite', platform, arch, generatedAt: new Date().toISOString(), components };
writeFileSync(path.join(outputRoot, 'runtime-components.json'), `${JSON.stringify(manifest, null, 2)}\n`);
writeFileSync(path.join(outputRoot, 'SHA256SUMS-components.txt'), components.map(component => `${component.sha256}  ${component.archiveName}`).join('\n') + '\n');
console.log(`Built runtime components: ${outputRoot}`);
