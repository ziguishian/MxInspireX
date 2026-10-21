# 智能模型路由与积分

本次变更接入现有 `TaskRuntime → DesignRuntime → OpenAI Agents SDK` 主执行路径。使用已有 SDK 中的研究、设计、审查 Agent 协作，共享项目资料和真实工具；详见 [Agent 执行与媒体交付](AGENT_EXECUTION.md)。当前搜索与模型默认策略见 [2026-09-14 更新](SEARCH_ROUTING_2026-09-14.md)。

## 使用方式

1. 在「设置 → AI Provider」选择 OpenRouter、中转站或本地 Ollama。远程服务填写地址和 Key；Ollama 默认连接 `http://127.0.0.1:11434/v1`，无需 Key。点击「保存并同步模型目录」后调用对应服务的 `/models`，成功后把目录写入本地 SQLite；远程 Key 写入已有安全存储。OpenRouter 同时补充 `/images/models` 和 `/videos/models`。CloseAI 的普通列表可能遗漏媒体模型：用户可另行配置 `sk-admin` 目录管理密钥，后端只在显式同步时调用 `/api/v1/management/models`，按返回的 `category` 分类完整模型并读取可明确换算的人民币报价；管理密钥与生成 Key 分开保存在系统凭据库，不进入任务、日志、导出或模型调用。没有管理密钥时仍同步普通目录，并对缺失的默认媒体模型依次验证带供应商前缀和无前缀 ID；只有 API 确认的实际 ID 才加入目录，界面会标明目录可能不完整。
2. 首页、画布和设置选择器此后只读取本地目录。打开页面、模型菜单、输入 Key 都不会自动刷新中转站。修改凭据或需要更新目录时再主动同步；不同服务与地址的目录隔离保存。
3. 默认使用 **Auto**。也可以选择快速、标准、最高质量，或在高级选项中手动指定文本模型。手动模型失败时不会自动换成其他模型。
4. 「设置 → 路由与积分」可以修改四个等级的模型、主服务、备用服务、推理强度、轮数、超时、重试和升级上限。新增模型先同步本地目录，再把对应 ID 填到等级配置。模型 ID 可带网关命名空间，只有唯一同名的模型会自动匹配；不会用另一版本代替。
5. 图像默认使用智能路由：探索稿从 **GPT-Image-2.5 Flare** 开始，常规、最终稿和精修从 **GPT-Image-2.5 Sunburst** 开始；随后才尝试另一个 2.5、GPT Image 2 和兼容的 Seedream。视频优先 **`bytedance/seedance-2.5`**；明确简单的短时草稿或预览使用 **`bytedance/seedance-2.0-mini`**。高级手动选模始终只调用所选模型。

### 本地 Ollama

- 内置 Provider key 为 `ollama`，默认模型为 `gpt-oss:20b`；也接受 Ollama `/v1/models` 返回的其他真实模型 ID。可用 `AICS_OLLAMA_BASE_URL` 修改初始地址，保存后的界面地址优先。
- 同步成功后界面切换为手动文本模型模式，不改变 Luna 的自动路由默认值。Ollama 使用 Chat Completions，并可通过 OpenAI Agents SDK 执行函数工具；当前本地 `gpt-oss:20b` 已验证普通回复和 `tool_calls`。
- Ollama 仅是文本 Provider。本地文本 token 仍显示在任务进度中，但不写入积分账本，调用轨迹的计费状态为 `not_applicable`。若此前保存过可用的 OpenRouter/兼容服务媒体目录，文本切到 Ollama 后图像、视频和音频继续使用该远程媒体配置；没有媒体服务时会明确返回配置错误，不把 Ollama 冒充媒体模型。
- Ollama 不提供当前应用依赖的托管联网搜索。使用本地模型测试时建议关闭「允许联网研究」，或另行配置独立、真实支持搜索的 Provider。

### 目录分类策略

模型分类描述的是**输出能力**，不是输入能力：能看图片并输出文字的 vision 模型仍属于文本模型；能生成图片的模型才进入图像选择器。证据按以下顺序处理：

