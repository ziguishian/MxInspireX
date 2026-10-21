import { afterEach, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { devWorkspace } from './dev-api.mjs';
const roots = [];
afterEach(() => roots.splice(0).forEach(root => rmSync(root, { recursive: true, force: true })));
function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'langju-dev-api-')); roots.push(root);
  mkdirSync(path.join(root, '.local'));
  return root;
}
it('preserves the default on a fresh checkout and honors an explicit environment override', () => {
  const root = fixture();
  expect(devWorkspace(root, {})).toBe(path.join(root, 'services/api/workspace-data'));
  expect(devWorkspace(root, { AICS_WORKSPACE_ROOT: 'chosen' })).toBe(path.join(root, 'chosen'));
});
it('reuses the saved workspace across launches and refuses a missing database', () => {
  const root = fixture();
  writeFileSync(path.join(root, '.local/dev-api.json'), JSON.stringify({ workspaceRoot: 'original' }));
  expect(() => devWorkspace(root, {})).toThrow('不会自动切换到空工作区');
  mkdirSync(path.join(root, 'original')); writeFileSync(path.join(root, 'original/catalog.sqlite'), '');
  expect(devWorkspace(root, {})).toBe(path.join(root, 'original'));
  expect(devWorkspace(root, {})).toBe(path.join(root, 'original'));
  expect(devWorkspace(root, { AICS_WORKSPACE_ROOT: 'override' })).toBe(path.join(root, 'override'));
});
