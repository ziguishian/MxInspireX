# 基于 OpenAI Agents SDK 的会话与上下文

每个项目使用稳定的主 Session，每条用户消息对应独立任务。主会话历史由 SDK 追加，任务记录负责界面、调度和结果展示。研究使用独立阶段 Session；资料通过 ID、正文摘录和真实工具回执交接。

## 官方能力与存储边界

- `Runner`、`Session`、`RunState`、`sessionInputCallback`、`callModelInputFilter` 来自已安装的 OpenAI Agents SDK。
- `sdk_context.mjs` 的 `ProjectSession` 通过内部 `/agent-session` 接口读写 SQLite。适配器提供版本检查、串行写入和幂等事务，不实现另一套模型历史循环。
- 主会话 ID 为 `project:{projectId}`；阶段 ID 为 `project:{projectId}:task:{taskId}:{stage}`。项目运行串行，SQLite 写入还会核对拥有任务与版本。
- `sdk_sessions` 保存 SDK 回放历史；`sdk_session_raw` 保存未压缩回放；`sdk_session_archive` 保存破坏性变更前的版本；`sdk_session_operations` 防止重复提交事务。
- 首次读取时从现有任务导入可获得的用户原文与答复，明确失败、取消和待核实状态。不会补造缺失工具消息或重新调用模型。

演示路径的会话优化（2026-10-14）：`session_blobs.py` 将 SDK 历史中的内联图片按项目和 SHA-256 无损去重、压缩到 `sdk_session_blobs`；回放历史、原始历史及版本只保存引用，接口还原原始内容。旧 Session 在首次访问时按单个会话原子迁移，保留 revision、操作摘要及完整原文，不批量改写实际工作区或执行 VACUUM。迁移释放的页由 SQLite 后续复用，数据库文件不会立即缩小。

已初始化会话的 `get/archive` 使用只读事务，避免争用写锁；`limit=0` 不载入图片。持有会话的 worker 缓存已确认历史，只在服务端确认成功后应用事务；重放、应答丢失或 release 后失效。新进程仍从服务器读取，版本与任务所有权检查不变。缓存失效不会自动重发任何生成或会话写入。

## 恢复

`agent_checkpoints` 使用版本 2，保存官方 RunState 字符串、模型配置签名、阶段结果、响应 ID、调用次数和完整可回放边界。恢复时重新注入凭据，以相同 Agent/工具/模型调用 `RunState.fromStringWithContext`，再交给 Runner。原请求不作为新的一轮输入追加。

SDK 0.17.2 对带有旧进程 Session 事务权限的序列化状态会明确拒绝反序列化。对此仅使用 SDK 指定的历史恢复方式：核对已保存会话是完整回放的前缀、工具调用都有回执，再通过幂等事务补入缺失历史，以空新增输入继续 Runner。不删除或修改 SDK 的安全字段。历史不一致、缺失回执或模型配置改变时停止，不猜测恢复。

进程退出后 `ExecutionStore` 先核对收费工具回执、本地资产和媒体任务。不确定的收费请求保持待核对，禁止通过改写参数重新生成。模型响应序号、同类错误修正次数和阶段累计恢复次数都进入检查点，跨重启继续累计；旧检查点只在首次进入新流程时导入，之后使用版本 2。

## 上下文选择

首轮确实没有历史、已选记忆、引用、附件、续接或计划时，由本地 `prepare_empty_selection` 保存空选择并标记 `analysisMode=empty_catalog`。它不生成用户事实，也不改变原始需求；Agent 仍可按原文保存有长期用途的新信息。有上下文或参考的任务继续由 Agent 做语义选择。普通回答结束后不再仅为记忆整理追加模型回合；用户明确要求记忆操作或存在待修正的记忆写入时仍需完成。

`ProjectContextResolver` 按本轮引用、连续任务、相关项目历史、有限检索的顺序选择资料。显式引用优先，区分素材与修改对象；历史模型回答不是事实来源。研究后的网页制作即使没有重新启动研究 Agent，也会继承本项目的来源与正文。