1. CloseAI 管理目录返回的 `category` 最优先，已知类别映射到 `text / image / video / audio / embedding / 3d`；无法识别的显式类别进入 `unknown`，绝不默认成文本。
2. 没有 `category` 时采用 `output_modalities`，再采用明确的端点声明，例如 `/images/generations`、`/audio/speech`、embeddings 和视频生成端点。
3. 缺少结构化元数据时才使用稳定的模型家族规则，例如 GPT-Image、DALL-E、Gemini Image、Seedream、Flux、Seedance、Sora、GPT Audio、TTS、embedding/rerank 和 3D 家族。已知生成家族可纠正中转站给所有模型套用的通用 `text` 元数据。
4. 完全没有类别信息的普通 OpenAI-compatible ID 为兼容旧中转站暂归文本，并标为低置信度；有显式但未知类别的模型保留在 `unknownModels`，界面显示“待识别”数量。

模型记录同时保存 `classificationSource` / `classificationConfidence`，便于追溯分类依据。`owned_by` 保留为中转站原始值；另用 `vendor` 表示按模型家族归一的厂商，因为部分中转站会把 DeepSeek、GLM、Kimi、Qwen、豆包和 MiniMax 统一错误标为 OpenAI。厂商字段不决定输出类型，也不能绕过本地目录的可用性校验。

2026-09-17 使用真实普通目录固化了 143 个 ID 的回归快照：132 个文本、9 个图像、2 个音频、0 个未知。该快照只验证兼容分类规则，不代表账户的永久完整目录；完整性仍以当前账户的管理目录同步结果为准。

## 路由结构

```text
任务与上下文
  → ModelRouter（本地规则选择档位与能力）
  → ExecutionPolicy（Pydantic 校验）
  → 等级配置 + 当前角色的业务工具
  → 原有 DesignRuntime / Agents SDK
  → 客观结果检查
      明确未提交的临时服务错误：当前端点最多恢复两次
      提交前本地目录明确缺少输入能力：GPT-6 Luna → GPT-6 Sol
      已提交、状态未知、工具错误或质量问题：不换模型重放
      配置缺失或用户取消：停止并返回明确原因
```

默认映射集中在 `services/api/app/model_config.py`：

| 等级 | 默认模型 | 典型任务 |
| --- | --- | --- |
| FAST | openai/gpt-6-luna | 问候、标签、提取、分类、简单翻译、JSON 转换 |
| STANDARD | openai/gpt-6-luna | 日常对话、需求总结、设计方向、附件与画布任务 |
| REASONING | gpt-6.1-sol | 用户手动选择严谨证明、多约束推导或高难度工程分析 |
| PREMIUM | gpt-6-astra | 用户手动选择最高质量 |

自动模式的轻量任务和日常设计 Agent 都使用 GPT-6 Luna；包含图片、文件或画布引用不会直接换成 GPT-6 Sol。只有调用前的本地模型目录明确声明 Luna 不支持本轮图片输入时，才在同一服务预先选择 GPT-6 Sol（`openai/gpt-6-sol`）。运行后的质量不足、工具参数错误、轮次变多或服务错误均不升级模型。GPT-6.1 Sol、GPT-6 Sol、Astra 及其他模型仍可手动选择。四个等级默认均不设置备用模型，自定义备用服务仍保留，但不会用于已提交请求的自动重放。

可用 `AICS_MODEL_FAST` / `STANDARD` / `REASONING` / `PREMIUM` 修改初始值；保存到设置后的自定义端点优先。版本 10 将未修改的 FAST / STANDARD GPT-5.6 Luna、STANDARD GPT-5.6 Terra 和 REASONING GPT-5.6 Sol 迁移到上述 GPT-6 默认值；继承服务的旧 Luna 搜索默认值也同步更新，独立搜索设置保留。版本 9 把未修改的内置 STANDARD Terra 恢复为 Luna、将旧内置轮次上限统一为 60、默认未提交恢复次数改为 2，并开启混合上下文压缩；用户自定义模型、端点、协议、角色模型、搜索设置和备用服务始终保留。版本 4—9 的旧迁移仍按原顺序执行，并保留当时的模型 ID，避免新默认值改变历史迁移判断。`AICS_IMAGE_MODEL` 仍显式覆盖三个图像槽位。目录接口的 `routeAvailability` 会逐档报告配置模型、解析模型、能力和不可用原因；本地目录无法证明 Luna 缺少能力时不会推测换模。

