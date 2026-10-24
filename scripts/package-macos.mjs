import { cpSync, existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, realpathSync, readlinkSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { verifySidecarBuild, verifyStandaloneWorker, workerName } from './agent-runtime-build.mjs';
import { assertReleaseNotRunning } from './package-guard.mjs';
import { packageDesktopRuntimeDependencies } from './desktop-runtime-dependencies.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const electronApp = path.join(root, 'node_modules', 'electron', 'dist', 'Electron.app');
const releaseRoot = path.resolve(process.env.AICS_RELEASE_DIR || path.join(root, 'dist', 'release'));
const APP_NAME = 'MxinspireX';
const targetApp = path.join(releaseRoot, `${APP_NAME}.app`);
const targetResources = path.join(targetApp, 'Contents', 'Resources');
const targetProject = path.join(targetResources, 'app');
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
// Finder and Stage Manager read the bundle's static ICNS before the Electron
// process can apply `nativeTheme`. Choose the family that matches the current
// macOS appearance for this build, while still shipping both variants for the
// running Dock/window icon to switch between later.
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
    // Light mode has no AppleInterfaceStyle preference key.
    return 'light';
  }
}

const staticIconAppearance = detectSystemAppearance();
const appIconSource = iconVariants[staticIconAppearance].icns;
const appIconPngSource = iconVariants[staticIconAppearance].png;
const executableName = 'MxinspireX';
const launchServicesRegister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister';

function copyTreeDereferenced(source, destination) {
  const info = lstatSync(source);
  if (info.isSymbolicLink()) {
    // Resolve each link before copying. Node's cpSync `dereference` option
    // follows the bytes but still recreates a symlink on macOS, which leaves
    // PyInstaller's external build-cache links in the shipped bundle.
    copyTreeDereferenced(realpathSync(source), destination);
    return;
  }
  if (info.isDirectory()) {
    mkdirSync(destination, { recursive: true });
    for (const entry of readdirSync(source)) {
      copyTreeDereferenced(path.join(source, entry), path.join(destination, entry));
    }
    return;
  }
  cpSync(source, destination);
}

if (process.platform !== 'darwin') {
  throw new Error('package:mac 只能在 macOS 上运行。');
}
if (!existsSync(electronApp)) {
  throw new Error(`未找到 Electron runtime: ${electronApp}`);
}
if (!existsSync(path.join(root, 'dist', 'renderer', 'index.html')) || !existsSync(path.join(root, 'dist', 'desktop', 'main.js'))) {
  throw new Error('请先运行 npm run build，确保 renderer 与 desktop 已编译。');
}
if (!existsSync(appIconSource)) {
  throw new Error(`未找到朗居应用图标: ${appIconSource}`);
}
if (!existsSync(appIconPngSource)) {
  throw new Error(`未找到朗居 PNG 图标: ${appIconPngSource}`);
}
for (const [appearance, variant] of Object.entries(iconVariants)) {
  if (!existsSync(variant.icns)) throw new Error(`未找到朗居 ${appearance} ICNS 图标: ${variant.icns}`);
  if (!existsSync(variant.png)) throw new Error(`未找到朗居 ${appearance} PNG 图标: ${variant.png}`);
}
// Reject a stale or incomplete frozen API before replacing the existing app.
const packageProfile = process.env.AICS_PACKAGE_PROFILE === 'lite' ? 'lite' : 'full';
const portableSidecarSource = path.resolve(process.env.AICS_SIDECAR_DIR || path.join(root, 'dist', 'sidecar', 'dist', 'aics-api'));
const sidecarBuild = verifySidecarBuild(root, portableSidecarSource, packageProfile);
verifyStandaloneWorker(sidecarBuild.worker);

function setPlistValue(plist, key, value) {
  try {
    execFileSync('/usr/libexec/PlistBuddy', ['-c', `Set :${key} ${value}`, plist], { stdio: 'ignore' });
  } catch {
    execFileSync('/usr/libexec/PlistBuddy', ['-c', `Add :${key} string ${value}`, plist], { stdio: 'ignore' });
  }
}

function setPlistIconMetadata(plist, iconName) {
  setPlistValue(plist, 'CFBundleIconFile', iconName);
  // Keep the explicit icon-file array in sync for small Finder/Dock/Stage
  // Manager previews while retaining CFBundleIconFile for Electron fallback.
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
    // Refresh the cached Finder/Stage Manager thumbnail when a release is
    // rebuilt at the same path with the other appearance family.
    execFileSync(launchServicesRegister, ['-f', targetApp], { stdio: 'ignore' });
  } catch {
    // Best effort only; LaunchServices will read the signed bundle on demand.
  }
}

