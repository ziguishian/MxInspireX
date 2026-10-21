#!/usr/bin/env node
/** Import only reviewed, watermark-clean showcase images. Never reads source photos. */
import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, realpath, stat } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptRoot = dirname(fileURLToPath(import.meta.url));
const assetRoot = resolve(optionFromArgs('--assets-root', join(scriptRoot, 'showcase-assets')));
function optionFromArgs(name, fallback = '') {
  const at = process.argv.indexOf(name);
  return at < 0 ? fallback : process.argv[at + 1] || fallback;
}
const manifest = JSON.parse(await readFile(join(assetRoot, 'manifest.json'), 'utf8'));
const args = process.argv.slice(2);
const option = (name, fallback = '') => { const at = args.indexOf(name); return at < 0 ? fallback : args[at + 1] || fallback; };
const apiBase = option('--api', 'http://127.0.0.1:8765').replace(/\/$/, '');
const workspace = option('--workspace');
const coverRoot = resolve(option('--cover-root', join(scriptRoot, '../apps/renderer/public/assets/showcase-products')));
const checkOnly = args.includes('--check');
const expectedCases = new Map([
  ['showcase-shan-yan', ['deliverable', 6]],
  ['showcase-song-yun', ['reference', 3]],
  ['showcase-de-shou-gong', ['deliverable', 2]],
  ['showcase-ma-ti', ['deliverable', 3]],
  ['showcase-song-jin', ['deliverable', 2]],
]);

function validateManifest() {
  if (manifest.version !== 1 || manifest.readyDirectory !== 'clean' || manifest.cases?.length !== expectedCases.size) throw new Error('素材清单版本、目录或案例数量不符合七案导入约定。');
  const seenFiles = new Set();
  const seenCases = new Set();
  for (const entry of manifest.cases) {
    const expected = expectedCases.get(entry.slug);
    if (!expected || seenCases.has(entry.slug) || entry.role !== expected[0] || entry.images?.length !== expected[1] || !entry.credit) throw new Error(`素材清单案例异常：${entry.slug}`);
    seenCases.add(entry.slug);
    for (const photo of entry.images) {
      if (!/^[a-z0-9-]+\.png$/.test(photo.file) || seenFiles.has(photo.file) || !photo.source || !photo.title) throw new Error(`素材清单文件异常：${photo.file}`);
      seenFiles.add(photo.file);
    }
  }
}
validateManifest();

const productCases = {
  'showcase-de-shou-gong': {
    name: '德寿宫｜器物礼盒', short: '德寿宫', category: '宫苑器物 / 礼赠设计', style: 'palace',
    accent: '#b48455', paper: '#ede8db', ink: '#263a35',
    headline: '把一座宫苑的\n好时光带回日常',
    introduction: '从礼盒到案头器物，让文化记忆成为可以拿起、使用与相赠的生活细节。现有两张实拍是本案视觉依据；未拍到的背面与内部结构不被虚构。',
    chapters: ['宫苑记忆', '器物入日常', '礼盒与相赠'],
    engineering: '礼盒开合、内托和器物放置关系仅作概念示意。器物口径、高度、背面造型、内衬公差、纸材与印刷工艺均待实物测量及白样确认。',
    marketing: '把一座宫苑的好时光，带回日常。\n从盒中器物到案头一隅，让文化记忆成为可使用、可相赠的生活细节。',
    handoff: '已整理礼盒、器物实拍与设计说明。三视图、准确尺寸和刀版尚无可靠依据，不能作为生产文件；下一步先测量实物，再验证结构白样。',
  },
  'showcase-ma-ti': {
    name: '马踏平安｜陶瓷随行礼', short: '马踏平安', category: '陶瓷文创 / 节令礼赠', style: 'playful',
    accent: '#ab563d', paper: '#f3eee4', ink: '#303a33',
    headline: '一件随行小物，\n一份平安祝愿',
    introduction: '挂饰的轻巧轮廓与杯具的日常尺度共同构成随行礼。三张实拍展示的是不同产品，而非同一器物的三视图。',
    chapters: ['随身挂饰', '案头器物', '节令相赠'],
    engineering: '系带连接、陶瓷壁厚、釉面安全和包装缓冲均需实物测试。现阶段只表达挂饰—系带—包装与杯具—手持—收纳的关系，不标注虚构尺寸。',
    marketing: '马踏平安，把好意头带在身边。\n一件随行的小物，一份能被放进日常的祝愿。',
    handoff: '产品实拍与传播叙事已整理。实际连接强度、尺寸、釉面安全和运输防护待实测；结构页为概念示意。',
  },
  'showcase-song-jin': {
    name: '宋锦｜葫芦胸针', short: '宋锦胸针', category: '织锦饰品 / 摄影作品集', style: 'museum',
    accent: '#b99967', paper: '#e9e3d6', ink: '#292a27',
    headline: '把一段织锦，\n别在今日衣襟',
    introduction: '在葫芦轮廓中观看织纹、金属包边与佩戴尺度。两张摄影作品保留真实细节与作者来源；未见背针结构不作成品三视图。',
    chapters: ['葫芦轮廓', '织物与金属', '近身收藏'],
    engineering: '正面摄影可用于讨论轮廓与纹样，背针、金属厚度、织物成分与佩戴尺寸均待实物确认。结构图只表示织物面—包边—背针的概念层级。',
    marketing: '把一段织锦，别在今日衣襟。\n细小的葫芦轮廓里，留下纹样、手感和一份随身携带的祝愿。',
    handoff: '作品集以获授权的两张摄影作品为核心，来源署名保存在资产元数据和网页页脚。背针连接、织物成分与尺寸待实物及工艺样确认。',
  },
};

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const imageSize = bytes => ({ width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) });
const clone = value => JSON.parse(JSON.stringify(value));