媒体路由独立于文本等级。图像、视频支持 draft / standard / final；3D 支持 draft / final。图像在没有用户明确质量或生产信号时默认 draft / low / 1K；参考图、编辑、主体保真和普通效果图不会自行升级。明确标准质量使用 standard / medium / 2K，明确最终、高清或正式交付使用 final / high / 2K，印刷、大屏或 4K 使用 final / high / 4K。图像自动顺序为：draft 使用 `Flare → Sunburst → GPT Image 2 → Seedream`，standard / final 使用 `Sunburst → Flare → GPT Image 2 → Seedream`。Seedream 再按实际档位、尺寸和参考编辑能力选择；候选必须保留尺寸、比例、参考图、透明背景和编辑协议要求。自动模式永不选择 `openai/gpt-5.4-image-2` 及其命名空间、大小写或日期别名；高级手动模式仍允许原样调用。自定义 `media.image` 槽位排在内置链前，但若配置为该自动禁用模型会跳过。

每个候选都重新创建 Provider 适配器并重新计算质量、分辨率及参考图参数。只有本地目录缺失、无用量回执的 HTTP 429，或无用量且明确表示模型不存在/不可用/无图像端点的 400、404、422 才安全继续。鉴权、余额、预算、审核、参数错误、取消、5xx、超时、断线、无效响应、失败事件和 SVG 输出均不换模；已提交但结果未知的请求保留回执和预算预留，防止第二笔费用。图像及文本调用统一写入 `model_call_trace`，记录 call kind、档位、Provider、模型、来源、耗时、状态、提交状态和计费确定性；资产和节点的 `imageRoute` 保存最终模型与参数调整。

正常成功的 Agent 轮次没有成本型上限；所有主阶段统一保留 60 轮技术防失控保护，触发时不升级模型、不重放已完成工具，并保留现有产物。SDK 隐式网络重试关闭：只有明确未提交的临时网络、限流或服务错误可在原端点恢复，最多 2 次并遵循 `Retry-After`；已提交或计费未知、本地运行、配置和余额错误均不重试。同类工具参数、结构化输出或本地预检错误最多让 Luna 自修正 2 轮，每阶段累计最多 6 次；失败签名和计数随执行检查点持久化。达到上限后，有真实产物则保留并待核实，无产物则返回明确失败。

文本等级不等同于 Agent 流程。普通对话直接答复，明确生成任务进入设计和审查，研究类任务才先进入研究阶段。必需产物按用户意图和节点类型独立确定，覆盖手动模式；分类结果的 `image_generation` 等别名会规范化。最终审查失败、空答复、交付缺失均视为未完成。重试/升级耗尽时保留真实失败结果、产物引用和问题清单。等待异步产物后的最终审查失败直接结束，不启动新一轮生成。

快速、标准和最高质量表示显式档位或手动策略，不授权运行后升级。配置缺失、网络错误、JavaScript 类型错误、协议错误、`ENOBUFS` 和本地运行错误不跨 Provider；确认未提交的文本 Provider 拒绝只允许在原端点恢复，已提交或提交状态不明时保留待核对状态并停止。参数、引用和质量问题由 Luna 在受控恢复额度内修正，或在本地立即返回。预算开启时只比较本地报价，不实时抓价，也不根据延迟自动改选模型。手动模式始终保持用户所选模型。

「研究与审查模型」可分别设置研究和审查模型、服务与协议，留空沿用主模型；计费使用各阶段实际调用的模型。用户手动指定模型时不使用角色覆盖。生成任务由 Agent 根据真实依赖安排批次，输入就绪的独立产物一起执行，不再设置固定并发数量，旧的 `maxParallelTools` 不影响新任务；写入同一节点或依赖上游产物时顺序执行。默认单任务预算留空表示不设上限；启用后，新调用先预留积分，返回后按实际记录结算。未知价格或计费单位会阻止新收费调用，已提交视频继续查询。估计用量不保证供应商最终收费不超出预算；未知收费保留预留，异步视频完成后更新原记录。

