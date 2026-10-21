#!/usr/bin/env node
/** Import the supplied Shan Ming artwork into one saved showcase project. */
import { createHash } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createEditorialPortfolio } from './editorial-portfolio.mjs';

const assetsRoot = join(dirname(fileURLToPath(import.meta.url)), 'showcase-assets/shan-ming-v1');
const manifest = JSON.parse(await readFile(join(assetsRoot, 'manifest.json'), 'utf8'));
const args = process.argv.slice(2);
const option = (name, fallback = '') => { const index = args.indexOf(name); return index < 0 ? fallback : args[index + 1] || fallback; };
const apiBase = option('--api', 'http://127.0.0.1:8765').replace(/\/$/, '');
const workspace = option('--workspace');
const checkOnly = args.includes('--check');
const slug = 'showcase-shan-ming';
const importPrefix = 'langju-shan-ming-v1-';
const nodePrefix = 'showcase-shan-ming-';
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);

function validateManifest() {
  if (manifest.version !== 1 || manifest.slug !== slug || !Array.isArray(manifest.images) || manifest.images.length !== 9) throw new Error('山茗素材清单版本或数量不正确。');
  const files = new Set();
  for (const image of manifest.images) {
    if (!/^[a-z0-9-]+\.png$/.test(image.file) || files.has(image.file) || !['deliverable', 'reference'].includes(image.role) || !image.sourceFile || !image.title || !/^[a-f0-9]{64}$/.test(image.sha256)) throw new Error(`山茗素材清单记录无效：${image.file}`);
    files.add(image.file);
  }
  if (manifest.images.filter(image => image.role === 'deliverable').length !== 7 || manifest.images.filter(image => image.role === 'reference').length !== 2) throw new Error('山茗交付素材和异品牌参考素材的数量不正确。');
}

async function preflight() {
  const images = [];
  for (const item of manifest.images) {
    const path = join(assetsRoot, item.file);
    const bytes = await readFile(path);
    if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) || bytes.length < 10_000) throw new Error(`${item.file}: 不是有效的演示 PNG 文件。`);
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (digest !== item.sha256) throw new Error(`${item.file}: 内容与已核对的原图不一致，未写入工作区。`);
    const width = bytes.readUInt32BE(16);
    const height = bytes.readUInt32BE(20);
    if (width < 300 || height < 300 || width > 16000 || height > 16000) throw new Error(`${item.file}: 图像尺寸异常。`);
    images.push({ ...item, bytes, width, height, digest });
  }
  return images;
}

async function request(path, init) {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) throw new Error(`${init?.method || 'GET'} ${path}: ${response.status} ${await response.text()}`);
  return response.json();
}
const json = (value, method = 'POST') => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(value) });
const projectPath = id => `/api/projects/${encodeURIComponent(id)}`;

async function verifyWorkspace() {
  if (!workspace) throw new Error('请用 --workspace 明确指定演示工作区。');
  const root = await realpath(resolve(workspace));
  await stat(join(root, 'catalog.sqlite'));
  const projects = await request('/api/projects');
  const anchor = projects.find(project => project.slug === 'showcase-song-yun');
  if (!anchor?.rootPath || await realpath(dirname(anchor.rootPath)) !== root) throw new Error('当前 API 与 --workspace 不是同一个演示工作区；没有写入任何内容。');
  const existing = projects.find(project => project.slug === slug);
  if (existing && !String(existing.brief || '').startsWith('已保存的演示案例：')) throw new Error('已有同名的非演示项目，已停止以保留用户内容。');
  return existing;
}

async function ensureProject(existing) {
  if (existing) return existing;
  const brief = '已保存的演示案例：山茗｜高山茶品牌包装系统。用户提供的七张山茗视觉资料用于包装与品牌展示；两张异品牌图片仅作参考。图中尺寸是概念方案标注，需打样核准。';
  const created = await request('/api/projects', json({ name: slug, brief }));
  if (created.slug !== slug) throw new Error(`新项目 slug 异常：${created.slug}，请检查已有项目。`);
  return request(projectPath(created.id), json({ name: manifest.name }, 'PUT'));
}

