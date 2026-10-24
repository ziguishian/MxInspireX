# MxinspireX

**本地优先 AI 设计 Agent 与无限画布 · 从一句需求，到一套设计。**

[![最新版本](https://img.shields.io/github/v/release/ziguishian/MxInspireX?style=flat-square&color=4b8bd8&label=Release)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Windows x64](https://img.shields.io/badge/Windows-x64-4b8bd8?style=flat-square)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Non-Commercial License](https://img.shields.io/badge/License-Non--Commercial-c79a49?style=flat-square)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/ziguishian/MxInspireX?style=flat-square&color=c79a49&label=Stars)](https://github.com/ziguishian/MxInspireX/stargazers)

MxinspireX 是灵矩绘境出品的 **AI 设计工作区**，面向设计师、创意团队和产品创作者，支持不同领域的设计任务，用来把需求与参考资料变成可继续编辑、比较和导出的设计作品。

你可以上传产品图、品牌资料或文档，用自然语言说明需求；Agent 结合上下文调用模型，将产品概念、包装、海报、IP 形象、场景图等结果放到同一个无限画布。后续可以继续对话修改，也可以连接节点，让上游文字或图片成为下一次生成的参考。

> **描述需求 → 加入参考 → Agent 生成 → 画布比较与修改 → 导出作品**

项目与文件保存在本机。使用云模型需配置自己的 API Key，模型调用按服务商计费；软件不附带免费额度。

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

[下载安装包](https://github.com/ziguishian/MxInspireX/releases) · [使用指南](docs/USER_GUIDE.md) · [产品事实与能力边界](docs/product-facts.md) · [问题反馈](https://github.com/ziguishian/MxInspireX/issues)

## 工作区预览

<img width="3840" height="1978" alt="MxinspireX 设计工作区与画布示例一" src="https://github.com/user-attachments/assets/838a1600-51fa-4382-81ea-13d7e9d9834b" />

<details>
<summary>展开更多画布与设计示例</summary>

<img width="3840" height="1978" alt="MxinspireX 设计工作区与画布示例二" src="https://github.com/user-attachments/assets/a53fa767-5d18-4aa2-9ae0-758ecd35e7a2" />
<img width="3840" height="1978" alt="MxinspireX 设计工作区与画布示例三" src="https://github.com/user-attachments/assets/005e4846-60de-4e4f-bb43-4ee812f649b7" />

</details>

## 能做什么

- **设计创作**：Logo、海报、产品、包装、IP 潮玩、空间效果图，以及文字策划和交互 HTML。
- **同款产品一致性**：先生成主图，再把真实主图传给场景生成；局部编辑保留来源和原作品。
- **持续项目与无限画布**：对话、文件和图片引用、批量任务、节点版本、布局、预览与导出。
- **多种产物**：图像、音频、视频、外部 3D 服务，以及本地参数化 CAD。具体能力取决于已配置服务和模型。
- **真实用量**：展示 Token 和人民币费用，区分服务商已确认扣费、参考估算与待对账。
- **本地数据**：项目和文件保存在本机，凭据使用系统凭据库或环境变量。所选云模型仍会接收完成任务所需的内容。

Agent 按依赖组织任务：就绪的独立产物可并行，依赖新主图的场景顺序生成。生成完成后直接交付，由人判断设计质量；未知收费请求不会自动重复提交。

## 快速启动

只使用软件可直接到 [GitHub Releases](https://github.com/ziguishian/MxInspireX/releases) 下载 Windows x64 安装包；以下是源码启动方式。

Windows 安装版支持更新提示，仅在用户确认后下载、重启安装。构建与发布步骤见 [桌面更新发布说明](docs/desktop-updates.md)。

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

## 常见问题

**MxinspireX 是否完全离线？** 项目与文件保存在本机，但使用云模型时仍会发送本次任务必要内容。

**是否包含免费模型额度？** 不包含。需要自己的 API Key，费用以服务商回执为准；非商业许可不等于模型调用免费。

**是否支持多种生成类型？** 支持图像、文本、视频、音频、HTML、CAD 等入口，具体能力取决于模型配置。外部 3D 服务需独立配置。

**生成的包装能直接生产吗？** 概念图片不能替代结构校核、工艺参数与打样确认。

面向搜索与 AI 阅读的资料索引见 [llms.txt](llms.txt)。独立公开介绍页构建与域名配置见 [SEO/GEO 说明](docs/search-discovery.md)。

## Star History

如果这个工作区对你有帮助，欢迎 Star，或通过 [Issues](https://github.com/ziguishian/MxInspireX/issues) 分享使用反馈。

<a href="https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
    <img width="800" alt="MxinspireX GitHub Star 增长历史" src="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
  </picture>
</a>

[在 Star History 查看交互图表](https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date)

## 许可与联系

当前源码采用 [MxinspireX 非商业许可 1.0](LICENSE)：允许非商业学习、研究、修改与分享；商业部署、收费服务、付费客户项目及商业设计生产须事先取得书面授权。它是源码可用许可，不属于 OSI 定义的开源许可。此前按 MIT 发布的版本（包括 v0.2.1）及已授予的权利保持原许可，不追溯变更。第三方依赖、字体和引擎遵循各自许可，见 `services/api/notices/`；用户资料和产物的所有权不因此转移。商业授权联系下方邮箱。

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
