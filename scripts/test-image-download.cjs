// Reproduce Chromium reusing a no-CORS image preview when saving the same URL.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/image-download-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const original = fs.readFileSync(path.join(root, 'apps/renderer/public/assets/home-design-examples-v1.png'));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const origin = 'http://127.0.0.1:5333';
    const media = require('node:http').createServer((req, res) => {
      if (req.url === '/fixed.png' || req.headers.origin) res.setHeader('Vary', 'Origin');
      if (req.headers.origin === origin) res.setHeader('Access-Control-Allow-Origin', origin);
      if (req.url === '/missing.png') { res.statusCode = 404; return res.end('missing'); }
      res.setHeader('Content-Type', 'image/png'); res.setHeader('Cache-Control', 'public, max-age=3600'); res.end(original);
    });
    await new Promise(resolve => media.listen(0, '127.0.0.1', resolve));
    const mediaBase = `http://127.0.0.1:${media.address().port}`;
    const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5333, strictPort: true, hmr: false }, logLevel: 'error' });
    const fixture = `<html><body><script type="module">
      import {exportNode} from '/src/nodeExport.ts';
      window.preview=name=>new Promise((resolve,reject)=>{const image=new Image();image.onload=resolve;image.onerror=reject;image.src=${JSON.stringify(mediaBase)}+'/'+name;document.body.append(image)});
      window.read=name=>fetch(${JSON.stringify(mediaBase)}+'/'+name).then(async response=>({ok:response.ok,size:(await response.blob()).size})).catch(error=>({error:error.name}));
      window.save=name=>exportNode({kind:'image',localFile:${JSON.stringify(mediaBase)}+'/'+name,title:name});window.ready=true;
    </script></body></html>`;
    server.middlewares.use('/image-download-check', async (_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(await server.transformIndexHtml('/image-download-check', fixture)); });
    await server.listen();
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); media.closeAllConnections(); media.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, partition: 'image-download-regression' } });
    const js = code => win.webContents.executeJavaScript(code, true), downloads = [];
    win.webContents.session.on('will-download', (_event, item) => {
      const file = path.join(output, item.getFilename()); item.setSavePath(file);
      item.once('done', (_event, state) => downloads.push({ file, state }));
    });
    try {
      await win.loadURL('http://127.0.0.1:5333/image-download-check');
      for (let i = 0; i < 100 && !await js('!!window.ready'); i++) await pause(50);
      await js("preview('legacy.png')");
      assert.equal((await js("read('legacy.png')")).error, 'TypeError', 'the old cached preview reproduces the CORS failure');
      await js("save('legacy.png')");
      for (let i = 0; i < 150 && !downloads.length; i++) await pause(50);
      assert.equal(downloads[0]?.state, 'completed');
      assert.deepEqual(fs.readFileSync(downloads[0].file), original, 'save bypasses the stale preview and preserves every original byte');
      await js("preview('fixed.png')");
      assert.deepEqual(await js("read('fixed.png')"), { ok: true, size: original.length }, 'Vary separates preview and fetch responses');
      assert.match(await js("save('missing.png').then(()=>'', error=>error.message)"), /文件不存在/);
      assert.equal(downloads.length, 1, 'a failed read must not download an error page');
      console.log(JSON.stringify({ passed: true, reproducedOldCorsFailure: true, originalBytes: original.length, checks: ['stale preview cache bypassed', 'Vary: Origin cache separation', 'missing file feedback'] }));
      win.destroy(); app.exit(0);
    } catch (error) { console.error(error); win.destroy(); app.exit(1); }
  });
}
