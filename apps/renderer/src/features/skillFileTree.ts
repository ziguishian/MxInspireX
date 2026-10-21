export interface SkillPackageFile {
  path: string;
  byteSize?: number;
  mime?: string;
}

export interface SkillFileTreeRow {
  path: string;
  name: string;
  depth: number;
  kind: 'directory' | 'file';
  byteSize?: number;
  mime?: string;
  collapsed?: boolean;
}

interface DirectoryNode {
  name: string;
  path: string;
  directories: Map<string, DirectoryNode>;
  files: SkillPackageFile[];
}

function compareName(left: { name: string }, right: { name: string }) {
  return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: 'base' });
}

/** Turns the flat package manifest into rows suitable for a familiar file tree. */
export function buildSkillFileTree(files: SkillPackageFile[], collapsedDirectories: ReadonlySet<string> = new Set()): SkillFileTreeRow[] {
  const root: DirectoryNode = { name: '', path: '', directories: new Map(), files: [] };

  for (const file of files) {
    const segments = file.path.split('/').filter(Boolean);
    if (!segments.length) continue;
    let parent = root;
    for (let index = 0; index < segments.length - 1; index++) {
      const name = segments[index];
      const path = parent.path ? `${parent.path}/${name}` : name;
      let directory = parent.directories.get(name);
      if (!directory) {
        directory = { name, path, directories: new Map(), files: [] };
        parent.directories.set(name, directory);
      }
      parent = directory;
    }
    parent.files.push({ ...file, path: segments.join('/') });
  }

  const rows: SkillFileTreeRow[] = [];
  const visit = (directory: DirectoryNode, depth: number) => {
    for (const child of [...directory.directories.values()].sort(compareName)) {
      const collapsed = collapsedDirectories.has(child.path);
      rows.push({ path: child.path, name: child.name, depth, kind: 'directory', collapsed });
      if (!collapsed) visit(child, depth + 1);
    }
    for (const file of [...directory.files].sort((left, right) => {
      if (left.path === 'SKILL.md') return -1;
      if (right.path === 'SKILL.md') return 1;
      return compareName({ name: left.path.split('/').at(-1) || left.path }, { name: right.path.split('/').at(-1) || right.path });
    })) {
      rows.push({
        path: file.path,
        name: file.path.split('/').at(-1) || file.path,
        depth,
        kind: 'file',
        byteSize: file.byteSize,
        mime: file.mime,
      });
    }
  };

  visit(root, 0);
  return rows;
}
