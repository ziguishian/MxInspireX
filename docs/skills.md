# 工作区 Skill 系统

通用 Agent 的七个 SDK Tools 共用 `SkillService`。Skill 保存专业方法、参考资料、模板与已有工具依赖；创建和加载都不自动执行工作流。业务交付继续使用 `design_plan`、现有生成工具、依赖调度与验收。

## 使用

- 侧栏扳手图标打开「技能库」（`/skills`）。页面沿用项目、资产与参考库的标题、搜索和卡片规范，以三列卡片展示名称、版本、用途、来源与状态；搜索即时生效，详情中可启停、卸载、查看历史版本、下载资源和导出兼容技能包。
- 新工作区和现有工作区首次运行新版本时，自动安装六个内置技能：Logo 样机与品牌延展、原创 IP、笔记本印刷设计、空间导览与导视、小红书图文、展厅空间与逐墙设计。只安装专业方法，不触发生成或任务绑定。
- 「新建技能」跳转首页对话并填入创建提示；补充需求并发送，Agent 编写后调用 `skill_create`。修改也跳转对话，携带目标 ID 先读取再更新。页面没有手工创建表单。
- 「从 GitHub 加载」接受公开仓库、目录或 SKILL.md 链接，先识别候选技能，再安装选中的目录。支持指定分支、标签、提交和目录，识别结果锁定到提交 SHA，重试复用操作 ID。安装仅写入当前工作区，不自动绑定任务。
- 对话示例：**“创建一个包装设计 Skill，适用于日用消费品，包含需求收集、材料参考、设计步骤和验收要求。只保存方法。”**
- 在另一个项目使用：**“使用包装设计 Skill，为这个产品提出设计方案。”** Agent 通过目录或 `skill_list` 查询真实 ID，再 `skill_load`。
- 首页和项目对话输入 **`#`** 可选择已启用的技能；继续输入中文名称、英文名称或适用场景搜索。方向键选择，Enter / Tab 确认，Esc 关闭，也可以点击选择。支持多个标签，与 `@` 资料引用并用；移除标签即取消本条消息的选择，草稿和已发送消息保留名称。
- `#` 标签的内部文本是 `#skill:<id>`。服务端根据本条消息中的真实 ID 重新核验工作区、启用状态、依赖与联网许可，忽略客户端传入的名称、版本和正文；最多选择 8 个。发送成功后锁定服务端版本，SDK 在首轮模型调用前串行经过 `skill_load` 网关加载，执行记录显示真实回执。恢复时保留已有绑定与卸载状态，普通话题标签、Markdown 标题和链接锚点不触发加载。
- 删除为目录软删除。已绑定的任务继续原版本；新任务重新选择 Skill。已确认的原计划续接和后台交付审查保留原版本。

## 存储与版本

`<工作区>/skills/<skill-id>/versions/<version>/` 包含标准 `SKILL.md`、`langju.json`、`references/` 和 `assets/`。SQLite 的 `skills`、`skill_versions`、`task_skill_bindings`、`skill_operations` 分别保存目录、不可变版本、任务绑定和操作回执。数据库通过兼容性初始化创建，不搬迁原提示词或知识库。

名称使用小写英文标识，`title` 保存中文显示名。正文最多 24,000 字符；每个资源最多 8 MiB，总包最多 24 MiB、64 个资源。Agent 创建的资源仅允许资料格式和包内相对路径。项目来源使用真实 `sourceAssetId` / `sourceDocumentId`，服务端核验归属并复制文件，后续不依赖来源项目。