async function preflight() {
  const files = [];
  const missing = [];
  for (const entry of manifest.cases) for (const photo of entry.images) {
    const path = join(assetRoot, manifest.readyDirectory, photo.file);
    try {
      const info = await stat(path);
      if (!info.isFile() || info.size < 10_000) throw new Error('empty');
      const bytes = await readFile(path);
      if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error('not PNG');
      const size = imageSize(bytes);
      if (size.width < 300 || size.height < 300 || size.width > 16000 || size.height > 16000) throw new Error('invalid dimensions');
      files.push({ ...photo, slug: entry.slug, role: entry.role, credit: entry.credit, path, bytes, digest: sha(bytes), size });
    } catch { missing.push(photo.file); }
  }
  return { files, missing };
}

async function request(path, init) {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) throw new Error(`${init?.method || 'GET'} ${path}: ${response.status} ${await response.text()}`);
  return response.json();
}
async function verifyTarget(root, projects) {
  const oldCases = ['showcase-shan-yan', 'showcase-song-yun'];
  for (const slug of oldCases) {
    const project = projects.find(item => item.slug === slug);
    if (!project?.rootPath) throw new Error(`${slug}: 旧案例不在目标工作区，尚未导入任何素材。`);
    if (await realpath(dirname(project.rootPath)) !== root) throw new Error(`API 当前服务的工作区与 --workspace 不一致：${slug}`);
    const board = await request(`${projectPath(project.id)}/canvas`);
    if (!board.nodes?.some(node => node.data?.showcaseRole === 'html') || !board.nodes?.some(node => node.data?.showcaseRole === 'intro')) throw new Error(`${slug}: 画布尚未完成四案策展，未修改工作区。`);
    if (slug === 'showcase-shan-yan' && !board.nodes.some(node => node.data?.showcaseRole === 'engineering')) throw new Error('山砚缺少工程边界节点，未修改工作区。');
  }
  const openapi = await request('/openapi.json');
  const schema = openapi.paths?.['/api/projects/{project_id}/assets/upload']?.post?.requestBody?.content?.['multipart/form-data']?.schema;
  const form = schema?.$ref ? openapi.components?.schemas?.[schema.$ref.split('/').at(-1)] : schema;
  if (!['sourceCredit', 'sourceFile', 'sourceRole'].every(key => form?.properties?.[key])) throw new Error('当前 API 尚不支持素材来源字段。请先启动包含本次改动的 API，未修改工作区。');
}
const json = (value, method = 'POST') => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(value) });
const projectPath = id => `/api/projects/${encodeURIComponent(id)}`;

