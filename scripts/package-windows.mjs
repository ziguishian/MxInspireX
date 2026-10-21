import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { downloadArtifact } from '@electron/get';
import extract from 'extract-zip';
import * as ResEdit from 'resedit';
import { bundleAgentWorker, fileDigest, workerName, runtimeSourceDigest } from './agent-runtime-build.mjs';
import { packageDesktopRuntimeDependencies } from './desktop-runtime-dependencies.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
const packageProfile = process.env.AICS_PACKAGE_PROFILE === 'lite' ? 'lite' : 'full';
const output = path.resolve(process.env.AICS_DISTRIBUTION_DIR || path.join(root, 'dist', 'packages', `LangjuAgent-${pkg.version}-${Date.now()}`));
const appDir = path.join(output, 'windows-x64', 'LangjuAgent');
const cache = path.join(root, '.tmp', 'package-downloads');
const pythonVersion = '3.13.15';
const pythonDigest = 'd1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf';
const hostPython = process.env.AICS_PYTHON || path.join(root, 'services/api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const uv = process.env.AICS_UV || 'uv';
const makensis = process.env.AICS_MAKENSIS || 'makensis';
if (existsSync(appDir)) throw new Error(`发布目录已存在，请选择新目录，避免覆盖可运行文件：${appDir}`);
execFileSync(makensis, ['-VERSION'], { stdio: 'inherit' });
mkdirSync(cache, { recursive: true });
mkdirSync(path.dirname(appDir), { recursive: true });

const electronVersion = JSON.parse(readFileSync(path.join(root, 'node_modules/electron/package.json'), 'utf8')).version;
console.log(`Downloading verified Electron ${electronVersion} win32-x64`);
const downloader = { async download(url, target) {
  // curl respects the host's configured proxy; checksum verification remains
  // in @electron/get for both the archive and official SHASUMS256.txt.
  const partialDir = path.join(cache, 'partial', electronVersion);
  mkdirSync(partialDir, { recursive: true });
  const partial = path.join(partialDir, path.basename(new URL(url).pathname));
  execFileSync('curl', ['--fail', '--location', '--silent', '--show-error', '--retry', '3', '--continue-at', '-', '--connect-timeout', '15', '--max-time', '1800', '--output', partial, url], { stdio: 'inherit' });
  cpSync(partial, target);
  rmSync(partial);
} };
const electronZip = await downloadArtifact({ version: electronVersion, artifactName: 'electron', platform: 'win32', arch: 'x64', cacheRoot: path.join(cache, 'electron'), downloader });
await extract(electronZip, { dir: appDir });
const pythonZip = path.join(cache, `python-${pythonVersion}-embed-amd64.zip`);
if (!existsSync(pythonZip)) execFileSync('curl', ['--fail', '--location', '--retry', '3', '--output', pythonZip, `https://www.python.org/ftp/python/${pythonVersion}/python-${pythonVersion}-embed-amd64.zip`], { stdio: 'inherit' });
if (fileDigest(pythonZip) !== pythonDigest) throw new Error('Python embedded runtime SHA-256 校验失败');

const app = path.join(appDir, 'resources/app');
const api = path.join(app, 'services/api');
mkdirSync(api, { recursive: true });
for (const directory of ['dist/renderer', 'dist/desktop', 'packages']) cpSync(path.join(root, directory), path.join(app, directory), { recursive: true });
cpSync(path.join(root, 'services/api/app'), path.join(api, 'app'), { recursive: true, filter: source => !source.split(path.sep).includes('__pycache__') });
writeFileSync(path.join(app, 'package.json'), JSON.stringify({ name: pkg.name, productName: pkg.productName, version: pkg.version, type: 'module', main: 'dist/desktop/main.js' }, null, 2));
packageDesktopRuntimeDependencies(root, app);
await bundleAgentWorker(root, path.join(api, 'app', workerName));
const pythonDir = path.join(api, 'python');
await extract(pythonZip, { dir: pythonDir });
writeFileSync(path.join(pythonDir, 'python313._pth'), 'python313.zip\n.\nLib/site-packages\n..\nimport site\n');
const requirements = path.join(output, `windows-${packageProfile}-requirements.txt`);
const exportArgs = ['export', '--project', path.join(root, 'services/api'), '--frozen', '--no-dev', '--no-emit-project'];
if (packageProfile === 'full') exportArgs.push('--extra', 'cad', '--extra', 'media');
execFileSync(uv, [...exportArgs, '--output-file', requirements], { stdio: ['ignore', 'ignore', 'inherit'] });
const wheelRequirements = path.join(output, 'windows-wheel-requirements.txt');
execFileSync(hostPython, [path.join(root, 'scripts/windows-wheel-requirements.py'), requirements, path.join(root, 'services/api/uv.lock'), wheelRequirements], { stdio: 'inherit' });
execFileSync(uv, ['pip', 'install', '--no-index', '--python-version', pythonVersion, '--python-platform', 'x86_64-pc-windows-msvc', '--only-binary', ':all:', '--require-hashes', '--no-deps', '--link-mode', 'copy', '--target', path.join(pythonDir, 'Lib/site-packages'), '-r', wheelRequirements, '--cache-dir', path.join(cache, 'uv')], { stdio: 'inherit' });

if (packageProfile === 'full') {
  execFileSync(hostPython, [path.join(root, 'scripts/cad-licenses.py'), path.join(appDir, 'resources/CAD-LICENSES'), path.join(pythonDir, 'Lib/site-packages')], { stdio: 'inherit' });
  cpSync(path.join(root, 'scripts/smoke-cad.py'), path.join(appDir, 'resources/cad-smoke.py'));
  writeFileSync(path.join(appDir, 'CAD-SMOKE.cmd'), '@echo off\r\n"%~dp0resources\\app\\services\\api\\python\\python.exe" "%~dp0resources\\cad-smoke.py" --api-dir "%~dp0resources\\app\\services\\api"\r\nif errorlevel 1 exit /b 1\r\n');
} else {
  const componentRoot = path.join(output, 'components', 'win32-x64');
  const componentStage = path.join(output, '.component-stage-win32-x64');
  rmSync(componentStage, { recursive: true, force: true });
  mkdirSync(componentRoot, { recursive: true });
  const optionalRequirements = path.join(output, 'windows-optional-requirements.txt');
  execFileSync(uv, ['export', '--project', path.join(root, 'services/api'), '--frozen', '--no-dev', '--no-emit-project', '--extra', 'cad', '--extra', 'media', '--output-file', optionalRequirements], { stdio: ['ignore', 'ignore', 'inherit'] });
  const components = [];
  const baseUrl = process.env.AICS_COMPONENT_BASE_URL?.replace(/\/$/, '') || '';
  const archiveComponent = (id, label, description, environment, source) => {
    const archiveName = `LangjuAgent-${pkg.version}-win32-x64-${id}-component.zip`;
    const archive = path.join(componentRoot, archiveName);
    execFileSync(hostPython, ['-c', 'import pathlib,sys,zipfile; root=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],"w",zipfile.ZIP_DEFLATED,compresslevel=9); [z.write(p,p.relative_to(root.parent).as_posix()) for p in sorted(root.rglob("*")) if p.is_file()]; z.close()', source, archive], { stdio: 'inherit' });
    components.push({ id, label, description, environment, archiveName, sha256: fileDigest(archive), bytes: statSync(archive).size, downloadUrl: baseUrl ? `${baseUrl}/${archiveName}` : null });
  };

  const cadWheelRequirements = path.join(output, 'windows-cad-wheel-requirements.txt');
  execFileSync(hostPython, [path.join(root, 'scripts/windows-wheel-requirements.py'), optionalRequirements, path.join(root, 'services/api/uv.lock'), cadWheelRequirements, '--roots', 'cadquery', '--exclude-requirements', wheelRequirements], { stdio: 'inherit' });
  const cadStage = path.join(componentStage, 'cad');
  const cadSite = path.join(cadStage, 'python-site-packages');
  mkdirSync(cadSite, { recursive: true });
  execFileSync(uv, ['pip', 'install', '--no-index', '--python-version', pythonVersion, '--python-platform', 'x86_64-pc-windows-msvc', '--only-binary', ':all:', '--require-hashes', '--no-deps', '--link-mode', 'copy', '--target', cadSite, '-r', cadWheelRequirements, '--cache-dir', path.join(cache, 'uv')], { stdio: 'inherit' });
  execFileSync(hostPython, [path.join(root, 'scripts/cad-licenses.py'), path.join(cadStage, 'CAD-LICENSES'), cadSite], { stdio: 'inherit' });
  cpSync(path.join(root, 'scripts/smoke-cad.py'), path.join(cadStage, 'cad-smoke.py'));
  archiveComponent('cad', '本地 CAD 与三维几何', '参数化建模、STEP/STL/GLB 导出和本地几何检查。', { AICS_CAD_PYTHONPATH: 'python-site-packages' }, cadStage);

  const mediaWheelRequirements = path.join(output, 'windows-media-wheel-requirements.txt');
  execFileSync(hostPython, [path.join(root, 'scripts/windows-wheel-requirements.py'), optionalRequirements, path.join(root, 'services/api/uv.lock'), mediaWheelRequirements, '--roots', 'imageio-ffmpeg', '--exclude-requirements', wheelRequirements], { stdio: 'inherit' });
  const mediaPackages = path.join(componentStage, '.media-packages');
  execFileSync(uv, ['pip', 'install', '--no-index', '--python-version', pythonVersion, '--python-platform', 'x86_64-pc-windows-msvc', '--only-binary', ':all:', '--require-hashes', '--no-deps', '--link-mode', 'copy', '--target', mediaPackages, '-r', mediaWheelRequirements, '--cache-dir', path.join(cache, 'uv')], { stdio: 'inherit' });
  const mediaStage = path.join(componentStage, 'media');
  mkdirSync(mediaStage, { recursive: true });
  const ffmpegBinary = readdirSync(path.join(mediaPackages, 'imageio_ffmpeg', 'binaries')).find(name => name.endsWith('.exe'));
  if (!ffmpegBinary) throw new Error('Windows 媒体能力包缺少 FFmpeg。');
  cpSync(path.join(mediaPackages, 'imageio_ffmpeg', 'binaries', ffmpegBinary), path.join(mediaStage, 'ffmpeg.exe'));
  archiveComponent('media', '本地音视频处理', '视频裁剪、拼接、配音和字幕封装。', { AICS_FFMPEG: 'ffmpeg.exe' }, mediaStage);
  const manifest = { schemaVersion: 1, version: pkg.version, profile: 'lite', platform: 'win32', arch: 'x64', generatedAt: new Date().toISOString(), components };
  writeFileSync(path.join(app, 'runtime-components.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  writeFileSync(path.join(componentRoot, 'runtime-components.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  writeFileSync(path.join(componentRoot, 'SHA256SUMS-components.txt'), components.map(component => `${component.sha256}  ${component.archiveName}`).join('\n') + '\n');
}
const icon = path.join(root, 'apps/desktop/assets/langju-agent.ico');
const exe = ResEdit.NtExecutable.from(readFileSync(path.join(appDir, 'electron.exe')), { ignoreCert: true });
const resources = ResEdit.NtExecutableResource.from(exe);
const icons = ResEdit.Data.IconFile.from(readFileSync(icon));
for (const group of ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries)) ResEdit.Resource.IconGroupEntry.replaceIconsForResource(resources.entries, group.id, group.lang, icons.icons.map(item => item.data));
for (const version of ResEdit.Resource.VersionInfo.fromEntries(resources.entries)) {
  version.setFileVersion(...pkg.version.split('.').map(Number), 0);
  version.setProductVersion(...pkg.version.split('.').map(Number), 0);
  for (const language of version.getAvailableLanguages()) version.setStringValues(language, {
    FileDescription: pkg.productName, ProductName: pkg.productName, CompanyName: '灵矩绘境',
    OriginalFilename: 'LangjuAgent.exe', InternalName: 'LangjuAgent',
  });
  version.outputToResourceEntries(resources.entries);
}
resources.outputResource(exe);
writeFileSync(path.join(appDir, 'LangjuAgent.exe'), Buffer.from(exe.generate()));
// Retain upstream license files, but only one executable launcher.
rmSync(path.join(appDir, 'electron.exe'));
for (const appearance of ['dark', 'light']) cpSync(path.join(root, `apps/desktop/assets/langju-agent-icon-${appearance}-1024.png`), path.join(appDir, `resources/langju-agent-icon-${appearance}-1024.png`));
cpSync(icon, path.join(appDir, 'resources/langju-agent.ico'));
writeFileSync(path.join(appDir, '使用说明.txt'), `MxinspireX ${pkg.version} · Windows x64${packageProfile === 'lite' ? ' 轻量版' : ''}\r\n\r\n完整解压本文件夹后，双击 LangjuAgent.exe 即可使用。不要单独移动 exe。\r\n${packageProfile === 'lite' ? 'CAD 与本地音视频处理可在“设置 → 能力组件”中按需安装；其它功能无需额外运行环境。' : '无需安装 Python、Node.js 或 FFmpeg。'}首次使用请在设置中填写自己的 API 地址与 Key。\r\n项目保存在“文档\\Langju Design Studio”（旧工作区会继续沿用）；Key 保存在当前用户的 Windows 凭据管理器。\r\n退出应用后再移动文件夹或升级。卸载安装版不会删除项目和个人配置。\r\n`);
writeFileSync(path.join(appDir, 'BUILD-METADATA.json'), JSON.stringify({ version: pkg.version, packageProfile, platform: 'win32', arch: 'x64', electronVersion, pythonVersion, generatedAt: new Date().toISOString(), sourceDigest: runtimeSourceDigest(root), workerDigest: fileDigest(path.join(api, 'app', workerName)), signing: 'unsigned' }, null, 2));
const prefix = `LangjuAgent-${pkg.version}-${packageProfile === 'lite' ? 'lite-' : ''}windows-x64`;
const zip = path.join(output, `${prefix}-portable.zip`);
execFileSync(hostPython, ['-c', 'import pathlib,sys,zipfile; root=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],"w",zipfile.ZIP_DEFLATED,compresslevel=6); [z.write(p,p.relative_to(root.parent).as_posix()) for p in sorted(root.rglob("*")) if p.is_file()]; z.close()', appDir, zip], { stdio: 'inherit' });
const installer = path.join(output, `${prefix}-setup.exe`);
const uninstall = [];
const scan = (directory) => {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    const relative = path.relative(appDir, absolute).split(path.sep).join('\\').replaceAll('$', '$$');
    if (entry.isDirectory()) { scan(absolute); uninstall.push(`RMDir "$INSTDIR\\${relative}"`); }
    else uninstall.push(`Delete "$INSTDIR\\${relative}"`);
  }
};
scan(appDir);
const uninstallFile = path.join(output, 'windows-uninstall-files.nsh');
writeFileSync(uninstallFile, uninstall.join('\n') + '\n');
execFileSync(makensis, ['-WX', '-V3', `-DAPP_DIR=${appDir}`, `-DOUTPUT_FILE=${installer}`, `-DAPP_VERSION=${pkg.version}`, `-DAPP_ICON=${icon}`, `-DUNINSTALL_FILES=${uninstallFile}`, path.join(root, 'scripts/windows-installer.nsi')], { stdio: 'inherit' });
console.log(`Windows portable: ${zip}\nWindows installer: ${installer}`);
