# 本地视觉参考库

## 使用

- 侧栏「参考库」打开 `/references`；旧 `/knowledge` 自动跳转。旧文本位于「历史资料」(`/references/legacy`)。
- 批量上传、拖入、粘贴 JPEG、PNG、WebP，或导入公开作品链接。图片立即入库，分类与视觉描述后台补齐；无法分析时仍可手动编辑和单项重试。
- 行业默认优先显示「文旅」「船舶」，两者为内置分类；原「文旅景区」统一为「文旅」，已有素材分类自动衔接。行业和设计类型分别筛选，可多选标注与自定义分类。资产库图片可「收藏到参考库」。
- 参考图按原始比例完整显示在瀑布流中；列表接近底部时继续读取下一批，不显示分页控件。
- 新的视觉设计先展示参考卡。卡片按设计案例、产品/摄影或材质/工艺标示候选依据；可分别选择借鉴造型语言、材质工艺、色彩关系、构图/信息层级、光影摄影或排版字体。选择表示从该维度学习，不是复制单张图。
- 参考库还显示工作区设计经验：仅收录用户确认执行的审查修订策略，不含客户事实、资产、原始提示词或未确认的模型判断。可在该页查看和删除；新计划最多使用三条作为候选策略，不覆盖用户要求或真实参考。
- 「换一批」排除已展示参考；「上传自己的参考」加入当前卡；「跳过参考」明确解除前置条件。已提供图片的任务直接采用，延续修改沿用原方向。

## 数据与恢复

图片保存在当前工作区 `references/originals`，缩略图在 `references/thumbnails`，SQLite 表位于工作区 `catalog.sqlite`。参考库与项目目录独立；采用时复制为项目资产。删除共享条目不会破坏项目图片，删除项目不影响共享参考。

`visual_references` 保存 SHA-256、尺寸、来源、作者、授权描述、分类、标签、用户改动字段和分析状态。字节级去重；联网采集另对 Behance 与 Imgix 的同源尺寸版本去重。同一作品的不同画面通过 `sourceGroup` 关联。网络临时候选使用 `saved=0`，采用/收藏后转为正式条目。

`reference_selections` 保存项目、源任务、候选批次、选择及继续任务 ID。后端验证候选归属；同一选择重复提交返回同一继续任务。项目副本映射持久化，选择后的实际资产 ID 和借鉴要点存入设计状态。Agent 实际看图反推并结合本项需求填写 `reference_analysis`；借鉴图转为文字语义，保真或编辑用途才发送原图，参见 `conversation-memory.md`。浏览器保存未提交的选图草稿，刷新后恢复。

分析队列使用持久状态：`pending → running → ready/failed`。重启恢复 pending；被中断的 running 标为 interrupted，需要用户重试，避免自动重复不确定的模型费用。人工修改字段不被分析覆盖。

## 搜索和 Agent

- 搜索采用行业/类型过滤、标题/标签/视觉描述召回，中文使用词组与二元片段匹配。
- 配置了真实 Embedding 时可增强召回；不使用哈希索引冒充语义搜索。
- 最多 12 个候选通过已配置的视觉模型查看并挑选最多 6 张；模型不可用时显示标签匹配结果，明确可放大检查。
- `reference_search`、`reference_inspect` 可供设计/研究角色使用；只有主设计角色调用 `request_reference_selection`。
- 默认任务在 SDK 执行前进入选择卡；生成工具和批量生成预检另有后端校验。等待参考时不进入交付补全/修复/验收。
- 本地不足时仅在当前任务 `allowExternalNetwork=true` 下沿用已有 `web_search`。公开页面解析 OG/Twitter/图片标签/JSON-LD，实际下载、格式和尺寸检查后才展示。网络请求有容量、超时、重定向及公开地址约束。
- 图像理解继续使用用户配置的模型，没有新增图像搜索服务、API Key 或本地视觉模型部署。

## API

统一前缀 `/api/references`：

| 接口 | 用途 |
| --- | --- |
| GET / | 搜索、过滤、按偏移量分批读取 |
| POST /upload | 批量 multipart files |
| POST /import-url | 导入 `{url, limit?}` |
| GET/POST /categories | 列出/新建行业或设计类型 |
| POST /from-asset | 收藏 `{projectId, assetId}` |
| GET/PATCH/DELETE /{id} | 详情、编辑、删除 |
| GET /{id}/content、/{id}/thumbnail | 本地原图/缩略图 |
| POST /{id}/analyze、/{id}/save | 重试分析/收藏临时候选 |
| POST /selections/{id}/upload?project_id=… | 为当前候选批次上传图片 |
| GET/POST /lessons、DELETE /lessons/{id} | 查看/手动添加/删除去敏工作区设计经验 |

通过原任务接口提交 `input.referenceSelection = {id, action: confirm|refresh|skip, selected: [{id, aspects}], notes}`，或在对话中输入本轮图片序号。`referenceWorkflow` 等内部状态不能由客户端伪造。

## 旧数据

旧共享知识库图片增量迁入参考库，迁移标记防止重复。旧文本不会自动转换 Skill；保留显式历史引用及项目附件解析，停止默认查询共享文本库。项目原有资产和文件目录保持兼容。

## 首批素材和检查

运行 `services/api/.venv/bin/python scripts/seed-references.py`，默认连接正在运行的本机 API。脚本按 12 个公开作品页、6 个主题采集目标 48 张，保存每项来源、分类和标签；重复内容复用原条目，已修改字段保留。结果写入 `outputs/reference-seed/report.json`，实际数量和失败原因以报告为准。

测试位于 `services/api/tests/test_reference_library.py` 和前端 `features/references.test.ts`，覆盖实际图片字节、存储与复制、候选归属、确认/跳过/换批、重复提交、手动上传、联网模拟、批量前置校验、实际生成适配器的多图输入及旧资料迁移。