async function ensureProject(projects, slug) {
  const existing = projects.find(item => item.slug === slug);
  if (existing) {
    if (productCases[slug] && !String(existing.brief || '').startsWith('已保存的演示案例：')) throw new Error(`${slug}: 已有同名非演示项目，已停止以避免覆盖用户数据。`);
    return existing;
  }
  const spec = productCases[slug];
  if (!spec) throw new Error(`${slug}: 原有项目不在工作区，不能创建替代项目。`);
  const created = await request('/api/projects', json({ name: slug, brief: `已保存的演示案例：${spec.name}。${spec.introduction}` }));
  return request(projectPath(created.id), json({ name: spec.name }, 'PUT'));
}

async function ensureAsset(project, photo, existingAssets) {
  const filename = `langju-showcase-v${manifest.version}-${photo.file}`;
  const existing = existingAssets.find(asset => asset.metadata?.originalName === filename);
  if (existing) {
    if (existing.sha256 !== photo.digest) throw new Error(`${photo.file}: 已导入同名不同内容，请升级清单版本，不覆盖原资产。`);
    return existing;
  }
  const form = new FormData();
  form.append('kind', 'image');
  form.append('file', new Blob([photo.bytes], { type: 'image/png' }), filename);
  form.append('sourceCredit', photo.credit);
  form.append('sourceFile', photo.source);
  form.append('sourceRole', photo.role);
  const asset = await request(`${projectPath(project.id)}/assets/upload`, { method: 'POST', body: form });
  existingAssets.push(asset);
  return asset;
}

function visualNode(slug, photo, asset, index, x, y, order) {
  const width = Math.round(Math.min(320, 680 * photo.size.width / photo.size.height));
  const height = Math.round(width * photo.size.height / photo.size.width);
  return {
    id: `showcase-${slug}-photo-${String(index + 1).padStart(2, '0')}`, type: 'creative', position: { x, y },
    data: {
      kind: 'image', title: `${String(index + 1).padStart(2, '0')}｜${photo.title}`,
      assetId: asset.id, asset: { ...asset, metadata: { ...asset.metadata, width: photo.size.width, height: photo.size.height } },
      previewSizingVersion: 2, previewSize: { width, height }, imageFit: 'contain',
      status: '已生成', showcaseRole: photo.role === 'reference' ? 'reference' : 'visual',
      ...(order ? { showcaseOrder: order } : {}),
      showcaseProvenance: { sourceFile: photo.source, credit: photo.credit, role: photo.role, reviewedSha256: photo.digest },
      productionNotes: photo.role === 'reference' ? '其他品牌的视觉研究资料；不是本项目交付物，不继承图中的品牌或奖项。' : '经授权的产品实拍；尺寸与工艺需实物核对。',
      autoPositioned: false,
    },
    meta: { createdBy: 'showcase-import', sourceVersion: manifest.version },
  };
}