async function ensureAsset(project, image, currentAssets) {
  const filename = `${importPrefix}${image.file}`;
  const existing = currentAssets.find(asset => asset.metadata?.originalName === filename);
  if (existing) {
    if (existing.sha256 !== image.digest) throw new Error(`${filename}: 同名资产内容不同，不能覆盖。`);
    return existing;
  }
  const form = new FormData();
  form.append('kind', 'image');
  form.append('file', new Blob([image.bytes], { type: 'image/png' }), filename);
  // Current packaged APIs may ignore these optional fields; node provenance
  // below always keeps the source and role alongside the saved image.
  form.append('sourceCredit', manifest.source);
  form.append('sourceFile', image.sourceFile);
  form.append('sourceRole', image.role);
  const asset = await request(`${projectPath(project.id)}/assets/upload`, { method: 'POST', body: form });
  currentAssets.push(asset);
  return asset;
}

const textNode = (id, title, text, role, order, x, y) => ({ id: `${nodePrefix}${id}`, type: 'creative', position: { x, y }, data: { kind: 'text', title, text, status: '已生成', showcaseRole: role, ...(order ? { showcaseOrder: order } : {}), previewSizingVersion: 2, autoPositioned: false }, meta: { createdBy: 'shan-ming-import', sourceVersion: 1 } });
const htmlNode = (id, title, html, order, x, y, embedded = {}) => ({ id: `${nodePrefix}${id}`, type: 'creative', position: { x, y }, data: { kind: 'html', title, html, htmlAssets: embedded, imageAssetIds: Object.keys(embedded), showcaseRole: 'html', showcaseOrder: order, status: '已生成', previewSize: { width: 960, height: 640 }, previewSizingVersion: 2, autoPositioned: false }, meta: { createdBy: 'shan-ming-import', sourceVersion: 1 } });

function imageNode(image, asset, index, order, x, y) {
  const width = image.role === 'reference' && image.height > image.width ? 480 : 620;
  const height = Math.round(width * image.height / image.width);
  return {
    id: `${nodePrefix}${image.file.replace(/\.png$/, '')}`, type: 'creative', position: { x, y },
    data: {
      kind: 'image', title: `${String(index + 1).padStart(2, '0')}｜${image.title}`,
      assetId: asset.id, asset: { ...asset, metadata: { ...asset.metadata, width: image.width, height: image.height } },
      imageFit: 'contain', previewSize: { width, height }, previewSizingVersion: 2,
      showcaseRole: image.role === 'reference' ? 'reference' : 'visual', ...(order ? { showcaseOrder: order } : {}),
      showcaseProvenance: { sourceFile: image.sourceFile, role: image.role, sha256: image.digest, source: manifest.source },
      productionNotes: image.role === 'reference'
        ? '其他品牌资料，仅供版式或结构研究；不是山茗的品牌、产品或交付成果。'
        : '用户提供的包装视觉方案。图中尺寸和刀版属于方案标注，未通过白样、工艺和实际产品核对，不能直接投产。',
      status: '已生成', autoPositioned: false,
    },
    meta: { createdBy: 'shan-ming-import', sourceVersion: 1 },
  };
}

function portfolioHtml(images, assets) {
  return createEditorialPortfolio({ slug, name: manifest.name, credit: manifest.source, rows: images.map((image, i) => ({ ...image, assetId: assets[i].id })) });
}

