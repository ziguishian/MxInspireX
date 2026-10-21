# EvoLink 接入

在「设置 → 模型与连接 → EvoLink」只需填写 API Key，点击「保存并同步模型目录」。官方域名 `https://api.evolink.ai` 已内置，请求使用 `/v1` 接口路径，设置中不显示地址字段；初始化、切换服务商与读取旧 EvoLink 配置时统一使用内置地址。密钥复用项目的系统安全存储，不进入浏览器 localStorage、项目文件或模型目录。无界面部署可使用 `AICS_PROVIDER_KEY_EVOLINK` 环境变量。

同步只在显式保存时请求 `/models`。后续打开设置、切换模型或进入项目只读取本地目录；不内置伪造的可用模型列表。账号权限、模型上下线及余额由 EvoLink 决定。没有 API Key 时可以查看入口，但不能同步或验证真实生成。

## 全局使用

- 首页、项目对话、画布生成和定时任务使用同一服务商配置与本地模型目录。
- 文本模型沿用现有 OpenAI 兼容文本/Agent 运行链路。自动路由依赖目录中实际可用的模型；目录不满足条件时保存后转为手动选择。
- 图像、视频保留同步目录中的原始模型 ID，避免替换为其他服务商的默认 ID。模型在输入框的「模型」菜单选择。
- 图像接口为 `/images/generations`，视频为 `/videos/generations`，已接入 Qwen 语音使用 `/audios/generations`；返回任务 ID，再通过 `/tasks/{id}` 查询。下载结果保存到本地资产与画布。
- 本地参考图通过 EvoLink 官方文件接口上传成临时 URL。视频沿用工作区首尾帧约定，最多两张；专用视频/音频参考数组尚未暴露为工作区输入。

文件上传使用文档指定的 `POST https://files-api.evolink.ai/api/v1/files/upload/base64`、Bearer 鉴权及 `base64_data` Data URL。EvoLink 传输统一发送真实应用标识 `User-Agent: MxinspireX/0.2.0`；JSON 请求声明 `Accept: application/json`。2026-10-21 联调中默认 Python urllib 标识触发文件网关 403/1010，使用应用标识后原图上传及下载通过；这是联调兼容性结论，不是文档要求的额外鉴权字段。下载仅带应用标识，不携带 API Key。

上传位于图片/视频生成提交之前；失败或返回无效地址时报告 `reference_upload_failed`，明确尚未提交生成，停止工具，不自动重试、切换接口或移除参考图。已提交生成后的查询/下载失败仍沿用原任务编号核对，不能因此重发生成。

