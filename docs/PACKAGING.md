# 桌面发布包

2026-10-22 的公开源码发布使用 `MxinspireX-0.2.0-source-时间戳.zip`，包含五种语言 README、`docs/USER_GUIDE.md` 和 `docs/images/` 实测截图。源码不含个人工作区、凭据或依赖，使用 `npm run start:portable` 启动；它不等同于下述独立桌面安装包。发布验收见 [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md)。

无数据源码开发包的换机说明见根目录 `RUN_IN_CODEX.md`。执行 `python3 scripts/package-source.py` 输出带时间戳的源码 ZIP、逐文件清单及整体校验和。源码包保留源码、锁文件及程序静态资源，排除工作区、凭据、依赖和构建产物；在新电脑运行 `npm run start:portable` 安装本机依赖并启动网页/API。归档后应在独立解压副本运行 `npm run verify:portable`，不能仅以 ZIP 校验代替可启动性验证。

macOS 构建机执行 `npm run package:all`，输出到带时间戳的 `dist/packages/LangjuAgent-版本-时间`，不会覆盖正在使用的 `dist/release`。

轻量版执行 `npm run package:lite`。它输出相同的 macOS/Windows 安装版和绿色版，但主程序只带核心 API；本地 CAD/三维几何和 FFmpeg 分别位于 `components/<平台>/`，由“设置 → 能力组件”按需安装。组件先核对随构建清单固定的 SHA-256，再解压到当前用户的应用数据目录，永远不写入项目工作区。设置 `AICS_COMPONENT_BASE_URL=https://...` 后构建时，清单会生成 HTTPS 下载地址；内部或离线构建不设置该变量，安装按钮会让用户选择同版本的 `component.zip`。

构建工具：Node.js、项目 Python 虚拟环境（含 PyInstaller）、uv、macOS Xcode command line tools，以及 NSIS 的 `makensis`（可用 `brew install nsis` 安装）。

产物：

| 平台 | 安装版 | 绿色版 |
| --- | --- | --- |
| macOS，与构建机架构一致 | `.pkg`，安装至 `/Applications` | `.zip`，解压后双击 `.app` |
| Windows x64 | NSIS `.exe`，默认安装到当前用户目录 | `.zip`，完整解压后双击 `LangjuAgent.exe` |

Windows 完整版内置官方 Electron x64、Python 3.13.15 embeddable、锁定的 Windows 原生依赖与 FFmpeg；轻量版的核心 Python 仍完全内置，CAD 和 FFmpeg 改为能力包。Python 归档用官方 SHA-256 校验，Electron 用官方 SHASUMS 校验，依赖按 uv.lock 导出并强制 wheel / hash 校验。无需用户预装运行环境。系统凭据写入 Windows Credential Manager，定时任务自带 tzdata；Agent 输出管道支持 Windows。

macOS 内置 PyInstaller 服务和打包后的 SDK worker。启动检查用独立临时工作区，禁止连接用户项目或调用付费模型。安装脚本会拒绝覆盖正在 `/Applications` 中运行的旧应用。

单独补打 Windows：`AICS_DISTRIBUTION_DIR=绝对输出目录 npm run package:win`。输出目录下不能已有 `windows-x64/LangjuAgent`，避免覆盖可运行文件。运行环境下载可以续传。

验证：

- `node scripts/smoke-packaged-macos.mjs /绝对路径/朗居设计Agent.app`
- `services/api/.venv/bin/python scripts/verify-windows-package.py /绝对输出目录`
- Windows 真机另需验证：首次启动、保存/读取/删除测试 Key、无真实费用的 Agent 模拟任务、时区计划、安装/卸载与关闭进程。结构检查不能替代真机测试。

发布证书尚未配置：Windows 未作 Authenticode 签名；macOS 使用 ad-hoc 本地签名，尚未 Developer ID 签名和公证。正式外部分发时需使用发布者证书签名及公证，不能宣称免系统安全提示。

API Key、个人项目库、虚拟环境和测试数据不进入发布包。卸载保留个人项目和系统凭据。

Electron 主进程直接导入的 npm 包必须位于根 `dependencies`，并通过 `scripts/desktop-runtime-dependencies.mjs` 复制到发行包的 `resources/app/node_modules`。发布校验必须确认这些依赖来自应用包内部，避免位于源码目录时意外向上解析开发环境依赖、换机后才暴露启动失败。

## 本地 CAD 运行依赖

CadQuery 2.8.0 及其原生依赖由 `services/api/uv.lock` 固定。完整版中 Mac 随 PyInstaller sidecar 分发、Windows 随内置 Python 分发；轻量版中 Mac 使用独立签名的 CAD worker，Windows 使用独立的锁定 wheel 目录。`AICS_PYPI_MIRROR` 只更改 wheel 下载地址，不改变版本或哈希；缺少的镜像文件回退到官方地址。

`scripts/cad-licenses.py` 收集实际 wheel 的许可证。OCCT 7.9.3 的官方 LGPL 文本、附加条款和源代码地址另存于 `services/api/notices`，随两个平台分发。Windows 安装目录包含 `CAD-SMOKE.cmd`，可直接使用内置 Python 运行原生 CAD 测试。

PDF 页面视觉读取使用 `pypdfium2`。`scripts/pdfium-licenses.py` 从实际锁定的 wheel 收集许可与通知，sidecar 将其放入 `PDFIUM-LICENSES`；PyInstaller 同时显式收集 `pypdfium2` 与 `pypdfium2_raw`，确保 PDFium 动态库进入离线发行包。

仅前端发生变化时，先运行 `npm run build`，可使用 `node scripts/package-distributions.mjs --reuse-builds` 复用已验证的 sidecar。Mac 打包仍会检查 sidecar 的源码摘要，API 有变化时必须重新 `npm run build:sidecar`。已有目录可能含正在运行的应用，建议每次使用新的 `AICS_DISTRIBUTION_DIR`。

CAD 验证命令和实际平台测试状态见 [本地 AI CAD](cad.md)。

## 含数据的演示版迁移包

用户明确要求备份现用演示版时，先核对实际进程、`/health` 和工作区，再在无活动任务时正常退出应用，冷复制实际 `.app`、工作区（含 SQLite/WAL、全部项目资产）与界面数据。这是个人备份，不是清空数据的公共发行包；系统凭据库中的密钥不导出，换机需要重新配置凭据。

复制品的 `catalog.sqlite.projects.root_path` 和各 `project.json.rootPath` 必须可重定位，不能在原路径仍存在时引用原工作区。旧演示版的迁移修复仅在旧路径不存在时发生，因此封装时可将复制品根路径改为不存在的统一迁移前缀，首次启动再由原逻辑重建到包内位置。原工作区不修改。归档检查文件校验、ZIP CRC、SQLite 完整性，并从独立副本启动验证全部项目根目录与 API 端口隔离。升级另用新构建包，保留用户正在使用的应用身份、工作区及配置，实际启动后再次核对 health 两个版本标记和内嵌 worker 摘要。
