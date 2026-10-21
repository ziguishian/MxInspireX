// Real Chromium navigation gestures, isolated from user projects and models.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5332, strictPort: true, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/overview-check', async (_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(await server.transformIndexHtml('/overview-check', fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8'))); });
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen();
      process.exitCode = await new Promise((resolve, reject) => { const child = require('node:child_process').spawn(require('electron'), [__filename], { env, stdio: 'inherit' }); child.on('error', reject); child.on('exit', code => resolve(code ?? 1)); });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1500, height: 1050, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'canvas-overview-fixture' } });
    const js = code => win.webContents.executeJavaScript(code), q = JSON.stringify;
    const rect = selector => js(`(()=>{const r=document.querySelector(${q(selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}})()`);
    const viewport = () => js('JSON.parse(JSON.stringify(flow.viewport.value))');
    const board = () => js('JSON.parse(JSON.stringify(state.board))');
    const near = (a, b, label) => assert.ok(Math.abs(a - b) < 1.5, label + ': ' + a + ' vs ' + b);
    const key = async keyCode => { win.webContents.sendInputEvent({ type: 'keyDown', keyCode }); win.webContents.sendInputEvent({ type: 'keyUp', keyCode }); await pause(160); };
    win.webContents.debugger.attach('1.3');
    const mouse = (type, x, y, held = false, count = 1, button = 'left') => win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type, x, y, button: type === 'mouseMoved' && !held ? 'none' : button, buttons: type === 'mousePressed' || held ? (button === 'right' ? 2 : 1) : 0, clickCount: type === 'mouseMoved' ? 0 : count });
    const clickAt = async point => { await mouse('mousePressed', point.x, point.y); await mouse('mouseReleased', point.x, point.y); await pause(160); };
    const click = async selector => { const r = await rect(selector); await clickAt({ x: r.x + r.width / 2, y: r.y + r.height / 2 }); };
    const screenPoint = point => js(`(()=>{const svg=document.querySelector('.canvas-overview svg'),p=svg.createSVGPoint();p.x=${point.x};p.y=${point.y};const r=p.matrixTransform(svg.getScreenCTM());return {x:r.x,y:r.y}})()`);
    const checks = [];
    try {
      await win.loadURL('http://127.0.0.1:5332/overview-check'); win.focus(); win.webContents.focus();
      for (let i = 0; i < 100 && !await js('!!window.ready'); i++) await pause(50);
      await js(`window.patchCount=0;const fixtureFetch=window.fetch;window.fetch=(url,options={})=>{if(options.method==='PATCH')patchCount++;return fixtureFetch(url,options)};
        state.epoch++;state.board={nodes:[{id:'a',position:{x:0,y:0},data:{kind:'image',title:'礼盒主视觉',draft:true}},{id:'b',position:{x:3000,y:2200},data:{kind:'text',title:'设计说明',text:'设计说明'}},{id:'c',position:{x:-1200,y:-900},data:{kind:'html',title:'方案网页',html:'<h1>方案</h1>'}}],edges:[{id:'ab',source:'a',target:'b'}]};void 0`);
      await pause(850); await js(`document.querySelector('[aria-label="收起对话"]')?.click();select('a');void 0`); await pause(200);
      assert.equal(await js(`document.querySelectorAll('.canvas-overview-node').length`), 3);
      assert.equal(await js(`document.querySelectorAll('.canvas-overview-edge').length`), 1);
      assert.equal(await js(`document.querySelector('.canvas-overview-toggle').getAttribute('aria-expanded')`), 'true');
      const toggle = await rect('.canvas-overview-toggle'), help = await rect('.support-fab'), map = await rect('.canvas-overview');
      near(toggle.right + 12, help.x, 'toggle immediately left of help'); near(toggle.y + toggle.height / 2, help.y + help.height / 2, 'controls share the same center line');
      assert.ok(map.bottom < toggle.y, 'overview above the corner controls');
      await js('flow.setViewport({x:100,y:100,zoom:1});void 0'); await pause(150);
      assert.ok(await js(`document.querySelector('.canvas-overview-node[data-node-id="a"]').classList.contains('selected')`));
      const before = await board();
      const destination = await js(`(()=>{const n=flow.findNode('b');return {x:n.position.x+n.dimensions.width/2,y:n.position.y+n.dimensions.height/2}})()`);
      await clickAt(await screenPoint(destination));
      let view = await viewport();
      near((1500 / 2 - view.x) / view.zoom, destination.x, 'click centers viewport horizontally');
      const canvasHeight = await js('document.querySelector(".design-canvas-area").clientHeight');
      near((canvasHeight / 2 - view.y) / view.zoom, destination.y, 'click centers viewport vertically');
      assert.equal(view.zoom, 1, 'navigation preserves zoom');
      const area = await js(`(()=>{const r=document.querySelector('.canvas-overview-viewport');return Object.fromEntries(['x','y','width','height'].map(k=>[k,Number(r.getAttribute(k))]))})()`);
      near(area.x, -view.x, 'visible range x'); near(area.width, 1500, 'visible range width');
      const start = await screenPoint({ x: area.x + area.width / 2, y: area.y + area.height / 2 });
      const units = await js(`(()=>{const m=document.querySelector('.canvas-overview svg').getScreenCTM();return {x:1/m.a,y:1/m.d}})()`);
      await mouse('mousePressed', start.x, start.y);
      for (let i = 1; i <= 8; i++) { await mouse('mouseMoved', start.x + 12 * i / 8, start.y + 8 * i / 8, true); await pause(20); }
      await mouse('mouseReleased', start.x + 12, start.y + 8); await pause(200);
      const moved = await viewport(); near(moved.x, view.x - 12 * units.x, 'viewport drag x'); near(moved.y, view.y - 8 * units.y, 'viewport drag y');
      await key('Right'); view = await viewport(); near(view.x, moved.x - 80, 'overview keyboard navigates view');
      assert.deepEqual(await board(), before, 'overview navigation never moves nodes');
      assert.deepEqual(await js('flow.getSelectedNodes.value.map(n=>n.id)'), ['a'], 'overview preserves selection');
      assert.equal(await js('patchCount'), 0, 'navigation never writes the board');
      assert.ok(await js(`!document.querySelector('.vue-flow__selection')`), 'overview cannot start a marquee');
      const center = await rect('.canvas-overview svg');
      await mouse('mousePressed', center.x + 5, center.y + 5, false, 2); await mouse('mouseReleased', center.x + 5, center.y + 5, false, 2); await pause(100);
      assert.ok(await js(`!document.querySelector('.canvas-action-menu')`), 'double-click does not create a node');
      await mouse('mousePressed', center.x + 5, center.y + 5, false, 1, 'right'); await mouse('mouseReleased', center.x + 5, center.y + 5, false, 1, 'right');
      assert.ok(await js(`!document.querySelector('.canvas-context-menu')`), 'overview does not open canvas menu');
      checks.push('all nodes and edges, selected highlighting, current viewport, click/drag/keyboard navigation without selection or document edits');
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='b'?{...n,position:{x:3400,y:2600}}:n)};void 0`); await pause(160);
      near(await js(`Number(document.querySelector('.canvas-overview-node[data-node-id="b"]').getAttribute('x'))`), 3400, 'live node changes update overview');
      await click('.canvas-overview-toggle'); assert.ok(await js(`!document.querySelector('.canvas-overview')`));
      assert.equal(await js(`localStorage.getItem('langjuart.canvasOverviewVisible')`), 'false');
      await js('state.epoch++;void 0'); await pause(750); assert.ok(await js(`!document.querySelector('.canvas-overview')`), 'hidden preference survives remount');
      await click('.canvas-overview-toggle'); assert.ok(await js(`!!document.querySelector('.canvas-overview')`));
      await js(`document.querySelector('.canvas-overview svg').focus();void 0`); await key('Escape');
      assert.ok(await js(`!document.querySelector('.canvas-overview') && document.activeElement.classList.contains('canvas-overview-toggle')`));
      await click('.canvas-overview-toggle');
      checks.push('live positions, persistent show/hide toggle, Escape closes and restores focus');
      for (const [width, theme] of [[1500, 'dark'], [780, 'light'], [390, 'light']]) {
        win.setContentSize(width, 1000); await js(`document.documentElement.dataset.theme='${theme}';document.querySelector('[aria-label="收起对话"]')?.click();void 0`); await pause(450);
        const overview = await rect('.canvas-overview'), controls = await rect('.canvas-toolbar-actions'), composer = await rect('.intake-composer');
        assert.ok(overview.x >= 0 && overview.right <= width && overview.y >= 0, 'overview fits at ' + width);
        assert.ok(controls.x >= 0 && controls.right <= width, 'controls fit at ' + width);
        assert.ok(overview.right <= composer.x || overview.x >= composer.right || overview.bottom <= composer.y || overview.y >= composer.bottom, 'overview does not cover composer at ' + width);
        assert.ok(await js(`(()=>{const el=document.querySelector('.canvas-overview-toggle'),r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})()`));
        fs.writeFileSync(`/private/tmp/aics-canvas-overview-${width}.png`, (await win.webContents.capturePage()).toPNG());
      }
      await js('state.epoch++;state.board={nodes:[],edges:[]};void 0'); await pause(350);
      assert.equal(await js(`document.querySelectorAll('.canvas-overview-node').length`), 0);
      assert.ok(await js(`!document.querySelector('.canvas-overview svg').getAttribute('viewBox').match(/NaN|Infinity/)`));
      assert.deepEqual(await js('window.errors'), []);
      checks.push('dark/light themes, 390px layout without composer overlap, empty canvas');
      console.log(JSON.stringify({ passed: true, checks }, null, 2));
    } catch (error) { console.error(error); fs.writeFileSync('/private/tmp/aics-canvas-overview-error.png', (await win.webContents.capturePage()).toPNG()); process.exitCode = 1; }
    finally { win.destroy(); app.exit(process.exitCode || 0); }
  });
}
