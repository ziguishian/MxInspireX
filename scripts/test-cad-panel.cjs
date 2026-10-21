// Real Vue parameter panel + local API + native CAD worker. No model service.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const net = require('node:net'), listener = net.createServer();
    await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
    const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
    const directory = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'cad-panel-'));
    const python = process.env.AICS_PYTHON || path.join(root, 'services/api/.venv/bin/python');
    const api = spawn(python, ['-m', 'app.server', '--port', String(port)], { cwd: path.join(root, 'services/api'), env: { ...process.env, AICS_WORKSPACE_ROOT: directory, AICS_TEST_MODE: '1' }, stdio: ['ignore', 'ignore', 'pipe'] });
    let logs = ''; api.stderr.on('data', data => { logs = (logs + data).slice(-10000); });
    let server;
    try {
      const origin = `http://127.0.0.1:${port}`;
      const request = async (url, body) => {
        const response = await fetch(origin + url, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(10000) });
        const result = await response.json(); assert.ok(response.ok, JSON.stringify(result)); return result;
      };
      let ready = false;
      for (let i = 0; i < 100; i++) { try { await request('/api/projects'); ready = true; break; } catch { await pause(100); } }
      assert.ok(ready, logs);
      const project = await request('/api/projects', { name: 'CAD 参数面板测试', brief: '本地改参', budgetMinor: null, currency: 'CNY' });
      const base = `/api/projects/${project.id}`;
      let build = await request(base + '/cad/builds', {
        title: '带孔底座', source: 'result = cq.Workplane("XY").box(params["length"],50,8).faces(">Z").workplane().pushPoints([[-30,-15],[30,-15],[-30,15],[30,15]]).hole(5)',
        parameter_definitions: [{ name: 'length', label: '长度', type: 'number', default: 80, minimum: 70, maximum: 150 }],
        assumptions: ['孔距按示例设定，生产前需确认。'],
      });
      const deadline = Date.now() + 420000;
      while (!['succeeded', 'failed', 'cancelled'].includes(build.status) && Date.now() < deadline) { await pause(500); build = await request(base + '/cad/builds/' + build.id); }
      assert.equal(build.status, 'succeeded', JSON.stringify(build));
      const frontendListener = net.createServer();
      await new Promise(resolve => frontendListener.listen(0, '127.0.0.1', resolve));
      const frontendPort = frontendListener.address().port;
      await new Promise(resolve => frontendListener.close(resolve));
      const { createServer } = await import('vite');
      server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: frontendPort, strictPort: true, hmr: false, proxy: { '/api': origin } }, logLevel: 'error' });
      server.middlewares.use('/cad-panel-check', async (_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(await server.transformIndexHtml('/cad-panel-check', fs.readFileSync(path.join(__dirname, 'fixtures/cad-panel.html'), 'utf8'))); });
      await server.listen();
      const query = new URLSearchParams({ project: project.id, asset: build.result.assetId, node: build.result.node.id });
      const url = `http://127.0.0.1:${server.httpServer.address().port}/cad-panel-check?${query}`;
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => { const child = spawn(require('electron'), [__filename, url], { env, stdio: 'inherit' }); child.on('error', reject); child.on('exit', code => resolve(code ?? 1)); });
    } finally {
      await server?.close();
      api.kill('SIGTERM');
      await Promise.race([new Promise(resolve => api.once('exit', resolve)), pause(6000)]);
      if (api.exitCode === null) api.kill('SIGKILL');
      fs.rmSync(directory, { recursive: true, force: true });
    }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1200, height: 800, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code);
    const wait = async (code, limit = 30000) => { const end = Date.now() + limit; while (Date.now() < end) { if (await js(code).catch(() => false)) return; await pause(100); } throw new Error('Timeout: ' + code + '\n' + await js('document.body.innerText')); };
    try {
      await win.loadURL(process.argv[2]);
      await wait(`document.querySelector('.cad-parameter input')?.value === '80' && !!document.querySelector('.cad-detail-preview canvas')`);
      await wait(`!!document.querySelector('.cad-viewer-controls button')`);
      assert.equal(await js(`getComputedStyle(document.querySelector('.cad-viewer-controls button')).color`), 'rgb(37, 52, 72)');
      assert.ok(await js(`document.querySelector('.cad-detail').open`));
      await js(`const input=document.querySelector('.cad-parameter input');input.value='100';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.cad-parameters form').requestSubmit()`);
      await wait('window.fixture.updated === 1', 420000);
      assert.ok(await js(`document.querySelector('.cad-parameters').textContent.includes('100.00 × 50.00 × 8.00')`));
      await js(`document.querySelector('.cad-history button').click()`);
      await wait(`document.querySelectorAll('.cad-history option').length >= 3`);
      await js(`const select=document.querySelector('.cad-history select');select.value=select.options[select.options.length-1].value;select.dispatchEvent(new Event('change',{bubbles:true}))`);
      await js(`document.querySelectorAll('.cad-history button')[1].click()`);
      await wait('window.fixture.updated === 2');
      assert.equal(await js(`document.querySelector('.cad-parameter input').value`), '80');
      assert.equal(await js(`window.requests.filter(r=>r.method==='POST' && r.url.endsWith('/cad/builds')).length`), 1);
      assert.ok(await js(`window.requests.every(r=>!r.url.includes('/tasks') && !r.url.includes('/generations'))`));
      fs.mkdirSync(path.join(root, '.tmp'), { recursive: true });
      fs.writeFileSync(path.join(root, '.tmp/cad-panel.png'), (await win.webContents.capturePage()).toPNG());
      console.log(JSON.stringify({ passed: true, checks: ['actual Vue dialog', 'native parameter rebuild 80 -> 100 mm', 'version restore to 80 mm', 'no Agent task or model generation request'] }));
      app.exit(0);
    } catch (error) { console.error(error); app.exit(1); }
  });
}
