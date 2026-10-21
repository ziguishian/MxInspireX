// Exercise the real built App against an isolated API; never call a model.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/first-request-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const project = { id: 'first-request-fixture', name: '灵感启程', brief: '设计一张春日海报', status: 'draft', slug: 'first-request-fixture', createdAt: new Date().toISOString() };
    let created = false, pending, tasks = [], mode = 'hold';
    const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' }); res.end(JSON.stringify(data)); };
    const complete = (res, body) => {
      if (mode === 'reject') return json(res, { detail: '暂时无法接收请求，请重试。' }, 503);
      const task = { id: `request-${tasks.length + 1}`, projectId: project.id, status: 'succeeded', agentKey: 'design', userMessage: body.brief, trace: [], output: { structured_data: { answer: '已收到你的灵感，创作继续。' } } };
      tasks.push(task); json(res, task);
    };
    const server = require('node:http').createServer(async (req, res) => {
      const url = new URL(req.url, 'http://fixture.invalid'), p = url.pathname;
      if (req.method === 'OPTIONS') return json(res, {});
      if (p === '/fixture/state') return json(res, { pending: !!pending, created, count: tasks.length });
      if (p === '/fixture/mode') {
        mode = url.searchParams.get('value');
        if (pending) { complete(...pending); pending = undefined; }
        return json(res, {});
      }
      if (p === '/api/intake') { created = true; return json(res, { project, files: [] }); }
      if (p === `/api/projects/${project.id}/tasks` && req.method === 'POST') {
        let body = ''; for await (const chunk of req) body += chunk;
        if (mode === 'hold') pending = [res, JSON.parse(body)]; else complete(res, JSON.parse(body));
        return;
      }
      if (p === '/health') return json(res, { status: 'ok' });
      if (p === '/api/providers') return json(res, [{ key: 'openrouter', label: 'Fixture', configured: true, available: true }]);
      if (p === '/api/providers/model-catalog') return json(res, { models: ['fixture-text'], textModels: ['fixture-text'], modelCatalog: [{ id: 'fixture-text', kinds: ['text'] }] });
      if (p === '/api/model-settings') return json(res, { credits: { sellCnyPerCredit: .1, cnyPerUsd: 7 }, media: { image: { standard: '' }, video: { standard: '' } } });
      if (p === '/api/projects') return json(res, created ? [project] : []);
      if (p === `/api/projects/${project.id}`) return json(res, project);
      if (p.endsWith('/tasks')) return json(res, tasks);
      if (/\/(canvas|preview)$/.test(p)) return json(res, { nodes: [], edges: [] });
      if (/usage|credits/.test(p)) return json(res, { points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 });
      if (/delivery.*claim/.test(p)) return json(res, null);
      json(res, []);
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
    const win = new BrowserWindow({ show: false, width: 1280, height: 900, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'first-request-fixture' } });
    const base = `http://127.0.0.1:${process.argv[2]}`;
    win.webContents.session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] }, (details, callback) => {
      if (details.url.startsWith('http://127.0.0.1:8765/')) callback({ redirectURL: details.url.replace('http://127.0.0.1:8765', base) });
      else callback({ cancel: !details.url.startsWith(base + '/') });
    });
    const js = code => win.webContents.executeJavaScript(code, true);
    const wait = async (check, label) => { for (let i = 0; i < 100; i++) { if (await check()) return; await pause(80); } throw new Error('Timeout: ' + label); };
    const query = code => () => js(code).catch(() => false);
    const send = async text => {
      await wait(query('document.querySelector(".intake-composer-editor")'), 'composer');
      await js(`(()=>{const el=document.querySelector('.intake-composer-editor');el.focus();el.textContent=${JSON.stringify(text)};el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));})()`);
      await wait(query('!document.querySelector(".composer-send").disabled'), 'ready to send');
      await js('document.querySelector(".composer-send").click()');
    };
    const fixture = path => fetch(base + path).then(res => res.json());
    const visible = () => js('!!document.querySelector(".first-request-card")');
    try {
      await win.loadFile(path.join(root, 'dist/renderer/index.html'));
      await wait(query('!!document.querySelector(".home-intake")'), 'homepage');
      await js("localStorage.setItem('langjuart.firstUseCompleted','true')");
      await send('设计一张春日海报');
      await wait(async () => (await fixture('/fixture/state')).pending, 'request in flight');
      assert.equal(await visible(), false, 'intake creation and pending POST must not celebrate');
      assert.equal(await js("localStorage.getItem('langjuart.firstRequestCelebrated')"), null);
      await fixture('/fixture/mode?value=reject');
      await wait(query('!!document.querySelector(".toast-error")'), 'submission rejected');
      assert.equal(await visible(), false, 'failed submission does not consume the first request');
      await fixture('/fixture/mode?value=accept');
      await js("document.querySelectorAll('.toast button').forEach(button=>button.click())");
      await send('设计一张春日海报');
      await wait(visible, 'first accepted request');
      await wait(query('document.body.textContent.includes("已收到你的灵感，创作继续。")'), 'task continues under celebration');
      assert.equal(await js("localStorage.getItem('langjuart.firstRequestCelebrated')"), 'true');
      assert.equal(await js("document.querySelector('.first-request-card').contains(document.activeElement)"), false, 'no focus stealing');
      assert.equal(await js("getComputedStyle(document.querySelector('.first-request-celebration')).pointerEvents"), 'none');
      await js("document.documentElement.dataset.theme='dark'"); await pause(250);
      const darkBackground = await js("getComputedStyle(document.querySelector('.first-request-card')).backgroundImage");
      fs.writeFileSync(path.join(output, 'dark.png'), (await win.webContents.capturePage()).toPNG());
      await js("document.documentElement.dataset.theme='light'"); await pause(80);
      assert.notEqual(await js("getComputedStyle(document.querySelector('.first-request-card')).backgroundImage"), darkBackground);
      fs.writeFileSync(path.join(output, 'light.png'), (await win.webContents.capturePage()).toPNG());
      await wait(async () => !await visible(), 'automatic dismissal');
      await send('继续完善海报');
      await wait(async () => (await fixture('/fixture/state')).count === 2, 'second request');
      assert.equal(await visible(), false, 'later requests do not repeat');
      win.reload(); await pause(400); await wait(query('!!document.querySelector(".design-workspace")'), 'restored project');
      await send('再微调字体');
      await wait(async () => (await fixture('/fixture/state')).count === 3, 'after reload');
      assert.equal(await visible(), false, 'reload keeps the first-request flag');
      // A fresh profile sending directly in an existing project uses the same entry point.
      await js("localStorage.removeItem('langjuart.firstRequestCelebrated')");
      await win.webContents.debugger.attach('1.3');
      await win.webContents.debugger.sendCommand('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
      win.reload(); await pause(400); await wait(query('!!document.querySelector(".design-workspace")'), 'existing project');
      await send('完善版式'); await wait(visible, 'first request in existing project');
      assert.equal(await js("getComputedStyle(document.querySelector('.first-request-confetti')).display"), 'none');
      assert.equal(await js("getComputedStyle(document.querySelector('.first-request-card')).animationName"), 'none');
      await js("window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))");
      await wait(async () => !await visible(), 'Escape dismisses');
      console.log(JSON.stringify({ passed: true, checks: ['only accepted requests celebrate', 'failed/pending sends do not consume first-use state', 'legacy intake flag does not suppress the corrected first-send event', 'task continues without focus stealing', 'auto-dismiss and Escape', 'once across repeat sends and reload', 'existing project entry point', 'reduced motion', 'dark/light screenshots'] }));
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); console.error(await js('document.body.innerText.slice(-1000)').catch(() => ''));
      fs.writeFileSync(path.join(output, 'error.png'), (await win.webContents.capturePage()).toPNG()); win.destroy(); app.exit(1);
    }
  });
}