## 模型接口与主动联网

- GPT-5 / GPT-6 系列（包括带命名空间的 ID）默认使用 Responses API 执行函数工具，覆盖 GPT-6.1 Sol、GPT-6 Sol、GPT-6 Luna 和 GPT-6 Astra，避免 Chat Completions 与 `reasoning_effort` 的不兼容组合。主服务和备用服务均可设置接口类型；显式选择 Chat Completions 时这些系列使用 `none`。其他文本模型仅在支持推理参数时发送该字段，历史对话采用 SDK 的标准消息结构。中转站不支持所选协议时会明确报错，不盲目降级或重发付费请求。
- OpenRouter 图像模型通过专用 `/images` 调用；其它中转站的 GPT-Image、DALL-E、Seedream 等通过对应的 OpenAI-compatible 图像接口调用；不新增 Seedream 原生图片 Provider。Gemini 图像模型按服务使用多模态 Chat Completions 或 CloseAI 的 Gemini 原生接口。模型名称保持为中转站确认的 ID。音频 Chat 模型使用音频 Chat Completions（OpenRouter 流式返回），TTS 使用 `/audio/speech`。
- Agent 可调用 `list_models` 查看本地目录，再通过 `generate_image`、`generate_video`、`generate_audio` 指定不同模型；`generate_3d` 使用设置中配置的 Meshy / Tripo / Rodin / Hunyuan3D 适配器。3D 需要对应服务凭据和地址。异步任务提交不等于产物生成完成。
- 开启「允许联网研究」后，Agent 获得 `web_search` 函数工具。后端启动同一打包运行时中的搜索 Agent，通过 OpenAI Agents SDK 和 Responses 查询公开网络；OpenRouter 使用 `openrouter:web_search` 服务端工具，兼容服务使用 SDK `webSearchTool`，解析引用并在对话展示可点击来源。关闭联网后不注册该工具，后端也会根据保存的任务配置拒绝调用。
- 搜索默认继承当前主 Agent 的实际 Provider、Base URL、模型、协议和档位上下文；`generate_text` 同样复用这一实际端点，不读取自动模式下的界面占位模型。只有用户显式配置独立搜索端点时才跨 Provider。参考库视觉分析、AI 图像评价和定时计划使用 STANDARD/Luna；视觉任务提交前会按本地目录校验图片输入能力。项目标题由本地规则从用户原文生成，不产生模型调用。中转站需真实支持相应搜索工具；不支持时报告错误，不用本地搜索冒充联网结果。
- 搜索记录文本用量及搜索调用次数，价格增加 `perSearch` 字段。未知搜索单价保持待计费，避免仅计文本费用导致低估。

