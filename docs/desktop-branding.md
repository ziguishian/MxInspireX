# 桌面品牌统一核对（2026-10-24）

产品显示名称统一为 `MxinspireX`，公司为「灵矩绘境」。应用图标使用已确认的橙色标记，Agent 吉祥物保持独立。GitHub 仓库路径 `MxInspireX` 不属于显示名称。

| 平台／状态 | 来源及规则 |
| --- | --- |
| Windows 开发启动 | `launch-dev-macos.mjs` 在 `dist/dev/windows-<摘要>/` 复制运行时，通过 `windows-branding.mjs` 生成 MxinspireX.exe；不修改 node_modules。摘要变化产生新目录，避免覆盖运行中文件。 |
| Windows 安装版／便携版 | `package-windows.mjs` 使用同一 PE 图标／版本信息写入函数；安装器、程序目录、exe、归档及能力包使用 MxinspireX。 |
| Windows 任务栏／通知 | AppUserModelId 与已有 NSIS appId 一致；窗口及通知使用当前主题 PNG。固定到旧 Electron.exe 的快捷方式仍需取消固定后重新固定新程序。 |
| macOS 开发／发布 | 均为 MxinspireX.app，显示名称和可执行文件 MxinspireX；完整／轻量打包器、校验脚本路径一致。安装前检测同时覆盖新旧名称的运行中应用。 |
| macOS Finder／未启动／Stage Manager | 使用构建时所选主题的 ICNS；静态包图标不会随运行时主题自动切换。 |
| 运行中／最小化／主题切换 | 主进程统一设置窗口 PNG；macOS 同步 Dock 图标。主题变化保持同一品牌标记，仅切换已有深浅变体。 |
| 页面标题／标题栏／关于 | 统一 MxinspireX；关于页与 favicon 随主题切换。加载动效使用同一 Logo 的透明轮廓蒙版，颜色由主题 CSS 控制。 |
| Linux | 目前没有专用安装包、.desktop 文件或 AppImage 发布入口；共享窗口代码已有名称和 PNG，不声称完成 Linux 桌面集成实测。 |

唯一母版：`scripts/brand-assets/mxinspirex-app-icon-{dark,light}.png`。通过 `scripts/brand-assets/export-app-icon.py` 导出网页 PNG、64px favicon、原生 PNG、ICNS 和 ICO；历史 `langju-agent` 资源文件名保留兼容。不要使用旧素材重新生成应用图标。

保持已有 appId／Bundle ID、工作区目录、用户数据目录和存储键不变。macOS 旧名称应用不会被本次代码修改自动删除；新旧安装升级、系统图标缓存及固定快捷方式需要发布前真机验证。已发布的历史包不重写。

验证入口：

- `python scripts/brand-assets/verify-app-icons.py`：逐像素核对母版、网页、原生 PNG、ICNS、favicon、ICO 及 ICO 尺寸。
- `npx vitest run scripts/windows-branding.test.mjs scripts/windows-update-installer.test.mjs`：实际 PE 资源写入与安装身份／更新配置。
- `npm run build`，然后 `node node_modules/electron/cli.js scripts/test-window-chrome.cjs`：深色、浅色、自定义主题标题栏与 favicon。

Windows 开发运行可验证；macOS 的签名、Finder、Dock、Stage Manager 和安装升级需在 macOS 验证。源码／资源检查不能代替平台真机结果。

本轮验证结果：图标像素核对通过；4 项 Windows PE／安装器测试通过；前端与桌面构建、类型检查通过；Electron 深色、浅色、自定义主题检查通过。Windows 已实际从新 MxinspireX.exe 打开「首页 · MxinspireX」，后端健康且沿用原工作区。PE 的 ProductVersion／FileVersion 字符串显式使用三段版本，避免 Electron 更新模块拒绝四段版本号；固定版本资源仍按 Windows 四段格式保存。未制作或发布新安装包，未验证旧版安装升级。
