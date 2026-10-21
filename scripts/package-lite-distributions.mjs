import { cpSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { version } = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
if (process.platform !== 'darwin') throw new Error('轻量版四格式打包需要 macOS；Windows 可单独使用 AICS_PACKAGE_PROFILE=lite npm run package:win。');
const output = path.resolve(process.env.AICS_DISTRIBUTION_DIR || path.join(root, 'dist/packages', `LangjuAgent-${version}-lite-${new Date().toISOString().replace(/[:.]/g, '-')}`));
mkdirSync(output, { recursive: true });
writeFileSync(path.join(root, '.tmp/current-package-dir.txt'), output);
console.log(`Lite distribution directory: ${output}`);

const macComponentRoot = path.join(root, 'dist', 'runtime-components', `${process.platform}-${process.arch}`);
const env = {
  ...process.env,
  AICS_PACKAGE_PROFILE: 'lite',
  AICS_DISTRIBUTION_DIR: output,
  AICS_RELEASE_DIR: path.join(output, `macos-${process.arch}-lite`),
  AICS_SIDECAR_DIR: path.join(root, 'dist', 'sidecar-lite', 'dist', 'aics-api'),
  AICS_RUNTIME_COMPONENT_MANIFEST: path.join(macComponentRoot, 'runtime-components.json'),
};
const run = (command, args) => execFileSync(command, args, { cwd: root, env, stdio: 'inherit' });
if (!process.argv.includes('--reuse-builds')) {
  run('npm', ['run', 'build']);
  run('npm', ['run', 'build:sidecar:lite']);
  run('npm', ['run', 'build:runtime-components']);
}

const app = path.join(env.AICS_RELEASE_DIR, '朗居设计Agent.app');
const macZip = path.join(output, `LangjuAgent-${version}-lite-macos-${process.arch}-portable.zip`);
const macPkg = path.join(output, `LangjuAgent-${version}-lite-macos-${process.arch}-installer.pkg`);
run(process.execPath, ['scripts/package-macos.mjs']);
run('/usr/bin/codesign', ['--verify', '--deep', '--strict', app]);
run('/usr/bin/ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', app, macZip]);

const components = path.join(output, 'mac-components.plist');
writeFileSync(components, `<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><array><dict><key>RootRelativeBundlePath</key><string>朗居设计Agent.app</string><key>BundleIsRelocatable</key><false/><key>BundleIsVersionChecked</key><false/><key>BundleHasStrictIdentifier</key><true/><key>BundleOverwriteAction</key><string>upgrade</string></dict></array></plist>`);
const pkgRoot = path.join(output, 'mac-lite-installer-root');
mkdirSync(pkgRoot, { recursive: true });
run('/usr/bin/ditto', [app, path.join(pkgRoot, '朗居设计Agent.app')]);
const installerScripts = path.join(output, 'mac-lite-installer-scripts');
mkdirSync(installerScripts, { recursive: true });
writeFileSync(path.join(installerScripts, 'preinstall'), '#!/bin/sh\nif /bin/ps -axo command= | /usr/bin/grep -q "^/Applications/朗居设计Agent.app/Contents/"; then\n  echo "请先退出朗居设计Agent，再安装更新。" >&2\n  exit 1\nfi\nexit 0\n', { mode: 0o755 });
run('/usr/bin/pkgbuild', ['--root', pkgRoot, '--component-plist', components, '--scripts', installerScripts, '--install-location', '/Applications', '--identifier', 'com.aicreativestudio.desktop', '--version', version, macPkg]);
run(process.execPath, ['scripts/smoke-packaged-macos.mjs', app]);

const destinationComponents = path.join(output, 'components', `${process.platform}-${process.arch}`);
mkdirSync(destinationComponents, { recursive: true });
cpSync(macComponentRoot, destinationComponents, { recursive: true });
run(process.execPath, ['scripts/package-windows.mjs']);
run(process.execPath, ['scripts/finalize-lite-distribution.mjs', output]);
console.log(`All four lite distributions created: ${output}`);