function buildNodes(images, assets) {
  const byFile = new Map(images.map((image, index) => [image.file, { image, asset: assets[index], index }]));
  const visual = (file, order, x, y) => { const row = byFile.get(file); return imageNode(row.image, row.asset, row.index, order, x, y); };
  const plan = '# 山茗｜项目背景与任务规划\n\n## 项目背景\n围绕高山茶建立品牌包装系统，让茶盒、手提礼盒、杯身和传播物料共享一套松影、青绿与深色纸张语言。现有资料为用户提供的视觉方案，不是已核准的产品摄影或生产文件。\n\n## 已知与待确认\n已知：品牌名、视觉方向、七张山茗方案图。待确认：茶品产地与等级、实物盒型/杯型、尺寸、公差、纸张克重、食品接触与印刷工艺。\n\n## 本轮交付\n产品与物料全景 → 包装系统 → 单品和杯身展开 → 手提盒结构方案 → 营销文案 → HTML 作品集与打样清单。';
  const nodes = [
    textNode('plan', '00｜山茗 · 项目背景与规划', plan, 'intro', 1, 0, -1000),
    textNode('identity', '01｜山茗 · 设计主张', '# 设计主张\n\n以松影建立识别，以青绿区分茶品，以深色纸面压住视觉重量；信息层级先读品牌，再读品类与单品名称。包装从远看有整体，近看能辨识具体产品。', 'chapter', 2, 800, -1000),
    visual('shan-ming-overview.png', 3, 0, 0),
    visual('shan-ming-gift-box-design.png', 4, 760, 0),
    textNode('system-chapter', '02｜山茗 · 包装系统', '# 包装系统\n\n从茶礼盒到方形茶盒，再延伸至纸杯和纸品。它们不是同一结构的不同角度，而是不同尺度、不同使用场景的系列物料。', 'chapter', 5, 0, 700),
    visual('shan-ming-system-dielines.png', 6, 0, 1280),
    visual('shan-ming-tea-box-dieline.png', 7, 760, 1280),
    visual('shan-ming-cup-sleeve.png', 8, 0, 2050),
    textNode('engineering-chapter', '03｜山茗 · 展开与打样', '# 展开关系\n\n杯身扇形、盒体折线、提手与粘口都已在视觉方案中表达。不同图纸出现的尺寸需统一复核；现阶段不能直接作为印刷或模切文件。', 'chapter', 9, 760, 2050),
    visual('shan-ming-gift-box-detail.png', 10, 0, 2760),
    visual('shan-ming-gift-box-flat.png', 11, 760, 2760),
    textNode('engineering', '04｜山茗 · 工程核对清单', '# 工程与打样边界\n\n这些 PNG 是包装结构及效果的设计示意，图中的尺寸、刀线和出血标注未经实物及印前核准。\n\n- 核对实际盒型、杯型、折线与粘口。\n- 按打样结果统一尺寸和公差，制作正式矢量刀版。\n- 验证纸材克重、印刷颜色、表面工艺与食品接触要求。\n- 确认茶品的真实名称、产地、等级与法定标签。', 'engineering', 12, 0, 3510),
    textNode('marketing', '05｜山茗 · 传播文案', '# 传播文案\n\n**品牌主张**　山水有灵，茶自天成。\n\n**礼赠短文案**　把山的安静折进茶盒，把好茶带进每一次日常相逢。\n\n**杯身短句**　一杯山茗，片刻清明。\n\n文案为演示提案；茶品产地、功效与等级尚未核实，不在传播中作相关声明。', 'marketing', 13, 760, 3510),
  ];
  const deliverables = images.map((image, index) => ({ image, asset: assets[index] })).filter(row => row.image.role === 'deliverable');
  const html = portfolioHtml(deliverables.map(row => row.image), deliverables.map(row => row.asset));
  const embedded = Object.fromEntries(deliverables.map(row => [row.asset.id, `data:image/png;base64,${row.image.bytes.toString('base64')}`]));
  nodes.push(htmlNode('portfolio', '06｜山茗 · 最终设计作品集', html, 14, 0, 4340, embedded));
  nodes.push(textNode('handoff', '07｜山茗 · 交付与待核实', '# 呈现与落地\n\n本案包含七张山茗视觉资料、品牌与包装叙事、营销文案和可浏览的设计作品集。另两张异品牌图片只保留在参考区，不进入山茗交付与首页回放。\n\n下阶段需要统一核对礼盒、茶盒、杯身的实际尺寸与结构，完成白样装配、食品包装合规和印前文件；本轮 PNG 不能直接投产。', 'handoff', 15, 1110, 4340));
  nodes.push(textNode('reference-note', '视觉研究｜异品牌参考（非山茗交付）', '# 仅作视觉研究\n\n「雲天晴」海报用于观察留白与文字层级；「ROCK GRIND／山砚」包装图用于观察礼盒展开图的信息编排。两者的品牌名、产品、奖项与包装设计均不属于山茗，不进入首页回放或最终作品集。', 'reference', undefined, 0, 5400));
  nodes.push(visual('reference-yun-tian-qing-poster.png', undefined, 0, 5980));
  nodes.push(visual('reference-rock-grind-box.png', undefined, 760, 5980));
  return nodes;
}

