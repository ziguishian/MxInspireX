# AI 开发指南：MxinspireX

> 最后核对：2026-10-21。适用于整个项目。先读本文，再按任务查看对应模块和测试，不必通读源码。
> 这里记录项目地图与开发约定；详细设计放在 `docs/`。若与实现不一致，核对对应代码与测试，并更新本文。


- **许可**：当前源码采用根 `LICENSE` 的 MxinspireX 非商业许可 1.0；商业使用需事先书面授权，不能再将当前版本标为 MIT 或 OSI 开源。此前 v0.2.1 和截至 `1222db5` 的 MIT 版本及其授权不变；第三方许可保留。后续打包携带当前许可和 `docs/licenses/`，新发版本不能覆盖旧 Release 来追溯变更许可，详见 `docs/licenses/README.md`。
- **产品**：本地优先的 AI 设计工作区，面向品牌、平面、产品、包装、数字界面、空间与多媒体等通用设计任务。用户通过对话、参考资料与无限画布完成设计和交付。
- **核心对象**：工作区包含多个项目；项目拥有持续对话、任务、资产、资料及画布。每条用户消息对应任务，主 Agent 会话按项目延续。
- **能力**：文本、图像、视频、音频、3D、HTML、本地参数化 CAD；知识检索、视觉参考库、技能库、导出与本地定时任务。
- **技术栈**：Vue 3 + TypeScript + Vite + Vue Router；Vue Flow 画布、Three.js 预览；Electron 桌面端；Python 3.12+ / FastAPI；Node.js / OpenAI Agents SDK；SQLite 与本地文件存储。LanceDB 是可选依赖。Electron 主进程运行依赖必须声明在根 `dependencies`，并由 `desktop-runtime-dependencies.mjs` 复制和验证，不能依赖开发目录的 `node_modules` 向上解析。
- **统一任务入口**：`design`。任务按需求调用研究、设计能力，没有固定步骤流水线；普通对话无需走完整设计流程。
- **界面语言**：以中文为主。产品名称为 `MxinspireX`，公司为 `灵矩绘境`；吉祥物默认灰色点阵机器人，可在外观设置中选择预设或自定义，并同步首页与项目 Agent 头像。视觉规范以已确认的深浅色预览为准，共用主题变量在 `style.css`，布局与细节在 `mx-theme.css`。Agent 机器人使用 `mascots/robot-soft.png`（3×2 图集），与奶油猫、云朵、小芽统一为柔和全身坐姿玩偶；旧 `mxinspirex-robot.png` 与 `mxinspirex-robot-states.png` 保留作历史/品牌资源；用户头像共用 `mxinspirex-user-line-avatars.png`（3×3 图集），保留原有 0–8 选择索引。代码前缀 `AICS`、历史素材文件名和本地存储键中的 `langjuart` / `lumo` 保留兼容，不用作显示名称。

- **主题维护**：以用户确认的中性灰配色为准。背景、侧栏、卡片、浮层和输入区分别使用 `--theme-bg`、`--theme-sidebar`、`--theme-surface`、`--theme-surface-floating` 和 `--theme-input`，在 `style.css` 中同时定义深浅色值。状态信号灯统一使用 `--theme-status-green/yellow/red`：就绪或成功为绿，处理中、待验证、待配置或警告为黄，故障或离线为红，不跟随中性强调色。共用控件、弹窗和跨页面覆盖统一放在 `mx-theme.css`；画布对话输入框在 `features/composer/composer.css` 中复用同一输入区变量。不要新增全局强制透明背景或隐藏焦点的 `!important` 规则。图片、视频、画板内容和风格参考保留自身颜色。

- **交互动效**：首页和项目输入框共用 `components/motion/StarBorder.vue` 与 `mx-theme.css` 的聚焦霓虹。首页、任务、作品卡片、资料网格及用户中心使用轻量 Vue Bits 适配，统一由 `features/motion/useMotion.ts` 尊重系统/应用减少动画和后台暂停；详见 `docs/vue-bits-motion.md`。鼠标保持系统光标，不添加跟随光晕；首页顶部 Token 和人民币数字首次读到真实数据后递增 800ms，后续轮询直接更新，未知值保持“—”，其他计费位置不做递增动画。
- **UI 尺度**：共用 `mx-theme.css` 的 `--ui-font-*`：页面标题 24px、分区标题 18px、卡片标题与正文 14px、控件 13px、辅助说明 12px；11px 仅用于短数字标记。常规控件高 40px、紧凑控件高 32px，控件/卡片/对话框圆角分别为 10/16/20px。媒体卡片使用 `--ui-media-*` 的上浮毛玻璃信息层；列表空状态复用 `EmptyState.vue`。不要在页面重新覆盖共用标题字号，首页展示标题和作品内容除外。
- **用户概览卡片**：头像弹出的卡片只保留个人资料、当前模型、最近一周活动趋势和设置入口。活动使用纯色蓝灰，无活动日使用中性底色；不显示 Token、项目、费用等统计数字，悬停也不显示精确用量。完整统计保留在首页和设置页面；读取失败不能伪装为无活动。
- **用户资料编辑**：用户中心点击昵称或简介文字即可原位编辑，保持原字体、居中与内容高度，不显示大输入框及保存/取消按钮；失去焦点自动保存，Esc 取消并恢复原文，空昵称保留原值。使用独立草稿，未修改时不重复保存；昵称支持 Enter 保存，简介支持 Ctrl/⌘ + Enter 保存并保留普通 Enter 换行。头像仍在 hover 或键盘聚焦时显示编辑图标（触屏始终可见），继续使用原生选择对话框。不要恢复统一的“编辑资料”表单入口。

## 2. 开始任务时怎么读

桌面标题栏左侧仅显示 MxinspireX 文字，不显示文件、编辑、视图、帮助菜单；中央显示累计 Token 和确认扣费，页面内不重复显示桌面用量。标题栏和侧栏空白支持拖动窗口。主题切换位于左下角，更新按钮仅有新版本时显示，两者在画布页隐藏；任务入口移至右上角，只列运行中任务。外观设置支持方格/点状/空白及本地图片画布背景，见 docs/desktop-ui-20261023.md。原生窗口按钮颜色通过 `windowAppearance.ts` 校验后，跟随 `appearance.ts` 的背景/前景色（含自定义配色）；不恢复旧荧光绿。应用图标母版为 `scripts/brand-assets/mxinspirex-app-icon-{dark,light}.png`，由 `export-app-icon.py` 转换为 ICO/ICNS/PNG，Agent 吉祥物独立保留。桌面外观验证：构建后执行 `node node_modules/electron/cli.js scripts/test-window-chrome.cjs`。

模型选择菜单（首页、项目对话及画布生成面板）只显示厂商图标和模型名，保留精简自动路由选项；不展示本地目录统计、能力长说明或价格。厂商识别复用 `features/modelBrand.ts`，本地矢量图集为 `assets/model-brands.svg`，由 `ModelBrandIcon.vue` 内联所选图形以兼容 Electron file URL。价格统一在设置「用量和计费」的 `CreditPricing.vue` 展示；加载/连接失败仍需显示真实状态。

图像提示词遵守视觉边界：主 Agent 在 `generate_image.prompt` 中一次性提炼主体、构图、色彩、材质、光照、风格和准确图内文案；编辑以“图像编辑任务：”开头并写修改/保留范围。不传推理、设计理由、流程、交付、验收或资产 ID。后端不重复追加完整设计规格、参考分析、选图记录、前置文档/HTML 或生产规则，只补必要的视觉约束；分析仍存任务和资产快照。不要增加提示词改写模型调用，详见 `docs/agent-flow.md` 的 v9 边界。

明确的简单单图任务（含已解析图片附件）使用 `execution_efficiency.mjs` 的精简工具集和 `image_reference_design.mjs` 的单图指令：需求/设计选择直接合并到生成参数；首轮唯一且已解析的图片由 `prepare_single_image_selection` 本地选为候选，不推断 identity/layout/edit，主 Agent 仍实际看图并填写分析。无历史无参考或唯一参考可首轮生成；多参考、历史和复杂资料仍由 Agent 选择。未完成选择时隐藏生成工具，成功后直接交付。精简上下文保留原文、实际图片、选中记忆和生成约束；可通过读取记忆恢复写工具。视觉修饰词不因“并/然后”误退完整流程，额外输出/分析/导出仍排除。简单首轮目标 1 次文本 + 1 次图像调用，多参考通常 2–3 轮，不硬截断恢复，不增加质量审查，详见 `docs/agent-flow.md` 的 v11。

跨类型回归 v15：明确“不做研究”跳过外部参考发现，但保留实际参考图及产品身份依赖；“不调用图像/不做图片”等否定语义不增加交付，HTML 中复用的商品图是输入。所有需记忆选择的写入工具在选择完成后开放，并在上下文说明前置动作，不能误报能力缺失。HTML 仅引用图片/附件时可本地补齐新建模式，已有 HTML 修改目标仍需明确；`html_syntax.py` 保存前检查 CSS 括号结构，不做设计质量审查或额外模型调用。异步交付的检查面板读取最终产物 ID，完成后清除已失效的等待文案。实测矩阵见 `docs/browser-design-sweep-20261022.md`。

