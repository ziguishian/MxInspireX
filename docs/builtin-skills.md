# 六个内置业务 Skill

源包位于 `services/api/app/builtin_skills/`，每个都是独立的标准 `SKILL.md`、`agents/openai.yaml`、`references/` 和可选 `assets/`。`langju.json` 仅声明本应用的工具映射；包内不携带脚本、私有模型配置或测试客户数据。

| 标识 | 对话示例 | 交付方向 |
|---|---|---|
| logo-mockup-suite | 用我刚生成的 Logo 做一套品牌延展 | 锁定母版、材质样机、应用说明 |
| tourism-ip-design | 给我们的湿地景区做一个原创 IP | 角色设定、视图、动作、文创应用 |
| notebook-print-design | 做一本 A5 线圈笔记本，给我效果图和印刷 SVG | 封面/封底/内页、字体转曲、出血和技术稿 |
| scenic-wayfinding-design | 根据上传底图做景区导览和方向牌 | 固定点位与路线、SVG 版面、台账、场景 |
| xiaohongshu-visual-post | 把这个项目做成三页小红书图文 | 封面、内页、标题正文和标签；不自动发布 |
| exhibition-hall-design | 根据三维视图、文档和参考图做展厅设计 | 墙面台账、整体母版确认、绑定同一母版的逐墙深化 |

## 安装与升级

FastAPI lifespan 调用 `install_bundled_skills`，先按 manifest.json 校验全部源文件与依赖，再利用现有不可变版本和幂等回执写入当前工作区。`bundled_skill_installs` 保存来源标识、已安装 ID 和内容哈希。页面来源列显示“内置”，可以查看、在对话中修改、启停、卸载和导出。

重复启动不增加版本；同名用户技能不被接管。卸载后不会在重启或升级时重装。升级只更新仍与上次内置内容哈希一致的包，保留启用状态；已修改的包保留用户版本。绑定旧版本的任务继续使用旧正文，旧版本不会被覆盖。工作区独立初始化，不跨工作区引用。

修改内置源包后，增加该项 revision，并更新 manifest.json 中对应文件的 SHA-256。内置目录与印刷字体均进入 sidecar 源摘要和文件校验；生产打包无法悄悄使用旧资源。

## SVG 印刷路径

现有 `canvas_create_svg` 增加两个可选参数，普通 SVG 行为保持兼容：

```json
{
  "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"154mm\" height=\"216mm\" viewBox=\"0 0 154 216\"><rect width=\"154\" height=\"216\" fill=\"#F5F1E8\"/><text x=\"25\" y=\"40\" font-family=\"Noto Sans SC\" font-size=\"6\">青屿手记</text></svg>",
  "outline_text": true,
  "print_spec": {"trim_width_mm":148,"trim_height_mm":210,"bleed_mm":3,"safe_margin_mm":5}
}
```

`outline_text` 使用应用内固定的 Noto Sans SC 常规字体与 fontTools，支持中文/拉丁文单行、x/y 基线、字距和首/中/尾对齐。字号与坐标使用无单位 SVG 数值。显式选择别的字体、粗斜体、CSS、tspan、复杂塑形和缺字都会报可操作错误；不静默替换指定字体。不读取任意本机字体路径。字形来自真实字体轮廓，结果无需安装字体。

`print_spec` 检查明确的 mm 物理尺寸、成品加出血、viewBox 比例、矢量与转曲结构，并记录 trimBox、safeBox、待人工确认项。返回 `structure_checked` 和 `pressApproved: false`；它不检测所有图形越界，不代表 CMYK/PDF-X、装订、专色或印厂验收。印刷净稿和技术标注分开保存。ZIP 导出保留 SVG 原件，通用报告 PDF 不作为印刷矢量文件。

字体原文件、官方固定发布版 URL、SHA-256、版权说明与 OFL 许可证位于 `services/api/app/print_fonts/`；由 sidecar 一并离线分发。没有增加 Skill 脚本执行环境。

## 视觉与集成验证

[样例画廊](examples/builtin-skills/index.html)、[逐项记录](examples/builtin-skills/validation.md)、[完整图像提示词](examples/builtin-skills/imagegen-prompts.json)。样例采用虚构“青屿”项目，全部图像由本次 Codex 内置 imagegen 生成；没有自动请求项目中的收费媒体服务。模型效果测试与 SDK 传输测试分开记录。

`scripts/build-skill-design-fixtures.py` 用真实 SVG 工具生成样例，`scripts/render-skill-design-fixtures.cjs` 用隔离 Chromium 渲染源稿；两者只用于开发验证，不是 Skill 自带执行脚本。
