# 风格参考雪碧图

生成方式：内置 image_gen（不是 CLI）。用于 StylePicker 的六种视觉参考。

文件：`apps/renderer/public/assets/style-presets-v1.png`，1536 × 1024，3 列 × 2 行；每格 512 × 512。使用真实 `<img>`，尺寸为容器的 300% × 200%，按行列定位并裁切显示，不切割原图。图片地址相对 `document.baseURI` 解析，兼容网页和桌面 `file://`；不要将相对图片 URL 放进 CSS 变量，否则打包后的样式表可能解析到 `assets/assets/`。

最终提示词：

```text
Use case: stylized-concept
Asset type: one production sprite sheet for a design app's visual style picker.
Primary request: a refined, inviting six-tile art-direction sampler. Exactly 3 columns by 2 rows, each tile square, equal sized, edge-to-edge, no gutters, no frames. Overall landscape 3:2 composition. Every tile is a fully finished independent image filling its cell. The app will crop the cells with CSS.
Subject repeated in all six tiles: a sculptural little bird-shaped teapot, one teacup, a folded gift box and a curved branch, shown as a compact still-life. Consistent central composition helps compare the art directions.
Row 1 left: balanced contemporary product design, soft cream and sage, gentle studio daylight, crisp simple forms (automatic style reference).
Row 1 center: modern East Asian design, charcoal ink arcs, warm ivory porcelain, restrained red accent and generous negative space.
Row 1 right: Song dynasty-inspired poetic still-life, pale celadon ceramic, misty landscape and delicate ink brushwork, subtle paper texture, tranquil.
Row 2 left: local artisan craft, warm terracotta and natural woven rattan, tactile handmade textures, sunlit ochre backdrop.
Row 2 center: future museum display, sculptural chrome and translucent blue materials, luminous cobalt glass, precise architectural lighting.
Row 2 right: youthful editorial illustration, playful clean shapes, flat coral teal and butter yellow, expressive bird silhouette, light grain, cheerful.
Constraints: no text, letters, numbers, logos, watermarks or UI. Strictly six square tiles in exact 3x2 geometry. Keep every subject fully inside its own tile. Elegant, professional and visually distinct styles.
```