GitHub 导入保留 `SKILL.md` 的原始 YAML frontmatter、`agents/openai.yaml`、`references/`、`assets/`、`scripts/`、许可证和其他包内文件。导出 ZIP 以技能名称为根目录，可解压到其他 Agent 的技能发现目录（Codex 当前为 `.agents/skills/`）；不需要 `langju.json` 才能使用。标准依据：[Codex Skills](https://learn.chatgpt.com/docs/build-skills)。

导入使用公开 GitHub API 将 ref 解析到提交 SHA，再从 codeload 下载固定提交；不读取 Git 凭证，不跟随重定向。压缩包下载最多 32 MiB、仓库 20,000 个条目，单个 Skill 最多 256 文件、24 MiB，资源单文件最多 8 MiB。拒绝路径穿越、符号链接、加密文件及不安全 YAML。私有仓库暂不支持，重名包明确报冲突，不静默覆盖。

格式兼容不代表运行环境相同：脚本原文可下载，但本应用不执行；MCP 与 `allowed-tools` 声明原样保留，不会安装外部工具或扩权。环境限制在详情及活跃上下文中展示。`policy.allow_implicit_invocation: false` 的技能不进入默认推荐目录，仅供明确指定使用；可通过 `skill_list` 查询。纯启停操作保留包字节不变，本地修改保留原元数据、脚本和来源并标记已修改。

内容和启用状态的更新产生新版本；完全相同的提交不增加版本。写操作用 `expected_version` 检查并发，冲突返回 HTTP 409。Agent 使用任务 ID + SDK tool call ID 幂等；页面保存使用稳定 `Idempotency-Key`。加载、卸载使用独立调用 ID，因此可以加载、卸载、再次加载。

## 运行时

目录在请求预算中低于用户上下文和活跃 Skill 正文，不能挤掉原本能保留的用户约束。空间不够时减少目录项，完整目录通过 `skill_list` 查询。未知模型的 8,000 字符预算仅用于历史选择，不能误当成已知模型容量；已知容量不足仍返回明确错误。

首轮提供最多约 3,500 字符的目录；全部目录通过分页工具查询，Agent 每次最多返回 10 个摘要；资源目录每次 8 项，可用 nextResourceOffset 继续读取。显式指定优先，自动匹配由现有 Agent 处理，普通问候不带目录、不加载业务 Skill。创建请求必须获得真实 `skill_create` 成功回执：提前返回文本会继续同一主 Agent、同一会话，字段失败则按错误修正；调用次数及预算耗尽时明确报未创建成功，不误报完成。缺少必要信息时仍可发起澄清。纯管理请求不会因为正文提到“品牌全案”“生成图片”而触发设计交付或研究。

加载通过服务端事务绑定真实任务。下一次模型调用加入独立 Skill 上下文块，活跃正文完整保留；模型容量不足会明确报错，绑定保留。资源按需读取，每次文本最多 6,000 字符。图片使用原生视觉输入；PDF、DOCX、PPTX 使用已有本地解析器读取正文；其他支持上传但无法提取正文的二进制资源可下载，并明确告知未读取内容。扫描 PDF 不自动进行 OCR。

目录、Skill 方法与项目事实分开。Skill 不能更改核心规则、用户要求、网络许可或预算，声明依赖只能启用已注册的 SDK 工具。研究和审查可发现、读取、加载、卸载；写入共享库仅限主 Agent，自动修复阶段禁止修改共享库。

请求投影在 SDK 的 Model 适配层应用，原始 Session 和审计记录不被改写。成功的 Skill 写操作只向模型呈现摘要，失败参数和错误保留供 Agent 修正；卸载后去掉主动注入与相关旧读取正文，保留真实产物和历史。检查点记录绑定版本、内容哈希和资源引用，恢复从本工作区重建原版本，即使目录已更新、停用或删除。

## API

| 路径 | 方法与用途 |
| --- | --- |
| `/api/skills` | GET 分页搜索；POST 创建 |
| `/api/skills/tools` | GET 已注册的 SDK 工具名称 |
| `/api/skills/github/inspect` | POST 识别 GitHub 仓库中的 Skill 目录 |
| `/api/skills/github/install` | POST 下载并安装选定目录，支持 Idempotency-Key |
| `/api/skills/{id}/export` | GET 导出标准 Skill ZIP（可传 version） |
| `/api/skills/{id}` | GET 详情（可传 version）；PATCH 更新；DELETE 软删除 |
| `/api/skills/{id}/versions` | GET 历史版本 |
| `/api/skills/{id}/versions/{version}/resources/{path}` | GET 被动资源下载 |
| `/api/projects/{project}/agent-tools/skill_*` | 七个任务级工具，沿用现有网关 |

下载使用 attachment、nosniff 与限制性 CSP，HTML/SVG 模板不能借本机 API 源执行代码。首版不包含插件市场、动态代码执行或独立 Skill Agent。

## 验证

```sh
services/api/.venv/bin/python -m pytest services/api/tests -q
npm test
npm run typecheck
npm run build
npm run build:web
npm run test:skills
npm run test:skill-mentions
```

`test_skill_sdk.py` 使用真实已安装 SDK、独立临时工作区和拦截传输验证 Responses / Chat Completions，涵盖草稿后继续创建、校验失败修正、无回执禁止成功、跨项目创建使用、卸载重载、更新删除后的中断恢复和产物不重做。不会调用真实付费模型。`test_skill_packages.py` 使用模拟 GitHub 传输验证 Codex 原文件往返、下载边界及 API。`test:skills` 使用构建后的页面、隔离模拟 API 和 Electron Chromium 验证管理页；运行前需完成桌面与浏览器构建。本机端口为 5295 / 5296，截图写入 `/tmp/aics-skills-*.png`。

`test:skill-mentions` 验证首页/项目输入框、浏览器/桌面路由、中文输入法、键盘/鼠标选择、分页、过期搜索响应、依赖缺失、读取失败重试、草稿恢复、移除标签和发送失败保留输入。只向隔离 API 提交模拟任务，不调用模型；截图在 `/tmp/aics-skill-mentions-*.png`。