assertReleaseNotRunning(releaseRoot);
rmSync(releaseRoot, { recursive: true, force: true });
mkdirSync(releaseRoot, { recursive: true });
// Use macOS ditto for the runtime bundle so framework-relative symlinks remain
// valid. A generic recursive copy can turn them into absolute links back to
// node_modules, which breaks icudtl.dat lookup in the packaged app.
execFileSync('/usr/bin/ditto', [electronApp, targetApp]);
// Keep the Electron runtime's fallback icon and the bundle's declared icon
// in sync so Finder, Dock and Launchpad all show the branded mark. The
// existence checks above intentionally fail the build instead of silently
// shipping Electron's default icon.
cpSync(appIconSource, path.join(targetResources, 'langju-agent.icns'));
cpSync(appIconSource, path.join(targetResources, 'electron.icns'));
// Ship both appearance variants.  Electron selects the matching PNG at
// runtime for Dock/window tiles; the ICNS files remain available to
// LaunchServices and to future asset-catalog based packaging.
for (const [appearance, variant] of Object.entries(iconVariants)) {
  cpSync(variant.icns, path.join(targetResources, `langju-agent-${appearance}.icns`));
  cpSync(variant.png, path.join(targetResources, `langju-agent-icon-${appearance}-1024.png`));
}
const targetElectronExecutable = path.join(targetApp, 'Contents', 'MacOS', 'Electron');
const targetBrandedExecutable = path.join(targetApp, 'Contents', 'MacOS', executableName);
if (existsSync(targetElectronExecutable) && !existsSync(targetBrandedExecutable)) {
  renameSync(targetElectronExecutable, targetBrandedExecutable);
}
mkdirSync(targetProject, { recursive: true });
mkdirSync(path.join(targetProject, 'dist'), { recursive: true });
cpSync(path.join(root, 'dist', 'renderer'), path.join(targetProject, 'dist', 'renderer'), { recursive: true });
cpSync(path.join(root, 'dist', 'desktop'), path.join(targetProject, 'dist', 'desktop'), { recursive: true });
cpSync(path.join(root, 'packages'), path.join(targetProject, 'packages'), { recursive: true });
cpSync(path.join(root, 'package.json'), path.join(targetProject, 'package.json'));
cpSync(path.join(root, 'LICENSE'), path.join(targetProject, 'LICENSE'));
cpSync(path.join(root, 'docs/licenses'), path.join(targetProject, 'docs/licenses'), { recursive: true });
packageDesktopRuntimeDependencies(root, targetProject);
if (packageProfile === 'lite') {
  const componentManifest = path.resolve(process.env.AICS_RUNTIME_COMPONENT_MANIFEST || path.join(root, 'dist', 'runtime-components', `${process.platform}-${process.arch}`, 'runtime-components.json'));
  if (!existsSync(componentManifest)) throw new Error('轻量版缺少按需能力组件清单，请先运行 npm run build:runtime-components。');
  cpSync(componentManifest, path.join(targetProject, 'runtime-components.json'));
}
cpSync(path.join(root, 'services', 'api'), path.join(targetProject, 'services', 'api'), {
  recursive: true,
  filter: (source) => !path.relative(path.join(root, 'services', 'api'), source).split(path.sep)
    .some(part => ['workspace-data', '__pycache__', '.pytest_cache', '.venv', 'tests', 'sidecar'].includes(part)),
});

// Keep Electron's explicit worker path and PyInstaller's internal fallback on
// exactly the same SDK bundle. Neither requires development node_modules.
const packagedWorker = path.join(targetProject, 'services/api/app', workerName);
cpSync(sidecarBuild.worker, packagedWorker);

const portableSidecarTarget = path.join(targetProject, 'services', 'api', 'sidecar', 'aics-api');
if (existsSync(portableSidecarSource)) {
  mkdirSync(path.dirname(portableSidecarTarget), { recursive: true });
  // PyInstaller's macOS one-dir build contains convenience symlinks from
  // `_internal` into the build cache.  Dereference them while copying so the
  // delivered app is self-contained; an external symlink invalidates the
  // bundle signature and can make LaunchServices fall back to Electron's
  // default icon/identity.
  copyTreeDereferenced(portableSidecarSource, portableSidecarTarget);
}
verifySidecarBuild(root, portableSidecarTarget, packageProfile);

