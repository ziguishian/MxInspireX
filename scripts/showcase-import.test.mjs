import { test } from 'vitest';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { copyFile, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(await readFile(join(scripts, 'showcase-assets/manifest.json'), 'utf8'));
const importer = join(scripts, 'import-showcase-additions.mjs');
const fixturePng = join(scripts, '../apps/renderer/public/assets/langju-logo-dark.png');

function run(args) {
  return new Promise(resolveRun => {
    const child = spawn(process.execPath, [importer, ...args], { cwd: resolve(scripts, '..') });
    let output = '';
    child.stdout.on('data', data => { output += data; });
    child.stderr.on('data', data => { output += data; });
    child.on('close', code => resolveRun({ code, output }));
  });
}

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'langju-showcase-test-'));
  const assets = join(root, 'reviewed');
  await mkdir(join(assets, 'clean'), { recursive: true });
  await writeFile(join(assets, 'manifest.json'), JSON.stringify(manifest));
  const populate = async () => {
    for (const entry of manifest.cases) for (const photo of entry.images) await copyFile(fixturePng, join(assets, 'clean', photo.file));
  };
  return { root, assets, populate };
}

test('showcase import refuses incomplete reviewed assets before contacting an API', async () => {
  const f = await fixture();
  try {
    const result = await run(['--assets-root', f.assets, '--workspace', join(f.root, 'wrong'), '--api', 'http://127.0.0.1:1']);
    assert.equal(result.code, 2);
    assert.match(result.output, /16\/16 张去水印成品未验收/);
    await f.populate();
    const checked = await run(['--assets-root', f.assets, '--check']);
    assert.equal(checked.code, 0, checked.output);
    assert.match(checked.output, /全部 16 张修整成品已就绪/);
  } finally { await rm(f.root, { recursive: true, force: true }); }
});

