import { createEditorialPortfolio, editorialSlugs } from './editorial-portfolio.mjs';
/** Shared read-only showcase layout and embedded portfolio generation. */
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const notes = '用户提供的概念设计图。图上的尺寸、材料、分件、刀版和工艺参数未经过实物与打样核准，不构成生产、安全测试或认证证明。';
const groupCopy = {
  '实拍起点': '先看用户提供的原始摄影，确认器物外观、色彩和陈列关系。保留产品标识与摄影署名；以下设计图是视觉延展方案。',
  '器型与材质': '按器型、三视图、成型关系、釉面和配件推进。视图与数值用于讨论设计方向，仍需实物测量、模具和工艺核对。',
  '系列与织纹': '由整体陈列进入六款配色与纹样关系。不同饰品保留各自织纹，用葫芦轮廓、金属边框和自然光建立共同语言。',
  '结构与细节': '从三视图进入边框、织物、背板与装配示意，再观察纹理和边缘。背部固定方式与材质不能由正面照片推断为事实。',
  '包装与礼赠': '先看完整礼赠关系，再看盒型、内托、纸品、携带与材料细节。效果图表达方向，刀版、公差、承重与运输保护需经白样核准。',
};

function portfolio(entry, assets) {
  if (editorialSlugs.includes(entry.slug)) return createEditorialPortfolio({ slug: entry.slug, name: entry.name, credit: entry.credit, rows: entry.images.map((image, i) => ({ ...image, assetId: assets[i].id })) });
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(entry.name)}</title><style>
  *{box-sizing:border-box}body{margin:0;background:#f4f0e8;color:#273d35;font-family:"Songti SC",Georgia,serif}header,main,footer{max-width:1320px;margin:auto;padding:55px clamp(24px,5vw,76px)}nav,small,figcaption,footer{font:12px/1.7 system-ui,sans-serif}nav{display:flex;justify-content:space-between;border-bottom:1px solid #bdb9a9;padding-bottom:20px}h1{font-size:clamp(40px,6vw,80px);font-weight:400;line-height:1.2}h2{font-size:34px;font-weight:400}p{max-width:820px;line-height:1.9}section{padding:44px 0;border-top:1px solid #bdb9a9}.grid{display:grid;grid-template-columns:1fr 1fr;gap:34px}figure{margin:0}img{display:block;width:100%;height:auto;background:#e6e1d8}figcaption{padding-top:12px;color:#596358}.label{color:#637568;letter-spacing:.12em}.hero{width:100%;max-height:720px;object-fit:contain;margin-top:40px}.boundary{background:#e5e7db;padding:30px}footer{border-top:1px solid #bdb9a9}@media(max-width:700px){.grid{grid-template-columns:1fr}header,main,footer{padding:30px 22px}nav{display:block}}
  </style></head><body><header><nav><span>LANGJU / DESIGN CASE</span><span>${escapeHtml(entry.subtitle)}</span></nav><h1>${escapeHtml(entry.name)}</h1><p>${escapeHtml(entry.heroIntro || '从实拍观察进入系列设计，以器物、材料和礼赠关系组织观看路径。')}</p><img class="hero" src="asset://${assets[0].id}" alt="${escapeHtml(entry.images[0].title)}"></header><main>${[...new Set(entry.images.map(image => image.group))].map(group => `<section><small class="label">${escapeHtml(group)}</small><h2>${escapeHtml(group)}</h2><p>${escapeHtml((entry.groupDescriptions || groupCopy)[group])}</p><div class="grid">${entry.images.map((image, index) => ({ image, index })).filter(row => row.image.group === group).map(({ image, index }) => `<figure><img loading="lazy" src="asset://${assets[index].id}" alt="${escapeHtml(image.title)}"><figcaption>${String(index + 1).padStart(2, '0')} / ${escapeHtml(image.title)} · ${image.role === 'photo' ? '原始实拍' : image.role === 'source' ? '用户产品资料' : image.role === 'generated' ? '图像模型生成' : '概念设计方案'}</figcaption></figure>`).join('')}</div></section>`).join('')}<section><h2>传播文案提案</h2><p>${escapeHtml(entry.marketing || (entry.key === 'ci' ? '一抹青瓷，把宫苑的好时光带回案头。让器物、礼盒与一份心意彼此呼应。' : '把一段织纹，留在今日身边。让小巧的葫芦轮廓，承接色彩、触感与一份心意。'))}</p></section><section class="boundary"><h2>从视觉方案到实物</h2><p>实拍与概念设计分别标明。尺寸、材质、固定关系、模具、刀版及包装保护均须实物测量和打样核对；本作品集不是生产文件或认证证明。</p></section></main><footer>${escapeHtml(entry.credit)}。原图标识与署名保留；模拟对话用于本地演示。</footer></body></html>`;
}

export function buildBoard(entry, assets) {
  const prefix = `${entry.slug}-v1-`; const nodes = []; let order = 1; let y = 0;
  const text = (id, title, body, role, x, top, width = 420) => ({ id: prefix + id, type: 'creative', position: { x, y: top }, data: { kind: 'text', title, text: body, status: '已生成', showcaseRole: role, showcaseOrder: order++, previewSize: { width, height: 360 }, previewSizingVersion: 2, autoPositioned: false }, meta: { createdBy: entry.createdBy || 'ci-jin-import', sourceVersion: 1 } });
  nodes.push(text('intro', '00｜项目背景与交付规划', `# ${entry.name}\n\n## 项目起点\n${entry.intro || `两张用户提供的实拍与${entry.images.length - 2}张概念设计资料。`}\n\n## 本轮范围\n${[...new Set(entry.images.map(image => image.group))].join(' → ')} → 传播文案 → 作品集。\n\n## 打样边界\n实拍确认可见外观；概念图中的数值与工艺需要实物复核。`, 'intro', 0, y, 560)); y += 480;
  for (const [section, group] of [...new Set(entry.images.map(image => image.group))].entries()) {
    nodes.push(text(`chapter-${section}`, `${String(section + 1).padStart(2, '0')}｜${group}`, `# ${group}\n\n${(entry.groupDescriptions || groupCopy)[group]}`, 'chapter', 0, y, 560)); y += 460;
    const rows = entry.images.map((image, index) => ({ image, asset: assets[index], index })).filter(row => row.image.group === group);
    for (let start = 0; start < rows.length; start += 3) {
      const heights = [];
      for (const [column, row] of rows.slice(start, start + 3).entries()) {
        const { image, asset, index } = row; const width = 560; const height = Math.round(width * image.height / image.width); heights.push(height);
        nodes.push({ id: prefix + image.file.replace(/\.(png|jpg)$/, ''), type: 'creative', position: { x: column * 650, y }, data: { kind: 'image', title: `${String(index + 1).padStart(2, '0')}｜${image.title}`, assetId: asset.id, asset: { ...asset, metadata: { ...asset.metadata, width: image.width, height: image.height } }, imageFit: 'contain', previewSize: { width, height }, previewSizingVersion: 2, autoPositioned: false, status: '已生成', showcaseRole: 'visual', showcaseOrder: order++, productionNotes: image.productionNotes || (image.role === 'photo' ? `用户提供的原始摄影，保留标识与署名。${entry.credit}。` : notes), showcaseProvenance: { sourceFile: image.sourceFile, source: entry.credit, role: image.role, sha256: image.sha256 } }, meta: { createdBy: entry.createdBy || 'ci-jin-import', sourceVersion: 1 } });
      }
      y += Math.max(...heights) + 150;
    }
    y += 160;
  }
  nodes.push(text('marketing', '传播文案与应用方向', `# 传播文案提案\n\n${entry.marketing || (entry.key === 'ci' ? '一抹青瓷，把宫苑的好时光带回案头。\n\n适用于器物介绍、开盒说明和礼赠卡片。容量、香型和燃烧安全以正式资料为准。' : '把一段织纹，留在今日身边。\n\n适用于系列卡片、单件礼盒和套装介绍。佩戴方式、织物成分和文化认证待正式资料核对。')}`, 'marketing', 0, y, 560));
  nodes.push(text('handoff', '交付与实物核对清单', `# 交付与下一步\n\n已整理${entry.images.length}张资料与作品集。\n\n- 核对尺寸、材质和背部/内部结构。\n- 以白样确认包装保护、装配和运输。\n- 核对产品文案、来源与授权范围。\n- 概念设计图不作为生产文件。\n\n${entry.credit}`, 'handoff', 650, y, 560)); y += 520;
  const embedded = Object.fromEntries(entry.images.map((image, index) => [assets[index].id, `data:image/${image.file.endsWith('.jpg') ? 'jpeg' : 'png'};base64,${image.bytes.toString('base64')}`]));
  nodes.push({ id: prefix + 'portfolio', type: 'creative', position: { x: 0, y }, data: { kind: 'html', title: `${entry.name}｜完整作品集`, html: portfolio(entry, assets), htmlAssets: embedded, imageAssetIds: assets.map(asset => asset.id), previewSize: { width: 1100, height: 760 }, previewSizingVersion: 2, autoPositioned: false, status: '已生成', showcaseRole: 'html', showcaseOrder: order++ }, meta: { createdBy: entry.createdBy || 'ci-jin-import', sourceVersion: 1 } });
  return { nodes, edges: [] };
}