v11 参考上传复用：按 [官方上传响应](https://evolink.ai/docs/en/api-manual/file-series/upload-base64) 的 `data.expires_at` 判断有效期（文档默认 72 小时）。仅成功 HTTPS URL、带时区且剩余有效期超过生成等待窗口加 60 秒时进入最多 128 项的进程内缓存；文件路径、文件内容或凭据变化均不复用。缺失有效期不猜测，重启后不保留。只缓存上传，不缓存生成提交；失效链接造成的已提交请求仍遵守未知收费保护。任务详情记录命中次数及上传、提交、等待和下载耗时，轮询观测的排队/处理时长不等同服务商内部精确耗时。

## 参数与边界

参数映射位于 `services/api/app/evolink.py` 和 `providers/evolink.py`。GPT Image 复用原生尺寸/质量规则；Nano Banana、Seedream、Qwen 等使用比例 `size` 与分辨率 `quality`；精确像素仅发送给相应支持的模型。视频保留时长、比例、分辨率等通用字段，Sora 与 MiniMax H3 有额外校验，H3 图生视频使用 `image_start` / `image_end`。不支持的明确参数应报错，不应静默升级质量或丢弃首尾帧要求。

模型目录识别不是对所有专用接口的承诺：已接入 `qwen-audio-3.1-tts-flash`；Suno/其他专用语音、Midjourney、审核、放大、视频编辑/延长、动作控制、图层拆分等保留在未分类目录，不进入普通对话和生成菜单。不同模型的最终参数限制仍由其官方接口校验。新增模型族需要核对协议并扩展适配与测试。

## 2026-10-21 恢复与语音接入

- 依据 [Qwen 语音官方接口](https://evolink.ai/qwen-audio-3-1-tts-flash)，以 `prompt` 传入朗读文本，默认 `voice=longanhuan_v3.1`、MP3，支持 0.5–2 倍语速。只有本地真实目录存在该模型才允许自动补齐空选择。缺模型/凭据时在 Agent 调用前拒绝；不改写手动选择。
- 图片和音频在服务商受理后立即保存原 job ID。任务状态 GET 与公开结果下载只对暂时性错误有限重试；下载不携带 Key，生成 POST 不重试。服务端及 worker 分别持久化操作状态，重启不能产生第二次生成。
- 任务详情“取回原结果”调用本地 `/image-results/{fingerprint}/recover`（兼容路径名，同时支持音频）。服务端核对项目、任务、原回执和媒体格式，只查询并取回原结果。重复点击复用已保存资产；运行中和已取消任务不通过此入口恢复。目标已有用户内容时新建节点，不覆盖；成功后沿用原计费记录及真实播放检查收尾。
- EvoLink Responses 可能跨上游资源路由。`portable_responses.mjs` 只调整请求副本：去除旧服务端消息/响应/会话 ID 和不透明推理数据，保留公开历史、工具参数与 `callId` 配对；本地 Session 原记录不变。响应受理事件记录请求编号，流式中断仍为已提交、待对账，绝不自动重发。
- 实测语音已生成并在浏览器播放；首次查询断线后通过产品入口取回同一笔 MP3，仅一次语音 POST，服务商报告 ¥0.0006。3D 仍需要独立支持的服务及凭据，EvoLink Key 不自动证明可用。

单次图像或视频调用只接收一个结果，多图使用现有批量任务。已受理请求查询失败、超时或响应不明时保留任务编号并停止自动重发；用户可到 EvoLink 控制台核对。视频继续由现有任务服务轮询与保存。图像查询中断后不自动重建任务，错误信息提供已获得的任务编号。

计费只采用服务商返回的实际货币金额，不使用 Token × 模型价格补算 EvoLink 扣款。任务处理耗时不当作视频长度，使用 `video_duration`。

## 实际扣费与对账

统一入口为 `services/api/app/evolink_billing.py` 的 `EvoLinkBillingClient.query(task_id=None)`：

- 传入异步任务编号：GET `https://api.evolink.ai/v1/tasks/{task_id}`，仅接受编号匹配、状态为 `completed` 的任务费用。优先使用 `usage.cost.cny`，其次使用 `usage.cost.usd` 并按原请求保存的汇率折算。明确返回的 0 有效，缺失、非法金额和未知币种不当作 0。
- 不传编号：GET `/v1/credits`，只返回账户/API Key 累计用量，标记 `scope=account`、`attributableToRequest=false`。`credits_reserved`、`credits_used`、账户余额和余额差均不能归属为某笔人民币扣款，也不能转换为 Token；该方法不写消费账本。
- 使用原服务商的本地凭据，只接受已核对的官方任务端点，不跟随重定向、不将密钥转发至其他端点，不保存原始响应或敏感字段。

正常图片/视频任务完成时直接记录返回费用；任务受理后查询或下载失败仍保存任务编号。设置 → 用量与计费的“同步 EvoLink 扣费”调用本地 `POST /api/billing/evolink/reconcile`，只对账未确认的原记录：每批最多 5 笔、查询间隔至少 60 秒，单次网络超时 10 秒，批次到 20 秒后不再启动下一笔查询。401/403/429 停止本批查询，其他异常和未返回费用仍保留待对账，不自动重发生成。

对账按原账本 ID 更新，保留项目、任务、日期、Token、原汇率；已确认费用不重复累计，迟到的处理状态不能覆盖费用回执。历史按价格计算的 EvoLink 金额不当作真实扣款，只有取得原任务费用后才能确认。缺少任务编号的旧记录，以及只返回聊天/Responses 响应 ID 的文本调用，继续待对账：目前核对的文档未提供其逐笔费用查询接口，不把文本响应 ID 传给异步任务接口，也不尝试猜测未公开路径。

`GET /api/credits` 和任务详情始终只读本地账本；界面每 3 秒刷新不会增加上游查询。首页、设置及任务详情区分“已确认扣费”“待对账”和“参考估算（非扣款）”；参考估算不计入已确认金额。

## 验证

`services/api/tests/test_evolink.py` 覆盖模型目录同步/离线缓存、独立密钥、图像质量映射、上传/轮询/下载、真实金额单位、视频字段、参数冲突，以及已受理任务不重复提交。`test_evolink_billing.py` 覆盖人民币优先、零值、预扣额度、账户范围、费用缺失/错误/错配、幂等对账、历史估价与 Token 保留。传输使用模拟响应，不产生真实模型费用。

真实联调需要用户在设置中保存自己的 EvoLink API Key，再选择账号目录中实际可用的模型。上传链路可独立验证，无需调用文本或图像模型；生成与计费仍需分别核对真实任务记录。

官方依据：[API 文档](https://evolink.ai/docs)、[任务查询](https://evolink.ai/docs/en/api-manual/task-management/get-task-detail)、[参考图上传](https://evolink.ai/docs/en/api-manual/file-series/upload-base64)、[Qwen Image](https://evolink.ai/qwen-image-3-0)、[MiniMax H3](https://evolink.ai/blog/hailuo-3-api-guide)。

计费接口核对于 2026-10-21：[任务费用](https://evolink.ai/docs/en/api-manual/task-management/get-task-detail)、[账户累计用量](https://evolink.ai/docs/en/api-manual/account-management/get-credits)、[Responses](https://evolink.ai/docs/en/api-manual/language-series/gpt/responses/responses-reference)。
