import { cp, lstat, readdir, realpath, stat } from 'node:fs/promises';
import path from 'node:path';

export type WorkspaceChangeMode = 'migrate' | 'existing';

export async function validateWorkspaceDestination(source: string, destination: string, mode: WorkspaceChangeMode) {
  const from = await realpath(source), to = await realpath(destination);
  const nested = (a: string, b: string) => {
    const relative = path.relative(a, b);
    return !relative || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
  };
  if (nested(from, to) || nested(to, from)) throw new Error('请选择当前工作区以外的独立目录，不能使用原目录或其父子目录。');
  if (!(await stat(to)).isDirectory()) throw new Error('请选择文件夹。');
  if (mode === 'migrate') {
    if ((await readdir(to)).length) throw new Error('迁移目标必须为空文件夹，不会覆盖其中的文件。');
  } else {
    const catalog = await lstat(path.join(to, 'catalog.sqlite')).catch(() => null);
    if (!catalog?.isFile() || catalog.isSymbolicLink()) throw new Error('所选目录不是已有工作区，缺少 catalog.sqlite。');
  }
  return { from, to };
}

// Run only after the local API has exited, including its SQLite connections.
// Leave the source and any partial destination intact on failure.
export async function copyWorkspace(source: string, destination: string) {
  const { from, to } = await validateWorkspaceDestination(source, destination, 'migrate');
  async function checkTree(directory: string) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error('工作区包含链接目录或文件，请先处理链接后再迁移。');
      if (entry.isDirectory()) await checkTree(filename);
    }
  }
  await checkTree(from);
  for (const name of await readdir(from)) {
    await cp(path.join(from, name), path.join(to, name), { recursive: true, force: false, errorOnExist: true, preserveTimestamps: true });
  }
}
