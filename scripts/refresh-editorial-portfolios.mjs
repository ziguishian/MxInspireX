#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir, realpath } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createEditorialPortfolio, editorialSlugs } from './editorial-portfolio.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const supplementalRoot = join(root, 'scripts/showcase-assets/editorial-v2');
const supplemental = JSON.parse(await readFile(join(supplementalRoot, 'manifest.json'), 'utf8'));
const args = process.argv.slice(2); const option = (key, fallback = '') => { const i = args.indexOf(key); return i < 0 ? fallback : args[i + 1]; };
if (!option('--workspace')) throw new Error('请明确指定 --workspace。');
const workspace = await realpath(resolve(option('--workspace')));
const output = resolve(option('--output', join(root, '.tmp/editorial-portfolios')));
const localOnly = args.includes('--preview');
const api = option('--api', 'http://127.0.0.1:8765').replace(/\/$/, '');
const request = async (path, init) => { const r = await fetch(api + path, init); if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`); return r.json(); };
const json = (body, method = 'POST') => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
const ciJin = JSON.parse(await readFile(join(root, 'scripts/showcase-assets/ci-jin-v1/manifest.json'), 'utf8'));
const ceMa = JSON.parse(await readFile(join(root, 'scripts/showcase-assets/ce-ma-v1/manifest.json'), 'utf8')).case;
const shan = JSON.parse(await readFile(join(root, 'scripts/showcase-assets/shan-ming-v1/manifest.json'), 'utf8'));
const entries = [...ciJin.cases, ceMa, { ...shan, credit: shan.source, images: shan.images.filter(image => image.role === 'deliverable') }];
await mkdir(output, { recursive: true });
// Verify all four destinations and every source before any write to the live API.
const projects = localOnly ? null : await request('/api/projects');
const plans = [];
for (const slug of editorialSlugs) {
  const entry = entries.find(item => item.slug === slug);
  const project = localOnly ? JSON.parse(await readFile(join(workspace, slug, 'project.json'), 'utf8')) : projects.find(p => p.slug === slug);
  if (!project?.brief?.startsWith('已保存的演示案例：') || await realpath(dirname(project.rootPath)) !== workspace) throw new Error(`案例与工作区不一致：${slug}`);
  const board = localOnly ? JSON.parse(await readFile(join(project.rootPath, 'canvas/board.json'), 'utf8')) : await request(`/api/projects/${project.id}/canvas`);
  const candidates = board.nodes.filter(n => n.data?.kind === 'html' && n.data?.showcaseRole === 'html');
  if (candidates.length !== 1) throw new Error(`最终作品集节点不是唯一：${slug}`);
  const node = candidates[0]; const rows = [];
  for (const image of entry.images) {
    const source = board.nodes.find(n => n.data?.kind === 'image' && n.data?.showcaseProvenance?.sha256 === image.sha256);
    if (!source?.data?.assetId) throw new Error(`${slug} 缺少已核对图片：${image.file}`);
    let dataUrl = node.data.htmlAssets?.[source.data.assetId];
    if (!dataUrl) throw new Error(`原作品集未保存来源图片：${image.file}`);
    if (createHash('sha256').update(Buffer.from(dataUrl.split(',')[1], 'base64')).digest('hex') !== image.sha256) throw new Error(`内嵌图片与清单不一致：${image.file}`);
    rows.push({ ...image, assetId: source.data.assetId, dataUrl });
  }
  const extras = [];
  for (const image of supplemental.images.filter(row => row.slug === slug)) {
    const bytes = await readFile(join(supplementalRoot, image.file));
    if (createHash('sha256').update(bytes).digest('hex') !== image.sha256) throw new Error(`新增图校验失败：${image.file}`);
    extras.push({ ...image, bytes, dataUrl: `data:image/png;base64,${bytes.toString('base64')}` });
  }
  plans.push({ slug, entry, project, board, node, rows, extras });
}
for (const plan of plans) {
  const { slug, project, entry, node, rows, extras, board } = plan;
  const path = `/api/projects/${project.id}`;
  const savedAssets = localOnly ? [] : await request(`${path}/assets`);
  for (const image of extras) {
    let asset = savedAssets.find(a => a.metadata?.originalName === `editorial-v2-${image.file}`);
    if (asset && asset.sha256 !== image.sha256) throw new Error('新增同名图片内容不同，未覆盖。');
    if (!localOnly && !asset) {
      const form = new FormData(); form.append('kind', 'image'); form.append('file', new Blob([image.bytes], { type: 'image/png' }), `editorial-v2-${image.file}`); form.append('sourceRole', image.role); form.append('sourceFile', image.sourceFile); form.append('sourceCredit', '内置 imagegen：基于已有方案生成的氛围概念图');
      asset = await request(`${path}/assets/upload`, { method: 'POST', body: form });
    }
    rows.push({ ...image, assetId: asset?.id || `editorial-preview-${image.file}` });
  }
  const html = createEditorialPortfolio({ slug, name: entry.name, rows, credit: entry.credit });
  const embedded = Object.fromEntries(rows.map(row => [row.assetId, row.dataUrl]));
  const next = { ...node, data: { ...node.data, html, htmlAssets: embedded, imageAssetIds: rows.map(row => row.assetId), portfolioEdition: 2, portfolioExtraAssetIds: rows.filter(row => row.role === 'generated-editorial').map(row => row.assetId), portfolioSources: rows.map(({ file, title, role, sha256, assetId }) => ({ file, title, role, sha256, assetId })), productionNotes: '作品集依据现有资料重新编排。补充氛围图为图像模型生成；所有图纸、材质与制作参数仍需实物及打样核对。' } };
  const standalone = html.replace(/asset:\/\/([a-zA-Z0-9._-]+)/g, (match, id) => embedded[id] || match);
  if (/asset:\/\//.test(standalone)) throw new Error('独立页面仍有未解析图片引用。');
  await writeFile(join(output, `${slug}.html`), standalone);
  if (!localOnly) {
    const backup = join(output, 'backups'); await mkdir(backup, { recursive: true });
    // Unique backups preserve the original as well as each subsequent edit.
    await writeFile(join(backup, `${slug}-${Date.now()}.json`), JSON.stringify(node));
    if (node.data.html !== html || node.data.portfolioEdition !== 2) {
      await request(`${path}/canvas`, json({ upsertNodes: [next], upsertEdges: [], removeNodeIds: [], removeEdgeIds: [], expectedNodes: { [node.id]: { data: node.data, position: node.position } }, expectedEdges: {} }, 'PATCH'));
      const after = await request(`${path}/canvas`);
      if (after.nodes.length !== board.nodes.length || after.edges.length !== board.edges.length || after.nodes.find(n => n.id === node.id)?.data.html !== html) throw new Error('作品集保存核对失败。');
      const others = after.nodes.filter(n => n.id !== node.id);
      if (JSON.stringify(others) !== JSON.stringify(board.nodes.filter(n => n.id !== node.id))) throw new Error('其他节点意外改变。');
    }
  }
  console.log(`${entry.name}：${localOnly ? '已预览' : '已更新'}，${rows.length} 张图片，最终 HTML 节点 ${node.id}。`);
}