test.skipIf(process.env.AICS_SHOWCASE_IMPORT_INTEGRATION !== '1')('showcase import is idempotent, keeps references separate, and spaces photo nodes', async () => {
  const f = await fixture();
  const workspace = join(f.root, 'workspace');
  await mkdir(workspace);
  await writeFile(join(workspace, 'catalog.sqlite'), 'test-only');
  await f.populate();
  const projects = new Map();
  const assets = new Map();
  const boards = new Map();
  const metrics = { projects: 0, uploads: 0, patches: 0 };
  let supportsProvenance = true;
  const seed = async slug => {
    const rootPath = join(workspace, slug);
    await mkdir(rootPath);
    const id = slug;
    const project = { id, slug, name: slug, rootPath };
    projects.set(id, project);
    assets.set(id, []);
    const node = (id, role, order, x, y, kind = 'text') => ({ id, type: 'creative', position: { x, y }, data: { kind, title: role, text: role, html: '<body></body>', showcaseRole: role, showcaseOrder: order } });
    boards.set(id, { nodes: slug === 'showcase-shan-yan' ? [node('intro', 'intro', 1, 0, -900), node('engineering', 'engineering', 18, 0, 1200), node('marketing', 'marketing', 19, 720, 1200), node('portfolio', 'html', 20, 0, 1950, 'html'), node('handoff', 'handoff', 21, 1120, 1950)] : [node('intro', 'intro', 1, 0, 0), node('portfolio', 'html', 20, 0, 1950, 'html')], edges: [] });
  };
  for (const slug of ['showcase-shan-yan', 'showcase-song-yun', 'showcase-yun-zi-wu-xin', 'showcase-yun-jin-xu']) await seed(slug);
  const respond = (response, status, value) => { response.writeHead(status, { 'content-type': 'application/json' }); response.end(JSON.stringify(value)); };
  const body = async request => { let text = ''; for await (const chunk of request) text += chunk; return JSON.parse(text); };
  const server = createServer(async (request, response) => {
    try {
      const path = new URL(request.url, 'http://localhost').pathname;
      if (path === '/openapi.json') return respond(response, 200, { paths: { '/api/projects/{project_id}/assets/upload': { post: { requestBody: { content: { 'multipart/form-data': { schema: { properties: supportsProvenance ? { sourceCredit: {}, sourceFile: {}, sourceRole: {} } : { kind: {} } } } } } } } } });
      if (path === '/api/projects' && request.method === 'GET') return respond(response, 200, [...projects.values()]);
      if (path === '/api/projects' && request.method === 'POST') {
        const input = await body(request);
        const project = { id: input.name, slug: input.name, name: input.name, brief: input.brief, rootPath: join(workspace, input.name) };
        await mkdir(project.rootPath);
        projects.set(project.id, project); assets.set(project.id, []); boards.set(project.id, { nodes: [], edges: [] }); metrics.projects += 1;
        return respond(response, 201, project);
      }
      const match = /^\/api\/projects\/([^/]+)(?:\/(.*))?$/.exec(path);
      const id = decodeURIComponent(match?.[1] || '');
      if (!projects.has(id)) return respond(response, 404, {});
      if (!match[2] && request.method === 'PUT') { Object.assign(projects.get(id), await body(request)); return respond(response, 200, projects.get(id)); }
      if (match[2] === 'assets' && request.method === 'GET') return respond(response, 200, assets.get(id));
      if (match[2] === 'assets/upload' && request.method === 'POST') {
        const form = await new Request('http://localhost' + path, { method: 'POST', headers: request.headers, body: request, duplex: 'half' }).formData();
        const file = form.get('file');
        const bytes = Buffer.from(await file.arrayBuffer());
        const asset = { id: `${id}-asset-${assets.get(id).length + 1}`, projectId: id, kind: 'image', pathRelative: `assets/${file.name}`, mime: 'image/png', sha256: createHash('sha256').update(bytes).digest('hex'), metadata: { originalName: file.name, sourceCredit: form.get('sourceCredit'), sourceFile: form.get('sourceFile'), sourceRole: form.get('sourceRole') } };
        assets.get(id).push(asset); metrics.uploads += 1;
        return respond(response, 201, asset);
      }
      if (match[2] === 'canvas' && request.method === 'GET') return respond(response, 200, boards.get(id));
      if (match[2] === 'canvas' && request.method === 'PATCH') {
        const patch = await body(request);
        const board = boards.get(id);
        for (const node of patch.upsertNodes) {
          const index = board.nodes.findIndex(item => item.id === node.id);
          if (index < 0) board.nodes.push(node); else board.nodes[index] = { ...board.nodes[index], ...node };
        }
        metrics.patches += 1;
        return respond(response, 200, board);
      }
      return respond(response, 404, {});
    } catch (error) { return respond(response, 500, { error: String(error) }); }
  });
  try {
    await new Promise(resolveListen => server.listen(0, '127.0.0.1', resolveListen));
    const url = `http://127.0.0.1:${server.address().port}`;
    const args = ['--assets-root', f.assets, '--workspace', workspace, '--cover-root', join(f.root, 'covers'), '--api', url];
    const wrongWorkspace = join(f.root, 'wrong-workspace');
    await mkdir(wrongWorkspace);
    await writeFile(join(wrongWorkspace, 'catalog.sqlite'), 'test-only');
    const wrongTarget = await run(args.map((part, index) => args[index - 1] === '--workspace' ? wrongWorkspace : part));
    assert.equal(wrongTarget.code, 1);
    assert.match(wrongTarget.output, /工作区与 --workspace 不一致/);
    supportsProvenance = false;
    const oldApi = await run(args);
    assert.equal(oldApi.code, 1);
    assert.match(oldApi.output, /API 尚不支持素材来源字段/);
    assert.deepEqual(metrics, { projects: 0, uploads: 0, patches: 0 });
    supportsProvenance = true;
    const first = await run(args);
    assert.equal(first.code, 0, first.output);
    assert.equal(metrics.projects, 3);
    assert.equal(metrics.uploads, 16);
    assert.equal(metrics.patches, 5);
    const songYun = boards.get('showcase-song-yun').nodes;
    assert.equal(songYun.filter(node => node.data.showcaseRole === 'reference' && node.data.kind === 'image').length, 3);
    assert.ok(songYun.filter(node => node.data.showcaseRole === 'reference').every(node => node.data.showcaseOrder === undefined));
    const shanYanPhotos = boards.get('showcase-shan-yan').nodes.filter(node => node.meta?.createdBy === 'showcase-import' && node.data.kind === 'image');
    assert.equal(shanYanPhotos.length, 6);
    for (let i = 0; i < shanYanPhotos.length; i++) for (let j = i + 1; j < shanYanPhotos.length; j++) {
      const a = shanYanPhotos[i]; const b = shanYanPhotos[j];
      assert.ok(a.position.x + a.data.previewSize.width <= b.position.x || b.position.x + b.data.previewSize.width <= a.position.x || a.position.y + a.data.previewSize.height <= b.position.y || b.position.y + b.data.previewSize.height <= a.position.y);
    }
    for (const slug of ['showcase-de-shou-gong', 'showcase-ma-ti', 'showcase-song-jin']) {
      const board = boards.get(slug);
      assert.ok(board.nodes.some(node => node.data.showcaseRole === 'engineering' && node.data.html.includes('NOT FOR PRODUCTION')));
      assert.ok(board.nodes.some(node => node.data.showcaseRole === 'html' && node.data.html.includes('影像来源')));
    }
    const snapshot = { ...metrics };
    const second = await run(args);
    assert.equal(second.code, 0, second.output);
    assert.deepEqual(metrics, snapshot);
  } finally {
    await new Promise(resolveClose => server.close(resolveClose));
    await rm(f.root, { recursive: true, force: true });
  }
}, 30_000);
