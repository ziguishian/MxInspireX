#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildBoard, validateBoard } from './showcase-board.mjs';

const assetsRoot = join(dirname(fileURLToPath(import.meta.url)), 'showcase-assets/ce-ma-v1');
export async function preflight() {
  const { version, case: entry } = JSON.parse(await readFile(join(assetsRoot, 'manifest.json'), 'utf8'));
  if (version !== 1 || entry.slug !== 'showcase-ce-ma' || entry.images.length !== 12) throw new Error('策马寻路清单不完整。');
  const seen = new Set(); const images = [];
  for (const image of entry.images) {
    if (!/^[a-z0-9-]+\.png$/.test(image.file) || seen.has(image.file) || !entry.groupDescriptions[image.group] || !['source', 'supplied-concept', 'generated'].includes(image.role)) throw new Error(`无效素材记录：${image.file}`);
    seen.add(image.file);
    const bytes = await readFile(join(assetsRoot, image.file));
    if (createHash('sha256').update(bytes).digest('hex') !== image.sha256 || !bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) || bytes.readUInt32BE(16) !== image.width || bytes.readUInt32BE(20) !== image.height) throw new Error(`素材校验失败：${image.file}`);
    images.push({ ...image, bytes });
  }
  for (const [role, count] of [['source', 2], ['supplied-concept', 6], ['generated', 4]]) if (images.filter(i => i.role === role).length !== count) throw new Error(`素材来源数量不符：${role}`);
  return { ...entry, images };
}

async function main() {
  const args = process.argv.slice(2); const option = (key, fallback = '') => { const index = args.indexOf(key); return index < 0 ? fallback : args[index + 1]; };
  const entry = await preflight();
  validateBoard(entry, buildBoard(entry, entry.images.map((_, i) => ({ id: `check-${i}`, metadata: {} }))));
  if (args.includes('--check')) { console.log('策马寻路预检通过：8 张用户资料、4 张生成图；顺序连续、布局无重叠。'); return; }
  if (!option('--workspace')) throw new Error('必须明确指定 --workspace。');
  const workspace = await realpath(resolve(option('--workspace'))); await stat(join(workspace, 'catalog.sqlite'));
  const api = option('--api', 'http://127.0.0.1:8765').replace(/\/$/, '');
  const request = async (path, init) => { const response = await fetch(api + path, init); if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`); return response.json(); };
  const json = (body, method = 'POST') => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const projects = await request('/api/projects');
  const anchor = projects.find(p => p.slug === 'showcase-ci');
  if (!anchor?.rootPath || await realpath(dirname(anchor.rootPath)) !== workspace) throw new Error('API 与指定演示工作区不一致，未写入。');
  let project = projects.find(p => p.slug === entry.slug);
  if (project) {
    if (!project.brief?.startsWith('已保存的演示案例：') || await realpath(dirname(project.rootPath)) !== workspace) throw new Error('同名项目不是本次演示数据。');
    const board = await request(`/api/projects/${project.id}/canvas`);
    if (board.nodes.length) {
      if (board.nodes.some(n => n.meta?.createdBy !== entry.createdBy)) throw new Error('目标画布含其他内容，已停止。');
      validateBoard(entry, board);
      const images = board.nodes.filter(n => n.data.kind === 'image');
      if (images.some((n, i) => n.data.showcaseProvenance?.sha256 !== entry.images[i].sha256)) throw new Error('已有画布内容与资料包不同，未覆盖。');
      console.log('策马寻路已完整导入，没有重复写入。'); return;
    }
  } else {
    project = await request('/api/projects', json({ name: entry.slug, brief: `已保存的演示案例：${entry.name}。六款系列视觉、两张产品资料与四张图像模型生成图；刀版及制作文件仅为模拟图像，参数需打样核对。` }));
    if (project.slug !== entry.slug) throw new Error('新建项目 slug 异常。');
    project = await request(`/api/projects/${project.id}`, json({ name: entry.name }, 'PUT'));
  }
  const path = `/api/projects/${project.id}`; const currentAssets = await request(`${path}/assets`); const assets = [];
  for (const image of entry.images) {
    const filename = `langju-ce-ma-v1-${image.file}`; let asset = currentAssets.find(a => a.metadata?.originalName === filename);
    if (asset && asset.sha256 !== image.sha256) throw new Error(`同名素材内容不同：${filename}`);
    if (!asset) {
      const form = new FormData(); form.append('kind', 'image'); form.append('file', new Blob([image.bytes], { type: 'image/png' }), filename); form.append('sourceCredit', entry.credit); form.append('sourceFile', image.sourceFile); form.append('sourceRole', image.role);
      asset = await request(`${path}/assets/upload`, { method: 'POST', body: form });
    }
    assets.push(asset);
  }
  const next = buildBoard(entry, assets); validateBoard(entry, next);
  await request(`${path}/canvas`, json({ upsertNodes: next.nodes, upsertEdges: [], removeNodeIds: [], removeEdgeIds: [], expectedNodes: Object.fromEntries(next.nodes.map(n => [n.id, null])), expectedEdges: {} }, 'PATCH'));
  validateBoard(entry, await request(`${path}/canvas`));
  console.log(`策马寻路已保存：${assets.length} 张图片、${next.nodes.length} 个节点，含模拟刀版、制作文件和作品集。`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
