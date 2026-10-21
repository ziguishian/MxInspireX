# 首页已保存案例与整套方案演示

首页的 `DesignExample.projectSlug` 打开真实本地项目，并由 `showcasePlayback.ts` 以只读视图按 `data.showcaseOrder` 逐项呈现画布。每张图片固定等待 15 秒；文本和 HTML 使用较短延时。回放不创建任务、Session、生成回执或计费记录，也不修改项目画布。离开项目即停止本轮回放。

从“我的项目”或项目直达链接进入已保存案例时，`showcasePlayback.savedMessages` 根据案例 slug 与当前画布的策展节点复用同一套叙事，直接显示完整预览对话，不启动回放或隐藏画布。预览对话排列在真实任务历史之前，不写入项目任务、Session 或模型上下文，正常输入和真实消息仍按普通项目处理。普通项目、空画布及未策展的同名项目不注入预览；切换项目会清除旧回放。 `node scripts/test-showcase-conversations.cjs` 使用隔离 API 与实际构建的网页/桌面界面验证四案入口、真实追加对话、首页回放及刷新恢复，并检查没有创建任务或写回画布。

案例注册表为 `features/home/designExamples.ts`，项目背景、澄清、用户模拟回复、AI 汇总、任务规划、营销文案和交付边界在 `showcaseNarratives.ts`。首页原“山砚”卡片已由“山茗”取代；山砚项目、数据和叙事脚本仍保留在工作区。首页的瓷与锦卡片分别以“瓷 · 德寿宫”和“锦 · 宋锦葫芦”替换宋韵雅集、云锦序；旧项目与叙事保留。策马寻路替换云自无心，保留旧项目；瓷、锦、山茗、策马寻路和马踏平安在相应项目画布导入后显示，避免空卡片。旧德寿宫、宋锦胸针卡片不再重复展示。

四案策展清单位于 `scripts/showcase-curation.json`；`scripts/curate-showcase-projects.mjs --workspace <工作区> --api <运行中的 API>` 为原四案保留选定的 12 张画面、四段章节、工程/制作边界、营销文案、Editorial HTML 作品集和交付说明。脚本只隐藏其管理的未选演示图，不删除原文件，也不移除用户后来加入的图片。运行前应核对 API 的项目 `rootPath` 与目标工作区一致，并备份画布和目录数据库。不要只根据源码推断当前桌面版正在使用哪个工作区。

新素材的 16 张原图映射及来源署名见 `scripts/showcase-assets/manifest.json`：山砚 6 张进入现有交付序列，其他品牌青瓷 3 张只进入宋韵雅集的视觉研究区，德寿宫 2 张、马踏平安 3 张、宋锦胸针 2 张分别建立新案。原图不作为成品导入；逐张局部去水印、核对器形/产品文字/材质后，将成品放入 `scripts/showcase-assets/clean/`。`scripts/import-showcase-additions.mjs --check` 会先检查全部 16 张；缺失时不写入任何工作区。正式导入通过现有项目、资产、画布 API 幂等执行，并将来源署名写入资产和节点元数据。导入前还会核对 API 的项目根目录、四案策展节点和上传接口的来源字段，避免把素材写入旧版 API 或错误工作区。新三案只有在画布写入成功后才显示首页卡片。图中其他品牌及奖项标识不转移成宋韵雅集的品牌或获奖声明。

新三案的工程 HTML 使用代码绘制结构关系，不伪造照片中未见的三视图、刀版、产品尺寸或制造参数；最终作品集各有独立的 Editorial 排版。实际可生产文件必须待实物测量、白样和工艺确认。

山茗是另一个独立资料包，见 `scripts/showcase-assets/shan-ming-v1/manifest.json`。七张山茗视觉资料按“产品全景→礼盒与包装系统→茶盒与纸杯→展开结构”编排，并带有营销文案和 HTML 作品集。用户提供的“雲天晴”海报和“ROCK GRIND／山砚”包装图只在参考区显示，不参与山茗首页回放与作品集。原图中的尺寸及刀版标注未经过打样验证，画布和网页明确说明不能直接投产。`scripts/import-shan-ming-showcase.mjs --check` 核对资料包，正式导入前核对 API 当前工作区；重复执行会复用同 SHA 资产与既有节点。运行中的打包桌面版不会自动加载源码界面改动，需构建并重新启动。

旧的 `designDemoCases.ts` / `designDemoPlayback.ts` 是另一套显式 `demoId` 路径，仍保留兼容；本页已保存案例不走那条路径。验证至少运行首页相关 Vitest、`npm run typecheck`、`npm run build:web`，并在当前工作区检查项目卡片、逐张占位、暂停/离开、画布节点顺序、HTML 和来源记录。`scripts/showcase-import.test.mjs` 默认检查素材预检；设置 `AICS_SHOWCASE_IMPORT_INTEGRATION=1` 后使用临时本地模拟 API 检查导入幂等、错工作区和旧 API 拦截，不会触碰真实工作区。

## 瓷与锦资料包

`scripts/showcase-assets/ci-jin-v1/manifest.json` 保存用户提供的 30 张原图副本及 SHA-256、原始文件路径、章节和实拍/概念属性：瓷有 2 张德寿宫实拍与 14 张设计图；锦有 2 张宋锦饰品实拍与 12 张设计图。原图标识和摄影署名保留。锦的首页封面使用实拍副本；瓷使用用户确认的青瓷葫芦与书法“瓷”、竖排“德寿宫”封面 `ci-cover-calligraphy.png`，仅用于首页，来源和 SHA-256 记录在 `coverProvenance`。案例内的实拍与设计图保持原样。

