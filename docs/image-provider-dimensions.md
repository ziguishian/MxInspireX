# 图像尺寸与 Provider 适配

尺寸规则由接口协议和所选模型共同决定。核对日期：2026-09-18。

| 接口 | 参数 | 适配规则 |
| --- | --- | --- |
| OpenRouter `POST /api/v1/images` | `aspect_ratio`、`resolution` 或 `size` | 比例和档位交由路由器转换；像素简写不套用原生 GPT Image 的本地校验。使用已同步目录中的参数枚举检查已知限制。 |
| 官方或兼容中转的 `/images/generations`、`/images/edits` | `size=WIDTHxHEIGHT` | GPT Image 2/2.5 按原生规则校验，比例请求转换为保持比例的合法尺寸；图片编辑沿用 multipart。 |
| 中转的 Chat Completions / Gemini 图像协议 | `image_config` / `imageConfig` | 把比例、分辨率映射到对应协议，不发送 Images API 的尺寸字段。 |

OpenRouter 的全局档位为 `512`、`1K`、`2K`、`4K`，具体模型可能只支持其中一部分。`size` 支持档位或像素简写；像素尺寸与其他尺寸提示冲突时，以像素尺寸为准，适配层清除重复提示后提交。`width/height` 统一转为 `size`，与另一个显式 `size` 冲突时返回参数错误。模型目录没有声明的能力仍由实际供应商决定。

比例先按数值归一（如 `32:18` 使用 `16:9`）。GPT Image 2/2.5 支持的自定义比例若不在 OpenRouter 的比例简写或模型枚举内，直接转换为同等比例、符合模型限制的 `size`；例如 `16:10` / `8:5` 在 2K 档提交 `2048x1280`。此时去掉 `aspect_ratio` / `resolution`，不改成相近比例。其他模型仍按已知接口能力校验，不推断其支持任意尺寸。

## 自动质量与分辨率策略

| 场景 | 媒体模型档位 | Provider quality | 分辨率 |
| --- | --- | --- | --- |
| 未明确质量或生产用途的海报、效果图、插画、改图与方向探索 | draft | low | 1K |
| 用户明确要求标准 / 普通质量 | standard | medium | 2K |
| 用户明确要求最终图、定稿、高清或正式交付 | final | high | 2K |
| 印刷、喷绘、展板、灯箱、大屏 | final | high | 4K |
| 用户明确要求超高质量 / xhigh | final | xhigh | 4K |
| 用户明确要求最好、最高质量或质量拉满 | final | max | 4K |

优先级为：用户原文明确要求 → 手动模型和工具/界面参数 → 明确交付用途判断 → 创意档默认。用户同时指定质量和具体尺寸时分别保留；例如“最高质量，但只要 2K”使用 `max + 2K`。具体像素尺寸高于 K 档位，画幅比例只决定形状，不再被当成分辨率。参考图、图片编辑、主体保真、普通效果图和设计计划中的正式交付项本身不触发升级；生成提示词中的“masterpiece/best quality”等装饰词也不能自行触发高质量，只有用户原文或直接界面参数可以升级。

缺少具体生产参数不改变图像输出边界：图像保持无免责声明、无概念角标、无待定占位文字，未知尺寸、材质和工艺写入节点 `productionNotes`。后端在统一尺寸和质量解析后、Provider 调用前仍追加该生产约束及负面提示，避免 Agent 提示遗漏；这不删除用户明确要求的标题、品牌文案、信息图或工程标注。

GPT Image 2/2.5 原生自定义尺寸要求：宽高为 16 的倍数，长短边比不超过 3:1，单边不超过 3840，总像素 655360–8294400。3:4 可用 `1152x1536`；`900x1200` 的宽度不满足原生对齐要求。`1024x1536` 是 2:3，不能作为保持 3:4 的替代方案。较早 GPT Image / DALL·E 模型使用各自的固定尺寸集，不静默更改设计比例。

具体像素同时区分来源：用户原文与界面明确输入的尺寸是严格约束，非法时直接返回参数错误，并可按明确大尺寸信号升级档位；Agent 根据构图或比例自行写出的像素不是用户分辨率要求，只抽取宽高比，不能升级质量或直接要求 2K/4K。例如用户只说横版、Agent 补写 `3840x1200` 时仍走 draft / low / 1K，并以合法的 3:1 创意档尺寸生成。最终来源、档位和实际尺寸写入 `imageRoute`；格式错误或用户明确指定的非法尺寸不会被静默更改。

