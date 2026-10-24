// Used by the existing runtime staging script; never publish from a local build.
module.exports = {
  appId: 'com.aicreativestudio.desktop',
  productName: 'MxinspireX',
  executableName: 'MxinspireX',
  publish: [{ provider: 'github', owner: 'ziguishian', repo: 'MxInspireX', releaseType: 'release' }],
  generateUpdatesFilesForAllChannels: false,
  win: { target: [{ target: 'nsis', arch: ['x64'] }], icon: 'apps/desktop/assets/langju-agent.ico' },
  nsis: { oneClick: false, perMachine: false, allowToChangeInstallationDirectory: true, deleteAppDataOnUninstall: false, license: 'LICENSE' },
};
