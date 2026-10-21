# 首页输入框山云 IP 素材

> 历史素材说明。当前默认形象为 `mxinspirex-robot-states.png` 点阵机器人；设置 → 外观支持提示词生成自定义首页图集，现行流程与切帧规则见 [首页吉祥物定制](home-mascot.md)。以下山云形象、坐标与名称说明只适用于旧资源。

首页 `HomePage.vue` 使用用户提供的山云形象，保留小居点击对白及每日定时提示。素材通过内置 imagegen 生成，透明 PNG 存入项目，不依赖生成工具的缓存路径。

- 成品：`apps/renderer/public/assets/lumo-composer-mountain-cloud-v2.png`，1536 × 1024、RGBA、3 列 × 2 行，每格 512 × 512。
- 从左到右、从上到下：平静、开心、眨眼、俏皮眨单眼、思考、困倦。
- 用户原始形象：`scripts/brand-assets/lumo-mountain-cloud-reference-v1.png`。
- 用户三视图与姿态参考：`scripts/brand-assets/lumo-mountain-cloud-poses-reference-v1.png`。

输入框使用较高图层遮住角色身体；角色可见区域保持可点击，输入框覆盖区域仍用于输入。角色绝对定位，不参与标题与输入框的排版；桌面标题下方保持原有 22 px 间距；不超过 900 px 的窄屏从顶部排版，标题不因角色变化上下移动，下方留出 144 px 供角色与上方气泡显示。角色宽度为上一版的 2/3：桌面 `calc(clamp(144px, 16vw, 184px) * 2 / 3)`、窄屏约 90.67 px。悬停和按下均不改变亮度，点击对白在角色上方显示，箭头朝下。

图片路径由 Vite 处理，支持网页和 Electron 的本地文件入口。Agent 回复、空对话欢迎区与首次请求欢迎卡片通过 `.agent-avatar-sprite` 共用此表情图集，详见 [小居头像](agent-ip-avatar.md)。系统开启减少动态效果时停用自动表情轮播，保留首页点击反馈。

图集原始格子并未严格对齐：第二、三列分别向左偏约 2、4 个源像素，第二排向上偏约 30 个源像素。`style.css` 为首页和所有头像统一定义 `--xiaoju-frame-*` 背景位置及 `xiaoju-sprite-expression` 动画，按上述偏移补偿；顶部裁去 32 个空白源像素，避免下排补偿时漏出上一排身体。各表情保持相同的山顶与身体基线，不修改角色容器的大小或位置。不要在组件里重新使用未经补偿的 `50% / 100%` 切帧坐标，也不因输入框聚焦改变动画时长。

界面、任务进度、成就说明与 Agent 自我介绍统一使用“小居”。历史素材文件名、函数名及每日提示的本地存储键继续保留 `lumo`，避免丢失资源引用或重复提示。SDK 持久化运行状态中的内部 Agent 标识也保持兼容，显示事件与身份提示使用“小居”。

旧机器人素材及旧生成脚本保留为历史资源；`scripts/generate-lumo-sprite.py` 只生成旧版机器人，不会更新此山云素材。

## 最终生成提示词

```text
Use case: identity-preserve.
Asset type: ONE production transparent PNG sprite atlas for a Vue desktop app composer mascot, exactly 3 columns x 2 rows, six equal square cells, landscape 1536 x 1024 canvas. No lines between cells.
Reference image 1: the user's approved mountain-cloud mascot, authoritative character identity and materials.
Reference image 2: the same mascot's three views and poses, use especially the prone pose as pose guidance. Ignore all typography, layout and captions in reference 2.
Primary request: replace the application's old robot with this exact adorable mountain-cloud character. Preserve the white soft cloud head/body, mint jade spiral cloud ears, layered emerald/mint mountain crown with white snow cap, dark glossy jade eyes with white highlights, soft peach blush, jade scarf trailing to viewer right, small round jade pendant tied with vermilion cord. Preserve soft premium 3D toy material and proportions.
In EVERY cell use identical frontal camera, identical character scale, identical mountain crown outline, ear positions, scarf and body silhouette. The mascot is leaning forward / resting behind an imaginary horizontal ledge, with two round white paws resting on the ledge, face above paws, a little upper torso below. Crown top around 8% cell height, face centered around 46%, paws around 73%, upper torso ends around 91%. The app will hide the lowest part behind its input box; do NOT draw a ledge or input box. No legs, no ground shadow, no objects or floating symbols.
Only facial expression changes:
top left (cell 1): calm curious open eyes and small gentle smile.
top middle (cell 2): delighted, bright open eyes, joyful open smiling mouth.
top right (cell 3): blink, both eyes softly closed, gentle smile.
bottom left (cell 4): playful wink, one eye closed, open happy smile.
bottom middle (cell 5): thoughtful, eyes glance gently up to the left, small thoughtful mouth, paws unchanged.
bottom right (cell 6): peacefully sleepy, closed relaxed eyes, small relaxed smile, paws unchanged.
Background: genuinely transparent alpha in every empty pixel and all gutters, no white or colored background, no checkerboard baked into pixels.
Composition: precisely aligned equal square frames, matching pose and registration across all six frames so CSS sprite animation does not jump; a 5% transparent safety margin at every cell edge. Clean edges, high readability when displayed at 130-175px wide.
No text, no labels, no watermarks. Keep only the tiny original scarf brand mark if visible. No redesign, no robot features.
```
