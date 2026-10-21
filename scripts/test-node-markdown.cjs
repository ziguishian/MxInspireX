// Real canvas regression: document rendering, scrolling, source editing and download.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const output = path.join(root, '.tmp/node-markdown-check');
const source = [
  '# 经博会贵宾定向礼盒',
  '概念说明与预算边界',
  '## 一、设计定位',
  '本礼盒定位为**贵宾／领导定向礼**，核心主题为“和光同尘·赴自在”。整体气质稳重、正式、克制，以杭州自然与人文意象建立地域文化识别度。',
  '> 以下为概念级方案，具体结构、材料和工艺待打样确认。',
  '## 二、礼盒视觉与六色关系',
  '- **外盒方向**：暖米与深色基底为主，辅以低对比水纹与桂枝纹样。\n- **开盒方向**：采用分区内衬，呈现东方生活场景。\n  - 桂金：标题、细线及局部工艺点缀\n  - 湖青：水纹与内衬分区\n  - 竹青：自然意象表达',
  '## 三、交付清单',
  '| 交付内容 | 用途 | 状态 |\n| --- | --- | --- |\n| 礼盒效果图 | 展示整体视觉 | 已完成 |\n| 包装结构图 | 打样沟通 | 待核实 |',
  '1. 确认礼盒内容与数量\n2. 确认材料和工艺\n3. 完成打样评审',
  '### 色彩参数',
  '使用 `#193D35` 作为主色。详细说明可查看[设计参考](https://example.com/design)。',
  '```css\n.gift-box {\n  color: #193d35;\n  /* ' + '保留长代码原始排版 '.repeat(18) + ' */\n}\n```',
  '| 项目 | 配色 | 包装 | 印刷 | 工艺 | 材料 | 打样 | 验收 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| 方案 | 湖青 | 礼盒 | 专色 | 烫金 | 纸材 | 待确认 | 待确认 |',
  '---',
  '第一行纯文本\n第二行纯文本',
].join('\n\n');

