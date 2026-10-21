# 联网搜索连续失败修复

> 历史记录：本页描述的 web 插件方案已于 2026-09-14 被 Agents SDK → OpenRouter 服务端搜索取代，见 [当前实现](SEARCH_ROUTING_2026-09-14.md)。

日志来源：本地 catalog.sqlite 的任务 `afd5049c-82e2-46d9-b75e-8fc9ef926c81` 及 `.tmp/packaged-app.log`。只读检查，未修改历史任务和积分。

2026-09-12 09:37:48–09:37:51（北京时间），研究 Agent 连续提交 8 个 `web_search`，全部收到 `HTTP 400: Invalid Responses API request`。当前服务为 OpenRouter；旧实现固定发送 OpenAI Responses 搜索请求，没有按服务适配。SDK 的并发队列仍发送后续查询，造成失败提示刷屏。后续 `web_read` 有网站拒绝抓取（403），但 `ResearchImportError` 未转换为工具错误，被显示成笼统的服务器错误。

修复：

- OpenRouter 使用 `/chat/completions` + `plugins: [{id: "web"}]`，读取嵌套 `url_citation`。支持当前本地目录中的文本模型，不再限定 OpenAI 模型。
- OpenAI / 中转站继续使用 Responses `web_search`。只有真实调用及可核验来源才算搜索成功。
- 搜索串行调度；永久错误停止本轮搜索，临时错误最多两次。状态写入 checkpoint；后续 SDK 轮次移除不可用工具，已排队调用不重复发送或打印错误。
- 相同成功查询复用本轮结果；失败网页不重复抓取。403 等错误保留具体原因，提示更换公开来源。
- 明确拒绝的 400/401/403/404/405/422 搜索释放预算预留，不产生新的待计费项；已返回的真实消费和不确定请求仍照实记账。
- 设置与执行记录统一称为“联网搜索”，并说明两个服务的协议区别。

验证使用模拟传输，未调用付费模型。新增 7 项测试覆盖 OpenRouter 请求与来源、缺少来源、400/积分、403、8 次批量调用的永久/临时失败及重启恢复。

协议依据：[OpenRouter Web Search](https://openrouter.ai/docs/guides/features/plugins/web-search)、[OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)。
