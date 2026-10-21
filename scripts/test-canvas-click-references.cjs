// Built App + real pointer gestures. API, assets, storage and tasks are isolated.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/canvas-click-references-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const project = { id: 'canvas-click-fixture', name: '画布点击引用测试', brief: '', status: 'draft', slug: 'canvas-click-fixture', createdAt: '2026-10-10T01:00:00Z' };
    const assets = ['image-a', 'image-b', 'manual'].map(id => ({ id, kind: 'image', pathRelative: `assets/${id}.png`, mime: 'image/png', byteSize: 100, projectId: project.id }));
    const board = { nodes: [
      ...assets.slice(0, 2).map((asset, index) => ({ id: `node-${asset.id}`, type: 'creative', position: { x: index * 340, y: 0 }, data: { kind: 'image', title: asset.id, assetId: asset.id, asset, previewSize: { width: 240, height: 180 } } })),
      { id: 'text-node', type: 'creative', position: { x: 0, y: 310 }, data: { kind: 'text', title: '文字方案', text: '这是一份文字方案。', previewSize: { width: 240, height: 160 } } },
    ], edges: [] };
    const png = fs.readFileSync(path.join(root, 'apps/renderer/public/assets/lumo-composer-mountain-cloud-v2.png'));
    const posts = [], tasks = [];
    const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' }); res.end(JSON.stringify(data)); };
    const server = require('node:http').createServer(async (req, res) => {
      const p = new URL(req.url, 'http://fixture.invalid').pathname;
      if (req.method === 'OPTIONS') return json(res, {});
      if (p === '/fixture/posts') return json(res, posts);
      if (p.endsWith('/tasks') && req.method === 'POST') {
        let raw = ''; for await (const chunk of req) raw += chunk;
        const body = JSON.parse(raw); posts.push(body);
        const task = { id: `fixture-task-${posts.length}`, agentKey: 'design', userMessage: body.brief, status: 'succeeded', createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), references: body.input, trace: [], output: { structured_data: { answer: '已收到引用。', deliveryStatus: 'passed' } } };
        tasks.unshift(task); return json(res, task);
      }
      if (p.endsWith('/content')) { res.writeHead(200, { 'Content-Type': 'image/png', 'Access-Control-Allow-Origin': '*' }); return res.end(png); }
      if (p === '/health') return json(res, { status: 'ok' });
      if (p === '/api/providers') return json(res, [{ key: 'openrouter', label: 'Fixture', configured: true, available: true }]);
      if (p === '/api/providers/model-catalog') return json(res, { models: ['fixture-text'], textModels: ['fixture-text'], modelCatalog: [{ id: 'fixture-text', kinds: ['text'] }] });
      if (p === '/api/model-settings') return json(res, { credits: { sellCnyPerCredit: .1, cnyPerUsd: 7 }, media: { image: { standard: '' }, video: { standard: '' } } });
      if (p === '/api/projects') return json(res, [project]);
      if (p === `/api/projects/${project.id}`) return json(res, project);
      if (p.endsWith('/tasks')) return json(res, tasks);
      if (p.endsWith('/events')) return json(res, {}, 503);
      if (/\/tasks\/[^/]+$/.test(p)) return json(res, tasks[0]);
      if (/\/(canvas|preview)$/.test(p)) return json(res, board);
      if (p.endsWith('/assets')) return json(res, assets);
      if (/usage|credits/.test(p)) return json(res, { points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 });
      if (/delivery.*claim/.test(p)) return json(res, null);
      return json(res, []);
    });
    try {
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, String(server.address().port)], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { server.closeAllConnections(); server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1500, height: 1100, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'canvas-click-references-fixture' } });
    const base = `http://127.0.0.1:${process.argv[2]}`;
    win.webContents.session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] }, (details, callback) => {
      if (details.url.startsWith('http://127.0.0.1:8765/')) callback({ redirectURL: details.url.replace('http://127.0.0.1:8765', base) });
      else callback({ cancel: !details.url.startsWith(base + '/') });
    });
    const errors = [];
    win.webContents.on('console-message', details => { if (details.level === 'error' && /Uncaught|Unhandled|Vue warn/.test(details.message)) errors.push(details.message); });
    const js = code => win.webContents.executeJavaScript(code, true), q = JSON.stringify;
    const wait = async code => { for (let i = 0; i < 120; i++) { if (await js(code).catch(() => false)) return; await pause(60); } throw new Error('Timeout: ' + code); };
    const editor = '.intake-composer-editor';
    const draft = () => js(`document.querySelector(${q(editor)}).dataset.renderedText`);
    const setDraft = async text => { await js(`(()=>{const el=document.querySelector(${q(editor)});el.focus();el.textContent=${q(text)};el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));})()`); await wait(`document.querySelector(${q(editor)}).dataset.renderedText===${q(text)}`); };
    const point = selector => js(`(()=>{const el=document.querySelector(${q(selector)}),r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2; if(!el.contains(document.elementFromPoint(x,y)))throw new Error('Covered click target: '+${q(selector)});return {x,y};})()`);
    win.webContents.debugger.attach('1.3');
    const mouse = (type, p, held = false) => win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type, x: p.x, y: p.y, button: type === 'mouseMoved' && !held ? 'none' : 'left', buttons: type === 'mousePressed' || held ? 1 : 0, clickCount: type === 'mouseMoved' ? 0 : 1 });
    const clickPoint = async p => { await mouse('mouseMoved', p); await mouse('mousePressed', p); await mouse('mouseReleased', p); await pause(180); };
    const click = async selector => clickPoint(await point(selector));
    const node = id => `.vue-flow__node[data-id="${id}"] .design-node-surface`;
    const blankPoint = () => js(`(()=>{const r=document.querySelector('.vue-flow__pane').getBoundingClientRect(),left=Math.max(r.left+20,document.querySelector('.design-chat-panel').getBoundingClientRect().right+20);for(let y=r.top+90;y<r.bottom-100;y+=50)for(let x=left;x<r.right-60;x+=50){const el=document.elementFromPoint(x,y);if(el?.classList.contains('vue-flow__pane'))return {x,y};}throw new Error('No blank canvas point');})()`);
    const blank = async () => clickPoint(await blankPoint());
    const checks = [];
    try {
      await win.loadFile(path.join(root, 'dist/renderer/index.html')); win.focus(); win.webContents.focus();
      await wait("!!document.querySelector('.home-intake')");
      await js("localStorage.setItem('langjuart.firstRequestCelebrated','true');document.querySelector('.sidebar-nav-item[aria-label=项目]').click()");
      await wait("!!document.querySelector('.project-card')"); await click('.project-card');
      await wait("document.querySelectorAll('.vue-flow__node').length===3 && !!document.querySelector('.intake-composer-editor')");
      await pause(900);
      await js("document.querySelector('[aria-label=\"隐藏画布观察视图\"]')?.click()");
      const original = '保留原有需求  ';
      await setDraft(original); await click(node('node-image-a'));
      assert.ok((await draft()).includes('@asset:image-a'));
      await blank(); assert.equal(await draft(), original, 'blank restores original text, including whitespace');
      checks.push('image click followed by blank cancels only the automatic reference');
      await click(node('text-node')); assert.ok((await draft()).includes('@node:text-node'));
      await blank(); assert.equal(await draft(), original);
      checks.push('text-node references use the same cancellation rule');
      await click(node('node-image-a')); await click(node('node-image-b'));
      assert.ok((await draft()).includes('@asset:image-a') && (await draft()).includes('@asset:image-b'));
      await blank(); assert.equal(await draft(), original);
      checks.push('consecutive asset clicks accumulate and blank cancels the batch');
      await click(node('node-image-a')); await click(node('node-image-a'));
      assert.equal((await draft()).match(/@asset:image-a/g).length, 1);
      await blank(); assert.equal(await draft(), original);
      await click(node('node-image-a')); await click(editor);
      const confirmed = await draft(); await blank(); assert.equal(await draft(), confirmed);
      await click(node('node-image-b')); await blank(); assert.equal(await draft(), confirmed);
      checks.push('clicking the composer confirms references; later blank clicks preserve them');
      const manual = '手动引用 @asset:manual 保留这句话';
      await setDraft(manual);
      await js(`(()=>{const input=document.querySelector('.file-tool input[type=file]'),dt=new DataTransfer();dt.items.add(new File(['fixture'],'保留附件.txt',{type:'text/plain'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
      await wait("!!document.querySelector('[aria-label=\"移除附件 保留附件.txt\"]')");
      await click(node('node-image-b')); await blank();
      assert.equal(await draft(), manual);
      assert.ok(await js("!!document.querySelector('[aria-label=\"移除附件 保留附件.txt\"]')"));
      assert.ok(await js("!!document.querySelector('.intake-composer-editor [data-reference-key=\"asset:manual\"]')"));
      checks.push('manual references, original text and attachments survive cancellation');
      await click(node('text-node'));
      const dragStart = await blankPoint(), dragEnd = { x: dragStart.x + 25, y: dragStart.y + 25 };
      const beforeDrag = await draft();
      await mouse('mousePressed', dragStart); await mouse('mouseMoved', dragEnd, true); await mouse('mouseReleased', dragEnd); await pause(180);
      assert.equal(await draft(), beforeDrag, 'a marquee drag is not a blank click');
      await blank(); assert.equal(await draft(), manual);
      checks.push('blank drag selects without cancelling references');
      await click('[aria-label="移除附件 保留附件.txt"]');
      await click('.composer-send');
      let posts; for (let i = 0; i < 100; i++) { posts = await fetch(base + '/fixture/posts').then(res => res.json()); if (posts.length) break; await pause(60); }
      assert.equal(posts.length, 1);
      assert.equal(posts[0].brief, manual);
      assert.deepEqual(posts[0].input.referencedAssets.map(asset => asset.id), ['manual']);
      assert.deepEqual(posts[0].input.referencedNodes, []);
      checks.push('submitted task contains no cancelled asset or node references');
      assert.deepEqual(errors, []);
      fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(checks, null, 2));
      console.log('PASS canvas click references\n' + checks.map(check => '- ' + check).join('\n'));
    } catch (error) {
      fs.writeFileSync(path.join(output, 'failure.png'), (await win.webContents.capturePage()).toPNG());
      console.error(error); process.exitCode = 1;
    } finally { win.destroy(); app.quit(); }
  });
}
