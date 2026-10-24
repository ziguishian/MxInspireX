import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fileDigest } from './agent-runtime-build.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { version } = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
const output = path.resolve(process.env.AICS_DISTRIBUTION_DIR || path.join(root, 'dist/packages', `MxinspireX-${version}-${new Date().toISOString().replace(/[:.]/g, '-')}`));
if (process.platform !== 'darwin') throw new Error('四平台格式统一打包脚本需要 macOS（pkgbuild / codesign）。Windows 可独立运行 package-windows.mjs。');
mkdirSync(output, { recursive: true });
writeFileSync(path.join(root, '.tmp/current-package-dir.txt'), output);
console.log(`Distribution directory: ${output}`);
const env = { ...process.env, AICS_DISTRIBUTION_DIR: output, AICS_RELEASE_DIR: path.join(output, `macos-${process.arch}`) };
const run = (command, args) => execFileSync(command, args, { cwd: root, env, stdio: 'inherit' });
const app = path.join(env.AICS_RELEASE_DIR, 'MxinspireX.app');
const macZip = path.join(output, `MxinspireX-${version}-macos-${process.arch}-portable.zip`);
const macPkg = path.join(output, `MxinspireX-${version}-macos-${process.arch}-installer.pkg`);
if (!process.argv.includes('--finalize-only')) {
if (!process.argv.includes('--reuse-builds')) {
run('npm', ['run', 'build']);
run('npm', ['run', 'build:sidecar']);
}
run(process.execPath, ['scripts/package-macos.mjs']);
run('/usr/bin/codesign', ['--verify', '--deep', '--strict', app]);
run('/usr/bin/ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', app, macZip]);
const components = path.join(output, 'mac-components.plist');
// Older app bundles accidentally retained Electron's 36.x bundle version.
// Do not silently skip installing the corrected 0.1.x application version.
writeFileSync(components, `<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><array><dict><key>RootRelativeBundlePath</key><string>MxinspireX.app</string><key>BundleIsRelocatable</key><false/><key>BundleIsVersionChecked</key><false/><key>BundleHasStrictIdentifier</key><true/><key>BundleOverwriteAction</key><string>upgrade</string></dict></array></plist>`);
const pkgRoot = path.join(output, 'mac-installer-root');
mkdirSync(pkgRoot, { recursive: true });
run('/usr/bin/ditto', [app, path.join(pkgRoot, 'MxinspireX.app')]);
const scripts = path.join(output, 'mac-installer-scripts');
mkdirSync(scripts, { recursive: true });
writeFileSync(path.join(scripts, 'preinstall'), '#!/bin/sh\nif /bin/ps -axo command= | /usr/bin/grep -Eq "^/Applications/(MxinspireX|朗居设计Agent)\\.app/Contents/"; then\n  echo "请先退出MxinspireX，再安装更新。" >&2\n  exit 1\nfi\nexit 0\n', { mode: 0o755 });
run('/usr/bin/pkgbuild', ['--root', pkgRoot, '--component-plist', components, '--scripts', scripts, '--install-location', '/Applications', '--identifier', 'com.aicreativestudio.desktop', '--version', version, macPkg]);
run(process.execPath, ['scripts/package-windows.mjs']);
}
const files = [macZip, macPkg, path.join(output, `MxinspireX-${version}-windows-x64-portable.zip`), path.join(output, `MxinspireX-${version}-windows-x64-setup.exe`)];
writeFileSync(path.join(output, 'SHA256SUMS.txt'), files.map(file => `${fileDigest(file)}  ${path.basename(file)}`).join('\n') + '\n');
writeFileSync(path.join(output, '使用说明.txt'), `MxinspireX ${version}\n\nWindows x64：setup.exe 是安装版；portable.zip 解压后双击 MxinspireX.exe。\nmacOS ${process.arch}：installer.pkg 安装到“应用程序”；portable.zip 解压后双击“MxinspireX.app”。本包面向 Apple 芯片 Mac。\n\n四种包均自带运行环境，无需额外安装 Python / Node.js / FFmpeg。首次使用请在设置中填写自己的 API 地址和 Key。\n更新前请退出旧应用。个人项目、API Key 和工作区不会打进发布包。\n当前未配置发布签名证书：Windows 未签名，macOS 为本地签名、未公证。系统可能提示未知发布者；对外正式分发前需签名和公证。\n`);
console.log(`All four distributions created: ${output}`);