接口依据：[OpenAI Astra 工具调用](https://developers.openai.com/api/docs/guides/latest-model)、[OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)、[CloseAI 协议支持](https://doc.closeai-asia.com/tutorial/library.html)、[CloseAI Gemini 接口](https://doc.closeai-asia.com/tutorial/api/gemini.html)。测试使用模拟传输，并未验证用户 CloseAI 账户的实际模型权限。

## 积分计算与本地账本

**默认：1 人民币 = 100 积分，成本倍率 1。**

- 积分 = 人民币成本 × 每元积分 × 倍率。
- 美元报价按设置中的记账汇率换算。初始 7.2 是可修改的记账假设，不是实时汇率。
- 文本按未缓存输入、缓存输入、输出分别乘以每百万单价，再除以 1,000,000。
- 图像区分输入图像、生成图像和图像用量单价；视频按返回的实际秒数或请求费；音频支持请求费、秒数或返回的文本用量。转写先读取本地文件时长，优先采用接口返回时长结算。实际媒体用量不足以按所配单价计算时保持待计费。
- 明确报告币种的实际费用优先；OpenRouter 的 `usage.cost` 按其 USD 契约处理。其它中转站需返回 `cost_currency` 或使用目录/手动报价。
- 中转站提供的价格显示为积分小字；缺价时使用已核对的默认表，显示来源与核对日期；未知模型仍显示「价格待配置」。可在设置录入报价；0 表示明确免费，留空表示未知。
- CloseAI 管理目录的文本、图像、音频和视频输入/输出价按人民币每百万单位归一保存；`cache_read_rate` 只在文本输入价有效时换算为缓存单价。`tiers` 的阈值及输入/输出倍率完整保留，但基础价标为条件参考价，不按平价自动结算，以免忽略阶梯计费。
- 未知价格或必要用量不完整时显示「待计费」，不会把原始 Token 数、字符估计或旧版 Token 汇总当作积分。
- 每条账本记录保留当次价格、汇率和倍率快照。调价不重算历史；视频/3D 轮询按供应商任务 ID 去重，已结算任务不会重复计入。

原有 Token 本地缓存保留，但不混入积分汇总。积分统计来自后端 `/api/credits`，覆盖新任务的文本、媒体与嵌入调用，并能按任务、日期、项目汇总。账本使用独立 `credits.sqlite`，避免与知识入库的数据库写事务互锁。

OpenRouter 定价中的 `image` 是**输入图片价格**，不会当作生成图片单价；参考[官方价格字段定义](https://openrouter.ai/docs/guides/overview/models)。复杂分档显示起始参考价并保留原始计价条件，不能按最低价直接结算；未明确单位时不猜测转换。默认价格来源、覆盖与优先级见 [model-pricing.md](model-pricing.md)。结构化分类遵循 [Structured Outputs 文档](https://developers.openai.com/api/docs/guides/structured-outputs)。

## 配置与追踪位置

- 工作区 `catalog.sqlite`：`model_catalogs`（按服务与地址隔离）、`model_settings`（等级、媒体、积分、价格与首选文本 Provider）、`model_call_trace`（统一调用记录；旧 `model_route_trace` 只读兼容）。
- 工作区 `credits.sqlite`：`credit_ledger`（用量、积分、价格快照与任务归属）。工作区位置沿用 `AICS_WORKSPACE_ROOT`。
- 工作区主数据库：`budget_reservations`（任务预算预留与异步结算关联）、`provider_health`（服务冷却状态）、`canvas_versions`（节点内容版本）。
- `GET/PUT /api/model-settings`：读取/保存配置。
- `GET /api/providers/model-catalog?provider=...&baseUrl=...`：只读本地目录。
- `POST /api/providers/openai-compatible/detect`：显式同步目录。CloseAI 可附带 `catalogSecret` / `saveCatalogCredential`；响应以 `catalogCoverage`、`catalogSources`、`catalogWarnings` 说明完整性与来源，不返回任何凭据。
- `GET /api/tasks/{task_id}/model-trace`：查看分类、等级、实际模型、服务、推理参数、重试/升级、用量、延迟、结果评价及 SDK span。
- 任务会话的执行过程也显示路由选择与切换信息。

SDK 使用本地 TraceProcessor，替换默认远程导出器，并关闭敏感输入/输出追踪。轨迹不保存 API Key；积分账本仅记录白名单用量字段。

## 主要变更文件

新增 `model_config.py`、`model_catalog.py`、`model_router.py`、`billing.py`；更新 `main.py`、`task_runtime.py`、`design_runtime.py`、`openai_agent_worker.mjs`、`design_tools.py`、`providers/registry.py`、`providers/http.py`、`schedules.py`。

前端新增 `modelEconomy.ts`、`components/ModelRouterSettings.vue`；更新 `App.vue`、`providerModels.ts`、`CanvasPromptPanel.vue`、`GeneralCanvas.vue`。测试覆盖后端路由/积分/目录、安装的 SDK 实际执行、主任务入口、前端本地目录与价格展示。

验证使用无付费网络的模拟传输，执行真实已安装 SDK 和真实本地工具存储；Ollama `gpt-oss:20b` 另做了本机 `/v1/models`、Chat Completions、函数工具与完整 Agents SDK worker 冒烟测试。未对用户的真实中转站执行收费生成，亦未重新打包桌面应用。服务是否开放指定模型与实际价格，仍以用户保存配置时同步的目录和返回用量为准。