1. 先用本文定位负责模块；仅在需要时读一篇相关专题文档。
2. 用 `rg -n` 定位函数、接口或字段，读相关片段及对应测试。`App.vue`、`main.py`、`design_tools.py`、`openai_agent_worker.mjs` 是大型入口，不要默认整篇读取。
3. 默认只搜索 `apps/`、`packages/`、`services/api/app/`、`services/api/tests/`、`scripts/`、`docs/`。跳过 `node_modules/`、`dist/`、`.tmp/`、`.local/`、`.venv/`、`workspace-data/`、`outputs/` 和缓存；需要排查实际产物时再定向访问。
4. 修改前核对现有实现与用户改动；如果当前目录有 Git，先查看工作区状态。不要将历史审计文档当成当前待办清单。
5. 完成后按影响范围验证；入口、路径、业务约束或命令改变时同步本文，细节写入对应专题文档。

## 3. 目录与职责

画布背景上传使用 `CanvasBackgroundSettings.vue` 的显式按钮同步打开文件选择器；`canvasBackgroundImage.ts` 在本机解码、缩放压缩 20 MB 以内的 PNG/JPEG/WebP，再保存本地设置。处理中／成功／错误均在按钮附近显示，保存失败保留原背景；图片不上传至 Provider、不成为生成参考。`scripts/test-window-chrome.cjs` 覆盖鼠标／键盘打开选择器、大图上传、刷新保存与移除。

桌面品牌统一为 `MxinspireX`，包括标题栏、应用包、可执行文件和发布归档。Windows 开发及发布共用 `scripts/windows-branding.mjs` 写入 PE 图标和产品元数据，开发运行时复制到 `dist/dev/windows-<摘要>/`，不修改 node_modules；应用 ID、数据目录与兼容键保持原值。原生图标、网页 Logo 和 favicon 使用已确认母版；旧 `generate-brand-assets.py` CLI 已禁用，导出使用 `export-app-icon.py`。平台状态矩阵、静态图标限制及验证入口见 `docs/desktop-branding.md`。

| 位置 | 职责与阅读入口 |
| --- | --- |
| `apps/renderer/src/` | Vue 前端。`App.vue` 协调应用状态、API、输入草稿、任务观察和全局浮层；`pages/` 是页面；`components/` 是界面组件；`features/` 是可复用逻辑。 |
| `apps/desktop/src/` | Electron：`main.ts` 管理窗口、工作区和 sidecar；`preload.ts` 暴露 `window.studio`；`htmlExport.ts` 负责桌面 HTML/PDF 导出。 |
| `packages/contracts/` | 前端共享 TypeScript 数据契约：项目、设计批次、会话记忆、技能。Python 数据结构需同步核对，并非自动生成。 |
| `services/api/app/main.py` | FastAPI 生命周期、服务装配及主要 HTTP 接口；技能、参考库、CAD 分别在 `skill_routes.py`、`reference_routes.py`、`cad_routes.py`。 |
| `services/api/app/` | Python 业务服务和同目录的 Node `.mjs` Agent 运行模块，详见下一节。 |
| `services/api/tests/` | Python API/业务/SDK 集成测试，以及由 Vitest 执行的 `.test.mjs`；模拟传输位于 `fixtures/`。 |
| `scripts/` | 开发启动、打包、独立 UI 验证与发布包检查；具体 npm 入口见根 `package.json`。 |
| `docs/` | 专题设计与历史排查记录；按本文索引读取。 |

### 按需求定位文件

以下路径中 `前端` = `apps/renderer/src/`，`后端` = `services/api/app/`，`桌面` = `apps/desktop/src/`。

| 要修改或排查 | 优先读这些文件 |
| --- | --- |
| 页面、导航、页面间共享状态 | 前端 `pages/`、`router.ts`、`features/navigation/`、`features/pageServices.ts`，需要共享协调时再读 `App.vue`。 |
| 输入框、附件、消息编辑、技能标签、待发送队列 | 前端 `components/composer/`、`features/composer/`、`features/composerDrafts.ts`、`features/messageQueue.ts`；后端 `task_runtime.py`、`project_context.py`、`conversation_context.py`。待发送队列按项目保存在 IndexedDB，复用队列项 ID 作为任务 `requestId`；流式结束、重进项目和手动续发共用 `messageQueue.ts` 判断，只有执行成功且交付通过时串行推进；失败、取消、待核实、未应用的运行中补充或等待用户补充时暂停并显示原因。队列支持原位编辑文字且保留引用/附件；任务入口位于输入框工具栏“风格”右侧，仅列出和计数状态为 `running` 的对话及独立画布任务，待发送清单位于项目输入框。 |
| 任务提交、进度、取消、恢复 | 前端 `designTaskStream.ts`、`features/taskQueue.ts`、`features/taskProgress.ts`、`features/taskErrors.ts`、`components/TaskRequestInspector.vue`；后端 `task_runtime.py`、`execution_store.py`、`task_updates.py` / `.mjs`（持久化补充及安全节点接收）、`task_activity.py`（精简工作摘要）、`task_inspection.py`（只读请求/产物/计费核对）、`server.py`。 |
| Agent 行为、工具定义、跨语言协议 | 后端 `openai_agent_worker.mjs`、`design_runtime.py`、`design_tools.py`、`agent_contracts.py`；`tool_contracts.mjs` 按入口能力发送工具契约，`execution_frame.mjs` 从持久化事实投影执行动作。 |
| 会话上下文、记忆、引用绑定 | 后端 `sdk_context.mjs`、`prompt_cache.mjs`（稳定前缀、按入口应用缓存选项）、`agent_sessions.py`、`project_context.py`、`conversation_context.py`、`conversation_memory.py`、`conversation_memory.mjs`；契约 `packages/contracts/conversationMemory.ts`。 |
| 需求整理、澄清、设计计划、交付范围 | 后端 `design_brief.py` / `.mjs`（主 Agent 内整理任务说明）、`design_planning.py`、`design_state.py`、`task_policy.py`、`deliverable_tracking.py`；契约 `packages/contracts/designBrief.ts`；前端 `components/TaskProgress.vue`、`features/clarification.ts`、`components/DesignClarificationCard.vue`。 |
| 批量生成与依赖调度 | 后端 `generation_batch.mjs`、`tool_scheduler.mjs`、`design_batches.py`、`design_tools.py`；契约 `packages/contracts/designBatches.ts`。 |
| 模型、Provider、联网、Token 与计费 | 后端 `model_config.py`、`model_catalog.py`、`model_capabilities.py`、`closeai_catalog.py`（CloseAI 完整目录与类别映射）、`model_prices.py` / `default_price_data.py`（默认价格）、`model_router.py`、`image_routing.py`（图像候选、能力过滤与安全降级）、`providers/`、`sdk_web_search.mjs`、`billing.py`、`token_usage.py`（缓存读写用量）、`budget.py`；前端 `providerModels.ts`、`modelEconomy.ts`、`components/ModelRouterSettings.vue`。 |
| 图像尺寸、质量、参考图、加载占位与响应超时 | 后端 `image_request_resolution.py`（单图/批量/改图统一解析与预检版本）、`image_intent.py`（逐图修改/参考语义智能判断）、`image_parameters.py`、`image_quality.py`、`image_output.py`、`image_reference_design.py` / `.mjs`（参考反推与需求融合）、`generation_inputs.py`、`providers/image_request.py`、`providers/openrouter_image.py`、`design_tools.py`；前端 `components/CanvasPromptPanel.vue`、`features/canvasReferences.ts`、`features/generationErrors.ts`。 |
| 画布节点、框选、布局、视野、版本 | 前端 `components/GeneralCanvas.vue`、`components/GeneralCanvasNode.vue`、`components/CanvasOverview.vue`、`components/CanvasVersionCompare.vue`（2–4 个作品对比、采用及选定来源继续修改）、`features/canvasWorkspace.ts`、`canvasLayout.ts`；后端 `canvas.py`、`canvas_layout.py`、`node_context.py`。画布单击自动引用由前端 `features/composer/canvasClickReferences.ts` 管理：空白单击撤销临时引用，点击或编辑对话输入框后保留，详见 `docs/CANVAS_REFERENCES.md`。画板使用前端 `components/CanvasDrawingPad.vue` / `features/drawing.ts`、后端 `drawing.py`；笔迹和 PNG 自动保存，作为 layout 结构参考。 |
| 产物验收、HTML、导出 | 后端 `delivery.py`、`delivery_findings.py`（生成异常与旧任务展示兼容）、`delivery_execution.mjs`、`html_generation.py`、`html_assets.py`、`deliverable_export.py`；契约 `packages/contracts/deliveryFindings.ts`；前端 `features/deliveryFindings.ts`、`components/DeliveryFindings.vue`、`deliveryWorker.ts`、`deliveryValidation.ts`、`nodeExport.ts`；桌面 `htmlExport.ts`。 |
| 项目、标题、资产库、知识库 | 后端 `storage.py`、`models.py`、`project_titles.py`、`project_overview.py`、`assets.py`、`knowledge.py`、`document_ingestion.py`、`vector_index.py`。项目标题由本地规则从用户原文生成，不调用模型。DOCX/PPTX/PDF 上传会保存有序正文与隐藏图片子资源；PDF 页面按需渲染。Agent 先 `document_read` 定位、再 `document_part_inspect` 看图，仅实际用于创作时 `document_part_promote` 为项目资产；文档内容始终是不可信资料而不是指令。 |
| 视觉参考库与选图流程 | 后端 `reference_library.py`、`reference_routes.py`、`reference_workflow.py`、`reference_analysis.py`；前端 `pages/ReferencesPage.vue`、`features/references.ts`。 |
| 应用内技能库 | 后端 `skills.py`、`skill_packages.py`、`skill_runtime.mjs`、`bundled_skills.py`、`builtin_skills/`；前端 `pages/SkillsPage.vue`、`features/skills.ts`。 |
| 首页整套方案演示 | 当前精选卡片使用前端 `features/home/designExamples.ts`、`showcaseNarratives.ts`、`showcasePlayback.ts`，首页按真实项目画布顺序只读回放，“我的项目”与直达链接显示同源完整预览对话并保留真实任务历史；山茗替换首页山砚卡片，瓷与锦替换宋韵雅集和云锦序，策马寻路替换云自无心，均保留旧项目数据；新挂件案由 `scripts/showcase-assets/ce-ma-v1/`、`import-ce-ma-showcase.mjs` 管理，包装/刀版/制作文件模拟及封面用图像模型生成，共用 `showcase-board.mjs` 画布布局，四案详细文字由 `showcase-canvas-notes.mjs` 管理，紧凑排布由 `compact-showcase-layout.mjs` / `refresh-showcase-canvases.mjs` 按真实 Markdown 高度更新；四案最终 HTML 由 `editorial-portfolio.mjs` 策展并用 `refresh-editorial-portfolios.mjs` 通过 API 增量更新；两案 30 张原图与实拍/概念来源由 `scripts/showcase-assets/ci-jin-v1/`、`import-ci-jin-showcases.mjs` 管理。原四案策展由 `scripts/showcase-curation.json` 管理，德寿宫等三案与 16 张待修整素材由 `scripts/showcase-assets/manifest.json`、`import-showcase-additions.mjs` 管理；山茗九张用户资料由 `scripts/showcase-assets/shan-ming-v1/`、`import-shan-ming-showcase.mjs` 管理，异品牌图只作参考。旧 `designDemoCases.ts` / `designDemoPlayback.ts` 仅保留显式 `demoId` 兼容路径。见 [home-design-demos.md](docs/home-design-demos.md)。 |
| 产品成就、内置彩蛋与吉祥物 | 后端 `achievements.py`、`easter_eggs.py`、`easter_egg_assets/`；前端 `components/AchievementCelebration.vue`、`pages/HomePage.vue`、`features/home/lumoTimeMessages.ts`、`style.css` 的 `.agent-avatar-sprite`。Agent 头像复用 `components/XiaojuAvatar.vue`，读取当前吉祥物选择；山云资源说明作为历史参考。内置彩蛋只从本地预生成资源创建节点，不调用 Provider、不计入图像生成成就。 |
| 全局 Agent 吉祥物定制 | 设置 → 外观中的前端 `components/MascotSettings.vue`、`features/home/mascot.ts`；后端 `mascot.py`、`mascot_routes.py`。内置机器人、奶油猫、云朵、小芽可直接切换；新资源在 `public/assets/mascots/`，切换不调用模型。自定义复用图像路由和计费，一次生成一张透明 3×2 图集，先预览再显式应用，同步首页、项目对话与首次请求彩蛋，保留任务状态表情；不自动重试。自定义图集存于工作区 `appearance/mascots/`，状态与当前选择存于 `catalog.sqlite`，见 [home-mascot.md](docs/home-mascot.md)。 |
| CAD、视频、定时任务 | 后端分别查看 `cad.py` / `cad_program.py` / `cad_worker.py`、`video.py` / `video_inputs.py`、`schedules.py`；前端对应 `components/CadPanel.vue`、`components/ModelViewer.vue`、`components/SchedulePanel.vue`。 |
| 桌面启动、发布包 | 桌面 `main.ts`、`preload.ts`、`runtimeComponents.ts`；脚本 `scripts/dev-api.mjs`、`scripts/launch-dev-macos.mjs`、`scripts/build-sidecar.mjs`、`scripts/build-runtime-components.mjs`、`scripts/agent-runtime-build.mjs`、`scripts/package-distributions.mjs`、`scripts/package-lite-distributions.mjs`。 |

