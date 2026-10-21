# MxinspireX

**从一句需求，到一套设计。** 灵矩绘境出品的本地优先 AI 设计工作区，将对话、参考资料和无限画布连接起来。

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

![同款产品主图、场景与局部编辑](docs/images/product-workflow.png)

## 能做什么

- **设计创作**：Logo、海报、产品、包装、IP 潮玩、空间效果图，以及文字策划和交互 HTML。
- **同款产品一致性**：先生成主图，再把真实主图传给场景生成；局部编辑保留来源和原作品。
- **持续项目与无限画布**：对话、文件和图片引用、批量任务、节点版本、布局、预览与导出。
- **多种产物**：图像、音频、视频、外部 3D 服务，以及本地参数化 CAD。具体能力取决于已配置服务和模型。
- **真实用量**：展示 Token 和人民币费用，区分服务商已确认扣费、参考估算与待对账。
- **本地数据**：项目和文件保存在本机，凭据使用系统凭据库或环境变量。所选云模型仍会接收完成任务所需的内容。

Agent 按依赖组织任务：就绪的独立产物可并行，依赖新主图的场景顺序生成。生成完成后直接交付，由人判断设计质量；未知收费请求不会自动重复提交。

## 快速启动

准备 **Node.js 22 或 24**（含 npm）和 **uv**，然后：

```sh
git clone https://github.com/ziguishian/MxInspireX.git
cd MxInspireX
npm run start:portable
```

首次启动会按锁文件安装依赖，并由 uv 准备 Python 3.12。打开终端显示的网址；默认是 `http://127.0.0.1:5173`，端口冲突时自动选择空闲端口。按 Ctrl+C 停止。

1. 点击左下角头像 → **设置 → 模型与连接**。
2. 选择服务商并填入自己的 Key。**EvoLink 官方地址已内置，只需填 Key**。
3. 同步模型目录，选择需要的文本与媒体模型。
4. 回到首页描述需求，可上传图片或文档，提交后在项目画布查看结果。

当前界面以中文为主；五种语言 README 不代表界面已完成五语本地化。源码与发布包不附带账号、Key、额度或个人项目。3D 服务需要单独配置。

## 图文使用指南

[打开完整使用指南](docs/USER_GUIDE.md)：首次配置、同款场景、局部编辑、文件驱动海报、HTML、CAD、导出和费用查询，附真实使用截图。

```text
为“暖屿”设计两张 1:1 图片：先做陶土香薰炉产品主图，
再沿用首图产品制作窗边木桌场景，保持造型、材质和颜色一致。
只生成这两张，不做额外研究。
```

## 开发与验证

```sh
npm run setup:portable    # 安装锁定依赖
npm run verify:portable   # 独立空工作区启动检查，不调用模型
npm run typecheck
npm test
npm run api:test
npm run build:web
npm run build            # 桌面前端及 Electron 编译
```

桌面开发：先运行 `node node_modules/electron/install.js`，再执行 `npm run dev`。打包流程见 [PACKAGING](docs/PACKAGING.md)，迁移启动见 [RUN_IN_CODEX](RUN_IN_CODEX.md)。源码 ZIP 是可安装依赖后运行的开发包，不是免安装的桌面二进制。

| 目录 | 内容 |
| --- | --- |
| `apps/renderer` | Vue 3、TypeScript、Vite、Vue Flow 界面 |
| `apps/desktop` | Electron 主进程、preload 和桌面导出 |
| `services/api` | FastAPI、Python 业务服务、Node Agent worker |
| `packages/contracts` | 跨前端模块的数据契约 |
| `scripts` / `docs` | 构建、验证、迁移和技术说明 |

便携启动的数据默认在 `.local/portable-workspace/`；备份、移动或升级前先停止应用。不要提交工作区、数据库、`.env` 或凭据。私人案例原图不随源码分发：布局测试仍执行，缺少整套原图时两项素材完整性测试会明确跳过；部分素材缺失仍会报错。

更多信息：[开发指南](AGENTS.md) · [Agent 链路](docs/agent-flow.md) · [实测记录](docs/browser-design-sweep-20261022.md) · [发布验证](docs/RELEASE_VALIDATION.md)

## 许可与联系

代码沿用仓库的 [MIT 许可](LICENSE)。第三方依赖、字体和引擎遵循各自许可，相关说明见 `services/api/notices/`；案例与用户上传内容的权利归各自权利人。

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
