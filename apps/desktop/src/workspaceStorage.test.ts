import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { copyWorkspace, validateWorkspaceDestination } from './workspaceStorage.js';

let root: string, source: string, target: string;
beforeEach(async () => {
  const base = path.resolve('.tmp');
  await mkdir(base, { recursive: true });
  root = await mkdtemp(path.join(base, 'workspace-storage-'));
  source = path.join(root, 'source'); target = path.join(root, 'target');
  await mkdir(source); await mkdir(target);
  await writeFile(path.join(source, 'catalog.sqlite'), 'catalog');
  await mkdir(path.join(source, 'project'));
  await writeFile(path.join(source, 'project', 'image.png'), Buffer.from([0, 1, 255, 42]));
});
afterEach(async () => { if (root) await rm(root, { recursive: true, force: true }); });

describe('workspace storage migration', () => {
  it('copies the complete workspace while retaining originals', async () => {
    await copyWorkspace(source, target);
    expect(await readFile(path.join(target, 'catalog.sqlite'), 'utf8')).toBe('catalog');
    expect(await readFile(path.join(target, 'project', 'image.png'))).toEqual(await readFile(path.join(source, 'project', 'image.png')));
    expect(await readFile(path.join(source, 'catalog.sqlite'), 'utf8')).toBe('catalog');
  });
  it('rejects existing target content without overwriting it', async () => {
    await writeFile(path.join(target, 'keep.txt'), 'keep');
    await expect(copyWorkspace(source, target)).rejects.toThrow('空文件夹');
    expect(await readFile(path.join(target, 'keep.txt'), 'utf8')).toBe('keep');
  });
  it('rejects self, child and parent destinations', async () => {
    for (const destination of [source, root, path.join(source, 'project')]) {
      await expect(validateWorkspaceDestination(source, destination, 'migrate')).rejects.toThrow('独立目录');
    }
  });
  it('requires a catalog to open an existing workspace', async () => {
    await expect(validateWorkspaceDestination(source, target, 'existing')).rejects.toThrow('catalog.sqlite');
    await writeFile(path.join(target, 'catalog.sqlite'), 'other');
    await expect(validateWorkspaceDestination(source, target, 'existing')).resolves.toMatchObject({ to: await import('node:fs/promises').then(fs => fs.realpath(target)) });
  });
  it('does not follow junctions or symbolic links into external data', async () => {
    await symlink(target, path.join(source, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
    await expect(copyWorkspace(source, target)).rejects.toThrow('链接');
  });
});
