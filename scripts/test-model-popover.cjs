// Test the real production bundles. All API data is isolated from user projects.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const defaultImage='openai/gpt-image-2.5-sunburst';
const modelCatalog=[
  {id:'text-fixture',name:'Text model',kinds:['text']},
  ...['Google: Nano Banana Pro (Gemini 3 Pro Image Preview) / Extended multilingual experimental model', 'Unbroken'+ 'ModelIdentifier'.repeat(12), 'ByteDance Seed: Seedream 5.0 Pro', 'Google: Nano Banana (Gemini 2.5 Flash Image)', 'Image five', 'Image six'].map((name,i)=>({id:'image-'+i,name,kinds:['image'],price:{currency:'USD',inputPerMillion:1.8,outputPerMillion:19.3,cachedPerMillion:.25,imageInputPerMillion:2.9,imageOutputPerMillion:120,perImage:.25}})),
  {id:defaultImage,kinds:['image'],price:{currency:'USD',perImage:.2}},
  {id:'bytedance/seedance-2.5',kinds:['video']}
];
const catalog={models:modelCatalog.map(m=>m.id),modelCatalog,savedAt:'2026-09-14',source:'local'};

if (!process.versions.electron) {
  (async () => {
    const { preview } = await import('vite');
    const server = await preview({ configFile: path.join(root, 'apps/renderer/vite.config.ts'), preview: { host: '127.0.0.1', port: 5320, strictPort: true } });
    const api = require('node:http').createServer((req, res) => {
      const p = new URL(req.url, 'http://fixture.invalid').pathname;
      const project = { id: 'model-fixture', name: '模型菜单验证', status: 'draft' };
      let data = [];
      if (p === '/health') data = { status: 'ok' };
      else if (p === '/api/projects') data = [project];
      else if (p === '/api/projects/model-fixture') data = project;
      else if (/\/(canvas|preview)$/.test(p)) data = { nodes: [], edges: [] };
      else if (p === '/api/providers') data = [{key:'openrouter',kind:'text',label:'OpenRouter',configured:true,defaultBaseUrl:'https://openrouter.ai/api/v1'}];
      else if (p === '/api/providers/model-catalog') data = catalog;
      else if (p === '/api/model-settings') data = {credits:{pointsPerCny:100,multiplier:1,usdToCny:7.2},media:{image:{draft:defaultImage,standard:defaultImage,final:defaultImage},video:{standard:'bytedance/seedance-2.5'}}};
      else if (/models|catalog/.test(p)) data = { models: [], modelCatalog: [], configured: false };
      else if (/usage|credits/.test(p)) data = { points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 };
      else if (/delivery.*claim/.test(p)) data = null;
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS' });
      res.end(JSON.stringify(data));
    });
    try {
      await new Promise((resolve, reject) => { api.once('error', reject); api.listen(5321, '127.0.0.1', resolve); });
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
    const win = new BrowserWindow({ show: false, width: 1280, height: 960, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'model-popover-fixture' } });
    const js = code => win.webContents.executeJavaScript(code);
    const wait = async code => { for (let i = 0; i < 100; i++) { if (await js(code).catch(() => false)) return; await pause(60); } throw new Error('Timeout: ' + code); };
    win.webContents.session.webRequest.onBeforeRequest((details, callback) => {
      if (details.url.startsWith('http://127.0.0.1:8765/')) return callback({ redirectURL: details.url.replace('127.0.0.1:8765', '127.0.0.1:5321') });
      if (/^https?:/.test(details.url) && !/^http:\/\/127.0.0.1:532[01]\//.test(details.url)) return callback({ cancel: true });
      callback({});
    });
    const trigger = '.composer-agent-wrap > button';
    const open = async () => {
      await wait(`!!document.querySelector('${trigger}')`);
      await js(`document.querySelector('${trigger}').click()`);
      await wait(`document.querySelector('.anchored-popover')?.style.visibility==='visible'`);
      await pause(120);
    };
    const close = async () => {
      await js(`document.querySelector('${trigger}').click()`);
      await wait(`!document.querySelector('.anchored-popover')`);
    };
    const bounds = () => js(`(()=>{const p=document.querySelector('.anchored-popover'),r=p.getBoundingClientRect(),a=document.querySelector('${trigger}').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,height:r.height,placement:p.dataset.placement,anchorTop:a.top,anchorBottom:a.bottom,width:innerWidth,viewportHeight:innerHeight,scrollHeight:p.scrollHeight,clientHeight:p.clientHeight,naturalHeight:document.querySelector('.anchored-popover-content').getBoundingClientRect().height+24}})()`);
    const check = async label => {
      const b = await bounds();
      assert.ok(b.top >= 41.9 && b.bottom <= b.viewportHeight - 11.9, label + ': within vertical safe area ' + JSON.stringify(b));
      assert.ok(b.left >= 11.9 && b.right <= b.width - 11.9, label + ': within horizontal safe area');
      if (b.placement === 'top') assert.ok(Math.abs(b.bottom - b.anchorTop + 8) < 1, label + ': above trigger');
      else assert.ok(Math.abs(b.top - b.anchorBottom - 8) < 1, label + ': below trigger');
      const above=b.anchorTop-8-42, below=b.viewportHeight-12-b.anchorBottom-8;
      const expected=below>=b.naturalHeight?'bottom':above>=b.naturalHeight?'top':below>=above?'bottom':'top';
      assert.equal(b.placement,expected,label + ': chooses a fitting side or the larger space');
      return b;
    };
    const checkRows = async label => {
      const result=await js(`(()=>{const list=document.querySelector('.agent-model-list');return {overflow:list.scrollWidth>list.clientWidth,rows:Array.from(list.querySelectorAll('.model-option'),button=>{const r=button.getBoundingClientRect();return {name:button.querySelector('strong').textContent,top:r.top,bottom:r.bottom,spill:Array.from(button.children).some(el=>{const b=el.getBoundingClientRect();return b.left<r.left||b.right>r.right+1||b.top<r.top||b.bottom>r.bottom+1})}})}})()`);
      assert.equal(result.overflow,false,label+': no horizontal overflow');
      assert.ok(result.rows.length>=7,label+': populated real model rows');
      result.rows.forEach((row,i)=>{assert.equal(row.spill,false,label+': row contains '+row.name);if(i)assert.ok(row.top>=result.rows[i-1].bottom+3,label+': rows never overlap')});
    };
    const errors=[];
    win.webContents.on('console-message',(_event,level,message)=>{if(level===3 && /ResizeObserver loop|Unhandled|TypeError/.test(message))errors.push(message);});
    const checks=[];
    try {
      await win.loadFile(path.join(root,'dist/renderer/index.html'));
      await open(); const home=await check('desktop home'); assert.equal(home.placement,'bottom');
      await js(`document.documentElement.dataset.theme='dark'`);
      fs.writeFileSync('/private/tmp/aics-model-popover-home.png',(await win.webContents.capturePage()).toPNG());
      checks.push('desktop home opens down, clear of title bar');
      // Verify window resizing repositions an already-open menu, including a short window.
      for(const height of [620,480,920]) {win.setContentSize(1100,height);await pause(300);await check('resized '+height);}
      checks.push('live window resize keeps the menu within the viewport');
      await close(); await win.loadURL('http://127.0.0.1:5320/projects/model-fixture');
      await wait(`!!document.querySelector('.design-workspace')`);
      await open(); assert.equal((await check('workspace')).placement,'top');
      await js(`document.querySelectorAll('.agent-model-tabs button')[1].click()`);await pause(160);
      assert.ok(await js(`!!document.querySelector('.anchored-popover')`),'tab clicks keep the teleported menu open');
      await check('short image tab');
      await wait(`document.querySelectorAll('.model-option').length>=7`);
      await checkRows('image names and full pricing');
      assert.equal(await js(`document.querySelector('.model-option.selected strong')?.textContent`),'GPT-Image-2.5 Sunburst','fresh selection uses GPT Image 2.5');
      assert.equal(await js(`document.querySelector('.model-option strong').textContent`),'GPT-Image-2.5 Sunburst','default is first');
      fs.writeFileSync('/private/tmp/aics-model-popover-image-fixed.png',(await win.webContents.capturePage()).toPNG());
      await js(`document.querySelectorAll('.model-option')[1].click()`);await open();await checkRows('selected long model with badge');
      assert.equal(await js(`localStorage.getItem('aics.imageModel')`),'image-0');
      await close();await win.reload();await wait(`!!document.querySelector('.design-workspace')`);await open();await js(`document.querySelectorAll('.agent-model-tabs button')[1].click()`);await wait(`document.querySelector('.model-option.selected strong')?.textContent.includes('Nano Banana')`);
      await js(`document.querySelector('.image-default-action').click()`);assert.equal(await js(`localStorage.getItem('aics.imageModel')`),defaultImage);assert.equal(await js(`localStorage.getItem('aics.imageModelManual')`),'false');
      await win.reload();await wait(`!!document.querySelector('.design-workspace')`);await open();await js(`document.querySelectorAll('.agent-model-tabs button')[1].click()`);await wait(`document.querySelector('.model-option.selected strong')?.textContent==='GPT-Image-2.5 Sunburst'`);
      win.setContentSize(390,760);await pause(200);await checkRows('narrow screen');win.setContentSize(1100,920);await pause(200);
      checks.push('long names and full tariffs stay inside rows; GPT Image 2.5 default, manual choice, and restoring default persist across reload');

      await js(`document.querySelectorAll('.agent-model-tabs button')[0].click()`);await pause(160);await check('text tab');
      fs.writeFileSync('/private/tmp/aics-model-popover-workspace.png',(await win.webContents.capturePage()).toPNG());
      checks.push('workspace opens up; changing model category recalculates height');
      await js(`document.querySelector('.anchored-popover').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
      await wait(`!document.querySelector('.anchored-popover')`);
      assert.ok(await js(`document.activeElement===document.querySelector('${trigger}')`));
      await open();await js(`document.querySelector('.design-workspace').click()`);await wait(`!document.querySelector('.anchored-popover')`);
      checks.push('Escape returns focus and clicking outside dismisses');
      // Isolate boundary cases by moving the existing trigger's wrapper within the fixture only.
      await win.loadURL('http://127.0.0.1:5320/');win.setContentSize(390,420);
      await wait(`!!document.querySelector('${trigger}')`);
      await js(`window.testWrap=document.querySelector('.composer-agent-wrap');document.body.append(testWrap);testWrap.style.cssText='position:fixed;top:190px;right:5px';`);
      await open(); const tiny=await check('both sides constrained');
      assert.ok(tiny.scrollHeight>tiny.clientHeight,'short viewport uses internal scrolling');
      await js(`document.querySelector('.anchored-popover').scrollTop=10000`);
      assert.ok(await js(`document.querySelector('.anchored-popover').scrollTop>0`));
      fs.writeFileSync('/private/tmp/aics-model-popover-short.png',(await win.webContents.capturePage()).toPNG());
      // A captured ancestor scroll updates the anchor, and hides the menu if it scrolls out of view.
      await js(`testWrap.style.top='65px';window.dispatchEvent(new Event('scroll'))`);await pause(160);await check('scrolled anchor');
      await js(`testWrap.style.top='-100px';window.dispatchEvent(new Event('scroll'))`);await wait(`!document.querySelector('.anchored-popover')`);
      checks.push('small screens clamp horizontally, scroll internally, and track anchor scrolling');
      assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks},null,2));
    } catch(error) { console.error(error);process.exitCode=1;fs.writeFileSync('/private/tmp/aics-model-popover-error.png',(await win.webContents.capturePage()).toPNG()); }
    finally { win.destroy();app.exit(process.exitCode||0); }
  });
}
