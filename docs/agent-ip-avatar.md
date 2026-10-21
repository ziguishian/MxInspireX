# 小居 Agent 动态头像

首页输入框、对话栏标题、Agent 回复、空对话欢迎区和首次请求欢迎卡片统一使用用户确认的山云“小居”。所有头像使用 `apps/renderer/public/assets/lumo-composer-mountain-cloud-v2.png` 的六种表情，素材来源与提示词见 [输入框山云素材](lumo-composer-assets.md)。

- 对话栏标题头像为 24 px，回复头像为 44 px，欢迎区与首次请求卡片为 88 px，共用 `style.css` 中的 `.agent-avatar-sprite`。
- CSS 通过 `background-size: 300% 200%` 定位六个表情，与首页共用经过位置补偿的 `--xiaoju-frame-*` 和 12 秒轮播，透明边缘搭配淡绿色底座。头像入场不使用位移、旋转或缩放，切换表情时容器和角色基线保持固定。
- 系统开启“减少动态效果”时停止表情轮播，显示同一张图集的开心表情。
- 显示名称、任务进度、窗口标题、帮助说明、成就与 Agent 身份提示统一为“小居”。对话栏标题也使用小居头像，产品品牌 Logo 继续用于导航。
- 历史素材文件名和内部存储键保留兼容；下方旧机器人资源与脚本仅用于追溯，不参与当前渲染。

## 旧机器人循环头像（历史 v3）

- 动态素材：`apps/renderer/public/assets/lumo-avatar-loop-v3.png`，APNG 格式，192 × 192，48 帧，每帧 65 ms，3.12 秒无限循环，约 2.04 MiB。
- 静态素材：`apps/renderer/public/assets/lumo-avatar-loop-v3-still.png`，用于系统开启“减少动态效果”时显示。
- 原始动作帧：`docs/assets/lumo-avatar-loop-v3-source.png`，内置 imagegen 生成的 4 列 × 3 行动作序列，共 12 张关键帧，1448 × 1086。
- 合成脚本：`scripts/build-lumo-avatar.cjs`。执行 `node scripts/build-lumo-avatar.cjs` 可重建动态图、静态图和检查用帧图；依赖项目已有的 Electron，无新增 npm 依赖。
- 制作方式：内置 imagegen 负责绘制连续关键帧；本地 Canvas 完成色键背景提取、角色位置对齐与帧合成，Node 编码为 APNG。未使用 imagegen CLI/API 回退。
- 动作：保持完整双手，轻微摆头、抬手挥动、笑眼眨眼；12 张关键帧之间补入短过渡，循环播放，不依赖悬停触发。
- 透明度：v3 输出是真正含 alpha 的 PNG，双手、围巾与帽尖直接显示在圆形底座外，无需 v2 的 SVG 遮罩。APNG 使用整帧替换，避免透明区域残留上一帧手臂。
- 使用位置：Agent 回复（44 px）、空对话欢迎区（88 px）、首次请求欢迎卡片（88 px），共用 `.agent-avatar-sprite`。标题仍使用品牌 Logo。
- 减少动态效果：媒体查询直接改为静态 PNG，同时关闭 CSS 入场动画；仅取消 CSS animation 无法停止 APNG，因此必须替换素材。
- v2 素材保留作为形象参考，与 v3 均不再用于当前界面。

### 旧版生成提示词

```text
Use case: identity-preserve.
Asset type: ONE production animation sprite sheet, 4 columns by 3 rows, twelve equally sized square frame cells, overall 4:3 aspect ratio (ideally 2048 x 1536). These are consecutive KEYFRAMES of the SAME character for a looping small chat avatar, not twelve different characters or designs.
Input image 1 is the exact identity and rendering reference. Preserve this old robot mascot exactly: white asymmetric hood with orange lining, glossy charcoal faceplate, two warm-white happy curved eyes and no mouth, orange scarf, white shirt with the same small orange chest insignia, dark backpack straps, two black mitten hands.
Every frame contains the COMPLETE SAME half-body bust, BOTH hands fully visible, one raised by the right side of the face in a friendly wave and the other reaching out lower on the left, no legs. Front view, same camera and 3D lighting, same materials and scale. The top of the hood, base of the shirt, face center and chest insignia should remain very consistently registered inside each tile. Character fills approximately 82 percent of every tile with generous safe padding on all sides. Never crop scarf or hands.
Animation: a very subtle, smooth, cheerful idle loop. Make SMALL changes only, a gentle hand wave and head sway within 4 degrees; torso basically stays still. Row-major order, left to right then next row:
1 relaxed base pose, happy eyes.
2 head and raised mitten move a little left.
3 head leans slightly left, mitten at left extreme.
4 head begins returning, mitten follows.
5 near center, eyes narrow slightly.
6 center, short closed curved eyes for blink.
7 center, eyes reopen into happy curves.
8 head and mitten move slightly right.
9 head at right extreme, mitten small outward wave.
10 head returns toward center.
11 almost base pose.
12 base pose close enough to frame 1 to loop seamlessly.
IMPORTANT technical background: replace the reference's checkerboard with ONE perfectly flat solid chroma-key GREEN #00FF00 across the entire sheet, including all padding and the gaps between arms/torso. This is a technical extraction background; absolutely no green reflected light on the character, no background shadows, no gradients, no checkerboard, no texture. No grid strokes, borders, labels, frame numbers, words or extra objects. Cell boundaries are implied only by the regular evenly spaced 4-by-3 placement. Render exactly twelve frames on one sheet. Character identity and facial proportions must stay consistent across all frames.
```

### 旧版验证

- 在真实 GeneralCanvas / Chromium 中检查深浅色对话、欢迎区域与透明边缘。
- 无悬停状态下连续采样超过一个循环，六次头像截图均不同，确认持续播放。
- 模拟 `prefers-reduced-motion: reduce` 后改用静态 PNG，两次间隔截图相同。
- 通过 `npm run build`，动态图和静态图已进入桌面构建目录。