## 4. 一次请求如何流转

网页并行与收尾 v19：`web_generation.mjs` 为简单单页提供精简工具集，保留升级为媒体计划的入口；页面文案由主 Agent 编写。就绪计划中的 supporting 内容媒体受理后，Agent 可同时编写网页，以 `deliverable://媒体交付ID` 引用未来资源；保存时只查询原操作并由 `html_assets.py` 按当前计划、唯一已保存媒体绑定 `asset://ID`。节点入口不支持未来占位。identity/layout 依赖仍先看真实像素；失败、取消、未知收费不重发、不保存未完成网页。多项输出由本地交付检查确定性收尾，保留预览、补充与恢复保护。实现与验证见 `docs/agent-flow.md` 的 v19；发布门禁覆盖 `test_web_pipeline_sdk.py` 和网页回归。

外部 Agent CLI：`scripts/mxinspirex.mjs`（`npm run cli -- --help`）通过既有本地 HTTP API 操作项目、任务、画布和资产，默认 JSON 输出；创建任务必须使用稳定 requestId，强制异步且不自动重试写请求。wait 超时不取消任务，recover 只取回已受理原结果。`scripts/package-cli.mjs` 在 Windows/macOS 分发包中生成复用 Electron Node 运行时的启动器，无新增依赖。入口、退出码和 Agent 调用约定见 `docs/cli.md`；测试 `scripts/mxinspirex.test.mjs`。

交互网页由主 Agent 按需组合文字、图片、视频和音频；新素材通过计划 `supporting=true` 和 HTML 项的 `dependsOn` / `inputs(role=content)` 关联，不增加最终交付数量，不绕过用户否定或节点原样生成。`canvas_create_html(style_framework=bootstrap)` 离线嵌入固定 Bootstrap 5.3.8；媒体通过真实 `asset://ID` 嵌入，预览和导出均可播放。框架正文不进入 Agent 编辑上下文，编辑继承 `styleFramework`。iframe 允许本地表单事件，CSP 继续禁止对外提交和网络访问。详见 `docs/web-generation.md`；真实交互回归 `npm run test:web-interactions` 不调用收费模型。

系统提示词与产品定位面向通用设计任务，不预设特定行业、文化主题或风格。主 Agent 按本轮目标判断领域；视觉评价按需求契合度判断（历史字段 `culturalRelevance` 保留兼容）；内置 IP／导视技能使用通用正文，旧技能 ID 保持稳定。参考库默认分类覆盖多个行业，旧分类和真实项目／案例内容保留，不做全库文本替换。

对话提示词由主 Agent 将模糊需求转为具体设计术语，按需选风格；生成边界通过 `generation_prompt` 事件展示实际提示词后直接执行，不额外调用润色模型。工作区 `prompt-templates/` 是独立模板集合，`prompt_templates.py` 提供导入/检索接口：空集合不搜索，非空最多检索三条候选，用户要求优先，模板不是指令。节点新任务保存 `nodePrompt.version=1`、original/submitted 与 canvasParams；图片/视频/音频走确定性工具调用，不跑主 Agent 文本模型。风格、镜头和上游文字在输入框内可见合并，提交后不再拼接或改写，后端 `node_prompt.py` 绑定持久化原文及参数；透明背景只走参数，不追加提示词。文本/HTML/CAD 使用隔离内容生成指令。旧任务不追溯改写。详见 `docs/agent-flow.md` 的「提示词组织与节点原样生成」。

模型与连接显示按能力分类的目录状态；普通中转站只有在目录同步成功、对应图像/视频/音频列表确为空且用户显式选择补充服务商时才跨服务调用。补充选择按主服务商和 URL 保存，候选来自已配置且有本地目录的其他服务商，`effectiveMediaOptions` 与 `taskMediaProvider` 共用来源；未同步/失败不视为缺失，不静默切换。Ollama 保留原远程媒体回退。3D 目录存在不代表协议已接入，仍要求独立服务配置；对应测试 `providerModels.test.ts`。

首页与项目对话共用 `components/composer/VoiceInput.vue`：录音最长两分钟，结束后由 `voice_input.py` 的 `/api/voice-input` 调用当前服务商目录中的转写模型，文字仅追加草稿，不自动发任务；密钥留在后端，记录计费，不自动重试，页面切换释放麦克风。不支持的模型目录需先配置转写服务。右上角任务列表仅展示运行任务，细循环条表示运行活动，不表示真实百分比。

待发送清单直接排列在项目输入框外侧上方，运行时工具栏只保留停止按钮；Ctrl/⌘ + Enter 按常规设置加入队列或补充当前任务。补充成功后从持久化 task.updates 显示对话气泡（待应用/已补充），不再显示成功 Toast；失败仍保留错误及幂等重试机制。