export function validateBoard(entry, board) {
  const nodes = board.nodes;
  const expectedCount = entry.images.length + new Set(entry.images.map(image => image.group)).size + 4;
  const portfolios = nodes.filter(n => n.data.kind === 'html');
  if (nodes.length !== expectedCount || portfolios.length !== 1 || nodes.filter(n => n.data.kind === 'image').length !== entry.images.length || nodes.some((n, i) => n.data.showcaseOrder !== i + 1)) throw new Error('图片、章节或作品集缺失，或回放顺序不连续。');
  const imageAssetIds = new Set([...nodes.filter(n => n.data.kind === 'image').map(n => n.data.assetId), ...(portfolios[0].data.portfolioExtraAssetIds || [])]);
  if (portfolios[0].data.imageAssetIds?.length !== imageAssetIds.size || !portfolios[0].data.imageAssetIds.every(id => imageAssetIds.has(id) && portfolios[0].data.htmlAssets?.[id])) throw new Error('作品集未完整包含画布图片。');
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    const a = nodes[i], b = nodes[j], x = a.data.previewSize, z = b.data.previewSize;
    if (!(a.position.x + x.width <= b.position.x || b.position.x + z.width <= a.position.x || a.position.y + x.height <= b.position.y || b.position.y + z.height <= a.position.y)) throw new Error(`节点重叠：${a.id} / ${b.id}`);
  }
}

