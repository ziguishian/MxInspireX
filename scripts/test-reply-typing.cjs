// Real Chromium/Vue rendering; all network and model calls are fixture-only.
const path = require('node:path'), fs = require('node:fs'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5298, strictPort: true, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/typing-check', async (_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(await server.transformIndexHtml('/typing-check', fs.readFileSync(path.join(__dirname, 'fixtures/reply-typing.html'), 'utf8'))); });
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen();
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, 'http://127.0.0.1:5298/typing-check'], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1440, height: 940, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code), q = JSON.stringify;
    const update = (text, status = 'running', animate = true) => js(`updateReply(${q(text)},${q(status)},${animate})`);
    const text = () => js(`latest()?.textContent.trim() || ''`);
    const waitFor = async check => { for (let i = 0; i < 160; i++) { if (await check()) return; await pause(25); } throw new Error('Timed out waiting for typing'); };
    try {
      await win.loadURL(process.argv[2]); await waitFor(() => js('window.ready'));
      assert.equal(await js(`document.querySelector('.design-message .agent-markdown').textContent.trim()`), '这是一条历史回复，打开页面时直接显示。');
      const first = '你好，我会先整理你的设计需求，再逐步完善视觉方案，让整个创作过程更清楚。';
      await update(first);
      const samples = await js(`new Promise(resolve=>{const values=[],end=performance.now()+650;function sample(){values.push(latest().textContent.trim().length);if(performance.now()<end)requestAnimationFrame(sample);else resolve(values)}sample()})`);
      assert.ok(samples[0] < first.length); assert.ok(new Set(samples).size > 12);
      assert.ok(samples.every((value, i) => i === 0 || value >= samples[i-1] && value - samples[i-1] <= 4));
      await waitFor(async () => await text() === first);
      await js(`window.firstParagraph=latest().querySelector('p');window.firstText=firstParagraph.firstChild;void 0`);
      const final = first + '\n\n## 方案重点\n\n**圆润**的造型，保持品牌一致。👩🏽‍💻\n\n- 配色清晰\n- 层次分明\n\n| 项目 | 内容 |\n| --- | --- |\n| 风格 | 简洁 |\n\n```js\nconst message = "你好";\n```';
      await update(final); await pause(150);
      const partial = await text();
      await update(final, 'succeeded'); await pause(30);
      assert.ok((await text()).length <= partial.length + 5, 'completion must drain the buffer, not flash the full answer');
      await waitFor(() => js(`latest().getAttribute('aria-busy') !== 'true'`));
      assert.equal(await js(`firstParagraph === latest().querySelector('p') && firstText === firstParagraph.firstChild`), true);
      for (const tag of ['h2', 'strong', 'ul', 'table', 'pre']) assert.equal(await js(`Boolean(latest().querySelector(${q(tag)}))`), true);
      assert.ok((await text()).includes('👩🏽‍💻'));
      console.log('PASS: 历史立即展示、连续逐字输出、结束后排空缓冲、Markdown 排版、已显示段落及文本节点保持稳定');
      await update('等待回复'.repeat(40)); await pause(70); await update('已停止生成。', 'cancelled', false); await pause(80);
      assert.equal(await text(), '已停止生成。'); assert.equal(await js(`latest().getAttribute('aria-busy')`), null);
      await update('后台回复'.repeat(40));
      await js(`Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))`); await pause(30);
      assert.equal(await text(), '后台回复'.repeat(40));
      await js(`Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))`);
      await js('longHistory()'); await pause(60);
      await update('正在持续输出。'.repeat(25)); await pause(90);
      await js(`document.querySelector('.design-chat-scroll').scrollTop=1;void 0`); await pause(250);
      assert.ok(await js(`document.querySelector('.design-chat-scroll').scrollTop < 5`), 'typing must not pull readers away from history');
      await js(`const scroll=document.querySelector('.design-chat-scroll');scroll.scrollTop=scroll.scrollHeight;void 0`); await pause(250);
      assert.ok(await js(`(()=>{const el=document.querySelector('.design-chat-scroll');return el.scrollHeight-el.scrollTop-el.clientHeight<3})()`));
      console.log('PASS: 停止立即显示、后台不积压动画、底部自动跟随、上翻阅读不抢滚动');
    } catch (error) { console.error(error); process.exitCode = 1; }
    finally { win.destroy(); app.exit(process.exitCode || 0); }
  });
}