`node scripts/import-ci-jin-showcases.mjs --check` 核对素材、回放顺序与布局；导入使用 `--workspace <演示工作区> --api <运行中的 API>`，须与山茗项目根目录一致。新建 `showcase-ci` / `showcase-jin`，不覆盖旧案例；重复导入跳过完整案例，目标画布有其他内容时停止。所有图片用真实资产引用，原图与概念图分别记录来源。三列画布按实际纵横比与每行最大高度排布，附章节、传播文案、实物核对清单和内嵌原图的 HTML 作品集。对话在前端只读模拟，不创建模型调用或计费记录。

图纸数字、模具、刀版和装配关系均属于概念资料，不能冒充经过打样的生产参数；锦统一称葫芦饰品，不从正面摄影断言背针或佩戴方式。更新源码后还需构建并同步到演示应用的 `dist/renderer`，重启核对首页及两个入口。

## 策马寻路青瓷挂件

`showcase-ce-ma` 替换首页云自无心入口。`scripts/showcase-assets/ce-ma-v1/manifest.json` 记录两张产品资料、六张用户提供的系列视觉，以及内置 imagegen 生成的包装展示、刀版模拟、制作文件模拟和封面四张图。原始资料与生成图分开记录来源和 SHA-256。四个章节为产品资料、六款系列视觉、包装与制作模拟、首页封面，共 12 张图、20 个画布节点。

`node scripts/import-ce-ma-showcase.mjs --check` 校验资料、来源、连续顺序与布局；正式导入指定 `--workspace <演示工作区> --api <运行中的 API>`，核对瓷项目根目录后才写入。完整案例再次导入时跳过，已有其他内容或来源哈希不一致时停止。画布与内嵌图片作品集共用 `scripts/showcase-board.mjs`，原瓷/锦导入器保留兼容导出。

生成提示说明位于同资料包的 `generation-prompts.txt`。模拟图表达抽屉盒、内托、随盒卡、刀线/折线/粘口、印刷面和分层关系；它们不包含实际可编辑图层或可投产刀模，尺寸、公差、套合与材料仍需实物打样。来源中的平安、香片等描述不作为已核实效果。独立封面为暖白背景、马形挂件和策马寻路题字；不改变项目内原图。

## 四案 Editorial 作品集（第二版）

瓷、山茗、策马寻路和锦的最终 HTML 统一由 `scripts/editorial-portfolio.mjs` 生成，各有独立的配色、字形与图像叙事。页面采用大图开场、疏密变化、品牌字形/色彩、非等分图像组合与简洁收束；制作图及来源记录收进可展开附录，全部项目图片仍可查看。图片按钮支持大图弹窗、键盘关闭及减少动态效果。没有远程字体、脚本、图片或 SVG。

补充的瓷、山茗氛围概念图及生成提示说明位于 `scripts/showcase-assets/editorial-v2/`。图片作为所属项目真实资产保存，`portfolioSources` 记录来源；`portfolioExtraAssetIds` 明确作品集独有补充资产，不需要增加或重新排列画布节点。原摄影、设计图、首页封面、模拟对话和其他节点保持原样。

`node scripts/refresh-editorial-portfolios.mjs --preview --workspace <演示工作区>` 先从已保存画布生成四份可独立打开的 HTML（默认 `.tmp/editorial-portfolios/`），不写入工作区。正式更新使用同命令去掉 `--preview` 并指定 `--api <运行中的 API>`；先校验全部四案的根目录、原始 SHA-256 和最终节点唯一性，备份旧节点，再使用 `expectedNodes` 乐观校验只更新最终 HTML。保存后验证其他节点和连线没有变化。重复更新复用补充资产。

`node scripts/test-editorial-portfolios.cjs` 用隔离 Chromium 检查 1440/390 px 下全部图片、无横向溢出、附录与大图交互，并生成各案开场、字形、系统及手机截图；使用上一步独立 HTML，不连接真实 Provider。只修改数据与策展脚本无需重新打包 sidecar；运行中的界面需重新进入项目读取更新内容。

## 四案紧凑画布与详细说明（第三版）

`showcase-canvas-notes.mjs` 管理四案共 28 个文本节点的具体说明，包括观察依据、设计判断、系列关系、制作分工、传播应用及打样步骤。`compact-showcase-layout.mjs` 保持既有节点 ID、资产、回放顺序和最终 HTML，采用开场四列、章节文字侧栏与三列图片错位填充、收尾说明与 HTML 并排布局；山茗异品牌资料仍在独立参考区。

更新流程先运行 `node scripts/refresh-showcase-canvases.mjs --prepare --workspace <演示工作区>`，再运行 `node scripts/test-showcase-canvas-layout.cjs`，使用生产 `CanvasMarkdown` 组件测量文字真实高度。`--preview` 生成紧凑预览数据；`node scripts/test-showcase-canvas-layout.cjs --layout` 检查实际渲染边界、图片和安全间距，并输出四案总览。

正式写回去掉 `--prepare` / `--preview` 并指定 `--api <运行中的 API>`。脚本先校验四个演示项目与目标工作区，备份所有画布，用 `expectedNodes` 同时校验旧位置和旧数据，再增量更新。更新后核对资产、HTML、来源、回放顺序及连线没有改变。输出与备份位于 `.tmp/showcase-canvas-refresh/`。文字保持 15 px，图片按真实纵横比完整展示；间距根据测量值计算，不通过缩小字体或固定文本高度压住溢出内容。