画布设计扩展：图片右键可本地转矢量（`vectorize.py`，VTracer，只允许路径 SVG，保留原图、重复转换复用结果）或使用 GPT Image 2.5 新节点透明抠图。色板与视频分镜使用 text 节点的 `editor=palette/storyboard` 子类型，结构化数据由 `design_nodes.py` 校验，前端 `DesignNodeEditor.vue` 编辑、`designNodes.ts` 与 `canvasReferences.ts` 实时构建引用。分镜连接视频后总时长只读，一次生成一条视频，不自动拆镜头付费生成。详见 `docs/canvas-design-nodes.md`；UI 回归入口 `node scripts/test-design-nodes.cjs`。

- 公开产品 SEO/GEO：`npm run build:site` 生成独立 `dist/site`；只有设置真实 `PUBLIC_SITE_URL` 才开启索引并生成 canonical/sitemap。工作区 HTML 始终 noindex。公开事实集中在 `docs/product-facts.md`、README 与可选 `llms.txt`，不暴露私人项目；见 `docs/search-discovery.md`。

- 发布前运行 `npm run verify:agent-release`；四个 `package:*` 入口已配置前置检查。测试使用隔离 API/SQLite 和模拟 Provider，覆盖七类节点、引用变化、持久化与恢复按钮，不证明真实供应商可用性，详见 `docs/agent-release-check.md`。节点单项摘要沿用实时引用；请求核对的取回入口只查询已受理原任务，禁止重复点击、运行中和取消后取回。工具级 `submitted=false` 不代表整轮未计费。

画布连线：单击选中标红，再次单击或 Delete / Backspace 直接删除，仅节点删除遵守确认设置。目标左侧输入连接点拖至空白画布可断开；多条入线时需先选中唯一要断开的连线。所有删除复用画布持久化与撤销，保留运行中节点锁定和输入框键盘保护。真实指针回归：`npm run test:canvas-edges`。

连线保存冲突校验将缺失标签与空字符串视为同一无标签状态，仍拒绝真正的标签或端点并发变更。`npm run test:canvas-edge-persistence` 需要运行中的本地 API（默认 8765，可用 `AICS_TEST_API_URL` 指定），自动创建并清理临时项目，以真实 API 验证删除后整页刷新、卸载重进、重进后撤销及恢复状态再次刷新。节点底部生成测试只捕获提交参数并结束测试占位状态，不调用 Provider；检查引用清除/恢复、单次提交及上游内容保留。撤销历史仅保留在应用进程内，整页刷新不恢复撤销栈。

空白媒体节点的画幅修改通过 `CanvasPromptPanel.vue` 的 `aspect-change` 事件即时更新并保存画布，复用 `nodeSizing.ts` 的 `nodeAspectPatch` 清除旧像素尺寸与比例别名；保留模型等其他参数，支持画布撤销。已有产物和运行中节点不受此修改影响。节点模型菜单复用 Teleport 的 `AnchoredPopover`，不使用原生 select 或随画布缩放的绝对定位列表。

桌面更新由 `apps/desktop/src/appUpdates.ts` 管理，入口为头像上方的 `AppUpdate.vue`。仅正式 Windows NSIS 版延迟检查公开 GitHub Releases；开发、便携和 macOS 禁用检测。下载和安装分别需要用户点击，`autoDownload` 与 `autoInstallOnAppQuit` 始终关闭。`scripts/package-windows.mjs` 保留运行环境组装，再经 `windows-update-installer.mjs` / `electron-builder.config.cjs` 生成安装包与 `latest.yml`（完整）或 `lite.yml`（轻量）；本地构建固定不发布。依赖必须进入 `desktop-runtime-dependencies.mjs`，不可绕过完整性和签名校验。发布与验证见 [desktop-updates.md](docs/desktop-updates.md)。

EvoLink 公开人民币报价由后端 `evolink_prices.py` / `evolink_price_data.json` 与前端 `CreditPricing.vue` 提供，按 `credits.usdToCny` 换算并保留原币种、单位及日期；公开目录不代表可调用模型，不补算实际扣费。更新入口 `scripts/import-evolink-prices.py`，单位和变体边界见 `docs/evolink-pricing.md`。

```text
首页 / 项目输入框
  → POST /api/intake（创建项目及接收资料，按需）
  → POST /api/projects/{project_id}/tasks（design）
  → TaskRuntime：保存输入、排队、事件、取消与恢复
  → RoutedDesignRuntime：模型路由与执行策略
  → DesignRuntime：Python 启动 Node worker，传入 JSON，读取 JSONL 事件
  → openai_agent_worker.mjs：SDK Runner / Session / 工具调用
  → /api/projects/{project_id}/agent-tools/{tool_name}
  → DesignToolRegistry → 业务服务 / Provider → AssetStore → CanvasStore
  → 保存回执、检查点和交付检查 → 前端更新对话及画布
```

