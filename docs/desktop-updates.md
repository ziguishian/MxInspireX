# 桌面版本检测与手动更新

更新源：公开仓库 `ziguishian/MxInspireX` 的正式 GitHub Releases。应用 ID 沿用 `com.aicreativestudio.desktop`，当前版本读根 `package.json`，本次没有修改版本号，也没有发布。

2026-10-22 核对：仓库公开，当前 Latest tag 为 `v0.2.0-20261022`，仅有源码归档与校验文件，没有 NSIS 安装器或更新 yml。需按本文发布首个带更新能力的安装版本；现有源码 Release 不能作为可安装更新。

## 用户操作与安全边界

- 正式 Windows NSIS 安装版启动 12 秒后检查一次，不阻塞首屏。没有新版本时不弹窗；错误仅在更新入口显示，不自动循环请求。
- 左下角头像上方是更新入口。发现新版本变蓝，弹窗显示当前版本、最新版本与说明。同一版本在当前组件会话只提示一次。
- 点击「立即下载」才下载；显示百分比、失败原因与手动重试。关闭弹窗不取消已确认的下载。
- 下载完成单独提示「立即重启更新」「稍后重启」。只有前者调用 `quitAndInstall(false, true)`。关闭弹窗、退出软件均不会自动安装（`autoDownload=false`、`autoInstallOnAppQuit=false`）。下次启动会重新检查，用户再次确认下载时由 updater 校验并复用缓存。
- 主进程拥有状态机、单实例锁、下载与安装；preload 只暴露查询、检查、下载、安装、订阅接口。IPC 限制为应用主窗口主 frame 及本地入口 URL，不允许隐藏交付 worker、预览 frame 或导航到外部站点的窗口调用。
- 保留 electron-updater 的 SHA512/大小检查与已配置发布者的 Windows 签名校验，不注入 GitHub Token，不覆盖验证函数，不降级安装。
- 开发模式（含 `AICS_DEV_MODE=1`）、便携版、macOS 不进行更新网络请求。浏览器页面没有 Electron 更新按钮。开发桌面可打开按钮查看禁用原因。

## 打包

原有 Python/Node/能力组件运行环境组装继续使用 `scripts/package-windows.mjs`。先创建无更新源的 portable ZIP，再通过 `scripts/windows-update-installer.mjs` 把同一预组装目录交给 electron-builder 26 创建 NSIS 安装器。不要直接运行裸 `electron-builder`，否则会缺少项目的运行环境组装步骤。

```powershell
npm ci
npm run typecheck
npx vitest run apps/desktop/src/appUpdates.test.ts scripts/windows-update-installer.test.mjs scripts/desktop-runtime-dependencies.test.mjs scripts/package-guard.test.mjs
npm run package:win
```

继续使用原有 `AICS_PYTHON`、`AICS_UV`、`AICS_DISTRIBUTION_DIR` 等构建配置；electron-builder 管理 NSIS，不再要求手动设置 `AICS_MAKENSIS`。完整环境依赖仍遵守原发布流程。

轻量 Windows 版：设置 `AICS_PACKAGE_PROFILE=lite` 后运行 `npm run package:win`。两种版本使用相同发布 tag，但各自的元数据和安装包不混用：

| 版本 | 元数据 | 安装包及差分文件 |
| --- | --- | --- |
| 完整版 | `latest.yml` | `LangjuAgent-<version>-windows-x64-setup.exe` 和同名 `.exe.blockmap` |
| 轻量版 | `lite.yml` | `LangjuAgent-<version>-lite-windows-x64-setup.exe` 和同名 `.exe.blockmap` |

使用两个独立输出目录构建两种版本，避免预组装目录覆盖。最终将两种更新元数据及对应文件上传到同一正式 Release。portable ZIP 可额外上传，但不是更新文件。`app-update.yml` 位于安装目录的 `resources` 内，指向对应 channel；不要手改 `latest.yml`/`lite.yml` 的文件名、大小或 SHA512。

## 人工发布步骤

