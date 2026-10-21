import { readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fileDigest } from './agent-runtime-build.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.resolve(process.argv[2] || '');
const { version } = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
if (!output || output === root) throw new Error('请传入明确的轻量版发布目录。');

const walkFiles = directory => {
  const files = [];
  if (!directory || !statSync(directory, { throwIfNoEntry: false })) return files;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(absolute));
    else files.push(absolute);
  }
  return files;
};

const assertPrivateDataExcluded = directories => {
  const forbiddenNames = new Set(['catalog.sqlite', 'credits.sqlite', 'workspace.json', 'dev-api.json', 'project.json', '.env', '.env.local']);
  const forbiddenDirectories = new Set(['workspace-data', '.local']);
  const violations = [];
  for (const directory of directories) {
    for (const file of walkFiles(directory)) {
      const parts = path.relative(directory, file).split(path.sep);
      if (forbiddenNames.has(parts.at(-1).toLowerCase()) || parts.some(part => forbiddenDirectories.has(part.toLowerCase()))) violations.push(file);
    }
  }
  if (violations.length) throw new Error(`发布包包含不应打包的用户数据：\n${violations.join('\n')}`);
};

const verifyComponents = directory => {
  const manifest = JSON.parse(readFileSync(path.join(directory, 'runtime-components.json'), 'utf8'));
  if (manifest.profile !== 'lite' || manifest.version !== version) throw new Error(`能力包清单版本不匹配：${directory}`);
  for (const component of manifest.components) {
    const archive = path.join(directory, component.archiveName);
    if (statSync(archive).size !== component.bytes || fileDigest(archive) !== component.sha256) throw new Error(`能力包校验失败：${archive}`);
  }
};

const app = path.join(output, `macos-${process.arch}-lite`, '朗居设计Agent.app');
const windowsApp = path.join(output, 'windows-x64', 'LangjuAgent');
const macComponentStage = path.join(root, 'dist/runtime-components/.build', `${process.platform}-${process.arch}`, 'staging');
const windowsComponentStage = path.join(output, '.component-stage-win32-x64');
const macComponents = path.join(output, 'components', `${process.platform}-${process.arch}`);
const windowsComponents = path.join(output, 'components', 'win32-x64');

execFileSync(path.join(root, 'services/api/.venv/bin/python'), [path.join(root, 'scripts/verify-windows-package.py'), output], { cwd: root, stdio: 'inherit' });
verifyComponents(macComponents);
verifyComponents(windowsComponents);
assertPrivateDataExcluded([app, windowsApp, macComponentStage, windowsComponentStage]);

const macZip = path.join(output, `LangjuAgent-${version}-lite-macos-${process.arch}-portable.zip`);
const macPkg = path.join(output, `LangjuAgent-${version}-lite-macos-${process.arch}-installer.pkg`);
const winZip = path.join(output, `LangjuAgent-${version}-lite-windows-x64-portable.zip`);
const winSetup = path.join(output, `LangjuAgent-${version}-lite-windows-x64-setup.exe`);
const packages = [macZip, macPkg, winZip, winSetup];
for (const file of packages) if (!statSync(file, { throwIfNoEntry: false })) throw new Error(`缺少发布包：${file}`);
writeFileSync(path.join(output, 'SHA256SUMS.txt'), packages.map(file => `${fileDigest(file)}  ${path.basename(file)}`).join('\n') + '\n');
writeFileSync(path.join(output, 'PRIVACY-AUDIT.txt'), `朗居设计Agent ${version} 轻量版 · 发布隐私检查\n\n通过：主程序、macOS 能力包与 Windows 能力包均未包含项目工作区、项目清单、SQLite 账本、开发工作区配置或环境变量文件。\n检查对象：macOS 应用、Windows 绿色版目录、两平台 CAD/媒体能力包的归档源。\n能力包只包含锁定版本的运行依赖、许可证和可执行组件；项目与个人配置仍只保存在安装后当前用户的数据目录。\n检查时间：${new Date().toISOString()}\n`);
writeFileSync(path.join(output, '使用说明.txt'), `朗居设计Agent ${version} 轻量版\n\n主程序不包含本地 CAD/三维几何和 FFmpeg，因此下载与安装体积更小；对话、图像生成、资料库、文档、画布、联网、模型路由和在线 3D/视频能力保持可用。\n\n需要本地 CAD 或本地音视频剪辑时，打开“设置 → 能力组件 → 按需安装”。未配置组件下载地址的内部包会打开文件选择器，请选择 components/对应平台目录中的 component.zip；文件会先校验 SHA-256，再安装到当前用户的应用数据目录。能力包不写入项目工作区，更新或卸载主程序不会删除个人项目。\n\nWindows x64：setup.exe 是安装版；portable.zip 是绿色版。macOS ${process.arch}：installer.pkg 是安装版；portable.zip 是绿色版。当前发布证书状态与完整版本相同。\n`);

for (const temporary of [path.join(output, `macos-${process.arch}-lite`), path.join(output, 'mac-lite-installer-root'), path.join(output, 'mac-lite-installer-scripts'), path.join(output, 'mac-components.plist'), path.join(output, 'windows-x64'), windowsComponentStage]) rmSync(temporary, { recursive: true, force: true });
for (const name of readdirSync(output)) if (/^windows-.*\.(txt|nsh)$/.test(name)) rmSync(path.join(output, name), { force: true });
console.log(`Finalized lite distributions: ${output}`);
