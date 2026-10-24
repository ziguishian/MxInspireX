# 桌面界面与生成素材（2026-10-23）

本次按用户要求新增原生文件、编辑、视图、帮助菜单；Token 与确认扣费位于桌面顶部中央。主题切换移至左下角，更新按钮仅发现版本时显示，画布页隐藏两者。任务入口位于右上角，只展示运行中任务。

外观设置新增方格、点状、空白及本地 PNG/JPEG/WebP 背景，保存于本机浏览器配置。2026-10-24 修订：上传按钮显式同步打开文件选择器，支持鼠标及 Enter/空格；图片上限调整为 20 MB，在本机缩放至最长边不超过 2560px，并压缩到适合本地存储的大小。按钮旁显示处理、保存与错误状态；失败保留原背景。背景不参与模型引用。大图预览避让 34px 桌面标题栏。首页拖拽反馈限定在输入区。

## 风格图

使用内置 image_gen 逐张生成，文件在 `apps/renderer/public/assets/style-references/`，展示比例 16:9。这些是原创示例，不是历史作品复制。新增瑞士平面、包豪斯、装饰艺术，保留旧风格键兼容。

风格资料参考：[MoMA 包豪斯](https://www.moma.org/explore/inside_out/2009/11/06/bauhaus-the-graphic-design-department-goes-back-to-school/)、[V&A 装饰艺术](https://www.vam.ac.uk/collections/art-deco)。

生成提示词主题：
- oriental: Contemporary Chinese design: a sculptural dark walnut tea tray, porcelain cup and graphic tea packaging, misty ink-wash mountain silhouette, ivory negative space, restrained cinnabar seal, refined editorial product photograph.
- song: Song dynasty inspired literati design: celadon ceramic tea vessels, thin bamboo twig, rice paper, pale blue-green glaze, distant soft ink landscape, quiet asymmetric composition, refined exhibition campaign.
- craft: Warm artisanal sustainable design: handmade paper packaging, natural linen, woven bamboo, terracotta vessels, tactile blind embossing, earthy pigments and sunlight, sophisticated craft brand still life.
- future: Futuristic museum exhibition design: translucent glass plinths and brushed aluminum sculptural objects, cool silver and ice blue, precise architectural lighting, restrained spatial typography, premium experimental exhibition.
- illustration: Contemporary playful flat editorial illustration: a colorful botanical garden cafe with tiny people, bold coral mustard cobalt and cream shapes, confident hand drawn contours, sophisticated magazine illustration.
- swiss: Swiss international typographic design poster, landscape composition: large black sans serif typography reading FORM / SPACE, disciplined asymmetric grid, red circle, offset monochrome architectural photography, white space, flat print design.
- bauhaus: Bauhaus graphic design: circles triangles rectangles in primary red yellow blue and black on warm ivory, rational asymmetric arrangement, subtle paper grain, functional typography reading FORM 1923, sophisticated geometric exhibition poster.
- deco: Art Deco luxury perfume packaging campaign: symmetrical stepped geometric gold linework, black and emerald, sunburst motif, elegant tall fluted glass bottle, refined 1920s decorative geometry, premium studio photograph.

## Logo 第二轮候选

第一轮未获用户认可。第二轮为 `docs/design/logo-candidates/v2-A.png` 至 `v2-D.png`，等待用户选择，未自动替换当前图标。

- A: A single bold vermilion organic ink seal: one continuous thick irregular square loop with a deliberate elegant opening and a compact ivory off-center negative space. Combines a modern Chinese seal and an infinite creative canvas. No characters. Flat vermilion on warm ivory.
- B: A radically simple electric cobalt glyph: two bold offset solid semicircles interlock into a compact asymmetric sculptural symbol, with a clean diagonal white negative-space channel. Flat cobalt on white. Strong editorial design studio identity. No letterforms.
- C: A warm orange architectural gateway: a single solid rounded arch with an unusual stepped interior opening, suggesting an entrance into imagined worlds. Flat warm orange on deep charcoal. Iconic bold silhouette. No cubes or outlines.
- D: A black and ivory abstract sprout of imagination: three broad rounded wedge petals attached to a short sturdy diagonal stem, forming a compact dynamic asymmetric mark. Flat ivory mark on near-black. More geometric than botanical, distinct designer tool identity.

所有 Logo 共用约束：正方形、单一居中符号、24px 识别、双色平面、无文字/机器人/轨道/折纸/阴影/3D；由内置 image_gen 生成。

## 验证

- `npm run typecheck`
- `npm run build` 与 `npm run build:web`
- `npx vitest run apps/renderer/src/features/canvasBackground.test.ts apps/desktop/src/windowAppearance.test.ts`：11 项
- `npm run test:style-picker`：桌面、网页、窄屏、失败重试、选择保留
- `node node_modules/electron/cli.js scripts/test-window-chrome.cjs`：三种配色、菜单导航、背景持久化
- `node node_modules/electron/cli.js scripts/test-desktop-image-preview.cjs`（需开发服务 5173）：真实预览关闭按钮 top=49.67px，高于原生标题栏底部 34px，关闭成功。

# 品牌加载动画

`BrandLoading.vue` 复用透明 Logo 蒙版，容器为 128px，初始仅显示细灰色空心轮廓，双层白色水波由下向上填满，约 4 秒循环。用于应用挂载前以及参考库、资料和资产首次读取；真实加载结束立即卸载，不增加最短等待时间或虚构百分比。减少动画时显示静态半满状态，后台暂停由 `useMotionPolicy` 管理。开发服务器运行时使用 `node node_modules/electron/cli.js scripts/test-brand-loading.cjs` 验证动画、蒙版、尺寸、白色填充、减少动画和卸载。
