import { cpSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

// These packages are imported by the compiled Electron main process. Electron
// does not bundle application dependencies, so every release must carry them
// inside resources/app instead of accidentally resolving the development
// checkout's node_modules directory.
export const desktopRuntimeDependencies = ['extract-zip', 'electron-updater'];

function packagePath(nodeModules, name) {
  return path.join(nodeModules, ...name.split('/'));
}

function resolveManifest(name, parentManifest) {
  return createRequire(parentManifest).resolve(`${name}/package.json`);
}

function copyPackage(name, parentManifest, targetNodeModules, copied) {
  const manifest = resolveManifest(name, parentManifest);
  const key = `${targetNodeModules}\0${name}`;
  if (copied.has(key)) return;
  copied.add(key);

  const source = path.dirname(manifest);
  const target = packagePath(targetNodeModules, name);
  mkdirSync(path.dirname(target), { recursive: true });
  cpSync(source, target, {
    recursive: true,
    filter: entry => path.basename(entry) !== 'node_modules',
  });

  const metadata = JSON.parse(readFileSync(manifest, 'utf8'));
  const nestedNodeModules = path.join(target, 'node_modules');
  for (const dependency of Object.keys(metadata.dependencies || {})) {
    copyPackage(dependency, manifest, nestedNodeModules, copied);
  }
}

export function packageDesktopRuntimeDependencies(projectRoot, appRoot) {
  const projectManifest = path.join(projectRoot, 'package.json');
  const metadata = JSON.parse(readFileSync(projectManifest, 'utf8'));
  const targetNodeModules = path.join(appRoot, 'node_modules');
  const copied = new Set();
  for (const dependency of desktopRuntimeDependencies) {
    if (!metadata.dependencies?.[dependency]) {
      throw new Error(`桌面运行依赖 ${dependency} 必须声明在 dependencies 中。`);
    }
    copyPackage(dependency, projectManifest, targetNodeModules, copied);
  }
  verifyDesktopRuntimeDependencies(appRoot);
}

function verifyPackage(name, targetNodeModules, checked) {
  const directory = packagePath(targetNodeModules, name);
  const manifest = path.join(directory, 'package.json');
  const key = `${targetNodeModules}\0${name}`;
  if (checked.has(key)) return;
  checked.add(key);
  if (!existsSync(manifest)) throw new Error(`发行包缺少桌面运行依赖：${name}`);
  const metadata = JSON.parse(readFileSync(manifest, 'utf8'));
  for (const dependency of Object.keys(metadata.dependencies || {})) {
    verifyPackage(dependency, path.join(directory, 'node_modules'), checked);
  }
}

export function verifyDesktopRuntimeDependencies(appRoot) {
  const targetNodeModules = path.join(appRoot, 'node_modules');
  const checked = new Set();
  for (const dependency of desktopRuntimeDependencies) {
    verifyPackage(dependency, targetNodeModules, checked);
  }
}
