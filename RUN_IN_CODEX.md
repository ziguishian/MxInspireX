# 在另一台电脑启动MxinspireX

这是 0.2.0 演示版的可迁移源码开发包。默认启动网页开发版，包含完整前端、API、Agent、CAD 与媒体代码；Electron 桌面源码也保留。包内没有个人项目、数据库、历史会话、Key 或本机环境。

## 交给 Codex

完整解压到一个可写目录，在新电脑的 Codex 中打开该目录，将下面这段话发给它：

> 阅读 AGENTS.md 和 RUN_IN_CODEX.md，按本机系统准备 Node.js 22 或 24 与 uv。执行 npm run setup:portable，然后执行 npm run verify:portable。检查通过后运行 npm run start:portable，并给我实际可打开的网址。使用默认空工作区，不导入历史数据，不调用收费模型。不要改业务代码来绕过环境问题。

## 直接启动

准备 Node.js 22 或 24（含 npm）和 uv，将它们加入 PATH。首次安装需要联网下载锁定依赖，uv 会准备 Python 3.12，无需手动激活虚拟环境。uv 缺失时，可让 Codex 安装；已安装 Python 和 pip 的电脑也可以执行 `python -m pip install uv`，再重新打开终端。

在解压目录执行：

```sh
npm run start:portable
```

这条命令会安装依赖并启动前后端。之后再次运行会复用本机已安装依赖。访问终端给出的地址；默认网页端口为 5173，API 为 8765。端口被占用时会选择空闲端口，并同步配置前端，避免连到另一个正在运行的项目。

全部路径按解压目录计算；新数据保存在 `.local/portable-workspace/`。不会沿用原电脑的 `.local/dev-api.json`、桌面工作区配置或环境中的工作区路径。按 Ctrl+C 停止两个服务；修改 Python 后端后重新运行。需要指定其他目录时使用 `npm run start:portable -- --workspace "绝对路径"`。

## 安装、验证与开发

```sh
npm run setup:portable
npm run verify:portable
npm run typecheck
npm run build:web
```

`setup:portable` 重新按 `package-lock.json` 和 `services/api/uv.lock` 安装本机依赖，不改锁文件。`verify:portable` 启动真实 API 与 Vite，核对健康检查、空项目列表、前端入口及 API 地址，然后自动退出并删除临时数据。它不会提交 Agent 任务或调用模型。仅启动已安装的环境可用 `npm run start:portable -- --no-install`。

macOS、Windows、Linux 共用 Node 启动脚本；虚拟环境使用各自的路径，不复制其他系统的 `node_modules` 或 `.venv`。Windows 可使用 PowerShell 或 CMD；无需执行 Bash、激活脚本或修改 PowerShell 执行策略。CAD 原生依赖能否安装取决于平台提供的 wheel；安装失败时保留错误信息，不用假结果代替该能力。

模型生成需要配置自己的服务地址和 API Key。macOS / Windows 可在应用设置中保存 Key；Linux 当前没有系统凭据写入适配器，应在启动环境中设置对应的 `AICS_PROVIDER_KEY_OPENROUTER` 或 `AICS_PROVIDER_KEY_OPENAI_COMPATIBLE`，不要把 Key 写入源码。没有 Key 时仍可打开界面和空工作区；本包不附带账号或额度。首次安装完成后本地界面可启动，模型和在线检索仍按所选服务使用网络。

默认网页入口无需 Electron 二进制。需要桌面开发时，先安装依赖，再执行 `node node_modules/electron/install.js`，使用 `npm run dev`；桌面环境和平台打包要求另见 `docs/PACKAGING.md`。迁移验收以 `verify:portable` 的网页/API 路径为准，不将它当作 Windows/Linux 桌面安装包验证。

## 无数据包的范围

保留程序静态资源（图标、首页封面、内置预览、字体）、内置技能、测试夹具和演示配置清单。排除个人工作区、SQLite/WAL/SHM、上传资料、历史产物、演示导入原始素材、本地配置、凭据、缓存、依赖及安装包。完整的已保存演示项目不会自动恢复。涉及原始案例素材的 `ce-ma-showcase` 和 `ci-jin-showcase` 专项测试需另行提供素材，不能用它们代替无数据启动验收。

`SOURCE_MANIFEST.json` 记录归档文件 SHA-256；包外提供整个 ZIP 的校验和与本次实际验证报告。
