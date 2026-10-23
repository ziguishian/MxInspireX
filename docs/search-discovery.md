# SEO 与 GEO

本地应用和公开产品资料分别处理：工作区 HTML 默认 `noindex,nofollow`，不将私人项目、资料库、设置、用量放进站点地图。这不是访问控制，公开部署 API 仍需独立鉴权。

GitHub 的 README、产品事实页和使用指南提供可抓取正文、下载入口、明确能力边界与 FAQ。`llms.txt` 仅作为可选资料索引，不宣称是搜索引擎标准，也不保证 AI 引用。

`npm run build:site` 生成 `dist/site` 的独立静态产品页，不依赖 Vue 执行或本地 API。包含 title、description、Open Graph、SoftwareApplication JSON-LD、FAQ 和公开文档链接。不添加虚构评分、价格或认证。

目前没有官网域名，因此默认不输出 canonical/sitemap，预览标记 noindex。正式域名就绪后，例如在 PowerShell：

```powershell
$env:PUBLIC_SITE_URL = 'https://your-domain.example/'
npm run build:site
```

将 `dist/site` 部署到对应 HTTPS 目录，生成 canonical、robots.txt 和仅含公开介绍页的 sitemap.xml。项目路径部署可设置 `https://your-domain.example/MxInspireX/`。不要部署工作区数据，也不要把 `dist/web` 当作此静态介绍页。GitHub Pages 可承载该目录，但本次不自动启用 Pages 或虚构官网地址。

上线后用 Search Console 验证站点所有权、提交 sitemap，并检查真实 HTTP 状态和可抓取内容。Google 的 AI 搜索沿用基础 SEO 原则，没有额外的专用标记要求：[官方说明](https://developers.google.com/search/docs/appearance/ai-features)。
