// Isolated Vue/Chromium UI: fixture data only, no sidecar or real providers.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/delivery-findings-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'),
      server: { host: '127.0.0.1', port: 5367, strictPort: false, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/delivery-findings-check', async (_req, res) => {
      let html = fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8');
      html = html.replace("messages:[{role:'assistant',content:'这是一段直接回答。'}],busy:false", 'messages:state.messages || [],busy:false');
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/delivery-findings-check', html));
    });
    try {
      await server.listen();
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename,
          `http://127.0.0.1:${server.httpServer.address().port}/delivery-findings-check`], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1440, height: 1100,
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code, true);
    try {
      await win.loadURL(process.argv[2]);
      for (let i = 0; i < 100 && !await js('Boolean(window.ready)'); i++) await pause(50);
      await js(`(async () => {
        const findings = [
          {kind:'problem',code:'typo',message:'包装标题拼写错误。',nextAction:'将标题修改为“朗居”。',nodeId:'defect'},
          {kind:'unverified',code:'small_text',message:'缩略总览中的小字看不清。',nextAction:'打开原图核对小字。',nodeId:'proof'},
          {kind:'production_confirmation',code:'size',message:'成品尺寸和材质尚未确认。',nextAction:'制作前提供成品尺寸与材质。',nodeId:'fabrication'},
          {kind:'generation_unconfirmed',code:'image_response_timeout',message:'图像响应超时，可能已计费。',nextAction:'先核对原请求和计费记录；核对前不要重新提交生成。',nodeId:'pending'},
        ];
        state.board = {nodes:[
          {id:'defect',type:'creative',position:{x:0,y:0},data:{kind:'text',title:'包装文案',text:'朗据',deliveryReview:{findings:[findings[0]]}}},
          {id:'proof',type:'creative',position:{x:360,y:0},data:{kind:'text',title:'规格小字',text:'参数说明',deliveryReview:{findings:[findings[1]]}}},
          {id:'fabrication',type:'creative',position:{x:0,y:360},data:{kind:'image',title:'包装视觉',localFile:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=',productionNotes:['成品尺寸和材质尚未确认。']}},
          {id:'pending',type:'creative',position:{x:360,y:360},data:{kind:'image',title:'生成请求',status:'生成结果待确认',error:'等待图像响应超时'}},
        ],edges:[]};
        state.messages = [{role:'assistant',taskId:'fixture-task',status:'succeeded',content:'产物已保存，请按具体原因继续。',execution:{deliveryStatus:'needs_review',reviewStatus:'failed',findings}}];
        state.epoch++;
      })()`);
      await pause(600);
      const groups = await js(`Array.from(document.querySelectorAll('.design-chat-panel .delivery-findings details')).map(el=>({kind:el.dataset.kind,text:el.innerText,open:el.open}))`);
      assert.deepEqual(groups.map(g => g.kind), ['problem', 'unverified', 'production_confirmation', 'generation_unconfirmed']);
      assert(groups.every(g => g.open && g.text.includes('下一步：')));
      assert(groups.at(-1).text.includes('核对前不要重新提交生成'));
      await js(`document.querySelector('.design-chat-panel .delivery-findings button').click()`);
      await pause(500);
      assert(await js(`(()=>{const node=document.querySelector('.vue-flow__node[data-id="defect"]').getBoundingClientRect();const area=document.querySelector('.design-canvas-area').getBoundingClientRect();return node.left<area.right&&node.right>area.left&&node.top<area.bottom&&node.bottom>area.top})()`));
      assert.equal(await js('window.generated.length'), 0);
      for (const [id, expected] of [['defect', '已发现问题'], ['proof', '尚未核实'], ['fabrication', '制作参数待确认'], ['pending', '生成结果待确认']]) {
        const text = await js(`document.querySelector('.vue-flow__node[data-id="${id}"] .delivery-findings').innerText`);
        assert(text.includes(expected), id + ': ' + text);
      }
      await js(`document.querySelector('.design-chat-scroll').scrollTop=0`);
      fs.writeFileSync(path.join(output, 'dark.png'), (await win.webContents.capturePage()).toPNG());
      await js("document.documentElement.dataset.theme='light'"); await pause(100);
      assert.equal(await js(`getComputedStyle(document.querySelector('.delivery-findings [data-kind="production_confirmation"] summary')).color`), 'rgb(132, 96, 21)');
      assert.equal(await js(`getComputedStyle(document.querySelector('.vue-flow__node .delivery-findings details')).backgroundColor`), 'rgb(255, 255, 255)');
      fs.writeFileSync(path.join(output, 'light.png'), (await win.webContents.capturePage()).toPNG());
      win.setSize(900, 900); await pause(150);
      const overflow = await js(`Array.from(document.querySelectorAll('.design-chat-panel .delivery-findings')).some(el=>el.scrollWidth>el.clientWidth+1)`);
      assert.equal(overflow, false, 'Finding cards must wrap in the chat panel');
      assert.equal(await js('window.generated.length'), 0);
      console.log(JSON.stringify({ passed: true, checks: ['four distinct categories with reasons and actions', 'scoped canvas notes', 'artifact navigation without generation', 'dark/light and narrow panel layout'], screenshots: output }));
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error);
      fs.writeFileSync(path.join(output, 'error.png'), (await win.webContents.capturePage()).toPNG());
      win.destroy(); app.exit(1);
    }
  });
}
