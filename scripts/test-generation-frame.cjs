// Real Vue Flow: requested aspect ratios survive loading and media replacement.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/generation-frame-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5373, strictPort: false, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/frame-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/frame-check', fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8')));
    });
    try {
      await server.listen();
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, `http://127.0.0.1:${server.httpServer.address().port}/frame-check`], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1700, height: 1100, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code, true);
    const wait = async (code, label) => {
      for (let i = 0; i < 120; i++) { if (await js(code)) return; await pause(50); }
      throw new Error(`Timeout: ${label}`);
    };
    const near = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1.1, `${label}: ${actual} ≠ ${expected}`);
    const measure = () => js(`(() => {
      const root = document.querySelector('.vue-flow__node[data-id="primary"]');
      const surface = root.querySelector('.design-node-surface'), stack = root.querySelector('.canvas-node-stack');
      const rect = surface.getBoundingClientRect(), zoom = flow.viewport.value.zoom;
      const handle = root.querySelector('.vue-flow__handle-right').getBoundingClientRect();
      return {width:rect.width/zoom,height:rect.height/zoom,outerWidth:stack.getBoundingClientRect().width/zoom,
        handleY:(handle.y+handle.height/2-rect.y)/zoom,loading:!!surface.querySelector('.design-media-loading')};
    })()`);
    const frame = async (width, height, loading) => {
      const actual = await measure();
      near(actual.width, width, 'surface width'); near(actual.height, height, 'surface height');
      near(actual.outerWidth, width, 'outer node width'); near(actual.handleY, height / 2, 'connection center');
      assert.equal(actual.loading, loading); return actual;
    };
    try {
      await win.loadURL(process.argv[2]); await wait('!!window.ready', 'fixture');
      await js(`window.setData = async data => {
        state.board = {nodes:[{id:'primary',type:'creative',position:{x:0,y:0},data:{kind:'image',title:'生成图像',previewSizingVersion:2,...data}}],edges:[]};
        await new Promise(requestAnimationFrame);
      };
      window.completeImage = async (width,height,metadata=true) => {
        const raster=document.createElement('canvas');raster.width=width;raster.height=height;
        const ctx=raster.getContext('2d');ctx.fillStyle='#154c48';ctx.fillRect(0,0,width,height);
        ctx.fillStyle='#e6ec87';ctx.font='bold 64px sans-serif';ctx.fillText(width+' × '+height,40,100);
        await setData({...state.board.nodes[0].data,generating:false,localFile:raster.toDataURL('image/png'),asset:{mime:'image/png',metadata:metadata?{imageOutput:{width,height}}:{}}});
      };void 0;`);
      const cases = [
        { name: 'square', params: { aspectRatio: '1:1' }, pixels: [1024, 1024], size: [720, 720] },
        { name: 'portrait-size', params: { size: '1024x1536', aspectRatio: '16:9' }, pixels: [1024, 1536], size: [720, 1080] },
        { name: 'portrait-snake', params: { aspect_ratio: '9:16' }, pixels: [864, 1536], size: [608, 1080] },
        { name: 'portrait-four-five', params: { size: '1216x1520' }, pixels: [1216, 1520], size: [720, 900] },
        { name: 'landscape', params: { size: '1536x864' }, pixels: [1536, 864], size: [720, 405] },
      ];
      for (const sample of cases) {
        await js(`setData({generating:true,params:${JSON.stringify(sample.params)}})`);
        await wait('!!document.querySelector(".design-media-loading")', sample.name + ' loading');
        await pause(200); await frame(...sample.size, true);
        if (sample.name === 'portrait-snake') fs.writeFileSync(path.join(output, 'portrait-loading.png'), (await win.webContents.capturePage()).toPNG());
        await js(`completeImage(${sample.pixels.join(',')})`);
        await wait('!document.querySelector(".design-media-loading") && !!document.querySelector(".design-node-surface img")?.naturalWidth', sample.name + ' complete');
        await pause(200); await frame(...sample.size, false);
      }
      // Change the requested ratio on an already decoded landscape node.
      await js(`setData({...state.board.nodes[0].data,generating:true,params:{aspect_ratio:'9:16'}})`);
      await wait('!!document.querySelector(".design-media-loading")', 'edit loading'); await pause(150);
      await frame(608, 1080, true);
      await js('completeImage(864,1536,false)');
      await wait('!document.querySelector(".design-media-loading")', 'edit complete'); await pause(150);
      await frame(608, 1080, false);
      assert.equal(await js('!!document.querySelector("button[title=将节点调整为推荐尺寸，可撤销]")'), false, 'portrait already at recommended size');
      // The loading indicator remains readable in a zoomed-out overview.
      await js(`setData({generating:true,params:{aspectRatio:'4:5'}})`);
      await pause(500); await js('select()'); await pause(300);
      assert.match(await js('document.querySelector(".canvas-prompt-panel").textContent'),/4:5/, 'node controls retain the requested ratio');
      const loadingInfo = () => js(`(() => {
        const root=document.querySelector('.vue-flow__node[data-id="primary"]'),dots=root.querySelector('.design-media-dots'),copy=root.querySelector('.design-media-loading-copy > span:last-child');
        return {icon:dots.getBoundingClientRect().width,text:parseFloat(getComputedStyle(copy).fontSize)*Number(getComputedStyle(root.querySelector('.design-media-loading')).getPropertyValue('--loading-scale'))*flow.viewport.value.zoom,
          grid:[...root.querySelectorAll('.design-loading-grid i')].slice(0,4).map(i=>({transform:getComputedStyle(i).transform,animation:getComputedStyle(i).animationName})),orbit:getComputedStyle(dots).animationName};
      })()`);
      for (const zoom of [.35,.5,1]) {
        await js(`flow.setViewport({x:720,y:150,zoom:${zoom}}).then(()=>undefined)`); await pause(250);
        const info=await loadingInfo();
        assert.ok(info.icon>=50 && info.text>=15, 'loading remains legible at '+zoom);
      }
      await js('flow.setViewport({x:720,y:100,zoom:.65}).then(()=>undefined)'); await pause(300);
      const beforeWave=await loadingInfo(); await pause(400); const afterWave=await loadingInfo();
      assert.notEqual(beforeWave.grid[0].transform,afterWave.grid[0].transform,'grid moves over time');
      assert.notEqual(afterWave.grid[0].transform,afterWave.grid[1].transform,'columns move in staggered waves');
      fs.writeFileSync(path.join(output,'loading-wave-dark.png'),(await win.webContents.capturePage()).toPNG());
      await js("document.documentElement.dataset.theme='light'"); await pause(150);
      fs.writeFileSync(path.join(output,'loading-wave-light.png'),(await win.webContents.capturePage()).toPNG());
      win.webContents.debugger.attach('1.3');
      await win.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
      const reduced=await loadingInfo();
      assert.equal(reduced.orbit,'none'); assert.ok(reduced.grid.every(i=>i.animation==='none'),'reduced motion disables waves');
      await win.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',{features:[]});win.webContents.debugger.detach();
      // Uploaded/automatic images have no stored dimensions: decoded width must reach the outer frame too.
      await js(`setData({params:{size:'auto'}});completeImage(600,1800,false)`);
      await wait('document.querySelector(".design-node-surface img")?.naturalHeight===1800 && !document.querySelector(".design-media-loading")', 'automatic output');
      await pause(150); await frame(360, 1080, false);
      // A user-resized frame remains intentional through another generation.
      await js(`setData({...state.board.nodes[0].data,generating:true,params:{size:'1024x1024'},previewSize:{width:500,height:320}})`);
      await wait('!!document.querySelector(".design-media-loading")', 'custom frame loading'); await frame(500, 320, true);
      await js('completeImage(1024,1024)'); await wait('!document.querySelector(".design-media-loading")', 'custom frame complete');
      await frame(500, 320, false);
      assert.deepEqual(await js('window.errors'), []);
      console.log(JSON.stringify({ passed: true, checks: ['square, landscape and portrait loading/finished dimensions', 'effective size overrides inherited ratio', 'editing ignores the old image ratio', 'decoded dimensions reach outer node and connections', 'readable loading at 35%, 50%, 100% zoom', 'staggered background waves and reduced motion', 'automatic output adopts actual ratio', 'manual frame survives generation'] }));
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); fs.writeFileSync(path.join(output, 'error.png'), (await win.webContents.capturePage()).toPNG());
      win.destroy(); app.exit(1);
    }
  });
}
