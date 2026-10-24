import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import * as ResEdit from 'resedit';

// Development and release launchers must carry the same Explorer/taskbar identity.
export function brandWindowsExecutable(source, destination, icon, pkg) {
  const exe = ResEdit.NtExecutable.from(readFileSync(source), { ignoreCert: true });
  const resources = ResEdit.NtExecutableResource.from(exe);
  const icons = ResEdit.Data.IconFile.from(readFileSync(icon));
  for (const group of ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries)) {
    ResEdit.Resource.IconGroupEntry.replaceIconsForResource(resources.entries, group.id, group.lang, icons.icons.map(item => item.data));
  }
  for (const version of ResEdit.Resource.VersionInfo.fromEntries(resources.entries)) {
    version.setFileVersion(...pkg.version.split('.').map(Number), 0);
    version.setProductVersion(...pkg.version.split('.').map(Number), 0);
    for (const language of version.getAvailableLanguages()) version.setStringValues(language, {
      FileDescription: pkg.productName, ProductName: pkg.productName, CompanyName: '灵矩绘境',
      FileVersion: pkg.version, ProductVersion: pkg.version,
      OriginalFilename: path.basename(destination), InternalName: pkg.productName,
    });
    version.outputToResourceEntries(resources.entries);
  }
  resources.outputResource(exe);
  writeFileSync(destination, Buffer.from(exe.generate()));
}
