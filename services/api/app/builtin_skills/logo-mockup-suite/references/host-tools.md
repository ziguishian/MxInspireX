# 在不同 Agent 中执行

在 Codex 中使用当前图像生成工具制作或编辑图片，使用文件工具保存所需文案与说明。每项视觉成品保存为独立 PNG/JPEG/WebP。

## 小居 / 朗居工具映射

- 用 `context_read`、`conversation_read`、`canvas_read`、`asset_search` 和 `asset_inspect` 读取本项目的品牌资料、批次进度与真实资产；用 `conversation_memory_read` 提取本聊天相关需求、资料身份与进度，用 `conversation_memory_update` 保存用户设计约束及本轮选择，用 `skill_read` 按路径和 offset 分页读取参考资源。
- 用 `design_plan` 保存本批执行清单与累计交付项，后续批次记入 deferred，具体见[分批交付](batch-workflow.md)。每张图片对应一个 kind=image、representation=raster 的条目，依赖关系写入 dependsOn。
- 用 `generate_image` 制作完整视觉成稿，包含图案、版式及约定文字。以 `source_asset_id` 或 `source_asset_ids` 传入实际母版或待调整样机，设置 `output_mode=create` 在新节点生成，保留所有已有图像。
- 独立项用 `generate_batch` 批量生成；依赖项在母版完成后执行。每个批次条目用 `deliverable_ids` 关联实际交付项；修改已有图片时把原图作为来源并新建结果节点，按回执保留全部旧图、已完成项和处理失败状态。
- 每张成品独立保存到画布，供用户分别查看与下载；按需要用 `canvas_create_text` 保存制作说明、角色设定、点位台账或发布文案。
- 验收时读取实际产物，核对文字、母版一致性及各 Skill 的专业检查项，按真实完成状态报告结果。

- 生成前从已选择的图片记忆建立交付项引用方案，按 `reference_snapshot_id` 和 `source_asset_ids` 使用对应原图。标准色、行业及持续要求按主题保存，单次调整使用 task 范围。每批结束更新真实进度与下一批建议。图像默认 final 档和接口最高有效质量，尺寸按用途及用户要求设置。

- 新视觉设计先用 `reference_search` 搜索参考库，必要时 `reference_inspect` 实际看图，由主 Agent 用 `request_reference_selection` 展示并等待用户选择。已有明确参考或用户已跳过时直接继续；采用真实项目资产 ID 和用户选定的配色、构图等要点，不将参考图计入交付成果。

## 生成后的检查

生成成功后直接交付，由系统基于本轮节点缩略总览执行一次统一审查。不要逐张 `asset_inspect`、例行 `canvas_read` 或启动自动修复复审。仅下一项生成确实依赖本轮新图时，才用 `asset_inspect(purpose=reference)` 分析该参考；已有引用及用户明确的局部检查仍可按需读取。
