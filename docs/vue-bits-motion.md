# Vue Bits 交互动效

2026-10-21：按已确认方案为六个界面位置增加轻量动效，保留中性灰主题、现有排版和红黄绿任务信号灯。

## 接入范围

| 位置 | 效果及实现 |
| --- | --- |
| 首页、项目输入框 | `components/motion/StarBorder.vue`：首页聚焦显示 1px 银白冰蓝流动边线，7 秒循环，无外溢彩色光晕；项目保留原有彩色边线。光效不覆盖输入区或弹层，失焦和后台暂停，减少动画时显示静态边线。 |
| 任务队列和进度 | `AnimatedList.vue`：初次出现及增删重排的轻量过渡。`TaskProgress.vue` 的阶段文案、交付项和结果信号独立更新，不延迟实际任务状态，不逐秒动画计时器。 |
| 首页 | `BlurText.vue` 和 `HomePage.vue`：标题轻微模糊淡入，其余内容移动 6px 淡入。每次应用会话只播放一次，不隐藏输入框或拦截输入。`HomeUsageSummary.vue` 在顶部中央以 11px 小字显示用量，窄屏移到品牌栏下方；刷新后首次读取真实值时用 `CountUp.vue` 递增 800ms，轮询直接更新，未知值保持“—”。 |
| 精选作品 | `DesignExampleCarousel.vue`：鼠标悬停最多 2° 的倾斜，保留上浮毛玻璃文字、键盘访问、轮播和打开项目行为。触屏不倾斜。 |
| 资产、参考库 | `MasonryGrid.vue`：使用真实布局坐标计算位移，筛选与尺寸改变后平滑排列，可视区新卡片轻微淡入。保留原网格、分页与加载逻辑，不请求额外内容。 |
| 用户中心 | `CountUp.vue`：项目数和本月活跃天数在可见时首次递增，420ms 内完成；无障碍文本始终是真实数值。此页 Token 和计费数字保持原始准确显示。 |

## 性能与偏好

- `features/motion/useMotion.ts` 在多个组件间共享一个系统偏好监听器、应用减少动画属性观察器和页面可见性监听器。
- 系统或应用任意一个开启减少动画时，直接展示最终状态，输入框保留静态彩色焦点轮廓。页面隐藏时暂停装饰，页面返回时不重放入场或计数。
- 原生动画按元素替换，切换路由取消；离屏数字立即回到真实值。卡片倾斜通过 rAF 合并指针事件，鼠标离开、禁用动画及卸载时清理。
- 通用交互 140ms、列表/卡片 220ms、首页入场 400ms、普通计数 420ms、首页用量计数 800ms。计数复用 Token/人民币格式器，保留小额费用精度并预留最终文本宽度；读屏始终读取准确值。流光仅输入框聚焦时运行。
- 不启用鼠标跟随光晕，不新增 WebGL 背景，不修改无限画布拖拽缩放，不影响 Agent、任务轮询或模型调用。

## 来源和依赖

参考并按需适配 [Vue Bits](https://github.com/DavidHDev/vue-bits) 的 StarBorder、BlurText、CountUp、TiltedCard、AnimatedList、Masonry。源码位于该仓库 `src/content/Animations/StarBorder/`、`TextAnimations/BlurText/`、`TextAnimations/CountUp/`、`Components/TiltedCard/`、`Components/AnimatedList/`、`Components/Masonry/`。

复用 Vue TransitionGroup、CSS、Web Animations API 和 rAF，未安装 React 或并行引入 motion-v / GSAP。许可证完整保存在 `apps/renderer/public/licenses/vue-bits.txt`，随网页和桌面构建复制。

## 验证入口

- `npm run typecheck`
- `npx vitest run apps/renderer/src/features/motion/useMotion.test.ts apps/renderer/src/components/TaskProgress.test.ts`
- `npm run build:web`
- 浏览器检查：深浅色聚焦、弹层与输入、任务状态切换、作品卡片点击、资料筛选与重排；减少动画与页面卸载应终止所有新增动效。

2026-10-21 验证：类型检查通过；动效生命周期、TaskProgress、任务队列、参考库和首页回放共 36 项测试通过；Web 生产构建通过，含许可证。实际首页/项目输入框、风格弹层、资产筛选及用户中心已检查。当前浏览器工作区没有已导入的精选项目，卡片倾斜/毛玻璃/点击和任务动态更新通过不连接 API 的临时组件页验证；网格筛选与重新排列最终均无元素重叠。
