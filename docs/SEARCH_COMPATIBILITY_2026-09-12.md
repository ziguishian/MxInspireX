# 联网搜索兼容性与超时修复

> 历史记录：本页描述的 web 插件方案已于 2026-09-14 被 Agents SDK → OpenRouter 服务端搜索取代，见 [当前实现](SEARCH_ROUTING_2026-09-14.md)。

## 现场问题

任务 `57167074-fc80-479b-8848-e5966e3091a4` 在 2026-09-12 10:07:08（北京时间）进入搜索，10:12:01 触发整轮 300 秒超时，随后自动重试。研究 Agent 使用 `openai/gpt-5.6-terra`，搜索却继承了任务原始配置 `aion-labs/aion-2.0`。线程采样确认后台在等待 SSL 响应。原实现同步读取整个响应，120 秒仅是网络读写超时，保活数据可让等待持续超过该时限。

## 调整后的流程

1. 搜索服务、模型的显式设置优先；留空时跟随当前执行的主 Agent / 研究 Agent，再从对应服务的本地模型目录匹配兼容模型。不重新同步目录，不把 Key 放进工具参数。
2. OpenRouter 使用 `/chat/completions` + `web` 插件；OpenAI 默认使用 `/responses` + `web_search`。OpenAI 专用 `search-api` 模型可使用 Chat Completions 的 `web_search_options`，通用 GPT 不能误用此接口。
3. 两种接口均请求流式响应；兼容网关返回完整 JSON。SSE 保活、分片、多行 data、最后一帧用量、嵌套来源和 HTTP 200 后的错误均单独处理。Responses 以最终完成事件为准，不把半截输出当成成功。
4. 搜索 HTTP 客户端使用可取消的异步连接及绝对总时限，单次最多 60 秒。任务中搜索累计最多占执行时限的 40%，上限 120 秒，并给 Agent 保留整理答复的时间。工作进程到本地网关也有独立的截止时间。
5. 超时、连接中断和结果不完整会停止本轮搜索；明确的临时服务拒绝最多再试一次。搜索失败按工具处理，不能因此升级、切换或重跑主模型。任务整体达到时限也不会误记为模型服务失败。
6. 搜索提交和结果写入持久化执行凭证。同一查询复用结果；未确认的搜索及停止状态可跨工作进程恢复，防止因重启或改写查询重复收费。明确被拒绝的请求释放预留；未知消费不伪装成免费，已返回的用量保留。
7. 执行记录显示实际搜索服务和模型，并在收到检索阶段/来源时更新简短进度。无法取得的事实明确标注未核验。

关闭连接可以结束应用等待，但不能承诺供应商停止计费。OpenRouter 文档明确列出部分供应商不支持通过断开连接取消后端推理。

## 验证

- 搜索协议、持续保活、流中途错误、截断、用量、模型继承、专用 Search API、取消和持久化去重的回归测试。
- SDK 工具网关响应头或响应体一直不返回时，搜索按时结束，已排队查询不继续发送，Agent 可返回带限制说明的答复。
- 路由测试确认工具超时和整体时限不会触发备用模型或档位升级。
- 本机当前只配置了 OpenRouter 的模型目录；OpenAI 独立服务的真实账号验证尚未执行。

协议依据：[OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)、[OpenAI Streaming](https://developers.openai.com/api/docs/guides/streaming-responses)、[OpenRouter Web Plugin](https://openrouter.ai/docs/guides/features/plugins/web-search)、[OpenRouter Streaming](https://openrouter.ai/docs/api/reference/streaming)。

实际接口检查：已通过当前配置的 OpenRouter + `openai/gpt-5.6-terra` 查询 IMO 官方首页，4.37 秒返回 `https://www.imo.org/` 来源。供应商返回 cost 为 0.0306325，搜索请求数为 1；这是独立调试请求，未写入用户项目积分。此前后端 396 项、前端 102 项测试及类型检查通过。

打包后验证：独立启动 macOS 包内的冻结后台，以本地 HTTP 服务模拟 OpenRouter 与 OpenAI Responses SSE。两个接口均正常返回来源；持续保活的请求均在配置总时限结束，改写查询也不会再次访问上游。macOS 桌面启动、内置 SDK、项目创建和导航检查通过。Windows 包内新增 HTTP 客户端及 CA 证书列入结构验证，Windows 真机运行仍待验证。
