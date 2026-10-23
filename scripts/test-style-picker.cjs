// Test the real production bundles. All API data is isolated from user projects.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { preview } = await import('vite');
    const server = await preview({ configFile: path.join(root, 'apps/renderer/vite.config.ts'), preview: { host: '127.0.0.1', port: 5316, strictPort: true } });
    const api = require('node:http').createServer((req, res) => {
      const p = new URL(req.url, 'http://fixture.invalid').pathname;
      const project = { id: 'style-fixture', name: '风格预览验证', status: 'draft' };
      let data = [];
      if (p === '/health') data = { status: 'ok' };
      else if (p === '/api/projects') data = [project];
      else if (p === '/api/projects/style-fixture') data = project;
      else if (/\/(canvas|preview)$/.test(p)) data = { nodes: [], edges: [] };
      else if (/models|catalog/.test(p)) data = { models: [], modelCatalog: [], configured: false };
      else if (/usage|credits/.test(p)) data = { points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 };
      else if (/delivery.*claim/.test(p)) data = null;
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS' });
      res.end(JSON.stringify(data));
    });
    try {
      await new Promise((resolve, reject) => { api.once('error', reject); api.listen(5317, '127.0.0.1', resolve); });
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await new Promise(resolve => server.httpServer.close(resolve)); api.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: true, width: 1280, height: 960, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'style-picker-fixture' } });
    const js = code => win.webContents.executeJavaScript(code);
    const wait = async code => { for (let i = 0; i < 100; i++) { if (await js(code).catch(() => false)) return; await pause(60); } throw new Error('Timeout: ' + code); };
    let blockImages = false;
    const failedImages = [];
    win.webContents.session.webRequest.onBeforeRequest((details, callback) => {
      if (details.url.includes('style-references/') && blockImages) return callback({ cancel: true });
      if (details.url.startsWith('http://127.0.0.1:8765/')) return callback({ redirectURL: details.url.replace('127.0.0.1:8765', '127.0.0.1:5317') });
      if (/^https?:/.test(details.url) && !/^http:\/\/127.0.0.1:531[67]\//.test(details.url)) return callback({ cancel: true });
      callback({});
    });
    win.webContents.session.webRequest.onErrorOccurred(details => { if (!blockImages && details.url.includes('style-references/')) failedImages.push(details.url); });
    const open = async () => {
      await wait(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='风格')`);
      await js(`[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='风格').click()`);
      await wait(`document.querySelector('.style-picker-dialog')?.open`);
    };
    const loaded = () => wait(`document.querySelectorAll('.style-preview-image img.is-loaded').length===9 && [...document.querySelectorAll('.style-preview-image img')].every(i=>i.complete && i.naturalWidth>0 && i.naturalHeight>0)`);
    const close = async () => { await js(`document.querySelector('.style-picker-close').click()`); await wait(`!document.querySelector('.style-picker-dialog').open`); };
    const checks = [];
    try {
      for (const mode of ['desktop', 'web']) {
        if (mode === 'desktop') await win.loadFile(path.join(root, 'dist/renderer/index.html'));
        else await win.loadURL('http://127.0.0.1:5316/projects/style-fixture');
        await pause(1500); await open(); await loaded(); await pause(500);
        const tiles = await js(`[...document.querySelectorAll('.style-preview-image img')].map(i=>{const p=i.parentElement.getBoundingClientRect(),r=i.getBoundingClientRect();return {width:r.width/p.width,height:r.height/p.height,x:(p.x-r.x)/p.width,y:(p.y-r.y)/p.height,src:i.currentSrc,opacity:getComputedStyle(i).opacity}})`);
        tiles.forEach((tile, i) => {
          assert.ok(Math.abs(tile.width - 1) < .01 && Math.abs(tile.height - 1) < .01);
          assert.ok(Math.abs(tile.x) < .01 && Math.abs(tile.y) < .01);
          assert.equal(tile.opacity, '1'); assert.ok(!tile.src.includes('/assets/assets/'));
          assert.ok(tile.src.startsWith(mode === 'desktop' ? 'file://' : 'http://127.0.0.1:5316/assets/'));
        });
        if (mode === 'desktop') fs.writeFileSync(path.join(root,'.tmp/style-picker-desktop.png'), (await win.webContents.capturePage()).toPNG());
        await js(`document.querySelectorAll('.style-preview-card')[2].click()`);
        await wait(`!document.querySelector('.style-picker-dialog').open`);
        await open(); await loaded();
        assert.equal(await js(`document.querySelector('.style-preview-card[aria-pressed="true"] strong').textContent`), '宋韵雅集');
        assert.equal(await js(`document.querySelectorAll('.style-preview-card[aria-pressed="true"]').length`), 1);
        await close();
        checks.push(mode + ': nine distinct image crops load; selection survives reopening');
      }
      win.setContentSize(390, 844); await open(); await loaded(); await pause(200);
      assert.ok(await js(`(()=>{const d=document.querySelector('.style-picker-dialog');return d.scrollWidth<=d.clientWidth+1 && d.getBoundingClientRect().width<=innerWidth && getComputedStyle(document.querySelector('.style-picker-grid')).gridTemplateColumns.split(' ').length===2})()`));
      fs.writeFileSync(path.join(root,'.tmp/style-picker-mobile.png'), (await win.webContents.capturePage()).toPNG());
      await close(); checks.push('mobile: two columns without horizontal overflow');
      win.setContentSize(1280, 960);
      blockImages = true; await win.webContents.session.clearCache();
      await win.loadFile(path.join(root, 'dist/renderer/index.html')); await open();
      await wait(`document.querySelectorAll('.style-preview-placeholder').length===9 && !!document.querySelector('.style-preview-error button')`);
      blockImages = false; await js(`document.querySelector('.style-preview-error button').click()`); await loaded();
      assert.equal(await js(`!!document.querySelector('.style-preview-error')`), false);
      await close(); await open();
      await js(`document.querySelector('.style-picker-dialog').dispatchEvent(new Event('cancel',{cancelable:true}))`);
      await wait(`!document.querySelector('.style-picker-dialog').open`);
      assert.deepEqual(failedImages, []);
      checks.push('desktop: blocked images show feedback, retry restores all nine, Escape closes');
      console.log(JSON.stringify({ passed: true, checks }, null, 2));
    } catch (error) {
      console.error(error); process.exitCode = 1;
      fs.writeFileSync(path.join(root,'.tmp/style-picker-error.png'), (await win.webContents.capturePage()).toPNG());
    } finally { win.destroy(); app.exit(process.exitCode || 0); }
  });
}
