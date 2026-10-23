import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { build, Platform, Arch } from 'electron-builder';
import builderConfig from '../electron-builder.config.cjs';

export async function buildWindowsUpdateInstaller({ root, appDir, output, prefix, profile }) {
  const channel = profile === 'lite' ? 'lite' : 'latest';
  const publisherName = process.env.WIN_PUBLISHER_NAME?.trim();
  if ((process.env.WIN_CSC_LINK || process.env.CSC_LINK) && !publisherName) {
    throw new Error('Signed releases require WIN_PUBLISHER_NAME (certificate subject) for update signature validation.');
  }
  const publish = builderConfig.publish.map(item => ({ ...item, channel }));
  // prepackaged skips afterPack. JSON is valid YAML and escapes names safely.
  writeFileSync(path.join(appDir, 'resources/app-update.yml'), JSON.stringify({
    provider: publish[0].provider, owner: publish[0].owner, repo: publish[0].repo, channel,
    updaterCacheDirName: `mxinspirex-${profile}-updater`, ...(publisherName ? { publisherName: [publisherName] } : {}),
  }, null, 2));
  await build({ projectDir: root, prepackaged: appDir, targets: Platform.WINDOWS.createTarget('nsis', Arch.x64), publish: 'never',
    config: { ...builderConfig, publish, directories: { output }, artifactName: `${prefix}-setup.exe`,
      win: { ...builderConfig.win, ...(publisherName ? { signtoolOptions: { publisherName } } : {}) } } });
}