阶段交接包含当前要求、时间基准、研究摘录、证据 ID 与类型、产物 ID、版本、检查问题和媒体状态。直接使用已有输出与回执，不增加总结模型调用。运行中的回执也直接参与交接，避免阶段切换抢在后台检查点落盘之前。

每轮任务的 `designState` 另存用户决策与来源，供执行、提问和界面共享；它是从用户原文或已校验提问答案得到的业务数据，不替代 SDK Session。继续执行时保留原始目标与已接受的交付清单，新增修改要求优先；旧来源和临时假设不能覆盖新确认信息。详见 [设计范围与交付计划](design-planning.md)。

- `context_read` 按 ID、查询和偏移读取证据、对话或产物，复用原有项目权限与画布范围规则。
- 正文、搜索摘要和用户文档分别标为 `web_body`、`search_summary`、`user_document`，保留可获得的来源、抓取时间、发布时间与摘录位置。未知时间不推测。
- 引用图片以原生多模态消息送入模型；重复图片优先保留当前轮版本。Chat Completions 的工具图片转换为原生用户图片内容。
- 每次动态输入保留当前需求全文、最近 4 轮原始对话、已选记忆、设计状态和仍待完成的交付项。旧轮次仍保存在 Session 中，可通过现有读取工具按需取得。
- 大 HTML、文档和工具正文留在已有存储中。调用前把历史工具结果缩减为状态、资产/节点 ID、关键错误及回执引用，保留合法 JSON 和调用/结果配对；旧图片去除 Base64 与重复视觉描述，仅当前实际使用的参考图保留规范化预览。
- 工具定义按研究、生成阶段和待交付类型裁剪，不向 Luna 重复发送无关的媒体工具。动态输入估算超过 12K tokens 时先在本地压至约 8K；当前要求、来源 ID、回执和未完成项不得静默丢弃。
- 节点读取时保存内容版本；写回时核对，阻止旧任务覆盖用户的新修改。

## 保存与交付

生成成功后直接交付，设计质量由用户判断。已删除独立审查模型、审查输入和解析、质量问题提示、审查缓存与审查重试；旧任务的审查结论不再展示，也不再阻塞消息队列。

本地交付记录只确认真实文件、数量与必要的预览加载状态。`deliveryStatus` 的 `pending` / `needs_review` 保留兼容，用于生成中、未完成交付和真实运行异常。`delivery_findings.py` 只提供对应操作原因；未确认结果仍保留计费核对与禁止重复提交规则。视频和迟到图片通过本地保存状态结束任务，无额外模型调用。

## 本地优先的混合压缩

