import { expect, test } from 'vitest';
import { buildSkillFileTree } from './skillFileTree';

test('renders a skill package as nested file-tree rows with SKILL.md at the root', () => {
  expect(buildSkillFileTree([
    { path: 'references/materials/printing.md', byteSize: 36 },
    { path: 'agents/openai.yaml', byteSize: 20 },
    { path: 'SKILL.md' },
    { path: 'references/brief.pdf', byteSize: 640 },
  ])).toEqual([
    { path: 'agents', name: 'agents', depth: 0, kind: 'directory', collapsed: false },
    { path: 'agents/openai.yaml', name: 'openai.yaml', depth: 1, kind: 'file', byteSize: 20, mime: undefined },
    { path: 'references', name: 'references', depth: 0, kind: 'directory', collapsed: false },
    { path: 'references/materials', name: 'materials', depth: 1, kind: 'directory', collapsed: false },
    { path: 'references/materials/printing.md', name: 'printing.md', depth: 2, kind: 'file', byteSize: 36, mime: undefined },
    { path: 'references/brief.pdf', name: 'brief.pdf', depth: 1, kind: 'file', byteSize: 640, mime: undefined },
    { path: 'SKILL.md', name: 'SKILL.md', depth: 0, kind: 'file', byteSize: undefined, mime: undefined },
  ]);
});

test('hides a collapsed directory descendants without hiding the directory itself', () => {
  const rows = buildSkillFileTree([{ path: 'references/brief.md' }, { path: 'SKILL.md' }], new Set(['references']));
  expect(rows.map(row => row.path)).toEqual(['references', 'SKILL.md']);
});