function engineeringHtml(spec) {
  const layers = spec.style === 'museum' ? ['织物面', '金属包边', '背针连接'] : spec.style === 'playful' ? ['器物 / 挂饰', '系带 / 收纳', '包装保护'] : ['器物', '内托', '外盒'];
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(spec.short)} / 结构示意</title><style>*{box-sizing:border-box}body{margin:0;padding:clamp(26px,6vw,84px);background:${spec.paper};color:${spec.ink};font-family:"PingFang SC",sans-serif}.label{color:${spec.accent};font:700 11px/1.5 Arial;letter-spacing:.18em}h1{max-width:10em;margin:18px 0;font:500 clamp(38px,6vw,80px)/1.12 "Songti SC",serif}.note{max-width:690px;line-height:1.9;color:${spec.ink}b8}.diagram{display:grid;grid-template-columns:repeat(3,1fr);align-items:center;gap:24px;min-height:350px;margin:52px 0 28px;padding:28px;border:1px solid ${spec.accent}66}.part{display:grid;place-items:center;min-height:230px;border:1.5px solid ${spec.accent};border-radius:42% 42% 15px 15px;background:linear-gradient(135deg,transparent,${spec.accent}25);font:24px "Songti SC",serif;text-align:center}.part:nth-child(2){border-radius:18px}.part:nth-child(3){border-radius:4px}.part span{display:block;margin-top:10px;color:${spec.accent};font:11px Arial}.foot{border-top:1px solid ${spec.accent}88;padding-top:18px;font-size:12px;line-height:1.8}@media(max-width:650px){.diagram{grid-template-columns:1fr}.part{min-height:160px}}</style></head><body><div class="label">CONCEPT STRUCTURE / NOT FOR PRODUCTION</div><h1>${escapeHtml(spec.short)}<br>结构关系示意</h1><p class="note">${escapeHtml(spec.engineering)}</p><div class="diagram">${layers.map((layer, index) => `<div class="part">${escapeHtml(layer)}<span>0${index + 1} / 待实测</span></div>`).join('')}</div><p class="foot">此页不是刀版、产品三视图或尺寸工程文件；实际结构、材料和生产参数必须经实物测量与打样确认。</p></body></html>`;
}

function portfolioHtml(spec, photos, assets) {
  const figure = (photo, index) => `<figure class="photo photo-${index + 1}"><img src="asset://${assets[index].id}" alt="${escapeHtml(photo.title)}"><figcaption><span>0${index + 1} / ${escapeHtml(photo.title)}</span><span>PRODUCT STUDY</span></figcaption></figure>`;
  const hero = figure(photos[0], 0);
  const detail = photos.slice(1).map((photo, index) => figure(photo, index + 1)).join('');
  const headline = escapeHtml(spec.headline).replace('\n', '<br>');
  const credit = escapeHtml(photos[0].credit);
  const number = spec.style === 'museum' ? 'III' : spec.style === 'playful' ? 'II' : 'I';
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(spec.name)} / Case Study</title><style>
  :root{--paper:${spec.paper};--ink:${spec.ink};--accent:${spec.accent}}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Songti SC","Noto Serif CJK SC",serif}figure{margin:0}img{display:block;width:100%;height:100%;object-fit:cover}.wrap{width:min(1500px,100%);margin:auto;padding-inline:clamp(22px,5vw,84px)}.eyebrow,.meta,figcaption,.num{font:11px/1.5 Arial,"PingFang SC",sans-serif;letter-spacing:.12em}.eyebrow{color:var(--accent)}nav{display:flex;justify-content:space-between;gap:20px;padding-block:30px;border-bottom:1px solid var(--accent)}.hero{display:grid;grid-template-columns:.85fr 1.15fr;min-height:790px;gap:5vw;align-items:center;padding-block:60px}.hero h1{margin:32px 0;font-size:clamp(52px,7vw,112px);font-weight:400;line-height:1.07;letter-spacing:-.07em}.hero p{max-width:570px;font-size:17px;line-height:2}.hero .photo{height:680px}.photo{position:relative;overflow:hidden;background:color-mix(in srgb,var(--paper) 78%,var(--ink))}figcaption{display:flex;justify-content:space-between;gap:20px;padding:12px 0;color:var(--ink);letter-spacing:.05em}.index{display:grid;grid-template-columns:1fr 2fr;gap:60px;padding-block:120px;border-top:1px solid var(--accent)}.index h2,.section-title{font-size:clamp(38px,5vw,76px);font-weight:400;line-height:1.15;letter-spacing:-.05em}.index p{max-width:790px;font-size:18px;line-height:2}.chapters{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:62px}.chapters div{min-height:190px;padding:18px 0;border-top:1px solid var(--accent);font-size:23px}.chapters span{display:block;margin-bottom:45px;color:var(--accent);font:13px Arial}.gallery{padding-block:90px}.gallery-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:30px}.gallery .photo{min-height:530px}.gallery .photo:last-child:nth-child(odd){grid-column:span 2}.statement{padding-block:130px;background:var(--ink);color:var(--paper)}.statement blockquote{max-width:1150px;margin:40px 0;font-size:clamp(40px,6.2vw,94px);line-height:1.25;letter-spacing:-.055em}.process{display:grid;grid-template-columns:.7fr 1.3fr;gap:70px;padding-block:125px}.process p{max-width:750px;font-size:17px;line-height:2}.process ul{padding:25px 0 0;list-style:none}.process li{display:flex;justify-content:space-between;gap:30px;padding:18px 0;border-top:1px solid var(--accent);font-size:15px}.footer{display:flex;justify-content:space-between;gap:40px;padding-block:30px;border-top:1px solid var(--accent);font:11px/1.7 Arial,"PingFang SC",sans-serif}
  body.playful .hero{grid-template-columns:1fr 1fr;min-height:680px}body.playful .hero h1{font-size:clamp(60px,8vw,128px)}body.playful .hero .photo{height:540px;border-radius:48% 48% 12px 12px}body.playful .gallery-grid{grid-template-columns:1fr 1fr 1fr}body.playful .gallery .photo{min-height:420px;border-radius:180px 180px 18px 18px}body.playful .gallery .photo:last-child:nth-child(odd){grid-column:auto}body.museum{background:#211f1d;color:#ebe4d7}body.museum nav,body.museum .index,body.museum .process li,body.museum .footer{border-color:#b9996777}body.museum .hero{grid-template-columns:1.2fr .8fr}body.museum .hero .photo{order:-1;height:800px}body.museum .gallery-grid{grid-template-columns:1fr 1fr}body.museum .gallery .photo{min-height:680px}body.museum figcaption{color:#d5c7ac}body.museum .statement{background:#b99967;color:#211f1d}
  @media(max-width:760px){.hero,.index,.process{grid-template-columns:1fr;min-height:0}.hero .photo,body.museum .hero .photo{height:auto;aspect-ratio:4/5}.hero .photo{order:-1}.chapters{grid-template-columns:1fr}.chapters div{min-height:0}.gallery-grid,body.playful .gallery-grid,body.museum .gallery-grid{grid-template-columns:1fr}.gallery .photo,.gallery .photo:last-child:nth-child(odd),body.playful .gallery .photo:last-child:nth-child(odd){grid-column:auto;min-height:0;aspect-ratio:4/5}.footer{display:block}}
  </style></head><body class="${spec.style}"><nav class="wrap"><span class="eyebrow">LANGJU / DESIGN CASE ${number}</span><span class="meta">${escapeHtml(spec.category)}</span></nav><main><section class="wrap hero"><div><span class="eyebrow">01 / THE IDEA</span><h1>${headline}</h1><p>${escapeHtml(spec.introduction)}</p></div>${hero}</section><section class="wrap index"><span class="eyebrow">02 / PROJECT INDEX</span><div><h2>从真实器物出发，<br>让设计有据可循。</h2><p>${escapeHtml(spec.introduction)}</p><div class="chapters">${spec.chapters.map((item, index) => `<div><span>0${index + 1}</span>${escapeHtml(item)}</div>`).join('')}</div></div></section><section class="wrap gallery"><span class="eyebrow">03 / PRODUCT & MATERIAL</span><h2 class="section-title">看见形态，也看见细节。</h2><div class="gallery-grid">${detail}</div></section><section class="statement"><div class="wrap"><span class="eyebrow">04 / THE MESSAGE</span><blockquote>${escapeHtml(spec.marketing).replace('\n', '<br>')}</blockquote></div></section><section class="wrap process"><div><span class="eyebrow">05 / PRODUCTION BOUNDARY</span><h2 class="section-title">从示意到实物，<br>还要走一步。</h2></div><div><p>${escapeHtml(spec.engineering)}</p><ul><li><span>已确认</span><span>现有产品照片所见外观</span></li><li><span>待确认</span><span>尺寸、材料与工艺参数</span></li><li><span>交付性质</span><span>设计示意；非生产文件</span></li></ul></div></section></main><footer class="wrap footer"><span>${escapeHtml(spec.name)} · DESIGN CASE / 2026</span><span>影像来源：${credit}</span></footer></body></html>`;
}