已完成的旧轮次降为纯文字记录时，`sdk_context.mjs` 移除该请求视图中的原消息 ID，避免 Responses 将它关联到已省略的 reasoning/tool 条目而返回 400。当前轮次及其 reasoning、调用和回执继续保留配对，规范 Session 与原生压缩窗口不变，不额外调用模型。参考 [OpenAI reasoning 上下文约定](https://developers.openai.com/api/docs/guides/reasoning)。

工具定义规模在选择上下文之前计入容量。超出本地目标时，同一用户轮次中较早的已完成工具调用也会转为带调用 ID、状态和资产/节点 ID 的短回执；最新工具批次、未完成调用、各工具最新待修正校验结果和当前用户原文保留，调用/结果始终配对。规范 Session 不变，原生压缩返回的完整窗口不再裁剪。`localCompacted` 只在实际缩减后报告，必要上下文仍超目标时记录 `localBudgetExceeded`，不把固定规则或用户要求静默截断。

设置中的 `memory.compactionEnabled` 默认开启。所有兼容入口先使用上述本地精简；若精简后仍超过“16K tokens 或模型上下文窗口 40%中的较小值”、且任务仍有待完成交付项，才在确认的 OpenAI 官方 Responses 入口调用一次 `OpenAIResponsesCompactionSession`。它使用本地 `input` 模式，每个任务最多尝试一次，不按固定轮数触发。

适配层把 SDK 的清空和追加合成一次 SQLite 原子替换；原始历史保留。原生压缩作为独立模型调用计费与展示，不计入失败恢复次数，也不自动重试。失败后停用本轮原生压缩并继续使用本地精简和按需读取，不阻断任务。切换供应商、入口或模型签名时，恢复未经压缩的回放，不发送不透明压缩项给未确认兼容的服务。

独立 `/responses/compact` 返回的整个窗口作为规范回放保留，包括不透明压缩项及仍然保留的消息、工具调用和结果；后续本地过滤不再改写、截断该窗口。压缩调用前写入尝试检查点；恢复后沿用尝试次数与停用状态，不因超时、异常或切换入口重复压缩。尚未触发、正在压缩、已完成、失败后使用本地精简、入口未确认兼容分别展示；兼容性跳过和预算拦截不计作已提交的压缩调用。规模仍是保守字符估算，界面标注“估算”，不冒充服务端实际 token 用量。

## 提示词缓存

`prompt_cache.mjs` 只在模型请求边界应用缓存策略，不改写规范 Session 或成功工具回执。固定 Agent 规则作为稳定前缀；时间、项目状态、证据和已停止工具说明放在历史之后的动态上下文消息中，已选记忆继续受保护。所有入口共用这一组织方式。

确认的 OpenAI 官方入口发送按会话和规则摘要生成的稳定 `prompt_cache_key`；确认的 OpenRouter 入口同时发送稳定 `session_id`，保持同一会话的粘性路由。GPT-5.6 及之后的已知 OpenAI 模型使用显式缓存边界，缓存规则和工具定义，动态上下文与一次性工具正文不设置写入边界。SDK 0.17 的 developer 消息经 provider passthrough 只出现在发出的请求视图中。较早模型保留隐式缓存。CloseAI、自定义中转和未知模型不发送未确认支持的新缓存选项，继续使用稳定前缀与上游自动缓存；不通过付费预热、探测或错误重发争取命中。

读取 Responses、Chat Completions 和 SDK 用量中的 `cached_tokens` / `cache_write_tokens`；缺失统计与明确零命中区分。任务进度展示累计读取比例、缓存写入量和部分调用缺少统计的情况；累计计数进入检查点及 trace 白名单，重复响应 ID 不重复累计。命中率以实际返回缓存统计的输入 token 为分母，包含原生压缩调用。日志不保存提示词、缓存内容或凭据。计费规则见 [model-pricing.md](model-pricing.md)。

依据：[OpenAI 提示词缓存](https://developers.openai.com/api/docs/guides/prompt-caching)、[OpenAI 压缩](https://developers.openai.com/api/docs/guides/compaction)、[OpenRouter 提示词缓存与粘性会话](https://openrouter.ai/docs/guides/best-practices/prompt-caching)。

## 诊断与验证

`sdk_context_manifests` 记录阶段、Session/检查点版本、资料 ID、节点版本、输入规模、工具定义规模、响应 ID、账单 ID 与实际积分。任务进度另外保存 `model_call`、`recovery_attempt` 和 `context_compaction` 的白名单计数、模型、阶段、耗时与 token 用量，供刷新、重连和重启后继续展示；不记录提示词、图片数据、凭据或隐藏推理。官方 RunState 属于恢复数据，不作为界面思考过程展示。

本地测试入口：

```sh
services/api/.venv/bin/python -m pytest services/api/tests -q
npm test
npm run test:context-optimization
npm run typecheck
```

测试使用模拟 API 与临时数据库，覆盖真实 SDK 的 Responses/Chat Completions 会话和恢复、OpenRouter/CloseAI 协议、研究证据继承、原生图片、合法 JSON 与配对、节点版本冲突、媒体防重、有限补证、本地压缩、原生压缩计费/失败/供应商切换。它们不证明每家中转站当前在线接口或实际价格始终正确，也不产生真实模型费用。

### 执行事实独立于正文精简

`execution_frame.mjs` 从当前 scope/revision、批次、交付进度与成功/未知回执生成有版本的执行投影。`sdk_context.mjs` 在裁剪说明正文后完整附加该投影，保留交付 ID、依赖、真实节点/资产 ID 和 `reuse` / `reconcile_only` / `generate` / `wait` 动作。它不是另一次模型摘要，也不改写规范 Session。模型容量估算计入实际展开的批量分支和严格工具契约；控制数据仍超过目标时如实报告，不为了满足字符目标丢失未完成项或防重复收费状态。
