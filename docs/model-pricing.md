# 模型默认价格

核对日期：2026-09-16。默认表位于 `services/api/app/default_price_data.py`，解析逻辑位于 `model_prices.py`。

## 来源与覆盖

缓存计费（2026-10-10）：`token_usage.py` 统一识别 `cached_tokens` 和 `cache_write_tokens`。普通输入、缓存读取、缓存写入互斥计价：`(input-read-write) × inputPerMillion + read × cachedPerMillion + write × cacheWritePerMillion`，再加输出及已声明附加费。写入单价是完整单价，不再次叠加普通输入费用；读写总量大于输入、负数、非数值或缺少实际发生的写入单价时保留待计费。上游实际费用优先。

手动报价可配置 `cacheWritePerMillion`；OpenRouter 目录的 `input_cache_write` 按单 token 转成每百万单价，CloseAI 的明确 `cache_write_price` 保留该服务报价。不能把 OpenAI 的写入倍率套到未知中转。已知写入价格高于普通输入价格时，预算按较高单价预留，结算仍按实际用量。缓存写入量进入账本白名单；同一响应回放沿用原账单 ID，已结算条目不重算，也不改写历史价格。

本轮核对补齐 72 个媒体模型：43 个图像模型、29 个视频模型。名单及原始费率保存在默认表中，不依赖当前用户数据库，也不改变模型可用性。