function validateStory(images) {
  const nodes = buildNodes(images, images.map((_, index) => ({ id: `preview-${index}`, metadata: {} })));
  const ordered = nodes.filter(node => Number.isInteger(node.data.showcaseOrder));
  if (nodes.length !== 18 || ordered.length !== 15 || ordered.some((node, index) => node.data.showcaseOrder !== index + 1)) throw new Error('山茗案例节点或回放顺序不完整。');
  const photos = nodes.filter(node => node.data.kind === 'image');
  if (photos.filter(node => node.data.showcaseRole === 'visual').length !== 7 || photos.filter(node => node.data.showcaseRole === 'reference' && node.data.showcaseOrder === undefined).length !== 2) throw new Error('山茗交付图和异品牌参考没有正确隔离。');
  const page = nodes.find(node => node.id === `${nodePrefix}portfolio`);
  if (!page || /雲天晴|ROCK GRIND|山砚/.test(page.data.html)) throw new Error('山茗作品集混入了异品牌内容。');
  for (let i = 0; i < photos.length; i++) for (let j = i + 1; j < photos.length; j++) {
    const a = photos[i]; const b = photos[j];
    if (!(a.position.x + a.data.previewSize.width <= b.position.x || b.position.x + b.data.previewSize.width <= a.position.x || a.position.y + a.data.previewSize.height <= b.position.y || b.position.y + b.data.previewSize.height <= a.position.y)) throw new Error(`山茗画面节点重叠：${a.id} / ${b.id}`);
  }
}

validateManifest();
const images = await preflight();
validateStory(images);
if (checkOnly) {
  console.log(`山茗素材核对通过：${images.filter(image => image.role === 'deliverable').length} 张案例内容、${images.filter(image => image.role === 'reference').length} 张异品牌参考；未写入工作区。`);
} else {
  const existing = await verifyWorkspace();
  const project = await ensureProject(existing);
  const path = projectPath(project.id);
  const currentAssets = await request(`${path}/assets`);
  const assets = [];
  for (const image of images) assets.push(await ensureAsset(project, image, currentAssets));
  const board = await request(`${path}/canvas`);
  const existingNodes = board.nodes.filter(node => String(node.id).startsWith(nodePrefix));
  if (existingNodes.length) {
    if (existingNodes.length !== 18 || !existingNodes.some(node => node.id === `${nodePrefix}portfolio`)) throw new Error('山茗画布只导入了一部分，已停止以保留现场。');
    console.log('山茗案例已导入；本次没有重复写入画布。');
  } else {
    if (board.nodes.length) throw new Error('山茗项目画布已有其他内容，已停止以保留用户编辑。');
    const nodes = buildNodes(images, assets);
    await request(`${path}/canvas`, json({ upsertNodes: nodes, upsertEdges: [], removeNodeIds: [], removeEdgeIds: [], expectedNodes: Object.fromEntries(nodes.map(node => [node.id, null])), expectedEdges: {} }, 'PATCH'));
    console.log(`山茗案例已导入：${nodes.length} 个画布节点，7 张山茗内容与 2 张异品牌参考。`);
  }
}