打包入口现有发布前置检查，详见 [Agent 发布检查](agent-release-check.md)。失败时先修复，不跳过生命周期脚本；检查不会发布版本或调用收费模型。

1. 确定新 SemVer 版本，运行 `npm version <新版本> --no-git-tag-version` 更新根清单与锁文件，提交审核过的改动。
2. 在 Windows 构建、验证完整和轻量安装包。建议把本版本说明写入 `build/release-notes.md`，也在 GitHub Release 正文填写说明。
3. 在仓库创建与版本一致的 tag，例如 `v0.2.1`，先创建 Draft Release。
4. 上传上表所有文件及可选便携包，确认两个 channel 的安装包均来自本次构建、hash 匹配。确认完成后由维护者将 Draft 发布为正式 Release，并设为 Latest。不要用 prerelease 验证稳定版用户更新。
5. 本地脚本固定 `publish: 'never'`，即使环境里有 Token 也不会上传。通过 GitHub 网页人工上传不需要在项目存 Token；若后续使用 CI，发布 job 需要 `contents: write` 权限或有对应仓库写权限的发布凭证，只放 GitHub Secrets/CI 环境，绝不能打入客户端。

旧自定义 NSIS 安装包没有更新功能。首次需要用户手动安装本实现的新安装包，之后才能接收后续更新；建议先退出旧软件并卸载旧安装程序（保留工作区和配置），避免旧卸载项与新安装目录共存。

## 签名与平台限制

- 当前只接入 Windows x64 NSIS；无签名构建会有 Windows 未知发布者/SmartScreen 提示，不能视作已完成正式发布签名验收。
- 配置 Windows 签名时使用 `WIN_CSC_LINK`/`WIN_CSC_KEY_PASSWORD`（或 electron-builder 的 `CSC_LINK`/`CSC_KEY_PASSWORD`），并设置 `WIN_PUBLISHER_NAME` 为证书发布者名称。脚本将该名称同时放入安装器签名配置和更新源的 `publisherName`，保留安装更新时的签名验证。设置证书但没有发布者名称会中止构建。证书及密码只保存在构建环境。
- 当前复用 prepackaged 目录，electron-builder 会签 NSIS 安装器，但不会重新签已组装的应用 EXE。正式签名流水线还需在组装完成、生成 portable ZIP/NSIS 之前签好 `LangjuAgent.exe` 及所需可执行文件；不要把仅安装器签名等同于整包签名。
- macOS 现有包仅 ad-hoc 签名，未接入自动更新。启用前需要 Apple Developer ID Application、hardened runtime、公证、签名的应用 ZIP/DMG 与 `latest-mac.yml`，并在真实 Mac 验证；当前仍用原人工下载安装流程。Linux 与其他 Windows 架构不在本次支持范围。

## 验证发布链路

在干净 Windows 测试机/虚拟机安装带更新功能的版本 A，再由维护者发布较高版本 B（同一 appId/相同签名身份、正确 channel）。验证启动后收到提示；点击稍后不产生下载；立即下载显示进度；断网后错误可重试；下载完成点稍后再退出不会安装；重新打开并确认缓存下载后，点击立即重启，完成 NSIS 安装且 `app.getVersion()` 为 B，项目和配置仍在。再检查应无新版本弹窗。重复点击只启动一次操作。

自动化测试覆盖状态机、禁用条件、IPC 调用来源、并发去重、无更新、失败重试、进度和确认安装。UI 模拟测试不能替代签名包校验、真实下载、差分更新、UAC、覆盖安装与重启后的数据保留验证。不得把测试夹具安装包上传正式 Release。

本次验证：状态机与现有运行依赖/打包保护测试通过，类型检查和前端/桌面编译通过；浏览器模拟验证了稍后操作不下载/安装、进度、失败重试和确认重启。electron-builder 配置通过其 schema 校验，运行依赖复制后可在独立目录解析。真实 NSIS 构建尚未完成：当前环境没有 Electron 二进制，官方分发下载持续无响应后停止；因此未验证安装器、真实 GitHub 更新、签名、差分、覆盖安装和重启。仓库没有 Lint 脚本，未声称执行 Lint。