文本 Agent 读取引用图时使用独立预览：最长边不超过 1600 像素、单图不超过 2 MB、总计不超过 8 MB，首次最多自动附带 8 张。超出预算的图片仅提供资产清单，可按 ID 再检查；实际编辑、主体保真和布局保真的图片 Provider 始终读取原图。预览的尺寸、字节数及原图摘要写入引用快照，预览不会覆盖项目资产。

## 套系与批量生成

`visualSeries.size` 表示共同版式目标。绑定阶段保留其比例，交给实际适配器确定生成像素数；相同目标尺寸不再被强制写进每次原生生成请求。显式生成尺寸如需调整，必须保持套系比例。原始版式目标记录在引用快照 `visualSeries.layoutSize`，实际参数和返回尺寸分别保存在资产 `params`、`imageOutput`。本逻辑不会重采样供应商图片，也不把更大图片声称为精确尺寸交付。

批量生成在派发前使用与单图生成共用的参数准备逻辑，回执 `imageRequests` 列出有效接口、模型和尺寸参数。Agent 推导像素只保留比例；其余任一项参数不合法时整批返回 `image_parameters_invalid`，不逐张提交。逐图用途也先一次性预检：明确修改、主体保真、沿用布局和风格参考分别在本地规范化为 `edit / identity / layout / inspiration`，只修改 mode 和必要 preserve，不再让 Agent 为单纯模式冲突多思考一轮。只有图片绑定关系仍不明确时才澄清。尚未生成的上游资产仍在实际执行到依赖项时解析，预检查不要求提前存在。

## 图像候选与降级

- draft：Flare → Sunburst → GPT Image 2 → Seedream 5.0 Lite / 4.5 / 5.0 Pro。
- standard / final：Sunburst → Flare → GPT Image 2；Seedream 候选依据实际档位、尺寸与编辑能力选择。参考图只参与能力过滤，不改变档位。
- 自动推导的探索 1K 可在 Lite 候选上提升到其最低 2K；用户明确 1K 时不改尺寸，改选 4.5 或 Pro。透明背景、蒙版、参考图数量或比例不兼容的 Seedream 候选在发送前剔除。
- 每个候选独立执行 `apply_image_quality` 和尺寸转换。GPT Image 2 不继承 2.5 的 `xhigh/max`，需要时使用其最高兼容质量；不能改动用户明确尺寸、比例、透明背景、蒙版或参考图要求。
- 仅“确定未产生生成”的拒绝可以继续候选链。超时、断线、5xx、无效响应、失败流事件和 SVG 均按结果未知或终态失败处理，不自动再发请求。

## 图像响应与超时

OpenRouter 仅在请求不含实际输入图片时，依据已同步目录的 `supports_streaming` 使用 SSE；目录的流式能力不能推断为支持流式改图。带 `input_references` 的 identity/edit 请求直接发送 `stream=false` 并保留原图、模型、质量与尺寸；仅语义借鉴的 inspiration 未传原图像素，仍按文生图能力处理。未声明支持时保留 JSON 响应。只保存 `image_generation.completed` 中的最终图片和用量，部分预览不作为交付；流式请求收到 JSON 时直接处理，不另发请求。图像连接的读取等待为 900 秒，以容纳高质量参考图编辑；这是 socket 空闲超时，不是整轮任务时限。

如果供应商仍明确拒绝流式模式，返回 `image_streaming_unsupported` 与 `stopTool=true`，防止 Agent 将协议限制解释成不支持图像输入，并通过改写提示词或移除原图反复重试。

读取超时或中断且未取得最终结果时，工具返回 `stopTool=true`，Agent 停止自动重提；持久化回执继续保留未确认状态，不能通过改提示词、重启或切换模型清除。节点显示“生成结果待确认”，保留原始错误，并提示先核对原请求、结果和计费记录。已经收到明确错误或不可保存的完整响应时，节点显示“生成失败”，检查原因归为“已发现问题”，保存停止回执；不因此解除自动重提或计费保护。模拟验证见 `test_openrouter_image_stream.py`。

来源：[OpenRouter 图像接口](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)、[OpenRouter 实际模型参数目录](https://openrouter.ai/api/v1/images/models)、[OpenAI 图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)、[OpenAI Images API](https://developers.openai.com/api/reference/resources/images/methods/generate)。