- `designTaskStream.ts` 先读取任务 SSE，断线后退回状态轮询；重新观察任务不应重新提交生成。
- `worker_failure.mjs` 沿异常 cause 链识别供应商断流；`other side closed` / `UND_ERR_SOCKET` 即使被 TypeError 包装，也不能判为本地故障或未提交。费用维持待对账，禁止自动重发。`TaskProgress.vue` 的状态文字原位更新，不使用 `out-in` 先移除节点的过渡；重新提交的耗时从本次 queued 事件计算，消息原创建时间仅用于对话顺序。
- 任务创建可带稳定 `requestId`；服务端按项目保存请求哈希与任务映射，相同内容返回原任务，不同内容复用同一 ID 返回 `409`。旧客户端仍可省略该字段。
- 就绪设计计划直接执行；无变更原因的重复保存返回 `plan_reused` 并保留原清单、视觉要求与进度，该状态不计入参数纠错；本批所有交付已有真实产物或不可重试的待核对结果后，再次复用计划直接保存并交付。真正变更通过 `design_plan.change_reason` 说明，仍校验已接受范围。网关前参数解析和 SDK 非法 JSON 均纳入持久化纠错上限；选图/跳过参考及纯继续复用原计划。七项礼盒回归见 `test_gift_plan_recovery.py`，运行版本核对 `/health.agentRuntimeRevision`。
- 多项规划的旧默认单轮输出额度在提交前由 `model_output.mjs` 预留为 32768 tokens；按交付约定或已有计划识别两项及以上，不能等可选计划生成后才扩容，且不超过模型声明的上限。普通任务仍为 4096，非默认自定义上限保持不变，不改写存储配置。计划继承已保存的视觉方向，避免重复输出。文本截断保留已报告用量、标明已提交并停止自动重发，不执行不完整工具，也不宣称升级模型。
- 计划范围 area 使用当前框架 ID 枚举并兼容已知中文标题；重复 ready 计划无 change_reason 时只读取原计划，不先校验或采用替代内容。批次缺工具名仅可根据明确绑定的 ready 图片交付项补齐。套系内 Agent 自行变动的比例在预检与执行时归回原计划，用户尺寸/比例、画布尺寸及像素冲突不覆盖。
- 项目主 Session 是 `project:{projectId}`；研究使用任务阶段 Session。同项目主任务串行，单任务内的独立生成可以并发。
- 图像断流保留 `generation_unconfirmed` 及未知计费回执，不自动重发。worker 与本地网关失联后由 `image_result_wait.mjs` 查询 `POST /api/projects/{project_id}/tasks/{task_id}/tool-result` 原参数回执，最多等待 15 分钟；迟到成功结果合入批次交付记录，检查点恢复也以真实成功回执修正旧失败状态。查询不会调用 Provider。
- `agent_sessions.py` 保存 SDK 历史；`execution_store.py` 保存执行检查点与工具回执；`conversation_memory.py` 保存有来源和范围的业务记忆。三者职责不同。
- 演示响应优化：明确单图/局部修改不例行另做需求记录、计划或技能目录查询；首轮无历史/附件/参考/计划时本地初始化空记忆选择，普通回答不为可选记忆整理补跑模型。工具 schema 提前计入上下文预算，同轮较早已完成工具转为配对短回执，最新批次和待修正错误保留。`session_blobs.py` 按项目无损去重 SDK 历史图片，旧会话按次原子迁移；会话读操作不占写锁，worker 仅缓存已确认事务。参考分析及未知收费保护不变；见 `docs/conversation-context.md`，验证入口 `test_agent_efficiency.py`、`test_memory_sdk.py` 和 `sdk_context.test.mjs`。
- 图像/音频工具通过 `image_jobs.py` 分别写入 `image_operations` / `audio_operations`，持久化受理并返回 202/operationId，worker 查询原操作；断线、重启和未知收费结果不得重发。`image_recovery.py` 保存 EvoLink 已受理任务编号，任务详情的“取回原结果”仅 GET 原任务并下载，不重新生成；按原回执幂等保存、不覆盖用户已有节点。`late_image_results.py` 同步真实保存结果，媒体播放检查通过后收尾，不触发额外模型调用。
- 迟到媒体使全部交付通过后，同步任务与检查点为 succeeded，清除当前错误并在 provenance 保留原失败原因；只恢复真实成功回执，取消任务不恢复、未完成交付不冒充成功。下载失败的已生成媒体使用原任务取回入口；只有 GET 查询和下载可以有限重试，生成 POST 不重发。
- EvoLink Responses 使用 `portable_responses.mjs` 在发出请求时去除旧服务端资源 ID 与不透明推理数据，保留公开消息、完整工具调用配对及本地 Session。流式受理后记录响应 ID，断流保留待对账，不能当作未提交重试。
- 混合类型交付使用 `design_planning.py` 的 `deliverables` 清单：一次登记用户要求的类型、数量和稳定 ID，不额外研究或等待确认；文字卡使用 `canvas_create_text`，已完成项不得因 Agent 改词而重做。`task_policy.py` 的数量只绑定最近的产物名词；“两张图和文字卡”是两张图片加一张文字卡。简单单图不受此清单要求影响。
- `media_preflight.py` 在模型调用前检查音频/3D 配置；EvoLink 仅在本地真实目录有 `qwen-audio-3.1-tts-flash` 时补齐空白语音选择，不替换手动模型。3D 在设置 → 模型与连接 → 独立 3D 服务配置，使用单独的地址/Key，不跟随文本服务切换。
- 视频异步受理后，同一任务同一节点或交付项的调用复用原 job（即使提示词被改写、worker 重启），不能重复收费；明确单视频交给后台查询，不再为等待结果补跑模型。EvoLink 默认 Seedance 家族只按本地目录解析对应文生/图生变体，不更换档位或覆盖手动选模。镜头默认跟随用户描述。
- HTML `srcdoc` 预览的 `#锚点` 由 `htmlPreview.ts` 在文档内滚动，不能导航回宿主应用；原沙箱和 CSP 保持有效。CAD 构建子进程的 HOME/USERPROFILE 指向本次临时构建目录，不能加载用户凭据和配置。真实浏览器跨类型测试记录见 `docs/browser-project-types-20261021.md`。
- v11：`delivery_execution.mjs` 的 `completionDecision` 统一生成后与最终交付检查的完成/缺项判断，只补依赖就绪项，未知收费不补发。批量 schema 与参考预检一次列出全部条目错误；展示精确数组下标，纠错计数签名仍使用 `*`，不能换条目重置预算。`task_timing.py` 和 `inspection.performance.timingMs` 记录上下文、文本、预检、上传、提交、服务商等待、下载与保存；缺失为 null，轮询观测的排队/处理包含在等待内，并行累计不能相加。EvoLink 上传复用仅使用带时区的官方有效期及同文件/内容/凭据，进程内最多 128 项；生成提交与未知收费保护不变。
- 工具严格解码只用于已确认支持的入口；未知中转保留本地校验，不按模型名猜测能力。批量参数使用工具分支契约。计划修改核对 revision/scope，执行动作和交付 ID 独立于正文精简保留；整批完成且无新补充时直接保存并完成任务。
- 媒体产物先保存成真实资产，再由画布节点引用资产 ID。Node worker 通过 Python 工具网关执行项目业务；Provider 协议适配集中在后端。
- 画布节点独立生成：服务端入队校验目标类型，worker 启动前绑定 taskId；前端不能在任务受理后补写 generating 覆盖快速完成结果。断线、取消失败及未知受理不清空原任务或自动重发；提交锁按项目/节点隔离，CAD 手动模型参与文本路由。回归见 `docs/canvas-node-generation-20261022.md`。
- 节点底部输入框真实回归见 `docs/node-composer-live-20261023.md`，自动化入口 `npm run test:node-composer`。音频默认音色由服务决定，不能在通用输入框固定 alloy；EvoLink GPT Image 2.5 的 auto 背景在适配层省略，明确透明/不透明保留。CAD 不展示不参与请求的画面参数。
- 节点生成前由 `node_context.check_canvas_inputs` 检查上游就绪状态、图片资产与提交快照、已读取内容版本；首次预检前变更也必须拦截，不能因资产不再匹配而漏掉节点版本检查。输入框重连与失败后新提交重新获取引用，原请求重放只返回原任务，不自动重发未知收费请求。
- 节点任务交付类型及数量由目标节点确定（单项），不能把提示词提及的上游图片/视频/文字再推断为额外交付。文字/HTML 节点 ID 不得作为计划图片资产 inputs；计划保存前给出准确纠错。普通文字误带无效 application_items 时，在写入前返回可纠正参数错误，沿用既有纠错上限，不直接报能力缺失。
- 节点连线引用按来源去重，文本完整传入、视频首尾帧保持顺序、多图保留全部资产。交付数量排除“第二张海报”等序号和“参考两张图”等输入数量，不能据此扩增生成。EvoLink Seedance 2.5 图生视频只接受 adaptive，输出沿用首帧比例；文生视频比例不变。回归包括节点输入框三类连线、重复点击、数量推断与服务适配。
- 独立节点会话隔离历史时，仍将显式连入的其他任务生成图加入记忆候选并保留原始来源；不导入无关资产。SDK 压缩已完成工具回执只缩短元数据，保留本轮已去重的图片像素，避免多图参考交替补读；历史图片和硬容量边界仍按原策略处理。
- 复杂设计在理解上下文后、澄清或规划前，由主 Agent 按需通过 `design_state.brief` 保存派生任务说明，不另设润色模型。原始消息和有来源的明确约束优先；假设与待确认项分开。局部修改不强制整理，需求变更或补充答案后清除旧说明，纯确认续接可复用。
- **生成后直接交付**：已删除自动质量审查 Agent、总览图生成、审查解析、审查缓存与失败重试。设计质量留给用户；不自动自检、修复、复审，不展示旧“已发现问题”“尚未核实”等质量结论。保留生成前参数校验、真实文件/数量/预览状态和未知收费保护。旧记录只在读取展示时兼容，不改历史计费账本。
- **执行优化策略 v2**：新任务由服务端写入 `executionPolicyVersion=2`；旧任务恢复不改策略。只有明确独立研究报告/研究阶段才单开研究 Agent，普通查证由主 Agent 按需使用检索工具。无歧义的单图/文本/HTML 取得真实产物且无运行中补充后直接完成任务；混合、未完成、未知结果和额外导出仍走完整判断。普通文本直接 `canvas_create_text`，显式 Skill 所需和历史任务仍兼容 `generate_text`。`execution_efficiency.mjs` 只精简模型看到的成功写入回执，不改真实内容；交付检查缓存以输入、画布、文件、参考、预览和补充版本失效。`/tasks/{id}/inspection.performance` 区分 SDK 请求、额外文本和已提交图像，缺少数据为 null，不把外层 `main_agent` 路由算作一次模型调用。回归见 `test_execution_efficiency.py`、`execution_efficiency.test.mjs`；Windows SDK 夹具使用 file URI 与 UTF-8，pytest 建议 `python -X utf8 -m pytest`。
- 项目 Agent 回复仅展示简洁状态、正文及必要异常提示；执行详情保留在运行记录，不在回复中展开。产物与用量入口使用头像栏图标；成功保存提示只保留正文一处（无正文时由状态区兜底），不重复展示底部“产物已保存”标签。
- 常规设置使用 `components/GeneralSettings.vue` 与 `features/generalSettings.ts`：本地保存任务后台通知、发送快捷键、启动恢复、产物定位及分类型删除确认。队列默认设置保留原键；通知只针对已观察到的运行任务终态变化，不回放历史。存储占用由 `storage_management.py` 读取，清理仅清除可重建的预览内存缓存，桌面端额外清理 HTTP 缓存；不得删除项目、原图、草稿、会话和运行记录。桌面打开目录仅使用主进程当前工作区路径。
- 桌面常规设置可迁移数据或打开已有工作区：`workspaceStorage.ts` 校验独立目录，迁移仅允许空目标且不跟随链接；主进程阻止活动任务期间切换，等待 API 真正退出后复制，保留原目录，原子保存位置并重启。失败不改变当前路径；环境变量固定位置或外部 sidecar 模式需先调整启动配置。回归入口 `workspaceStorage.test.ts`。
- 外观顶部的 `AppearanceSettings.vue` 提供模式缩略图、中性灰/雾海蓝/苔原绿/暖沙/暮光紫/蔷薇六套配色，以及强调色、背景、文字和字体自定义。`features/appearance.ts` 按深浅模式分别保存自定义颜色，只覆盖共用主题变量；默认中性灰恢复原 CSS，不覆盖状态信号色或作品颜色。修改即时生效并本地保存，系统模式变化由 `applyTheme` 同步重新应用配色。
- 任务终态包括 `succeeded`、`failed`、`cancelled`；交付状态独立，例如 `pending`、`passed`、`needs_review`、`failed`。执行结束不等于所有交付已通过。
- `needs_review` 仅兼容表示未完成交付或执行异常，不再代表设计质量结论。`delivery_findings.py` 只呈现文件缺失、生成失败、未完成计划和请求结果未知等运行状态；成功产物直接标记完成。异步媒体及迟到图像按本地保存结果收尾，不再启动模型。

- 同款产品主图与场景通过计划 `inputs.role=identity` 绑定真实资产；新主图用 `source=deliverable`，已有产品图用 `source=asset`，不增造母版。`product_identity.py` 在明确无歧义时补齐依赖并规范参考用途；`generation_batch.mjs` 延后尚需看主图的场景，worker 在成功回执中附本地主图预览，下一轮直接组织场景参数。统一图像预检强制真实图片及分析，不能退为无图文生图；多个场景共享主图后并行，成功项不重做，不增加质量审查。详见 `docs/agent-flow.md` v13，回归 `test_product_identity.py` 和 SDK `product_identity` 场景。

## 5. 必须保留的业务边界

