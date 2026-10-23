import { mkdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
const repo = pkg.repository.url.replace(/\.git$/, '');
const escape = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
export function publicSiteFiles(siteUrl = '') {
  let canonical = '';
  if (siteUrl) {
    const url = new URL(siteUrl);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || /^(localhost|127\.|\[?::1)/i.test(url.hostname)) throw new Error('PUBLIC_SITE_URL must be a public HTTPS directory URL');
    canonical = url.href.replace(/\/?$/, '/');
  }
  const title = 'MxinspireX — 本地优先 AI 设计 Agent 与无限画布';
  const description = '灵矩绘境的 MxinspireX 将对话、参考资料与无限画布连接起来，支持产品、包装、文创、图像、视频、HTML 与参数化 CAD 设计。自带模型密钥，项目保存在本地。';
  const schema = { '@context': 'https://schema.org', '@type': 'SoftwareApplication', name: 'MxinspireX', description,
    applicationCategory: 'DesignApplication', operatingSystem: 'Windows', softwareVersion: pkg.version,
    author: { '@type': 'Organization', name: '灵矩绘境' }, license: `${repo}/blob/main/LICENSE`,
    downloadUrl: `${repo}/releases`, ...(canonical ? { url: canonical } : {}), sameAs: repo,
    featureList: ['持续项目对话', '无限画布与节点引用', '图像与视频生成', '交互 HTML', '本地参数化 CAD', '用量与计费核对'] };
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title><meta name="description" content="${escape(description)}">
<meta name="robots" content="${canonical ? 'index,follow,max-image-preview:large' : 'noindex,nofollow'}">
${canonical ? `<link rel="canonical" href="${escape(canonical)}"><meta property="og:url" content="${escape(canonical)}">` : ''}
<meta property="og:type" content="website"><meta property="og:locale" content="zh_CN"><meta property="og:site_name" content="MxinspireX">
<meta property="og:title" content="${title}"><meta property="og:description" content="${escape(description)}"><meta name="twitter:card" content="summary">
<script type="application/ld+json">${JSON.stringify(schema).replace(/</g, '\\u003c')}</script>
<style>body{max-width:860px;margin:0 auto;padding:48px 24px;background:#fafafa;color:#242424;font:16px/1.8 system-ui,sans-serif}h1{font-size:32px;line-height:1.3}h2{margin-top:36px;font-size:22px}a{color:#245da8}nav{display:flex;gap:24px;flex-wrap:wrap}footer{margin-top:48px;border-top:1px solid #ddd;padding-top:20px;color:#555}li{margin:8px 0}img{max-width:100%;height:auto;border-radius:12px}</style></head>
<body><header><p>灵矩绘境 · MxinspireX ${escape(pkg.version)}</p><h1>本地优先的 AI 设计 Agent 与无限画布</h1><p>${escape(description)}</p>
<nav aria-label="产品链接"><a href="${repo}/releases">下载安装包</a><a href="${repo}">GitHub 源码</a><a href="${repo}/blob/main/docs/USER_GUIDE.md">使用指南</a><a href="#faq">常见问题</a></nav></header>
<main><section><h2>MxinspireX 是什么？</h2><p>MxinspireX 是面向文旅、文创及产品设计场景的 AI 设计工作区。用户通过对话说明需求，将图片、文档和画布节点作为参考，持续生成和修改设计产物。它不是模型服务商，使用前需要配置自己的模型服务与 API Key。</p></section>
<section><h2>可以完成哪些设计？</h2><ul><li>Logo、海报、产品概念、包装与 IP 形象的视觉探索。</li><li>沿用真实产品主图生成场景，或基于已有图片进行局部修改。</li><li>文字策划、交互 HTML、音频、视频，以及独立服务的 3D 生成。</li><li>本地参数化 CAD 建模与 STEP、STL、GLB 导出。</li><li>在无限画布连接节点，使用上游文字和图像组织后续任务。</li></ul><p>媒体能力取决于已配置服务与模型；生成的概念设计不等于可直接生产的工程文件。</p></section>
<section><h2>如何开始？</h2><ol><li>从 GitHub Releases 下载对应平台的安装包。</li><li>打开设置中的“模型与连接”，填写自己的服务地址与 API Key。</li><li>同步模型目录，描述需求并上传必要参考，在项目画布查看结果。</li></ol><p>当前发布目标为 Windows x64。源码开发环境还需 Node.js 与 uv；其他平台请核对 Release 的实际附件。界面以中文为主。</p></section>
<section id="faq"><h2>常见问题</h2><h3>是否完全离线？</h3><p>不是。项目与文件保存在本机；云模型调用会向所选服务发送完成任务所需的内容。本地优先不表示云生成完全离线。</p><h3>是否包含免费模型额度？</h3><p>不包含账号、Key 或模型额度。当前源码仅限非商业使用，商用须书面授权；历史 MIT 版本保持原许可。模型调用费用由所选服务商决定。软件区分已确认扣费、参考估算与待对账。</p><h3>修改图片会覆盖原作吗？</h3><p>图像调整保留来源并生成新节点。节点连线用于引用上游内容，不表示允许覆盖上游作品。</p><h3>请求失败会自动重新扣费吗？</h3><p>结果未知的请求不会自动重复提交。有已受理任务编号的媒体，可在产物记录中查询和取回原结果；失败不代表服务商未收费。</p><h3>安装包有数字签名吗？</h3><p>请以各版本发布说明为准。当前构建配置未提供发布证书，Windows 可能提示未知发布者。</p></section>
<section><h2>公开资料</h2><p><a href="product-facts.md">产品事实与能力边界</a> · <a href="llms.txt">机器可读资料索引</a> · <a href="${repo}/issues">问题反馈</a> · <a href="${repo}/releases">版本记录</a></p></section></main>
<footer>产品：MxinspireX · 开发方：灵矩绘境。功能和支持平台以对应版本文档为准。</footer></body></html>`;
  return { 'index.html': html, 'robots.txt': canonical ? `User-agent: *\nAllow: /\nSitemap: ${canonical}sitemap.xml\n` : 'User-agent: *\nDisallow: /\n',
    ...(canonical ? { 'sitemap.xml': `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${escape(canonical)}</loc></url></urlset>` } : {}) };
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const output = path.join(root, 'dist/site');
  const files = publicSiteFiles(process.env.PUBLIC_SITE_URL || '');
  mkdirSync(output, { recursive: true });
  // A fresh output directory is supplied by the release workflow; remove a
  // stale sitemap when switching back to a domain-free preview.
  const { rmSync } = await import('node:fs');
  if (!files['sitemap.xml']) rmSync(path.join(output, 'sitemap.xml'), { force: true });
  for (const [name, contents] of Object.entries(files)) writeFileSync(path.join(output, name), contents, 'utf8');
  copyFileSync(path.join(root, 'docs/product-facts.md'), path.join(output, 'product-facts.md'));
  copyFileSync(path.join(root, 'llms.txt'), path.join(output, 'llms.txt'));
  console.log(`Public site: ${output}; indexing ${process.env.PUBLIC_SITE_URL ? 'enabled' : 'disabled (no public domain configured)'}`);
}
