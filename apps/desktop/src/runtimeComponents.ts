import { createHash } from 'node:crypto';
import { chmodSync, createReadStream, createWriteStream, cpSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { dialog } from 'electron';
import extract from 'extract-zip';

export type RuntimeComponentState = {
  id: string;
  label: string;
  description: string;
  installed: boolean;
  available: boolean;
  bytes: number;
  source: 'download' | 'file';
};

type RuntimeComponentDefinition = {
  id: string;
  label: string;
  description: string;
  archiveName: string;
  sha256: string;
  bytes: number;
  downloadUrl?: string | null;
  environment: Record<string, string>;
};

type RuntimeComponentManifest = {
  schemaVersion: 1;
  version: string;
  profile: 'lite';
  platform: string;
  arch: string;
  components: RuntimeComponentDefinition[];
};

function validRelativePath(value: string) {
  return Boolean(value) && !path.isAbsolute(value) && !value.split(/[\\/]/).some(part => part === '..');
}

async function digest(filename: string) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

export class RuntimeComponentManager {
  private readonly manifest: RuntimeComponentManifest | null;
  private readonly installRoot: string;

  constructor(projectRoot: string, userDataRoot: string) {
    const manifestPath = path.join(projectRoot, 'runtime-components.json');
    this.manifest = existsSync(manifestPath) ? this.readManifest(manifestPath) : null;
    const version = this.manifest?.version || 'development';
    this.installRoot = path.join(userDataRoot, 'runtime-components', version, `${process.platform}-${process.arch}`);
  }

  private readManifest(filename: string): RuntimeComponentManifest {
    const value = JSON.parse(readFileSync(filename, 'utf8')) as RuntimeComponentManifest;
    if (value.schemaVersion !== 1 || value.profile !== 'lite' || !Array.isArray(value.components)) {
      throw new Error('按需组件清单格式无效。');
    }
    if (value.platform !== process.platform || value.arch !== process.arch) {
      throw new Error(`按需组件平台不匹配：${value.platform}-${value.arch}`);
    }
    for (const component of value.components) {
      if (!/^[a-z][a-z0-9-]*$/.test(component.id) || !/^[a-f0-9]{64}$/.test(component.sha256) || !component.archiveName.endsWith('.zip')) {
        throw new Error('按需组件清单包含无效条目。');
      }
      if (!component.environment || Object.values(component.environment).some(entry => !validRelativePath(entry))) {
        throw new Error(`按需组件 ${component.id} 的运行路径无效。`);
      }
      if (component.downloadUrl && new URL(component.downloadUrl).protocol !== 'https:') {
        throw new Error(`按需组件 ${component.id} 只允许从 HTTPS 下载。`);
      }
    }
    return value;
  }

  private definition(id: string) {
    const component = this.manifest?.components.find(item => item.id === id);
    if (!component) throw new Error('这个版本没有提供所选能力组件。');
    return component;
  }

  private componentRoot(id: string) {
    return path.join(this.installRoot, id);
  }

  private marker(id: string) {
    return path.join(this.componentRoot(id), '.installed.json');
  }

  private isInstalled(component: RuntimeComponentDefinition) {
    try {
      const marker = JSON.parse(readFileSync(this.marker(component.id), 'utf8')) as { sha256?: string };
      return marker.sha256 === component.sha256
        && Object.values(component.environment).every(relative => existsSync(path.join(this.componentRoot(component.id), relative)));
    } catch {
      return false;
    }
  }

  status(): RuntimeComponentState[] {
    return (this.manifest?.components || []).map(component => ({
      id: component.id,
      label: component.label,
      description: component.description,
      installed: this.isInstalled(component),
      available: Boolean(component.downloadUrl),
      bytes: component.bytes,
      source: component.downloadUrl ? 'download' : 'file',
    }));
  }

  environment() {
    const result: Record<string, string> = {};
    for (const component of this.manifest?.components || []) {
      if (!this.isInstalled(component)) continue;
      for (const [key, relative] of Object.entries(component.environment)) {
        result[key] = path.join(this.componentRoot(component.id), relative);
      }
    }
    return result;
  }

  private async download(component: RuntimeComponentDefinition) {
    if (!component.downloadUrl) return null;
    mkdirSync(path.join(this.installRoot, '.downloads'), { recursive: true });
    const destination = path.join(this.installRoot, '.downloads', component.archiveName);
    const response = await fetch(component.downloadUrl, { signal: AbortSignal.timeout(60 * 60 * 1000) });
    if (!response.ok || !response.body) throw new Error(`组件下载失败（HTTP ${response.status}）。`);
    await pipeline(Readable.fromWeb(response.body as never), createWriteStream(destination));
    return destination;
  }

  private async selectArchive(component: RuntimeComponentDefinition) {
    const result = await dialog.showOpenDialog({
      title: `选择“${component.label}”能力包`,
      properties: ['openFile'],
      filters: [{ name: '朗居能力包', extensions: ['zip'] }],
    });
    return result.canceled ? null : result.filePaths[0] || null;
  }

  async install(id: string) {
    const component = this.definition(id);
    const archive = await this.download(component) || await this.selectArchive(component);
    if (!archive) return { cancelled: true, components: this.status() };
    if (await digest(archive) !== component.sha256) throw new Error('能力包 SHA-256 校验失败，文件可能不完整或版本不匹配。');

    mkdirSync(this.installRoot, { recursive: true });
    const staging = path.join(this.installRoot, `.installing-${component.id}-${process.pid}`);
    rmSync(staging, { recursive: true, force: true });
    mkdirSync(staging, { recursive: true });
    try {
      await extract(archive, { dir: staging });
      const extracted = path.join(staging, component.id);
      if (!existsSync(extracted)) throw new Error('能力包缺少预期的组件目录。');
      for (const relative of Object.values(component.environment)) {
        if (!existsSync(path.join(extracted, relative))) throw new Error(`能力包缺少运行文件：${relative}`);
      }
      const target = this.componentRoot(component.id);
      rmSync(target, { recursive: true, force: true });
      try {
        renameSync(extracted, target);
      } catch {
        cpSync(extracted, target, { recursive: true });
      }
      if (process.platform !== 'win32') {
        for (const relative of Object.values(component.environment)) chmodSync(path.join(target, relative), 0o755);
      }
      writeFileSync(this.marker(component.id), `${JSON.stringify({ sha256: component.sha256, installedAt: new Date().toISOString() }, null, 2)}\n`);
    } finally {
      rmSync(staging, { recursive: true, force: true });
    }
    return { cancelled: false, components: this.status() };
  }
}