模型上下文压缩保留画布 scope 的节点 ID、版本和数组结构，节点正文独立压缩；不能将结构字段压成省略字符串后再作为数组读取。上下文 manifest 的证据列表按实际发送的数组记录。

画布手动对齐、均匀分布和方向键微调后，将选中节点标记为 `autoPositioned=false`；对齐基准节点即使坐标不变也必须固定，防止保存、内容尺寸变化或新增节点触发自动排版而破坏对齐。未选中节点和显式“自动整理”继续使用自动排版，撤销/重做保留位置及自动排版标记。

纠错预算按新的失败回执计数；同一失败之后成功的前置资料补齐或进度说明不重复消耗纠错次数。`design_spec_required` 必须重新开放规划工具。生成尝试终止不等于产物保存成功，上传失败或未知结果按真实回执收尾；交付有问题且没有真实就绪资产时标记失败。文本响应完整结束后清除活动响应 ID，后续本地校验错误不得沿用旧 ID 误报断流或未知计费，原用量记录保留。回归见 `test_gift_plan_recovery.py`、`delivery_execution.test.mjs`。

计划保存及复用均核对视觉方向与逐图规格是否可执行，使用与生成预检相同的校验。`design_spec_required` 纳入持久化纠错上限且不能缓存为成功回执；预检明确 `submitted=false` 的工具不显示生成完成，修正次数不能靠改写提示词或恢复任务重置。

参考选择仅在存在真实候选图片时展示。无候选时 `referenceWorkflow` 记录为 `unavailable` 并继续，不生成空选择卡或等待选图；历史空卡片不阻塞输入及队列。此状态不代表用户主动跳过参考，也不解除实际附件、产品身份和原有设计约束。

常规设置的“发送时默认加入队列”开关本地持久化，默认关闭：运行中的纯文字消息直接补充，开启后加入下一项；附件、引用和技能仍入队。队列右侧可将纯文字补充给当前任务，发送前持久化原任务绑定并复用稳定请求 ID；结果未确认的补充不得自动改作新任务发送。无运行任务时维持正常发送及队列顺序。

执行策略 v3（`delivery-identity-20261022-v16`）：新任务的单项完成标记以服务端交付约定为准，普通续接或澄清答案不必重复数量。范围不明确、多项或附带其他交付时，主 Agent 在生成前通过现有 `design_plan` 登记本轮稳定交付 ID；不再用“包装”等个别名词推断单图。成功回执按真实节点去重，明确未提交的预检失败不妨碍完成，未知结果不忽略。`execution_store.py` 的 `tool_delivery_claims` 持久化任务内交付身份和已接收补充的版本，参数改写、同轮并发及重启不重复生成；不同交付、不同任务保持独立。旧任务恢复不升级策略。回归见 `test_delivery_identity.py`、`test_execution_efficiency.py` 和 `generation_batch.test.mjs`，细节见 `docs/agent-flow.md`。

1. **真实数据与项目归属**：文件、资产、引用和工具输入需校验项目范围；不能用占位图、默认研究结论或裸 URL 冒充已完成产物。测试 Provider 仅在 `AICS_TEST_MODE=1` 启用。
2. **恢复与防重复收费**：复用已保存的成功回执、Session 与资产；响应丢失、重启后的未知收费请求需保留待核对状态，不能通过重发或改参数绕过。文本调用只有明确未提交的临时网络、限流或服务错误可在原端点恢复，最多 2 次；同类参数/结构错误最多修正 2 轮，每阶段累计恢复最多 6 次，计数写入检查点。正常 Agent 轮次没有成本型上限，只保留 60 轮技术保护。图像自动降级仅允许目录缺失、无用量 429，以及无用量且明确模型不存在/不可用/无图像端点的 400/404/422；5xx、超时、断线、无效响应、失败事件和 SVG 不降级。取消、重试、模型切换均须保留这一约束。
3. **按依赖生成**：输入已就绪的独立交付项使用 `generate_batch`；有上游新产物依赖或修改同一节点时顺序执行。不要重新加入固定并发数量限制；单项失败不丢弃其他成功项。
4. **计划与引用**：品牌/全案先明确本轮范围，交付项通过稳定 `deliverable_ids` 关联真实节点。输入框附带的普通图片默认是参考候选，不等于待覆盖节点或强制排版依据；只有用户明确要求沿用排版/构图、已接受计划或套系母版时才使用 `layout`。客户端不提供逐图用途手动选择，也不在草稿、队列、重发或画布任务中提交或沿用旧 `referenceMode/referenceModes` 覆盖值；图片用途统一按用户原文、图片绑定关系和视觉分析智能判断。指向具体图片或图中对象的增删、替换、改色、换背景及时间/环境/状态变化均视为 `edit`，“生成/制作/做一张”本身是中性动词；明确只借鉴风格、配色、氛围或制作另一款才是参考。多图只有资产提及、文件名或图1/图2等能唯一绑定时才对单图强校验；同一分句列出多图或“参考图/这张图”无法区分对象时保持 `ambiguous`，明确“所有图片/这两张图都”才作用于全部图片。高置信度用途在统一预检内直接规范化为 `edit/identity/layout/inspiration`，只修改 mode 和必要 preserve，不再消耗 Agent 纠错回合；只有图片绑定本身不明确时才澄清。Agent 使用图像参考前实际看图、反推视觉描述并融合本项需求，填写 `reference_analysis`；`inspiration` 仅注入语义，`identity` / `layout` / `edit` 按保留项传入原图；用户画板默认 `layout`，保留结构关系而不复制草稿笔触。明确改图不得扩大用户指定范围；遮罩重绘的原图分析必须为 `edit`。反推描述不冒充原作者提示词。文本 Agent 只接收最长边 1600、单图不超过 2 MB、总计不超过 8 MB 且最多 8 张的规范化预览；实际图片 Provider 始终读取原图。所有图像调整都将旧图作为来源并在新节点生成，保留画布上的全部图像；仅当前画布输入的空白待生成节点可以直接填充。已有内容节点只作为来源，必须直接连到新空白节点后生成；目标节点及其资产不得引用自身，旧自环边不参与生成。图像输出模式由统一解析器补齐，预检与执行共享来源绑定并核对版本；严格多图绑定仅漏传部分 ID、但方案内逐图分析已经完整时由预检直接补齐，存在方案外图片或缺少分析时返回精确差异并只自动修正一次；收费回执仍按原始调用参数匹配。图像像素默认是可继续生产使用的干净成品；未知尺寸、材质、工艺及“概念示意/仅供参考/参数待确认”等内部说明写入节点 `productionNotes`，不画成角标、水印或占位文字，除非用户明确要求可见的信息图或工程标注。智能召回和新选图片记忆默认只是候选，按交付项实际选用；显式记忆引用方案和旧快照继续严格校验。主题用于收窄自动召回，显式选择可以复用旧主题中仍适用的记忆且不改写其原范围。澄清续接保留原目标、答案、跳过状态和引用。用户事实需有真实来源；历史生成图不会自动成为用户确认的 Logo 或母版。
5. **画布并发**：节点生成使用 `canvas_node` 独立任务和独立 Session，不进入项目对话、标题、草稿或待发送队列；不同节点可并行，同一节点只允许一个活动任务。使用增量节点/边变更与内容版本检查，避免整份旧快照覆盖 Agent 或用户的新修改；轮询不能抢走用户手动调整的视野。自动排版仅移动未锁定节点，把锁定节点作为障碍；解锁触发补排，排版遇到 409 时静默刷新并延后，不能向对话抛原始 JSON。回归入口 `npm run test:auto-layout-locks`。
6. **SVG 生成全局禁用**：生产 Agent / Skill 不得通过 SVG 工具、内嵌 SVG、旧设置或复用旧 SVG 交付绕过。视觉产物使用图像模型，精确文字按需使用 HTML/CSS。历史文件查看与应用界面图标仍可保留。依据是 `svg_policy.py` / `.mjs` 及 `test_svg_policy.py`，旧专题文档中的 SVG 制作说明已过时。
7. **Provider、上下文与凭据**：手动选模优先；默认配置集中在 `model_config.py`，FAST / STANDARD 均为 GPT-6 Luna（`openai/gpt-6-luna`），REASONING 为 GPT-6.1 Sol（`gpt-6.1-sol`），PREMIUM 为 GPT-6 Astra（`gpt-6-astra`）。自动模式不因附件、参考图或画布任务换模；仅在提交前由本地目录明确证明 Luna 缺少所需输入能力时，才在同一服务切到 GPT-6 Sol（`openai/gpt-6-sol`）。输出质量、工具错误、轮次变多、网络或本地运行错误均不得自动升级到 Sol 或 Astra；GPT-6.1 Sol、GPT-6 Sol、Astra 及其他模型仍可手动选择。每轮模型输入保留当前需求、最近 4 轮原始对话、已选记忆、设计状态和未完成交付，旧工具正文及图片改为回执/资产引用并按需读取；预计超过 12K 时本地压至约 8K，仍超过 `min(16K, 模型窗口 40%)` 且有待完成项时才允许一次原生压缩，失败不重试也不阻断。`generate_text` 复用本轮实际端点；搜索、参考分析、AI 评价和定时计划默认跟随最近明确选择的文本 Provider，只有显式独立配置才跨 Provider；项目标题纯本地生成。图像自动路由 draft 为 Flare → Sunburst → GPT Image 2 → Seedream，standard/final 为 Sunburst → Flare → GPT Image 2 → Seedream；自动模式过滤 GPT-5.4 Image 2，手动选择仍允许且不兜底。旧 DeepSeek/GLM、未修改的内置 Terra STANDARD、旧轮次上限、v5 全 Sunburst以及 untouched 的固定 OpenRouter 搜索默认配置在读取时迁移；配置版本 10 同步迁移旧内置 GPT-5.6 Luna / Sol 为 GPT-6 Luna / GPT-6.1 Sol，保留自定义端点、模型、角色模型、媒体槽位、搜索配置与手动选模。可用模型取本地已同步目录。打开菜单不自动联网同步。CloseAI 可选目录管理密钥只在显式同步时读取完整模型类别与报价，必须与普通生成 Key 分开保存和使用；没有管理密钥时保留普通目录与经 API 确认的媒体别名。模型输出分类按管理 `category`、输出模态、端点、稳定家族规则依次取证；显式未知类别留在 `unknownModels`，不默认冒充文本。中转站原始 `owned_by` 与家族归一 `vendor` 分开保留。所有模型调用只在 `model_call_trace` 记录调用种类、档位、端点、模型、来源、耗时、状态、提交状态和计费确定性，不保存提示词、Base64 或凭据。所有凭据经 `credentials.py` / `windows_credentials.py` 进入系统凭据库或环境变量，不写入任务、画布、日志或导出。修改默认值时同步核对前端 `modelEconomy.ts`。模型价格遵循手动报价、目录报价、已核对默认表的优先级；按规格变化的起始价只展示参考，实际费用优先，不重算历史账本。
   - 可选 `ollama` 文本 Provider 默认连接 `http://127.0.0.1:11434/v1` 并使用 `gpt-oss:20b`，无需 Key、仅手动选模、不改变 Luna 自动默认值，本地调用不进入积分账本；它不是媒体或托管搜索 Provider。
   - 缓存规则和动态项目上下文分开组装；只向已确认的官方/OpenRouter 入口发送缓存控制，CloseAI/未知中转继续兼容的稳定前缀与本地精简。缓存读取与写入按各入口明确报价分别计费，缺失统计不冒充零命中，缺失写入单价保留待计费。原生压缩返回的完整窗口不得再次裁剪；尝试次数跨检查点保留，失败不重试、不探测其他收费入口。详见 `docs/conversation-context.md`。