const plist = path.join(targetApp, 'Contents', 'Info.plist');
const bundleIcon = existsSync(path.join(targetResources, 'langju-agent.icns')) ? 'langju-agent.icns' : 'electron.icns';
const appVersion = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')).version;
for (const [key, value] of [['CFBundleDisplayName', APP_NAME], ['CFBundleName', APP_NAME], ['CFBundleIdentifier', 'com.aicreativestudio.desktop'], ['CFBundleExecutable', executableName], ['CFBundleShortVersionString', appVersion], ['CFBundleVersion', appVersion]]) {
  setPlistValue(plist, key, value);
}
setPlistIconMetadata(plist, bundleIcon);

const pythonPath = path.join(targetProject, 'services', 'api', '.venv', 'bin', 'python');
const portableSidecarExecutable = path.join(portableSidecarTarget, process.platform === 'win32' ? 'aics-api.exe' : 'aics-api');
let pythonRuntime = { exists: existsSync(pythonPath), portable: false, isSymlink: false, linkTarget: null, resolvedPath: null };
if (pythonRuntime.exists) {
  try {
    const stat = lstatSync(pythonPath);
    const resolvedPath = realpathSync(pythonPath);
    pythonRuntime = {
      exists: true,
      portable: resolvedPath.startsWith(`${targetProject}${path.sep}`),
      isSymlink: stat.isSymbolicLink(),
      linkTarget: stat.isSymbolicLink() ? readlinkSync(pythonPath) : null,
      resolvedPath,
    };
  } catch {
    pythonRuntime = { ...pythonRuntime, portable: false };
  }
}
const metadata = {
  productName: APP_NAME,
  generatedAt: new Date().toISOString(),
  packageProfile,
  staticIconAppearance,
  appPath: targetApp,
  rendererEntry: path.join(targetProject, 'dist', 'renderer', 'index.html'),
  apiEntry: path.join(targetProject, 'services', 'api', 'app', 'main.py'),
  bundledPython: existsSync(pythonPath) ? pythonPath : null,
  pythonRuntime,
  portableSidecar: existsSync(portableSidecarExecutable) ? portableSidecarExecutable : null,
  iconVariants: Object.fromEntries(Object.keys(iconVariants).map((appearance) => [appearance, {
    icns: path.join(targetResources, `langju-agent-${appearance}.icns`),
    png: path.join(targetResources, `langju-agent-icon-${appearance}-1024.png`),
  }])),
  sidecarRuntime: {
    exists: existsSync(portableSidecarExecutable),
    executable: existsSync(portableSidecarExecutable) ? portableSidecarExecutable : null,
    mode: existsSync(portableSidecarExecutable) ? 'pyinstaller-onedir' : 'python-venv',
  },
  agentRuntime: {
    worker: packagedWorker,
    frozenWorker: path.join(portableSidecarTarget, '_internal', 'app', workerName),
    sourceDigest: sidecarBuild.manifest.sourceDigest,
    workerDigest: sidecarBuild.manifest.workerDigest,
    standaloneSmokePassed: true,
  },
  note: existsSync(portableSidecarExecutable)
    ? 'Packaged app prefers the portable PyInstaller sidecar; the development Python venv is intentionally omitted.'
    : 'This unpacked bundle includes a development Python environment or external symlink. Build the portable sidecar before signing/notarizing.',
};
writeFileSync(path.join(releaseRoot, 'BUILD-METADATA.json'), `${JSON.stringify(metadata, null, 2)}\n`, 'utf8');
writeFileSync(path.join(releaseRoot, 'README.txt'), `${APP_NAME} macOS unpacked bundle\n\nOpen "${APP_NAME}.app". The app starts the local FastAPI sidecar on 127.0.0.1:8765 and stores projects in ~/Documents/Langju Design Studio.\n`, 'utf8');
// Re-sign after replacing Electron's plist, executable name, icons, and the
// bundled sidecar.  An ad-hoc signature is sufficient for local development
// and keeps Finder/Stage Manager willing to resolve the branded bundle.
execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', '--timestamp=none', targetApp]);
refreshLaunchServices();
console.log(`Packaged: ${targetApp}`);
console.log(`Static macOS icon: ${staticIconAppearance} (${appIconSource})`);
console.log(`Sidecar runtime: ${metadata.sidecarRuntime.mode}`);
