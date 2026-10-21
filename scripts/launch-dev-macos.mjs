import { closeSync, cpSync, existsSync, lstatSync, mkdirSync, openSync, readlinkSync, renameSync, rmSync } from 'node:fs';
import { execFileSync, spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const electronApp = path.join(root, 'node_modules', 'electron', 'dist', 'Electron.app');
const devRoot = path.join(root, 'dist', 'dev');
const devApp = path.join(devRoot, '朗居设计Agent.app');
const devResources = path.join(devApp, 'Contents', 'Resources');
const devMacOS = path.join(devApp, 'Contents', 'MacOS');
const devProject = path.join(devResources, 'app');
const desktopEntry = path.join(root, 'dist', 'desktop', 'main.js');
const iconVariants = {
  dark: {
    icns: path.join(root, 'apps', 'desktop', 'assets', 'langju-agent-dark.icns'),
    png: path.join(root, 'apps', 'desktop', 'assets', 'langju-agent-icon-dark-1024.png'),
  },
  light: {
    icns: path.join(root, 'apps', 'desktop', 'assets', 'langju-agent-light.icns'),
    png: path.join(root, 'apps', 'desktop', 'assets', 'langju-agent-icon-light-1024.png'),
  },
};
// LaunchServices and Stage Manager resolve the static bundle icon before
// Electron starts.  Unlike the running Dock icon, they do not evaluate
// `nativeTheme` or the renderer preference.  Select the static ICNS family at
// bundle creation time so a fresh launch gets a tile that matches macOS.
function detectSystemAppearance() {
  const override = process.env.AICS_MACOS_APPEARANCE?.trim().toLowerCase();
  if (override === 'dark' || override === 'light') return override;
  try {
    const value = execFileSync('/usr/bin/defaults', ['read', '-g', 'AppleInterfaceStyle'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim().toLowerCase();
    return value === 'dark' ? 'dark' : 'light';
  } catch {
    // The AppleInterfaceStyle key is absent in macOS Light mode.
    return 'light';
  }
}

const staticIconAppearance = detectSystemAppearance();
const iconSource = iconVariants[staticIconAppearance].icns;
const iconPngSource = iconVariants[staticIconAppearance].png;
const iconName = 'langju-agent.icns';
const launchServicesRegister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister';
// A copied Electron runtime keeps `Electron` as its executable name.  Some
// macOS surfaces use that runtime identity (and its default icon) for small
// previews even when CFBundleIconFile has been updated.  Give the bundle a
// stable product executable name so LaunchServices treats it as our app.
const executableName = 'LangjuAgent';

function setPlistValue(plist, key, value) {
  try {
    execFileSync('/usr/libexec/PlistBuddy', ['-c', `Set :${key} ${value}`, plist], { stdio: 'ignore' });
  } catch {
    execFileSync('/usr/libexec/PlistBuddy', ['-c', `Add :${key} string ${value}`, plist], { stdio: 'ignore' });
  }
}

function setPlistIconMetadata(plist, iconName) {
  setPlistValue(plist, 'CFBundleIconFile', iconName);
  // Newer LaunchServices consumers prefer the explicit array for thumbnail
  // and Stage Manager previews. Keep it pointed at the same canonical ICNS.
  try {
    execFileSync('/usr/libexec/PlistBuddy', ['-c', 'Delete :CFBundleIconFiles', plist], { stdio: 'ignore' });
  } catch {
    // The key is absent on a fresh Electron bundle.
  }
  execFileSync('/usr/libexec/PlistBuddy', ['-c', 'Add :CFBundleIconFiles array', plist], { stdio: 'ignore' });
  execFileSync('/usr/libexec/PlistBuddy', ['-c', `Add :CFBundleIconFiles:0 string ${iconName}`, plist], { stdio: 'ignore' });
}

function refreshLaunchServices() {
  if (!existsSync(launchServicesRegister)) return;
  try {
    // The same dev bundle path is reused between launches. Force LaunchServices
    // to invalidate its cached thumbnail after replacing the static ICNS.
    execFileSync(launchServicesRegister, ['-f', devApp], { stdio: 'ignore' });
  } catch {
    // Icon cache refresh is best effort; the next Finder/Stage Manager pass
    // will still read the selected ICNS from the signed bundle.
  }
}

function prepareDevApp() {
  if (!existsSync(electronApp)) throw new Error(`未找到 Electron runtime: ${electronApp}`);
  if (!existsSync(iconSource)) throw new Error(`未找到朗居应用图标: ${iconSource}`);
  if (!existsSync(iconPngSource)) throw new Error(`未找到朗居 PNG 图标: ${iconPngSource}`);
  for (const [appearance, variant] of Object.entries(iconVariants)) {
    if (!existsSync(variant.icns)) throw new Error(`未找到朗居 ${appearance} ICNS 图标: ${variant.icns}`);
    if (!existsSync(variant.png)) throw new Error(`未找到朗居 ${appearance} PNG 图标: ${variant.png}`);
  }
  const frameworkLink = path.join(devApp, 'Contents', 'Frameworks', 'Electron Framework.framework', 'Electron Framework');
  let hasAbsoluteFrameworkLink = false;
  if (existsSync(devApp)) {
    try {
      hasAbsoluteFrameworkLink = lstatSync(frameworkLink).isSymbolicLink() && path.isAbsolute(readlinkSync(frameworkLink));
    } catch {
      // A partially copied bundle is rebuilt below instead of being launched.
      hasAbsoluteFrameworkLink = true;
    }
  }
  if (!existsSync(devApp) || hasAbsoluteFrameworkLink) {
    if (existsSync(devApp)) rmSync(devApp, { recursive: true, force: true });
    mkdirSync(devRoot, { recursive: true });
    // Keep the branded shell separate from node_modules so macOS uses this
    // bundle's icon in Stage Manager during development.
    execFileSync('/usr/bin/ditto', [electronApp, devApp], { stdio: 'ignore' });
  }

  cpSync(iconSource, path.join(devResources, iconName));
  // Electron's runtime may still consult its legacy filename in some macOS
  // surfaces, so keep both resource names pointed at the same branded ICNS.
  cpSync(iconSource, path.join(devResources, 'electron.icns'));
  // The runtime Dock API consumes PNG; keep a copy inside the bundle for
  // packaged/development parity while the ICNS serves LaunchServices.
  // Keep both appearance variants inside the bundle.  The Electron main
  // process selects the matching PNG through nativeTheme at launch and when
  // macOS changes appearance; the ICNS variants are available to future
  // LaunchServices/asset-catalog tooling and offline inspection.
  for (const [appearance, variant] of Object.entries(iconVariants)) {
    cpSync(variant.icns, path.join(devResources, `langju-agent-${appearance}.icns`));
    cpSync(variant.png, path.join(devResources, `langju-agent-icon-${appearance}-1024.png`));
  }
  const electronExecutable = path.join(devMacOS, 'Electron');
  const brandedExecutable = path.join(devMacOS, executableName);
  if (existsSync(electronExecutable) && !existsSync(brandedExecutable)) {
    renameSync(electronExecutable, brandedExecutable);
  }
  const plist = path.join(devApp, 'Contents', 'Info.plist');
  setPlistValue(plist, 'CFBundleDisplayName', '朗居设计Agent');
  setPlistValue(plist, 'CFBundleName', '朗居设计Agent');
  setPlistValue(plist, 'CFBundleIdentifier', 'com.aicreativestudio.desktop.dev');
  setPlistIconMetadata(plist, iconName);
  setPlistValue(plist, 'CFBundleExecutable', executableName);

  // Refresh the outer ad-hoc signature after changing the executable and
  // plist.  This gives LaunchServices a new, consistent bundle identity
  // without requiring a developer certificate for local development.
  execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', '--timestamp=none', devApp], { stdio: 'ignore' });
  refreshLaunchServices();
  console.log(`Static macOS icon: ${staticIconAppearance} (${iconSource})`);
}

function stageDevEntry() {
  // A copied Electron.app is a packaged shell and ignores a bare JS entry
  // argument on macOS.  Stage the compiled desktop entry under Resources/app
  // so the branded shell loads our main process instead of default_app.asar.
  if (!existsSync(desktopEntry)) {
    throw new Error('未找到 dist/desktop/main.js，请先编译桌面端。');
  }
  rmSync(devProject, { recursive: true, force: true });
  mkdirSync(devProject, { recursive: true });
  cpSync(path.join(root, 'dist', 'desktop'), path.join(devProject, 'dist', 'desktop'), { recursive: true });
  // Keep a built renderer beside the entry for packaged fallback/debugging;
  // normal development uses the Vite URL selected by AICS_DEV_MODE.
  if (existsSync(path.join(root, 'dist', 'renderer'))) {
    cpSync(path.join(root, 'dist', 'renderer'), path.join(devProject, 'dist', 'renderer'), { recursive: true });
  }
  cpSync(path.join(root, 'package.json'), path.join(devProject, 'package.json'));
}

function launchElectron(binary, args) {
  // The development command is often started from a short-lived terminal or
  // PTY.  Inheriting that descriptor lets a later Chromium/Electron log write
  // hit a closed pipe and terminate the main process with EPIPE.  Give the
  // app a durable file descriptor instead; the main process still forwards
  // useful API messages through its guarded logger.
  mkdirSync(devRoot, { recursive: true });
  const logPath = path.join(devRoot, 'electron.log');
  const logFd = openSync(logPath, 'a', 0o644);
  try {
    return spawn(binary, args, {
      cwd: root,
      env: { ...process.env, AICS_DEV_LOG_PATH: logPath, AICS_DEV_MODE: '1', AICS_PROJECT_ROOT: root },
      stdio: ['ignore', logFd, logFd],
    });
  } finally {
    closeSync(logFd);
  }
}

if (process.platform === 'darwin') {
  prepareDevApp();
  stageDevEntry();
  // stageDevEntry writes the compiled entry into Contents/Resources/app after
  // prepareDevApp's initial signature. Re-seal the complete bundle so
  // LaunchServices, Stage Manager, and Gatekeeper do not see a stale or
  // invalid sealed-resources record.
  execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', '--timestamp=none', devApp], { stdio: 'ignore' });
  refreshLaunchServices();
  const child = launchElectron(path.join(devApp, 'Contents', 'MacOS', executableName), [
    `--user-data-dir=${path.join(devRoot, 'user-data')}`,
  ]);
  child.on('exit', (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 0);
  });
} else {
  const electronCli = path.join(root, 'node_modules', 'electron', 'cli.js');
  const child = launchElectron(process.execPath, [electronCli, desktopEntry]);
  child.on('exit', (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 0);
  });
}