8. **应用内 Skill 与本地任务**：技能包是产品数据，安装或加载不会自动执行其脚本，也不授予额外工具权限；定时任务只在本地 API 运行时执行。`builtin_skills/` 中的说明面向产品 Agent，不是本项目开发指南。
9. **图像质量与分辨率**：用户明确指定的模型、质量和尺寸优先；未明确质量或生产用途时默认 creative / draft、low / 1K，明确普通/标准质量时使用 standard、medium / 2K，明确最终、高清或正式交付时使用 final、high / 2K，印刷与大屏使用 final、high / 4K，明确要求最好效果时 max / 4K。参考图、改图、主体保真、普通效果图和 Agent 扩写出的精细描述都不能自行升级档位。模型档位、Provider quality 和分辨率由 `image_quality.py` 统一决定。用户原文和界面尺寸是严格约束；Agent 自行推导的 `3840x1200` 等像素只提供画幅比例，不升级质量或直接要求 2K/4K，实际输出仍按创意档合法 1K 尺寸生成。参数预检失败在本地修正或立即返回，不得用说明性回合耗尽调用次数。OpenRouter 带原图的请求使用非流式响应，不能因流式限制移除原图或改成纯文字重生成；详细规则见 `docs/image-provider-dimensions.md`。

## 6. 运行、配置与数据位置

从无数据源码包在新电脑启动时，先读 `RUN_IN_CODEX.md`：`npm run start:portable` 通过 `scripts/run-portable.mjs` 安装锁定依赖并启动网页/API，默认使用解压目录下的 `.local/portable-workspace`，不读取原电脑工作区配置。`npm run verify:portable` 使用临时空工作区验证启动后退出，不调用模型；端口冲突时自动选择空闲端口并同步前端 API 地址，通过 `AICS_DEV_WEB_ORIGIN` 仅为该回环地址增加 CORS 许可。需要 Node.js 22 / 24 和 uv，Python 3.12 由 uv 准备。

以下命令均从项目根目录执行；依赖版本以 `package-lock.json` 和 `services/api/uv.lock` 为准。

```bash
# 初次安装
npm install --ignore-scripts
uv sync --project services/api

# 网页开发：Vite + API
npm run dev:web

# 桌面开发：Vite + Electron，由桌面启动 sidecar；浏览器与桌面共用 8765
npm run dev

# 已有独立 API 时复用它
AICS_SKIP_SIDECAR=1 npm run dev
```

- 网页开发：`http://127.0.0.1:5173`；API 默认 `http://127.0.0.1:8765`，健康检查 `GET /health`。
- 桌面开发的 Python sidecar 默认不带 `--reload`；修改后端源码或模型默认值后，需重启 sidecar 或桌面应用才能加载。核对实际运行配置时读取 `/health` 的 `modelDefaultsVersion` 和 `/api/model-settings`，不能仅根据源码或构建结果判断已生效；切换新模型还需同步当前服务的模型目录。
- 修改 `services/api/app/builtin_skills/` 中的资源时，必须同步更新 `manifest.json` 中的文件 SHA-256 和 revision；否则完整性校验会阻止 API 启动。开发重载会同时监听 Python、MJS、JSON、Markdown 与 YAML，使随后写入的清单能够再次触发恢复。
- `services/api/app/easter_egg_assets/` 是随 sidecar 打包的只读预生成图片；运行时复制到项目的系统资源带 `systemHidden`，画布可展示但不进入普通资产库或百图成就计数。
- 桌面自行启动 API 时，开发版固定使用 `8765`，使 Vite 页面在普通浏览器和 Electron 中共用同一 API；端口被占用时明确失败，复用已有 API 应设置 `AICS_SKIP_SIDECAR=1`。打包版优先使用 `8765`，占用时可分配其他端口，并通过 `window.studio.apiBaseUrl` 告知 Electron 页面。前端地址优先使用 `window.studio.apiBaseUrl`，其次 `VITE_API_BASE_URL`，最后 `8765`；不要在组件内写死端口。
- **浏览器开发工作区优先级**：`AICS_WORKSPACE_ROOT` → `.local/dev-api.json` 的 `workspaceRoot` → `services/api/workspace-data`。用 `node scripts/dev-api.mjs --print-workspace` 查看实际路径，不要为排查问题擅自切换现有目录。
- **桌面工作区优先级**：`AICS_WORKSPACE_ROOT` → Electron 用户数据目录中的 `workspace.json` → 检测到的旧工作区 → Documents 下的 `Langju Design Studio`。
- 工作区 `catalog.sqlite` 存项目、任务、模型、Session 等元数据；`credits.sqlite` 单独存计费账本。项目文件夹存 `project.json`、资产、资料、画布、版本与导出；各服务负责自己的表初始化和兼容升级。
- 调试使用临时工作区；真实 `workspace-data/`、`.local/`、数据库、系统凭据和发布包不是测试夹具。启动真实 API 可能恢复未完成任务，先确认使用的工作区。
- 网页使用 History 路由，桌面 `file://` 使用内存路由。当前参考库为 `/references`，历史资料为 `/references/legacy`，旧 `/knowledge` 跳转到参考库；完整路由以 `features/navigation/routes.ts` 为准。设置使用 `/settings/:section` 独立页面，默认用户中心 `/settings/account`，兼容 `/account` 与 `/settings` 跳转。`pages/SettingsPage.vue` 管理分类和内容容器，`AccountPage.vue` 展示真实工作区数据；其余设置由 `App.vue` 通过 Teleport 注入，保留原配置处理逻辑。设置和图标侧栏布局统一在 `settings.css`，不要恢复设置弹窗。头像点击先打开信息概览小卡片，点击卡片中的“设置”才进入设置页；卡片只展示现有资料和真实使用数据。用户头像使用简笔画人物图集，首页吉祥物与项目 Agent 头像共用外观设置中的形象。

## 7. 怎么验证改动

按影响范围选测试，纯文档改动检查路径、命令和内容即可。新增业务行为应验证实际结果及重要边界，避免只重复实现逻辑。