const textNode = (id, title, text, role, order, x, y) => ({ id, type: 'creative', position: { x, y }, data: { kind: 'text', title, text, showcaseRole: role, showcaseOrder: order, previewSizingVersion: 2, status: '已生成', autoPositioned: false }, meta: { createdBy: 'showcase-import' } });
const htmlNode = (id, title, html, role, order, x, y, assets = {}) => ({ id, type: 'creative', position: { x, y }, data: { kind: 'html', title, html, htmlAssets: assets, imageAssetIds: Object.keys(assets), showcaseRole: role, showcaseOrder: order, previewSize: { width: 960, height: 640 }, previewSizingVersion: 2, status: '已生成', autoPositioned: false }, meta: { createdBy: 'showcase-import' } });

function changes(before, after) {
  const upsertNodes = after.nodes.filter(node => JSON.stringify(before.nodes.find(old => old.id === node.id)) !== JSON.stringify(node));
  const expectedNodes = Object.fromEntries(upsertNodes.map(node => [node.id, before.nodes.find(old => old.id === node.id) || null]));
  return { upsertNodes, upsertEdges: [], removeNodeIds: [], removeEdgeIds: [], expectedNodes, expectedEdges: {} };
}

async function save(project, before, after) {
  const patch = changes(before, after);
  if (!patch.upsertNodes.length) return;
  await request(`${projectPath(project.id)}/canvas`, json(patch, 'PATCH'));
  console.log(`${project.slug}: 已写入 ${patch.upsertNodes.length} 个新增/更新节点`);
}