- [OpenRouter 图像模型目录](https://openrouter.ai/api/v1/images/models)返回各模型的端点详情地址；默认表的图像费率来自 `https://openrouter.ai/api/v1/images/models/{model}/endpoints` 的 `pricing` 数组。
- [OpenRouter 视频模型目录](https://openrouter.ai/api/v1/videos/models)提供 `pricing_skus`；参见[视频模型价格字段说明](https://openrouter.ai/docs/guides/overview/multimodal/video-generation)。已有本地目录中的 SKU 会直接解析，优先于内置快照。
- 端点目录暂未给出报价的四个模型，使用模型页面：[Muse Image](https://openrouter.ai/meta/muse-image)、[Krea 2 Large](https://openrouter.ai/krea/krea-2-large)、[Krea 2 Medium](https://openrouter.ai/krea/krea-2-medium)、[Krea 2 Medium Turbo](https://openrouter.ai/krea/krea-2-medium-turbo)。Krea 的价格为起始参考价，风格参考、情绪板可能另计。
- GPT Image 2.5 的文本输入、图像输入和图像输出分别计价，与 [OpenAI Sunburst 模型页](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)一致。不能用图像输出 Token 单价冒充每张图片价格。

## 价格优先级与计费

1. 服务响应返回的实际费用在结算时优先。
2. 手动设置的模型价格优先于目录及默认表；按 provider、base URL、模型隔离。
3. 本地目录的供应商报价（含视频 SKU）优先于内置默认表。有效的零价保留，不合并其他服务的单价。
4. 完全缺少可解析报价时，读取已核对的默认表，标记 `source=default`、`sourceUrl`、`checkedAt`。只匹配完整模型 ID 或唯一的无命名空间 ID；不猜测模型版本、后缀或其他厂商命名空间。

读取目录不联网、不重写用户配置、不增加模型 ID。旧目录在新版代码读取时即可获得默认价格，后续同步不会删除内置兜底。无需把参考价伪装成用户手动报价写入数据库。

固定每张、每秒价格可按真实用量计算。Token 价格要求对应的实际用量；按张报价不会因为响应额外包含 Token 统计而改用 Token 计费。

不同分辨率、音频、参考素材、最低消费、分段百万像素价格等不能扁平化为统一单价。此类条目显示最低的已公布单位价、保留原始 `priceDetails`，并标记 `referenceOnly`；在供应商未返回费用且没有手动合同单价时继续待计费，不用最低报价结算。设置页不会自动把起始参考价复制为手动固定价。

内置表来自 OpenRouter。在其他中转站上仅作为参考展示，须由当前服务返回实际费用或配置手动报价后结算，不把 OpenRouter 价格当作其他服务的合同价。

五个 OpenRouter 动态入口（Auto、Auto Beta、Bodybuilder、Fusion、Pareto Code）的目录价格为 `-1`，显示动态计价；既不当作负数也不当作免费。参见 [Auto Router](https://openrouter.ai/openrouter/auto) 与 [Fusion 计价说明](https://openrouter.ai/docs/guides/routing/routers/fusion-router)。

每条消费记录继续保存当时的价格快照，不按新报价重算历史；EvoLink 可通过原任务编号补查实际费用，更新原条目，绝不重发生成请求。SVG 相关模型在目录里有价格并不开放 SVG 生成能力。

## 更新与验证

### Token 与人民币展示（2026-10-21）

应用不再展示积分或积分/Token 换算规则。`GET /api/credits` 保留历史接口名，新增真实 `totalTokens` / `inputTokens` / `outputTokens`、`tokenByDay` / `tokenByTask`、`tokenUnreported`、`costCny` / `estimatedCostCny` 和 `pricedRequests`；分类汇总使用相同口径。总 Token 优先采用响应明确返回的总量，否则累加已返回的输入和输出；缓存及模态明细是子集，不重复计算。未返回完整统计的调用单独提示，图片张数、媒体秒数和费用绝不换算为 Token。

汇总 `costCny` 仅累计具有服务商费用回执的金额（`costSource=provider_reported` 或历史 `price.source=reported`），`reportedRequests` 记录已确认笔数，`awaitingReconciliation` 记录未确认笔数，`evolinkPending` 用于 EvoLink 对账。历史本地按价格计算的金额仅进入 `estimatedCostCny`，不能因旧条目为 `settled` 就当作真实扣款；EvoLink 不提供这种估价兜底。美元费用按原请求的 `usdToCny` 快照折算，不随当前汇率或旧积分比例改变。首页顶部中央以小字常驻累计 Token 与已确认扣费，参考估算单独标记“非扣款”；没有费用回执显示“—”和待对账，不把未知当作 0。用户概览、活动图、桌面顶栏和设置页共用该数据，可见页面每 3 秒只读本地账本，任务更新时立即读取。空工作区和明确零扣费显示 0；刷新失败保留上次数据并标明状态。首页刷新后首次读到真实用量时递增 800ms，轮询直接更新，减少动画时直接显示真实值；其他位置计费数字不做递增动画。

设置 → 用量与计费分别展示各类 Token、已确认人民币费用、参考估算及待对账数，提供“同步 EvoLink 扣费”按钮，查询规则见 [EvoLink 对账](evolink-integration.md)。模型参考单价保留每百万 Token、张、秒等真实单位。手动报价允许输入服务商原始 USD/CNY 费率，但不等于真实扣款凭据。历史 `points` 字段、账本文件名和预算存储单位仅为兼容已有数据与预算约束保留，不参与前端用量与费用展示、不提供转换开关。

### 历史积分接口兼容

`GET /api/credits` 读取实际账本，保留原有 `points` / `byDay` / `byTask` 结算语义，增加 `estimatedPoints`、`unpriced`、`byKind` 和单独的估算日期/任务汇总。`credit_reporting.py` 只做读取，不重价、不写账、不调用服务商。文本与审查、图像、视频、音频、联网搜索、知识检索、3D 分别显示实际 Token、记录数、已核算、参考估算及待核实数。

参考估算只用于已经返回用量、且价格快照能完整覆盖该用量的未结算记录；跨服务的无条件公开报价仅作参考，不计入 `points`。分档价、动态价、缺少缓存单价或不完整用量仍显示待核实。音频和视频按 Token 收费时需要实际模态拆分；不将媒体 Token 冒充普通文本单价。0 费率表示明确免费，空值表示未知。

前端共享 `features/credits.ts`，活动图只统计已返回 Token，与价格是否可用无关。`CreditPricing.vue` 在用量与计费设置中展示各类别的模型单价和来源。`GET /api/credits/prices` 只读缓存目录，`PUT /api/credits/prices` 只保存指定服务、端点、模型的手动报价，其他设置保持原值。新报价用于后续请求，历史记录保留当时价格。正常生成 Key 不被自动用于管理接口；服务不返回价格时需同步其受支持的价格目录或填写实际费率。

回归入口：`test_credit_reporting.py`、`test_cache_billing.py`、`test_model_catalog.py`、`test_model_prices.py`；覆盖真实费用替代估算、幂等记录、读取不改账、条件价格、媒体模态拆分和单模型报价保存。

维护者更新默认表时，重新查询对应官方端点，保留计价单位、变体和来源，更新核对日期。未知模型继续显示价格待配置，不能按同系列其他模型的单价猜填。

测试覆盖价格优先级、有效零价、命名空间隔离、图像 Token 和张数区分、视频美分与美元转换、条件报价及实际费用优先、旧账本防重复计费、动态路由价格与前端编辑字段过滤。使用模拟传输和临时工作区，无真实付费生成。