if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5334, strictPort: true, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/markdown-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/markdown-check', fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8')));
    });
    try {
      await server.listen();
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1500, height: 1100, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const q = JSON.stringify, prefix = '.vue-flow__node[data-id="primary"] ', region = prefix + '.canvas-markdown';
    const js = code => win.webContents.executeJavaScript(code, true);
    const wait = async (code, label) => { for (let i = 0; i < 100; i++) { if (await js(code)) return; await pause(50); } throw new Error('Timeout: ' + label); };
    const click = selector => js(`document.querySelector(${q(prefix + selector)}).click()`);
    const patch = async data => { await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='primary'?{...n,data:{...n.data,...${q(data)}}}:n)};void 0`); await pause(100); };
    const node = () => js('JSON.parse(JSON.stringify(state.board.nodes[0]))');
    const screenshot = async name => {
      const rect = await js(`(()=>{const r=document.querySelector(${q(prefix + '.design-asset-node')}).getBoundingClientRect();return{x:Math.floor(r.x-15),y:Math.floor(r.y-10),width:Math.ceil(r.width+30),height:Math.ceil(r.height+20)}})()`);
      fs.writeFileSync(path.join(output, name + '.png'), (await win.webContents.capturePage(rect)).toPNG());
    };
    const downloads = [];
    win.webContents.session.on('will-download', (_event, item) => { item.setSavePath(path.join(output, item.getFilename())); item.once('done', (_e, status) => downloads.push({ status, path: item.getSavePath() })); });
    try {
      await win.loadURL('http://127.0.0.1:5334/markdown-check');
      await wait('!!window.ready', 'canvas mounted');
      await js('reset("text")'); await pause(200);
      await patch({ title: '礼盒概念说明与预算边界', text: source, draft: false, previewSize: { width: 580, height: 860 } });
      await js('flow.setViewport({x:640,y:110,zoom:1})'); await pause(150);
      const rendered = await js(`(()=>{const r=document.querySelector(${q(region)});return{heading:r.querySelector('h1').textContent, sections:r.querySelectorAll('h2').length, strong:r.querySelector('strong').textContent, nested:!!r.querySelector('ul ul'), tables:r.querySelectorAll('table').length, quote:!!r.querySelector('blockquote'), code:r.querySelector('pre code').textContent, linebreak:!!r.querySelector('p br'), link:r.querySelector('a').getAttribute('rel'), text:r.textContent}})()`);
      assert.equal(rendered.heading, '经博会贵宾定向礼盒'); assert.equal(rendered.sections, 3);
      assert.equal(rendered.strong, '贵宾／领导定向礼'); assert.ok(rendered.nested && rendered.quote && rendered.linebreak);
      assert.equal(rendered.tables, 2); assert.match(rendered.code, /color: #193d35/); assert.equal(rendered.link, 'noopener noreferrer');
      assert.ok(!rendered.text.includes('## 一、') && !rendered.text.includes('**贵宾'));
      assert.equal((await node()).data.text, source, 'rendering preserves original Markdown');
      for (const theme of ['dark', 'light']) {
        await js(`document.documentElement.dataset.theme=${q(theme)}`); await pause(100); await screenshot(theme);
        assert.ok(await js(`(()=>{const r=document.querySelector(${q(region)});return r.scrollWidth<=r.clientWidth&&parseFloat(getComputedStyle(r.querySelector('h1')).fontSize)>parseFloat(getComputedStyle(r).fontSize)})()`));
      }
      await js('document.documentElement.dataset.theme="dark"');
      await js(`select();document.querySelector(${q(region)}).focus()`); await pause(100);
      const before = await node();
      win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'DOWN' }); win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'DOWN' }); await pause(200);
      assert.deepEqual((await node()).position, before.position, 'reading with arrows does not move node');
      assert.ok(await js(`(()=>{const r=document.querySelector(${q(region)});r.scrollTop=100;return r.scrollTop===100})()`), 'long document scrolls');
      await click('[aria-label="放大文字"]');
      await wait(`getComputedStyle(document.querySelector(${q(region)})).fontSize==='16px'`, 'font control');
      await click('[aria-label="编辑文本"]');
      assert.equal(await js(`document.querySelector(${q(prefix + 'textarea[aria-label="编辑节点文本"]')}).value`), source);
      const revised = source + '\n\n## 四、下一步\n\n**请确认打样数量。**';
      await js(`(()=>{const input=document.querySelector(${q(prefix + 'textarea[aria-label="编辑节点文本"]')});input.value=${q(revised)};input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await click('.design-text-editor button:last-child');
      await wait(`document.querySelectorAll(${q(region + ' h2')}).length===4`, 'edited source rendered');
      assert.equal((await node()).data.text, revised);
      await click('[aria-label="导出文本"]');
      for (let i = 0; i < 100 && !downloads.length; i++) await pause(50);
      assert.equal(downloads[0]?.status, 'completed'); assert.equal(fs.readFileSync(downloads[0].path, 'utf8'), revised);
      await patch({ previewSize: { width: 260, height: 240 }, textStyle: { fontSize: 28 } });
      assert.ok(await js(`(()=>{const r=document.querySelector(${q(region)}), pre=r.querySelector('pre'), table=r.querySelectorAll('.agent-markdown-table')[1];pre.scrollLeft=100;table.scrollLeft=100;return r.scrollWidth<=r.clientWidth&&pre.scrollLeft>0&&table.scrollLeft>0})()`), 'wide code and tables scroll inside narrow node');
      await patch({ text: '', summary: '## 旧节点摘要\n\n**仍可渲染**' });
      assert.equal(await js(`document.querySelector(${q(region + ' h2')}).textContent`), '旧节点摘要');
      await patch({ text: '## 正在更新\n\n**尚未完成' });
      await patch({ text: '## 正在更新\n\n**已经完成**' });
      assert.equal(await js(`document.querySelector(${q(region + ' strong')}).textContent`), '已经完成');
      await patch({ text: '<script>window.markdownUnsafe=true</script>\n\n<img src=x onerror="window.markdownUnsafe=true">\n\n[执行](javascript:alert%281%29)' });
      assert.equal(await js(`!!window.markdownUnsafe || !!document.querySelector(${q(region + ' script, ' + region + ' img, ' + region + ' a')})`), false);
      assert.deepEqual(await js('window.errors'), []);
      console.log('PASS: Markdown document styles in both themes, nested lists, tables, quotes, code, source editing/download, font size, keyboard/overflow scrolling, legacy summaries, growing output and escaped HTML.');
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); console.error(await js('window.errors').catch(() => []));
      fs.writeFileSync(path.join(output, 'error.png'), (await win.webContents.capturePage()).toPNG()); win.destroy(); app.exit(1);
    }
  });
}