async function addExisting(project, photos, assets, board) {
  const slug = project.slug;
  const after = clone(board);
  const ids = photos.map((_, index) => `showcase-${slug}-photo-${String(index + 1).padStart(2, '0')}`);
  const already = ids.filter(id => after.nodes.some(node => node.id === id));
  if (already.length === ids.length) return;
  if (already.length) throw new Error(`${slug}: 仅部分新增画面存在，已停止以避免重复移动原节点。`);
  if (slug === 'showcase-song-yun') {
    const bottom = Math.max(0, ...after.nodes.map(node => Number(node.position?.y || 0))) + 950;
    after.nodes.push(textNode(`showcase-${slug}-reference-note`, '视觉研究｜其他品牌青瓷资料', '# 参考资料，不是本案交付\n\n以下三张图属于“雲天雨過 / 汐山明”等其他品牌。只讨论青瓷釉色、产品摄影和包装比例，不沿用其品牌标识或奖项，也不计入宋韵雅集的生成成果。', 'reference', undefined, 0, bottom));
    photos.forEach((photo, index) => after.nodes.push(visualNode(slug, photo, assets[index], index, index * 380, bottom + 450)));
  } else {
    const engineering = after.nodes.find(node => node.data?.showcaseRole === 'engineering');
    if (!engineering || !Number.isFinite(Number(engineering.data?.showcaseOrder))) throw new Error('山砚尚未应用四案策展顺序，请先运行 curate-showcase-projects.mjs。');
    const insertY = Number(engineering.position.y);
    const frameHeights = photos.map(photo => Math.min(680, Math.round(320 * photo.size.height / photo.size.width)));
    const firstRowHeight = Math.max(...frameHeights.slice(0, 3));
    const secondRowHeight = Math.max(...frameHeights.slice(3));
    const insertedHeight = firstRowHeight + secondRowHeight + 260;
    after.nodes.forEach(node => {
      if (Number(node.data?.showcaseOrder) >= 18) {
        node.data.showcaseOrder += photos.length;
        node.position.y += insertedHeight;
      }
    });
    photos.forEach((photo, index) => after.nodes.push(visualNode(slug, photo, assets[index], index, (index % 3) * 380, insertY + (index < 3 ? 0 : firstRowHeight + 130), 18 + index)));
    const page = after.nodes.find(node => node.data?.showcaseRole === 'html');
    if (page && !String(page.data.html).includes('data-showcase-addon="shan-yan"')) {
      const gallery = `<section data-showcase-addon="shan-yan" style="padding:8vw 5vw;background:#171c19;color:#f0eee5"><p style="font:11px Arial;letter-spacing:.2em;color:#9eaa82">PRODUCT PHOTOGRAPHY / REAL MATERIAL</p><h2 style="font:400 clamp(38px,5vw,76px) Songti SC,serif">真实纸材与产品细节</h2><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px">${photos.map((photo, index) => `<figure style="margin:0"><img style="width:100%;height:auto;display:block" src="asset://${assets[index].id}" alt="${escapeHtml(photo.title)}"><figcaption style="padding:12px 0;font:12px Arial">${escapeHtml(photo.title)}</figcaption></figure>`).join('')}</div><p style="margin-top:36px;font:12px Arial">来源：${escapeHtml(photos[0].credit)}</p></section>`;
      page.data.html = String(page.data.html).replace('</body>', `${gallery}</body>`);
      page.data.htmlAssets = { ...(page.data.htmlAssets || {}), ...Object.fromEntries(photos.map((photo, index) => [assets[index].id, `data:image/png;base64,${photo.bytes.toString('base64')}`])) };
      page.data.imageAssetIds = [...new Set([...(page.data.imageAssetIds || []), ...assets.map(asset => asset.id)])];
    }
  }
  await save(project, board, after);
}

