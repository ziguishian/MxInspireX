import { mkdtempSync, realpathSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { fileURLToPath } from 'node:url';
import { packageDesktopRuntimeDependencies, verifyDesktopRuntimeDependencies } from './desktop-runtime-dependencies.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

describe('desktop runtime dependencies', () => {
  it('copies a self-contained dependency tree outside the source checkout', () => {
    const app = mkdtempSync(path.join(tmpdir(), 'langju-desktop-runtime-'));
    try {
      packageDesktopRuntimeDependencies(root, app);
      verifyDesktopRuntimeDependencies(app);
      const require = createRequire(path.join(app, 'dist', 'desktop', 'main.js'));
      const resolved = require.resolve('extract-zip');
      expect(resolved.startsWith(path.join(realpathSync(app), 'node_modules', 'extract-zip'))).toBe(true);
      expect(typeof require('extract-zip')).toBe('function');
      expect(require.resolve('electron-updater').startsWith(path.join(realpathSync(app), 'node_modules', 'electron-updater'))).toBe(true);
    } finally {
      rmSync(app, { recursive: true, force: true });
    }
  });
});
