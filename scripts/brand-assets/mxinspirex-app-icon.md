# MxinspireX application icon

Browser tabs use dedicated 64px `mxinspirex-favicon-{dark,light}.png` exports with the same tight bounds as native icons. Page logos and the loading mask keep their original padding.

User-selected artwork supplied on 2026-10-23: black mirrored geometric symbol on white, from codex-clipboard-70001511-2936-427d-a1bd-928def416433.png.

The original artwork is preserved in mxinspirex-app-icon.png. The approved silhouette was edited with imagegen on 2026-10-23 into orange transparent PNG masters: mxinspirex-app-icon-dark.png (bright orange for dark surfaces) and mxinspirex-app-icon-light.png (deeper orange for light surfaces). Both were checked by compositing in Electron against the actual theme backgrounds; negative spaces and corners are transparent.

Prompt: Preserve the exact silhouette, symmetry, rounded corners, proportions, two separate mirrored shapes and central narrow gap. Change black to warm orange (dark: #FF9A3D; light: #D85A12). Remove the white background and internal negative spaces to alpha transparency. No tile, shadow, texture or text. Clean antialiased edges. Centered square image. Actual generated colors may vary from the requested hex values.

Run python scripts/brand-assets/export-app-icon.py to export Windows ICO, macOS ICNS/iconsets and renderer PNG. Native icons fit the visible artwork within 944px of a 1024px canvas (about 92% width), preserving proportions and transparency. Bounds ignore alpha below 128 so invisible generator noise cannot shrink the icon. Renderer PNGs preserve the original margins for the page and loading animation. About, favicon and native window icons follow the resolved theme; the static Windows installer icon uses the light variant. Agent mascots remain independent.
