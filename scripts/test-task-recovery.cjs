const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ configFile: path.join(root, 'apps/renderer/vite.config.ts'), appType: 'custom',
      server: { host: '127.0.0.1', port: 5393, strictPort: false, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/task-recovery', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      const html = fs.readFileSync(path.join(__dirname, 'fixtures/task-recovery.html'), 'utf8');
      res.end(await server.transformIndexHtml('/task-recovery', html));
    });
    try {
      await server.listen();
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, `http://127.0.0.1:${server.httpServer.address().port}/task-recovery`], { env, stdio: 'inherit' });
        child.once('error', reject); child.once('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
    win.webContents.on('console-message', event => { if (event.level === 'error') console.error(event.message); });
    const js = code => win.webContents.executeJavaScript(code, true);
    const button = `document.querySelector('[aria-label="取回原媒体"] button')`;
    async function wait(code) {
      for (let i = 0; i < 120; i++) { if (await js(code)) return; await new Promise(resolve => setTimeout(resolve, 50)); }
      throw new Error(`Timeout: ${code}`);
    }
    try {
      await win.loadURL(process.argv[2]);
      await wait(`!!${button} && !${button}.disabled`);
      for (const status of ['running', 'queued', 'cancelled']) {
        await js(`state.status=${JSON.stringify(status)};state.epoch++;void 0`);
        await wait(`!!${button} && ${button}.disabled`);
        await js(`${button}.click()`);
        assert.equal(await js('posts.length'), 0);
      }
      await js(`state.status='failed';state.epoch++;void 0`);
      await wait(`!!${button} && !${button}.disabled`);
      await js(`${button}.click();${button}.click()`);
      await wait('recovered === 1');
      assert.deepEqual(await js('posts'), ['http://fixture.invalid/api/projects/fixture/tasks/task/image-results/original/recover']);
      await wait(`!${button}`);
      assert.equal(await js('saved'), true);
      console.log('PASS: recovery state guards, double click, saved result and no generation request');
      app.exit(0);
    } catch (error) { console.error(error); app.exit(1); }
  });
}
