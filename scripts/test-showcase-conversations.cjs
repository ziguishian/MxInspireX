// Full-app regression: both showcase entrances share a narrative; saved tasks remain real.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/showcase-conversations');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const cases = [ ['showcase-ci', '瓷 · 德寿宫'], ['showcase-shan-ming', '山茗'], ['showcase-ce-ma', '策马寻路'], ['showcase-jin', '锦 · 宋锦葫芦'] ];
const projects = [...cases, ['ordinary', '普通项目']].map(([id, name]) => ({ id, slug: id, name, brief: id === 'ordinary' ? '' : '已保存的演示案例：' + name, status: 'draft', previewRevision: 'fixture-1', createdAt: '2026-10-13T00:00:00Z', updatedAt: '2026-10-13T00:00:00Z' }));
const boardFor = id => ({ nodes: [
  { id: 'intro-' + id, type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'text', title: '方案背景', text: '当前案例的已保存方案', showcaseRole: 'intro', showcaseOrder: 1, autoPositioned: false } },
  { id: 'image-' + id, type: 'creative', position: { x: 600, y: 0 }, data: { kind: 'image', title: '系列视觉', assetId: 'fixture-image', showcaseOrder: 2, autoPositioned: false } },
  { id: 'html-' + id, type: 'creative', position: { x: 0, y: 600 }, data: { kind: 'html', title: '最终作品集', html: '<main>最终汇报</main>', showcaseOrder: 3, autoPositioned: false } },
  { id: 'handoff-' + id, type: 'creative', position: { x: 1100, y: 600 }, data: { kind: 'text', title: '交付说明', text: '当前案例交付说明', showcaseRole: 'handoff', showcaseOrder: 4, autoPositioned: false } },
].map(node => id === 'ordinary' ? { ...node, data: { ...node.data, showcaseOrder: undefined } } : node), edges: [] });
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const { preview } = await import('vite');
    const server = await preview({ configFile: path.join(root, 'apps/renderer/vite.config.ts'), preview: { host: '127.0.0.1', port: 5391, strictPort: true } });
    let createdTasks = 0, changedCanvases = 0;
    const api = require('node:http').createServer((req, res) => {
      const p = new URL(req.url, 'http://fixture.invalid').pathname;
      if (req.method === 'POST' && /\/tasks$/.test(p)) createdTasks++;
      if (req.method !== 'GET' && req.method !== 'OPTIONS' && /\/canvas(?:\/|$)/.test(p)) changedCanvases++;
      res.setHeader('Access-Control-Allow-Origin', '*'); res.setHeader('Access-Control-Allow-Headers', '*'); res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, DELETE, OPTIONS');
      let data = [];
      const id = p.match(/^\/api\/projects\/([^/]+)/)?.[1];
      if (p === '/health') data = { status: 'ok' };
      else if (p === '/api/projects') data = projects;
      else if (id && p === '/api/projects/' + id) data = projects.find(project => project.id === id);
      else if (id && /\/(canvas|preview)$/.test(p)) data = boardFor(id);
      else if (id && /\/tasks$/.test(p)) data = id === 'showcase-ci' ? [{ id: 'real-task', projectId: id, agentKey: 'design', status: 'succeeded', userMessage: '请继续调整真实项目', createdAt: '2026-10-13T01:00:00Z', updatedAt: '2026-10-13T01:00:00Z', trace: [], output: { structured_data: { answer: '这是实际保存的追加对话。', deliveryStatus: 'passed' } } }] : [];
      else if (/models|catalog/.test(p)) data = { models: [], modelCatalog: [], configured: false };
      else if (/usage|credits/.test(p)) data = { points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 };
      else if (/delivery.*claim/.test(p)) data = null;
      else if (/assets\/fixture-image\/content$/.test(p)) { res.setHeader('Content-Type', 'image/png'); res.end(fs.readFileSync(path.join(root, 'apps/renderer/public/assets/home-design-examples-v1.png'))); return; }
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data));
    });
    try {
      await new Promise((resolve, reject) => { api.once('error', reject); api.listen(5392, '127.0.0.1', resolve); });
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => { const child = require('node:child_process').spawn(require('electron'), [__filename], { env, stdio: 'inherit' }); child.on('error', reject); child.on('exit', code => resolve(code ?? 1)); });
      assert.equal(createdTasks, 0, 'preview must not submit model tasks');
      assert.equal(changedCanvases, 0, 'preview must not persist board changes');
    } finally { await new Promise(resolve => server.httpServer.close(resolve)); api.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1440, height: 1000, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'showcase-conversation-fixture' } });
    win.webContents.session.webRequest.onBeforeRequest((details, callback) => {
      if (details.url.startsWith('http://127.0.0.1:8765/')) callback({ redirectURL: details.url.replace('127.0.0.1:8765', '127.0.0.1:5392') });
      else callback({ cancel: /^https?:/.test(details.url) && !/^http:\/\/127\.0\.0\.1:539[12]\//.test(details.url) });
    });
    const js = code => win.webContents.executeJavaScript(code);
    const wait = async (code, label) => { for (let i = 0; i < 100; i++) { if (await js(code).catch(() => false)) return; await pause(100); } throw new Error('Timeout: ' + label); };
    const click = async selector => { await wait(`!!document.querySelector(${JSON.stringify(selector)})`, selector); await js(`document.querySelector(${JSON.stringify(selector)}).click()`); };
    const checkSaved = async (id, name) => {
      const count = id === 'showcase-ci' ? 12 : 10;
      await wait(`document.querySelectorAll('.design-message').length===${count}`, name + ' full conversation');
      const result = await js(`(()=>{const messages=[...document.querySelectorAll('.design-message')];return {messages:messages.map(m=>m.innerText),nodes:document.querySelectorAll('.vue-flow__node').length,realTasks:messages.filter(m=>m.dataset.taskId==='real-task').length,previewTasks:messages.slice(0,10).filter(m=>m.dataset.taskId).length}})()`);
      assert.equal(result.nodes, 4, name + ' keeps complete board');
      assert(result.messages[9].includes('展示页面与交付说明已呈现完成'));
      assert.equal(result.previewTasks, 0);
      assert.equal(result.realTasks, id === 'showcase-ci' ? 2 : 0);
      if (id === 'showcase-ci') assert(result.messages[11].includes('实际保存的追加对话'));
      fs.writeFileSync(path.join(output, id + '.png'), (await win.webContents.capturePage()).toPNG());
    };
    try {
      for (const [id, name] of cases) {
        await win.loadURL('http://127.0.0.1:5391/projects');
        await click(`[aria-label="打开项目 ${name}"]`);
        await checkSaved(id, name);
      }
      await win.loadURL('http://127.0.0.1:5391/projects/showcase-ci'); await checkSaved('showcase-ci', '直达链接');
      await win.loadURL('http://127.0.0.1:5391/projects/ordinary');
      await wait('!!document.querySelector(".design-workspace")', 'ordinary project');
      assert.equal(await js('document.querySelectorAll(".design-message").length'), 0);
      await win.loadURL('http://127.0.0.1:5391/');
      await click('.example-artwork[aria-label^="打开瓷"]');
      await wait('document.querySelectorAll(".design-message").length===4', 'home staged conversation');
      assert.equal(await js('document.querySelectorAll(".vue-flow__node").length'), 1);
      await click('[aria-label="项目"]');
      await click('[aria-label="打开项目 瓷 · 德寿宫"]'); await checkSaved('showcase-ci', '离开回放后再次进入');
      await win.loadFile(process.env.AICS_SHOWCASE_RENDERER_ENTRY || path.join(root, 'dist/renderer/index.html'));
      await click('[aria-label="项目"]');
      await click('[aria-label="打开项目 锦 · 宋锦葫芦"]'); await checkSaved('showcase-jin', '桌面入口');
      win.reload(); await checkSaved('showcase-jin', '桌面刷新');
      console.log(JSON.stringify({ passed: true, checks: ['four project-list entrances show complete conversations', 'real history remains after preview', 'direct links and desktop reload restore preview', 'home still stages playback', 'ordinary project stays empty', 'no task creation or canvas writes'], screenshots: output }));
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); console.error(win.webContents.getURL()); console.error(await js('document.body.innerText.slice(-1800)').catch(() => ''));
      fs.writeFileSync(path.join(output, 'error.png'), (await win.webContents.capturePage()).toPNG()); win.destroy(); app.exit(1);
    }
  });
}
