# 交互网页生成

对话入口由主 Agent 组织信息层级、视觉方向与页面交互，按需复用或生成图片、文案、视频、音频。不会为每个网页机械调用全部媒体模型，也不新增提示词润色模型或确认步骤。节点入口继续只执行用户当前输入，不继承对话设计指令、不额外生成媒体。

## 素材与执行

新素材由 `design_plan.deliverables[].supporting=true` 标识，HTML 最终交付通过 `dependsOn` 以及 `inputs` 中 `source=deliverable, role=content` 引用。这些素材不改变用户最终交付的类型与数量，但仍走原有任务、计费、取消、依赖就绪和未知结果保护；禁止项不能以内部素材名义绕过。已有素材直接复用，不重复收费。HTML 必须实际引用声明的内容媒体。

`canvas_create_html` 支持 `asset://真实ID`，适用于图片、video、audio、source 和 CSS URL。只嵌入当前任务有权访问的项目资产；预览与导出均使用本地 data URL，不开放供应商 URL 或应用接口。最多 12 项媒体；单图 8 MB、图片合计 16 MB；单视频或音频 32 MB，所有媒体合计 64 MB。超限明确报错，不擅自压缩或再生成。`imageAssetIds` 保留兼容，新记录同时提供 `mediaAssetIds`、`videoAssetIds`、`audioAssetIds`。

## 样式与交互

`style_framework=bootstrap` 嵌入固定版本 Bootstrap 5.3.8 CSS 和 bundle JS，默认作为对话网页的组件基础。Agent 仍须按任务定制排版、留白、配色和响应式，框架本身不是视觉质量保证。`none` 支持用户明确要求的自包含实现；不依赖 CDN、远程字体或运行时下载。框架文件校验 SHA-384，并随侧车与 Windows 包分发，保留 Bootstrap / Popper MIT 声明。

筛选需改变实际内容并提供重置/空状态；切换需显示对应视图；表单需校验与可见反馈，没有后端时明确是本地演示；媒体使用真实来源、原生 controls，不默认有声自动播放。此版本不提供登录、支付、服务器表单或数据库服务。

iframe 使用 `allow-scripts allow-forms`，允许本地表单提交事件，CSP 仍禁止表单导航、网络连接及外部脚本，且不授予同源权限。离线 HTML 导出保留组件和媒体。编辑时读取 authored HTML 与 `styleFramework`，跳过可信框架正文；保存时继承框架，避免反复让模型重写第三方代码。SVG 边界只豁免本地哈希验证后完全匹配的框架代码，用户自行写入的 SVG 仍按现有策略检查。

## 验证

- `test_web_generation.py`：计划范围、用户否定、节点隔离、媒体引用、编辑/导出、框架幂等及 SVG 边界。
- `web_generation.test.mjs`、`htmlPreview.test.ts`：工具可见范围、媒体解析与沙箱策略。
- `npm run test:web-interactions`：隔离 Electron 中实测预览及离线导出的 Bootstrap 标签页、折叠、筛选、表单校验与反馈、WAV 和 MP4 播放。测试不调用真实收费 Provider，不读写用户项目。

2026-10-24 首轮验证：559 项 Vitest 通过、3 项既有跳过；105 项相关 Python 用例通过；typecheck、桌面构建和上述真实交互回归通过。后续已修复 SDK fixture 的 Windows `file://` 路径和 UTF-8 协议，并将 SVG 预检拒绝纳入已有参数纠错机制；此前排除的 8 项 `test_real_sdk_tool_filter_and_batch_gate` 已全部通过，含共享 fixture 的技能/SVG 测试共 73 项通过。未调用真实收费模型验证生成审美，不将组件接入视为所有模型输出均合格。
