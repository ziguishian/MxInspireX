import { describe, it, expect } from 'vitest';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import * as ResEdit from 'resedit';
import { brandWindowsExecutable } from './windows-branding.mjs';
import config from '../electron-builder.config.cjs';

const root = process.cwd();
describe('Windows executable identity', () => {
  it.skipIf(!existsSync(path.join(root, 'node_modules/electron/dist/electron.exe')))(
    'writes the approved icon and product metadata without changing Electron', () => {
      const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
      const source = path.join(root, 'node_modules/electron/dist/electron.exe');
      const original = readFileSync(source);
      const dir = path.join(root, '.tmp/windows-brand-test');
      mkdirSync(dir, { recursive: true });
      const target = path.join(dir, `${config.executableName}.exe`);
      const icon = path.join(root, config.win.icon);
      brandWindowsExecutable(source, target, icon, pkg);
      expect(readFileSync(source).equals(original)).toBe(true);
      const exe = ResEdit.NtExecutable.from(readFileSync(target));
      const resources = ResEdit.NtExecutableResource.from(exe);
      const versions = ResEdit.Resource.VersionInfo.fromEntries(resources.entries);
      expect(versions.length).toBeGreaterThan(0);
      for (const version of versions) for (const lang of version.getAvailableLanguages()) {
        expect(version.getStringValues(lang)).toMatchObject({
          FileDescription: pkg.productName, ProductName: pkg.productName,
          FileVersion: pkg.version, ProductVersion: pkg.version,
          OriginalFilename: 'MxinspireX.exe', InternalName: pkg.productName, CompanyName: '灵矩绘境',
        });
      }
      const bytes = item => Buffer.from(item.isRaw() ? item.bin : item.generate());
      const expected = ResEdit.Data.IconFile.from(readFileSync(icon)).icons.map(item => bytes(item.data));
      const groups = ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries);
      expect(groups.length).toBeGreaterThan(0);
      for (const group of groups) {
        const actual = group.getIconItemsFromEntries(resources.entries).map(bytes);
        expect(actual).toEqual(expected);
      }
    });
});
