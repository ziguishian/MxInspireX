# 画布设计工具（2026-10-23）

- 图片右键 → 转为矢量 SVG：VTracer 0.6.15 在本地描摹 PNG/JPEG/WebP，保留原节点，新建可预览、放大、下载的 SVG 资产节点。输入最多 4000 万像素，描摹边长最多 2048；适合 Logo、插画和平面图形，照片会被近似为色块。重复转换同一节点同一图片复用已有结果；删除矢量节点后允许重新转换。它是显式本地操作，不开放 Agent 的 SVG 绘制权限。输出只允许 svg/g/path，不嵌入位图或外部链接。
- 图片右键 → 一键抠图：仅使用本地模型目录中的 GPT Image 2.5，创建新图像节点并连接原图，提交 background=transparent、output_format=png，使用已有任务、计费及透明像素验证。不默默替换模型，不自动重复生成。生成式抠图可能改变细节，不能等同像素级无损抠图。
- 新增 → 色板：1–8 个 HEX 颜色，可调色、增删，连接任意生成节点后以最新配色约束传入。按顺序表达主色、辅助色和点缀色。
- 新增 → 视频分镜：1–12 个镜头，编辑画面、运镜、整数秒时长，支持排序和删除。连接一个视频节点后，顺序写入提示词、总时长覆盖视频时长控件（只读），一次提交一条视频；首尾帧仍直接从图像入线读取。空镜头描述、多份分镜、超过 60 秒阻止提交。模型支持的时长仍由原视频适配校验。此版本不逐镜头生成或拼接，不能保证供应商逐帧准确遵循镜头时长。

色板和分镜持久化为 text 节点的 editor 子类型，复用原有保存、冲突检测、撤销与引用版本校验。服务端从结构化字段重建 text，前端每次从实时节点计算引用，断线不会残留内容。

验证：`node scripts/test-design-nodes.cjs`（隔离 API，真实 Vue Flow，付费请求只捕获）；Vitest `designNodes.test.ts` / `canvasReferences.test.ts` / `canvasGeneration.test.ts`；pytest `test_design_nodes.py`。真实模型质量及正式安装包内 VTracer 运行需单独实测，不由模拟测试证明。

依赖说明：[VTracer 官方仓库](https://github.com/visioncortex/vtracer)，MIT 许可；Python 依赖、uv.lock、sidecar 的 collect-all 已同步。原许可保存在 `docs/licenses/VTracer-LICENSE.txt`，随现有打包流程携带。