| 场景 | 命令 / 说明 |
| --- | --- |
| TypeScript / Vue / 桌面类型 | `npm run typecheck` |
| JS/TS 单元测试 | `npm test`，包含前端、脚本及后端 `.test.mjs` |
| 交付状态与原因展示 | `npm run test:delivery-findings` 使用隔离模拟画布检查四类提示、原因/下一步、产物定位与深浅色/窄面板，不调用真实 Provider。 |
| 指定 JS/TS 测试 | `npm test -- apps/renderer/src/designTaskStream.test.ts`（替换为相关测试路径） |
| Python 全套 | `npm run api:test` |
| 指定 Python 测试 | `uv run --project services/api pytest services/api/tests/test_canvas_interactions.py -q`（替换为相关测试路径） |
| 桌面构建 | `npm run build` → `dist/renderer` 与 `dist/desktop`；不包含 sidecar 重打包 |
| 网页构建 | `npm run build:web` → `dist/web`；预览 `npm run preview:web` |
| 画布或输入交互 | 按需选 `npm run test:canvas-selection`、`test:canvas-workspace`、`test:interaction-upgrade`（队列暂停/编辑、请求核对、运行中补充与版本对比）、`test:message-editing`、`test:clarification`、`test:drawing-canvas` 等；完整清单在 `package.json` |
| 小居表情图集与头像 | `npm run test:xiaoju-sprite` 检查六个表情在首页与 24 / 44 / 88 px 头像中的实际图像基线，`npm run test:generation-feedback` 检查运行中对话显示。共用位置补偿与动画位于前端 `style.css`，组件不重复定义切帧坐标。 |
| 网页/桌面导航或技能页面 | 先 `npm run build` 与 `npm run build:web`，再运行 `test:page-navigation`、`test:skills` 或 `test:skill-mentions` |

- Python 测试由 `services/api/tests/conftest.py` 启用测试模式，业务测试使用 `tmp_path` 和模拟 Provider。SDK 集成测试可运行真实已安装 SDK，但上游传输使用 fixtures；不等于验证真实服务在线能力。
- `scripts/test-*.cjs` 多为隔离 Electron/Chromium 界面验证，部分读取构建产物，部分自行启动 Vite；运行选定脚本前查看其前置条件。`npm test` 不代替这些界面验证。
- 跨层改动通常需要类型检查、相关 Vitest / pytest 和受影响的构建；只做网页构建不能证明桌面路径、preload 或 sidecar 可用。
- 缓存与压缩展示使用 `npm run test:context-optimization`，检查真实 Vue 组件的读取/写入统计、缺失数据、原生压缩状态、深浅主题与窄屏；使用隔离页面和模拟数据，不连接真实 Provider。稳定前缀、缓存写入单价及压缩恢复边界见 `docs/conversation-context.md`、`docs/model-pricing.md`。
- 发布打包另见 `docs/PACKAGING.md`：`npm run package:mac` 重建 `dist/release`；`npm run package:all` 输出完整版本，`npm run package:lite` 输出轻量核心包及独立 CAD/媒体能力包。后端或 worker 改动需重新构建 sidecar，不要把普通前端构建当成完整发布包验证。

## 8. 按需阅读的专题文档

显式补齐由 `missing_delivery.py` 验证原任务和实际缺项，禁止重做已保存项或重发未知收费请求；前端 `taskOutcome.ts` 统一主结论，详细行为见 `docs/agent-flow.md`。真实 Token 和人民币汇总由 `credit_reporting.py` 和前端 `features/credits.ts` 提供：`HomeUsageSummary.vue` 在首页顶部中央以小字显示累计 Token 与已确认扣费，估算单列为非扣款；用户概览和活动图共用实际 Token。没有费用回执的请求保持待对账，不能将旧账本按价格计算的 `settled` 当作真实扣款。`evolink_billing.py` 提供统一费用查询与有界批次对账，设置 → 用量与计费可查询原任务；本地用量轮询不访问上游，不将账户余额差归属到单次调用。历史字段和预算存储保留兼容，前端不显示积分规则，不由费用或媒体张数换算 Token。手动报价入口为 `CreditPricing.vue`，边界见 `docs/model-pricing.md` 和 `docs/evolink-integration.md`。

简易设计执行优化入口：`services/api/app/reference_efficiency.py` 管理可选空参考降级，`execution_efficiency.mjs` 收起已就绪计划的重复规划工具，`application_inventory.py` 根据实际产物生成应用清单状态。三者均不增加模型调用；产物保存后直接交付，详见 `docs/agent-flow.md`。修改时运行 `test_design_efficiency_gaps.py`、`test_execution_efficiency.py` 与相关 MJS 测试。

图像 401/402/403 拒绝在 `design_tools.py` 保存为任务级 `stopTool` 回执；`generation_batch.mjs` 将终止失败视为已尝试，不允许自动补齐阶段重发。已完成产物保留，未生成项仍未交付，见 `test_image_dispatch.py` 和 `test_execution_efficiency.py`。

EvoLink 文件与媒体传输使用真实应用 User-Agent；下载不带 Key。参考上传失败使用 `reference_upload_failed`，注明生成尚未提交并停止工具，不移除原图或自动重试。官方接口与联调边界见 `docs/evolink-integration.md`。

| 主题 | 文档 |
| --- | --- |
| 总体边界 / Agent 流程 | [architecture.md](docs/architecture.md)、[agent-flow.md](docs/agent-flow.md) |
| 前端页面 / 导航 / 草稿 | [frontend-pages.md](docs/frontend-pages.md)（路由以当前代码为准） |
| 首页输入框 IP / 六表情素材 | [lumo-composer-assets.md](docs/lumo-composer-assets.md) |
| Session、上下文与恢复 | [conversation-context.md](docs/conversation-context.md) |
| 用户记忆、图片引用与质量 | [conversation-memory.md](docs/conversation-memory.md) |
| 设计规划 / 批次续接 | [design-planning.md](docs/design-planning.md)、[design-batch-continuation.md](docs/design-batch-continuation.md)（SVG 部分已过时） |
| 模型路由 / 费用 / 搜索 | [MODEL_ROUTER.md](docs/MODEL_ROUTER.md)、[SEARCH_ROUTING_2026-09-14.md](docs/SEARCH_ROUTING_2026-09-14.md) |
| 模型默认价格与计费边界 | [model-pricing.md](docs/model-pricing.md) |
| EvoLink 模型目录与异步图像/视频 | [evolink-integration.md](docs/evolink-integration.md)；后端 `evolink.py` 分类与参数、`providers/evolink.py` 上传/任务查询/结果下载；测试 `test_evolink.py`。设置、输入框和定时任务共用服务商 `evolink`。连接设置只填 Key，官方域名 `https://api.evolink.ai` 与 `/v1` 路径内置，不显示地址字段；旧 EvoLink 配置也归一到该地址。 |
| 图像尺寸与 Provider 参数 | [image-provider-dimensions.md](docs/image-provider-dimensions.md) |
| 画布选择 / 引用 | [canvas-selection.md](docs/canvas-selection.md)、[CANVAS_REFERENCES.md](docs/CANVAS_REFERENCES.md) |
| 视觉参考库 / 技能库 | [visual-reference-library.md](docs/visual-reference-library.md)、[skills.md](docs/skills.md)、[builtin-skills.md](docs/builtin-skills.md) |
| CAD / 发布 | [cad.md](docs/cad.md)、[PACKAGING.md](docs/PACKAGING.md) |

历史 `*_AUDIT_*`、`*_INCIDENT_*`、`*_FIXES_*`、`LEGACY_CLEANUP_*` 用于追溯特定问题，不要求每次阅读。不要据旧记录恢复已删除的流程或已禁用的能力。

## 9. 维护本文

- 公开源码发布保留五语 README、MIT LICENSE、`docs/USER_GUIDE.md` 与 `docs/images/` 截图；归档以 `scripts/package-source.py` 的文件白名单和排除规则为准。源码包必须独立解压、安装锁定依赖并通过 `verify:portable`。私人案例媒体完整性测试在整套素材均不存在时明确跳过；布局断言照常运行，有部分素材时仍严格校验。发布结果记录在 `docs/RELEASE_VALIDATION.md`。

- 本文保留稳定的项目地图、命令和关键约束，不追加每轮工作日志、测试全量输出、用户资料或临时机器路径。
- 新功能优先放入对应页面、组件或业务模块；复用现有 `pageServices`、任务运行时、Provider 适配器和存储边界，避免继续把独立逻辑堆进入口文件。
- 新增模块、调整接口/存储/路由、改变生成策略或发布流程时，更新相关定位行及核对日期；详细说明放到 `docs/` 后从这里链接。
- 已有旧文档与当前行为冲突时，明确标记失效部分；模型 ID、供应商参数与精确限制以当前配置、适配器及测试为准，避免在多份文档中重复维护。

新增内置吉祥物：月团（moon-bunny）、暖栗（amber-fox）、汐团（sea-otter）、星眠（star-penguin），共八个预设；新增资源为透明 3×2 六表情图集，前端 mascot.ts、后端 mascot.py 和 mascot_routes.py 必须同步注册。生成提示词见 docs/design/mascots-20261023.json。

工作流 v1：独立 /workflows 模板库由 workflow_routes.py 管理，素材独立复制；打开创建工作副本。文件夹由节点搜索添加，FolderInputNode.vue 在一个节点内上传和展示文件列表，运行时逐项展开引用。WorkflowControls.vue 提供可编辑的整个流程重复次数、右侧上下箭头和绿色运行图标；workflow.ts 校验 DAG 并复制输出。GeneralCanvas 顺序等待原节点任务结果，失败/未知停止，退出画布停止追加，不自动恢复收费请求。内置空白图片节点右键可设转矢量/抠图步骤。扩展契约 capability_contracts.py 仅接受宿主显式注册的受信任处理器，不支持任意脚本热安装。规范 docs/workflows-and-extensions.md；验证 scripts/test-workflows.cjs、workflow.test.ts、test_workflows.py。
