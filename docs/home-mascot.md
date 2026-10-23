# 全局 Agent 吉祥物定制

入口：设置 → 外观 → Agent 吉祥物。可直接点选点阵机器人、奶油猫、云朵、小芽四款预设，立即同步到首页、项目对话的欢迎区与消息头像、首次请求彩蛋，并按工作区保存；不需要配置图像模型，不产生生成请求或积分费用。

下方保留自定义生成功能：用户填写角色描述，选择沿用全局图像模型或本次指定的模型，生成后检查六个表情，再点击“应用此形象”。“恢复默认”让所有 Agent 头像回到内置点阵机器人，不删除已生成的图集。设置与图集按工作区保存，重启后继续生效。

## 内置预设

- `features/home/mascot.ts` 的 `mascotPresets` 管理预设 ID、中文名称、说明、图集路径和六帧显示位置。资源随前端打包，Electron 使用相对资源基址。
- 四款统一为柔和、圆润的全身坐姿玩偶。机器人使用 `public/assets/mascots/robot-soft.png`，保留暖灰机身和点阵屏幕，替换旧金属半身头像；其余为 `cream-cat.png`、`cloud.png`、`sprout.png`。均是内置 image_gen 生成的 1536×1024 透明 PNG，生成提示词保存在 [mascot-preset-prompts.json](mascot-preset-prompts.json)。原机器人文件保留作历史资源，不再作为 Agent 默认头像。
- 默认机器人也通过 `mascotSpriteStyle` 读取图集与切帧位置，无设置注入时使用相同的新图集，避免首页、设置卡片和消息头像分别回退旧素材。
- 新图集保持原图像素，使用 CSS 切帧位置校准中心及脚部基线（每格 y=480）；六个表情复用首页现有互动和减少动画规则。预设保留自身颜色。
- 后端仅接受白名单预设 ID。复用 `mascot_settings.active_id` 保存 `preset:<id>`；默认机器人仍为 NULL，旧 UUID 自定义选择继续兼容，无需迁移。切换预设不创建生成记录，也不覆盖 `latest` 自定义预览。

## 生成与显示

- 使用现有图像 Provider、凭据、模型目录、路由与计费服务。一次点击最多提交一次图像生成，不调用设计 Agent、提示词润色或额外审查模型；不自动重试或切换服务购买第二张图片。
- 自动附加 3 列 × 2 行、真实透明 PNG、统一角色与留白要求。按行排列：待机、思考、开心、眨眼、等待、困倦（双眼闭合）。使用创意档与 `aspectRatio: 3:2`，实际参数由 `image_routing.py` 适配。
- 本地校验文件大小、比例、透明通道、六格非空与边缘裁切，再将角色按共享缩放及基线注册为 1536×1024 图集。无法确定视觉一致性的部分由用户通过深浅底预览检查；不把本地校验当作模型审美审查。
- 内置与自定义图集通过 `mascotSpriteStyle` 共用 `--xiaoju-image` 和切帧变量；首页直接显示、对话头像的伪元素继承同一组变量，避免局部固定机器人或重复绘制。历史消息也显示当前选择。原有点击互动、任务状态表情、待机眨眼及系统/应用的减少动画设置继续生效；形象保留自身颜色。用户简笔画头像和品牌图标独立维护。
- 生成在本地 API 后台执行，切换页面不取消；前端只轮询已有状态。失败不会替换当前形象，可能已收费的失败会明确提示。服务重启将未确认完成的生成标为失败，不重新提交。

## 模块与持久化

- 前端：`components/MascotSettings.vue` 负责表单与预览；`features/home/mascot.ts` 负责状态、轮询和共享样式，应用级注入；`HomePage.vue`、`components/XiaojuAvatar.vue` 消费当前形象，`FirstRequestCelebration.vue` 复用头像组件。头像不单独请求设置或调用模型。
- `activeName` 统一外观设置、画布对话标题、消息署名和头像无障碍名称；预设使用对应中文名称，自定义使用“自定义形象”。对话消息头像为 32px，与旁边名称垂直居中，切换形象不改变行内对齐。
- 后端：`mascot.py` 负责生成、校验、存储；`mascot_routes.py` 提供接口，`main.py` 只装配服务与路由。
- 工作区 `catalog.sqlite` 中的 `mascot_generations` 保存请求、状态及错误，`mascot_settings` 保存当前图集 ID。PNG 在 `appearance/mascots/<uuid>.png`。不保存 API Key；模型凭据沿用原有凭据服务。
- 计费来源 `mascot`，路由追踪 ID `mascot:<generation_id>`。预览、应用、恢复和状态查询不调用模型。

## HTTP 接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/mascot` | 返回 `active`、`activePreset` 和 `latest`；使用自定义时 `activePreset` 为 null |
| `POST /api/mascot/generations` | `requestId`（UUID）、`prompt`（4–2000 字符）、`provider`、可选 `model`；返回 202 |
| `GET /api/mascot/generations/{id}` | 查询生成状态 |
| `GET /api/mascot/generations/{id}/image` | 读取已成功生成的 PNG |
| `PUT /api/mascot` | `{presetId: "robot" / "cream-cat" / "cloud" / "sprout"}` 应用预设；`{generationId: UUID}` 应用自定义；`{generationId: null}` 恢复默认。不能同时指定预设和自定义 |

同一 `requestId`、相同参数返回原结果，不再调用图像服务；同 ID 不同参数或已有生成进行中返回 409。网络断线后前端先核对已有状态，不自动重新提交 POST。图像路径只接受 UUID，不暴露工作区绝对路径。

## 验证

`services/api/tests/test_mascot.py` 覆盖接口、真实路由的比例与透明参数、一次调用、非法图集、持久化、重复请求、并发及重启恢复；增加预设切换/恢复/重启、非法 ID、与自定义互斥及不产生生成调用测试。图像 Provider 使用测试桩，不产生费用。`features/home/mascot.test.ts` 覆盖预览与应用分离、模型覆盖、状态轮询、不确定提交保护、预设保存失败保留当前选择和静态资源路径。

`components/XiaojuAvatar.test.ts` 覆盖项目与彩蛋使用预设、自定义图集的全部任务状态、恢复默认及未应用预览不改变头像、无注入时默认回退。浏览器验证首页和项目消息的实际图集、切帧位置与减少动画，避免只检查状态值。