async function addProduct(project, spec, photos, assets, board) {
  const slug = project.slug;
  const after = clone(board);
  const prefix = `showcase-${slug}`;
  const existing = after.nodes.filter(node => String(node.id).startsWith(prefix));
  if (existing.length) {
    if (photos.every((_, index) => existing.some(node => node.id === `${prefix}-photo-${String(index + 1).padStart(2, '0')}`))) return;
    throw new Error(`${slug}: 演示节点不完整，已停止以保留现场，请人工检查。`);
  }
  const plan = `# ${spec.name}｜项目基本信息与任务规划\n\n## 项目背景\n${spec.introduction}\n\n## 设计判断\n${spec.chapters.map((item, index) => `${index + 1}. ${item}`).join('\n')}\n\n## 本轮交付\n产品实拍解读、设计语言、结构关系示意、营销文案和可浏览的作品集。照片没有证明的视角、材料、尺寸与刀版不虚构；工程页仅为设计示意。`;
  after.nodes.push(textNode(`${prefix}-plan`, `00｜${spec.short} · 项目信息与规划`, plan, 'intro', 1, 0, 0));
  after.nodes.push(textNode(`${prefix}-chapter`, `01｜${spec.short} · 产品与设计语言`, `# 产品观察\n\n${spec.introduction}\n\n观看顺序：${spec.chapters.join(' → ')}。`, 'chapter', 2, 0, 620));
  photos.forEach((photo, index) => after.nodes.push(visualNode(slug, photo, assets[index], index, index * 380, 1100, 3 + index)));
  const photoBottom = 1100 + Math.max(...photos.map(photo => Math.min(680, Math.round(320 * photo.size.height / photo.size.width))));
  const next = 3 + photos.length;
  const productionY = photoBottom + 180;
  after.nodes.push(htmlNode(`${prefix}-engineering`, `${String(next).padStart(2, '0')}｜${spec.short} · 结构关系示意`, engineeringHtml(spec), 'engineering', next, 0, productionY));
  after.nodes.push(textNode(`${prefix}-marketing`, `${String(next + 1).padStart(2, '0')}｜${spec.short} · 营销文案`, `# ${spec.short}｜传播文案\n\n${spec.marketing}`, 'marketing', next + 1, 1100, productionY));
  const embedded = Object.fromEntries(photos.map((photo, index) => [assets[index].id, `data:image/png;base64,${photo.bytes.toString('base64')}`]));
  const closingY = productionY + 850;
  after.nodes.push(htmlNode(`${prefix}-portfolio`, `${String(next + 2).padStart(2, '0')}｜${spec.short} · 最终设计作品集`, portfolioHtml(spec, photos, assets), 'html', next + 2, 0, closingY, embedded));
  after.nodes.push(textNode(`${prefix}-handoff`, `${String(next + 3).padStart(2, '0')}｜${spec.short} · 交付与待核实`, `# 呈现与落地\n\n${spec.handoff}\n\n影像来源：${photos[0].credit}`, 'handoff', next + 3, 1120, closingY));
  await save(project, board, after);
}

const { files, missing } = await preflight();
if (missing.length) {
  console.error(`尚有 ${missing.length}/16 张去水印成品未验收，未修改工作区：\n${missing.map(name => `- ${name}`).join('\n')}`);
  process.exitCode = 2;
} else if (checkOnly) {
  console.log(`全部 ${files.length} 张修整成品已就绪；尚未修改工作区。`);
} else {
  if (!workspace) throw new Error('请通过 --workspace 指定真实演示工作区；不能隐式选择目录。');
  const root = await realpath(resolve(workspace));
  await stat(join(root, 'catalog.sqlite'));
  const projects = await request('/api/projects');
  await verifyTarget(root, projects);
  for (const entry of manifest.cases) {
    const project = await ensureProject(projects, entry.slug);
    if (!projects.some(item => item.id === project.id)) projects.push(project);
    const existingAssets = await request(`${projectPath(project.id)}/assets`);
    const photos = files.filter(file => file.slug === entry.slug);
    const assets = [];
    for (const photo of photos) assets.push(await ensureAsset(project, photo, existingAssets));
    const board = await request(`${projectPath(project.id)}/canvas`);
    if (productCases[entry.slug]) {
      await addProduct(project, productCases[entry.slug], photos, assets, board);
      await mkdir(coverRoot, { recursive: true });
      await copyFile(photos[0].path, join(coverRoot, `${entry.slug.replace(/^showcase-/, '')}-cover.png`));
    } else await addExisting(project, photos, assets, board);
  }
  console.log('七案素材导入完成；来源署名保存在资产与节点元数据中。');
}
