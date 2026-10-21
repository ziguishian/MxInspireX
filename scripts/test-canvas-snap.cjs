// Pixel-level regression for node-frame alignment, using an isolated fixture API.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5304, strictPort: true, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/snap-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/snap-check', fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8')));
    });
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen();
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, 'http://127.0.0.1:5304/snap-check'], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1500, height: 1100, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code), q = JSON.stringify;
    const selector = (id, child) => `.vue-flow__node[data-id="${id}"] ${child}`;
    const box = (id, child = '.design-node-surface') => js(`(()=>{const r=document.querySelector(${q(selector(id, child))}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}})()`);
    const near = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1.2, `${message}: ${actual} vs ${expected}`);
    win.webContents.debugger.attach('1.3');
    const mouse = (type, x, y, held = false) => win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type, x, y, button: type === 'mouseMoved' && !held ? 'none' : 'left', buttons: type === 'mousePressed' || held ? 1 : 0, clickCount: type === 'mouseMoved' ? 0 : 1 });
    const image = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="350"><rect width="600" height="350" fill="#42573c"/><circle cx="300" cy="175" r="80" fill="#bbd77b"/></svg>');
    try {
      await win.loadURL(process.argv[2]); win.focus(); win.webContents.focus();
      for (let i = 0; i < 100 && !await js('!!window.ready'); i++) await pause(100);
      const checks = [];
      for (const zoom of [.45, .85, 1.4]) {
        await js('reset("image")'); await pause(100);
        await js(`state.board={nodes:[{id:'primary',type:'creative',position:{x:0,y:100},data:{kind:'image',title:'图像预览',localFile:${q(image)},asset:{mime:'image/png',metadata:{imageOutput:{warning:'图片说明和标题不应改变预览区域的吸附中心。'}}}}},{id:'neighbor',type:'creative',position:{x:510,y:90},data:{kind:'image',title:'新建图像节点',draft:true,previewSize:{width:350,height:255}}}],edges:[]};void 0`);
        await pause(850);
        await js(`document.querySelector('[aria-label="收起对话"]')?.click();select('primary');void 0`); await pause(300);
        // Deliberately different title heights expose offsets hidden by equal-size cards.
        await js(`document.querySelector(${q(selector('primary', 'header'))}).style.minHeight='50px';flow.setViewport({x:130,y:80,zoom:${zoom}});void 0`); await pause(200);
        const source = await box('primary'), target = await box('neighbor'), header = await box('primary', 'header');
        const start = { x: header.x + 35 * zoom, y: header.y + 10 * zoom };
        const end = { x: start.x + 31, y: start.y + target.cy - source.cy + 5 };
        await mouse('mouseMoved', start.x, start.y); await mouse('mousePressed', start.x, start.y);
        for (let i = 1; i <= 6; i++) { await mouse('mouseMoved', start.x + (end.x - start.x) * i / 6, start.y + (end.y - start.y) * i / 6, true); await pause(30); }
        await pause(120);
        const snapped = await box('primary'), stationary = await box('neighbor');
        near(snapped.cy, stationary.cy, `frame centers at ${zoom} zoom`);
        const guideY = await js(`(()=>{const line=[...document.querySelectorAll('.canvas-alignment-guides line')].find(l=>l.getAttribute('y1')===l.getAttribute('y2'));if(!line)return null;return new DOMPoint(Number(line.getAttribute('x1')),Number(line.getAttribute('y1'))).matrixTransform(line.getScreenCTM()).y})()`);
        assert.notEqual(guideY, null); near(guideY, snapped.cy, 'guide passes through preview center');
        if (zoom === .85) fs.writeFileSync('/tmp/aics-canvas-center-snap.png', (await win.webContents.capturePage()).toPNG());
        await mouse('mouseReleased', end.x, end.y); await pause(180);
        near((await box('primary')).cy, (await box('neighbor')).cy, 'center persists after drag');
        assert.equal(await js('document.querySelectorAll(".canvas-alignment-guides line").length'), 0);
        const saved = await js('JSON.parse(JSON.stringify(state.board))');
        await js(`state.board=${q(saved)};void 0`); await pause(120);
        near((await box('primary')).cy, (await box('neighbor')).cy, 'saved position retains center');
        checks.push(`preview-center snapping and guide at ${zoom} zoom, with title, warning and expanded prompt excluded`);
      }
      // Explicit alignment must translate frame coordinates back to node origins.
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='primary'?{...n,position:{...n.position,y:n.position.y-70}}:n)};void 0`);await pause(150);
      await js(`flow.addSelectedNodes([flow.findNode('primary'),flow.findNode('neighbor')]);document.querySelector('[aria-label="画布操作与快捷键"]').click();void 0`);await pause(100);
      await js(`[...document.querySelectorAll('.canvas-align-options button')].find(b=>b.textContent==='垂直居中').click()`);await pause(700);
      near((await box('primary')).cy, (await box('neighbor')).cy, 'alignment action centers content frames');
      checks.push('multi-node alignment uses the same preview geometry');
      assert.deepEqual(await js('window.errors'), []);
      console.log(JSON.stringify({ passed: true, checks })); win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); fs.writeFileSync('/tmp/aics-canvas-snap-error.png', (await win.webContents.capturePage()).toPNG()); win.destroy(); app.exit(1);
    }
  });
}
