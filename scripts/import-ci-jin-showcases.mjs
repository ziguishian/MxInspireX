#!/usr/bin/env node
/** Import the user-supplied porcelain and brocade cases without model calls. */
import { createHash } from 'node:crypto';
import { readFile, realpath, stat, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const assetsRoot = join(root, 'showcase-assets/ci-jin-v1');
export const manifest = JSON.parse(await readFile(join(assetsRoot, 'manifest.json'), 'utf8'));
import { buildBoard, validateBoard } from './showcase-board.mjs';
export { buildBoard, validateBoard } from './showcase-board.mjs';
export async function preflight() {
  if (manifest.version !== 1 || manifest.cases.length !== 2) throw new Error('案例清单无效。');
  const cases = [];
  for (const entry of manifest.cases) {
    if (!['ci', 'jin'].includes(entry.key) || entry.slug !== `showcase-${entry.key}` || entry.images.length !== (entry.key === 'ci' ? 16 : 14)) throw new Error('案例数量或 slug 不正确。');
    const seen = new Set(); const images = [];
    for (const image of entry.images) {
      if (!/^(?:ci|jin)-\d{2}\.(?:png|jpg)$/.test(image.file) || seen.has(image.file) || !['实拍起点', '器型与材质', '系列与织纹', '结构与细节', '包装与礼赠'].includes(image.group) || !['photo', 'concept'].includes(image.role)) throw new Error(`素材记录无效：${image.file}`);
      seen.add(image.file);
      const bytes = await readFile(join(assetsRoot, image.file));
      const digest = createHash('sha256').update(bytes).digest('hex');
      if (digest !== image.sha256 || image.width < 300 || image.height < 300) throw new Error(`素材未通过核对：${image.file}`);
      images.push({ ...image, bytes });
    }
    if (images.filter(image => image.role === 'photo').length !== 2) throw new Error('每案需要两张原始实拍。');
    cases.push({ ...entry, images });
  }
  return cases;
}

async function main() {
  const args = process.argv.slice(2); const option = (key, fallback = '') => { const i = args.indexOf(key); return i < 0 ? fallback : args[i + 1]; };
  const cases = await preflight();
  for (const entry of cases) validateBoard(entry, buildBoard(entry, entry.images.map((image, i) => ({ id: `check-${i}`, metadata: {} }))));
  if (args.includes('--check')) { console.log('瓷与锦预检通过：30 张原图、连续回放顺序、无重叠布局。未写入工作区。'); return; }
  if (!option('--workspace')) throw new Error('必须通过 --workspace 指定演示工作区。');
  const workspace = await realpath(resolve(option('--workspace'))); await stat(join(workspace, 'catalog.sqlite'));
  const api = option('--api', 'http://127.0.0.1:8765').replace(/\/$/, '');
  const request = async (path, init) => { const response = await fetch(api + path, init); if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`); return response.json(); };
  const json = (body, method = 'POST') => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const projects = await request('/api/projects');
  const anchor = projects.find(project => project.slug === 'showcase-shan-ming');
  if (!anchor?.rootPath || await realpath(dirname(anchor.rootPath)) !== workspace) throw new Error('API 与指定演示工作区不一致，未修改。');
  // Validate both existing destinations before making any mutations.
  const destinations = [];
  for (const entry of cases) {
    const project = projects.find(p => p.slug === entry.slug);
    if (project && (!project.brief?.startsWith('已保存的演示案例：') || await realpath(dirname(project.rootPath)) !== workspace)) throw new Error('同名项目不是本次演示数据，已停止。');
    const board = project ? await request(`/api/projects/${project.id}/canvas`) : null;
    if (board?.nodes.length && (board.nodes.some(n => n.meta?.createdBy !== 'ci-jin-import') || board.nodes.length !== entry.images.length + new Set(entry.images.map(i => i.group)).size + 4)) throw new Error('目标画布已有其他内容或不完整，已停止。');
    destinations.push({ entry, project, board });
  }
  for (const destination of destinations) {
    const { entry, board } = destination; let { project } = destination;
    if (board?.nodes.length) { console.log(`${entry.name}已导入，没有重复写入。`); continue; }
    if (!project) {
      project = await request('/api/projects', json({ name: entry.slug, brief: `已保存的演示案例：${entry.name}。两张实拍与${entry.images.length - 2}张概念设计资料；模拟对话仅作展示，尺寸与工艺待打样复核。` }));
      if (project.slug !== entry.slug) throw new Error('新项目 slug 不符合预期。');
      project = await request(`/api/projects/${project.id}`, json({ name: entry.name }, 'PUT'));
    }
    const path = `/api/projects/${project.id}`; const savedAssets = await request(`${path}/assets`); const assets = [];
    for (const image of entry.images) {
      const filename = `langju-ci-jin-v1-${image.file}`; let asset = savedAssets.find(a => a.metadata?.originalName === filename);
      if (asset && asset.sha256 !== image.sha256) throw new Error(`同名资产内容不同：${filename}`);
      if (!asset) {
        const form = new FormData(); form.append('kind', 'image'); form.append('file', new Blob([image.bytes], { type: image.file.endsWith('.jpg') ? 'image/jpeg' : 'image/png' }), filename); form.append('sourceFile', image.sourceFile); form.append('sourceCredit', entry.credit); form.append('sourceRole', image.role);
        asset = await request(`${path}/assets/upload`, { method: 'POST', body: form });
      }
      assets.push(asset);
    }
    const next = buildBoard(entry, assets); validateBoard(entry, next);
    const backupRoot = resolve(option('--backup-dir', join(root, '../.tmp/ci-jin/import-backups'))); await mkdir(backupRoot, { recursive: true });
    await writeFile(join(backupRoot, `${entry.slug}-before.json`), JSON.stringify(board || { nodes: [], edges: [] }));
    await request(`${path}/canvas`, json({ upsertNodes: next.nodes, upsertEdges: [], removeNodeIds: [], removeEdgeIds: [], expectedNodes: Object.fromEntries(next.nodes.map(n => [n.id, null])), expectedEdges: {} }, 'PATCH'));
    const saved = await request(`${path}/canvas`); validateBoard(entry, saved);
    console.log(`${entry.name}：${saved.nodes.length} 个节点，${assets.length} 张原图，作品集已保存。`);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
