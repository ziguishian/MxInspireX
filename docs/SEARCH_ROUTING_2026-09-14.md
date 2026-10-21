# OpenRouter 搜索与模型默认策略（2026-09-14）

> 历史记录：下文默认路由、自动升级和固定搜索服务说明已失效。2026-10-10 的 GPT-6 默认映射、输入兼容选择及搜索继承规则见 [MODEL_ROUTER.md](MODEL_ROUTER.md)，以当前代码和测试为准。

按最终确认，联网搜索复用 OpenRouter 的地址和已保存 Key，不新增 OpenAI 官方凭据配置。主 Agent 仍使用 OpenAI Agents SDK；其 `web_search` 函数通过后端的预算、回执与联网权限检查，委托同一 SDK 运行时中的搜索 Agent 执行 hosted tool。

## 排查结论

- 10:29 的敦煌任务使用旧 OpenRouter web 插件链路，返回计费信息但没有可解析的来源，因而被判定不可用。相同服务较早的请求曾成功返回来源，不能据此认定 Key 失效。
- 本次直接验证 SDK Responses 搜索时，HTTP 400 的明确校验错误位于 `include[0]`。OpenRouter 当前不接受 `web_search_call.action.sources` 这一 OpenAI 扩展字段。精简请求后返回真实 `web_search_call`。
- OpenRouter 官方已将旧 `plugins: [{id: "web"}]` 方案标为弃用。当前实现通过 SDK 的 HostedTool 扩展发送 `openrouter:web_search`，设置 `engine: native`；兼容服务继续使用 SDK `webSearchTool()`。OpenRouter 不发送上述 include 字段，改为读取原始流中的引用标注。
- 来源来自返回的 URL citation 或已完成搜索调用的 action sources；仅有模型正文里的链接不算引用证据。既要有完成调用或供应商报告的搜索次数，也要有可核验公开来源，才返回成功。

## 默认路由

| 用途 | 默认模型与策略 |
| --- | --- |
| 搜索 | `openai/gpt-5.6-luna`，OpenRouter Responses，复用现有 Key |
| 日常文本 | FAST 为 `openai/gpt-5.6-luna`，STANDARD 也为 `openai/gpt-5.6-luna`；两档均无重复备用项。搜索仍使用 Luna |
| 强推理 | Luna 的结构化分类明确识别复杂推理难点后使用 REASONING；模型能力不足仍可逐级升级，临时服务故障不导致贵模型升级 |
| 图像 | 各质量档均为 `openai/gpt-image-2.5-sunburst` |
| 视频 | 默认及正式交付优先 `bytedance/seedance-2.5`；明确简单、短时的草稿或预览使用 `bytedance/seedance-2.0-mini` |

多阶段、长文本、一般设计调研和媒体最高质量本身不触发昂贵文本模型。视频的复杂场景、对白、长时长或音频要求优先 2.5。明确手动指定的媒体模型保留。旧版默认配置在读取时迁移；其它自定义媒体模型不替换，迁移版本随下次保存持久化。

SDK 隐式重试关闭，单次搜索总时限 60 秒，可随任务取消。永久拒绝或结果不完整会停止本轮重复搜索；查询成功可复用回执。真实 token 用量、供应商 cost 和搜索次数继续进入原计费流程，已明确拒绝且无用量的请求不扣积分。前端的失败步骤保留具体错误说明。

## 验证记录

- 最终 SDK → OpenRouter 实际调用：Luna，耗时 5.96 秒，1 次搜索，返回敦煌研究院 2 条官方引用；供应商报告成本 $0.01137963。脱敏结果：`.tmp/sdk-openrouter-search-check.json`。独立诊断调用未写入项目积分账本。
- 较早用于定位参数问题的成功诊断请求成本 $0.0119515；其余 HTTP 400 请求没有返回计费用量。此次两次成功诊断合计 $0.02333113。
- 后端完整回归 461 项通过；另增加 2 个搜索次数兼容用例后，搜索专项 21 项通过。前端 121 项通过，类型检查及桌面构建通过。
- 冻结后端通过本机模拟的 OpenRouter / 兼容服务搜索、总时限与停止重放验证；桌面包的 UI、预加载、SDK 和项目导航验证通过。已正常退出空闲旧实例并打开新版，读取运行中后端确认全部新默认值生效。当前包位于 `dist/release/朗居设计Agent.app`，旧包保留于 `dist/release-before-sdk-routing-1789355664`。
- 未额外执行收费图像、视频生成；四个指定模型已存在于用户保存的 OpenRouter 模型目录。切换图像模型不能保证所有中文排版完全无误，生成后仍需检查具体产物。

协议依据：[OpenRouter 服务端搜索](https://openrouter.ai/docs/guides/features/server-tools/web-search)、[OpenRouter Responses 搜索](https://openrouter.ai/docs/api_reference/responses/web-search)、[OpenAI 搜索工具](https://developers.openai.com/api/docs/guides/tools-web-search)。
