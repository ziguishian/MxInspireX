// Exercise real canvas menus, binary downloads and the desktop PDF bridge.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const image = fs.readFileSync(path.join(root, 'apps/renderer/public/assets/home-design-examples-v1.png'));
const html = `<style>body{margin:0;font:24px system-ui;color:#163d32;background:#f7f4ec}section{box-sizing:border-box;padding:80px;height:1900px;break-after:page}.hero{background:#163d32;color:#f7f4ec}h1{font-size:80px}img{width:100%;height:720px;object-fit:cover}p{line-height:1.8}button{padding:20px;background:#e6c789;color:#163d32;border:0;font:inherit}</style><section class="hero"><p>DESIGN / EXPORT</p><h1>自然空间 · 设计提案</h1><img src="asset://cover"><p>图像与网页排版应完整保留。</p><button onclick="this.textContent='交互正常'">查看设计</button></section><section><h1>第二页 · 设计说明</h1><p>HTML 保留交互，PDF 保留版式与中文。</p></section>`;
const output = path.join(root, '.tmp/canvas-export-check');
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5331, strictPort: true, hmr: false }, logLevel: 'error' });
    const kinds = ['image','video','audio','text','document','3d','html','empty','generating','broken'];
    const extension = {image:'png',video:'mp4',audio:'wav',document:'pdf','3d':'glb'};
    const board = { nodes: kinds.map((kind, i) => ({id:kind,type:'creative',position:{x:i*1600,y:0},data:{kind:['empty','generating','broken'].includes(kind)?'image':kind,title:`保存测试-${kind}`, ...(kind==='html'?{html,htmlAssets:{cover:`data:image/png;base64,${image.toString('base64')}`}}:kind==='text'?{text:'完整文本\n第二行。'}:kind==='empty'?{}:{localFile:`http://127.0.0.1:5331/media/${kind}`,asset:{pathRelative:`source.${extension[kind]||'png'}`}}), ...(kind==='generating'?{generating:true}:{})}})), edges:[] };
    server.middlewares.use('/media/', (req,res) => { if(req.url==='/broken'){res.statusCode=503;return res.end('unavailable')}res.setHeader('Content-Type',req.url==='/image'?'image/png':'application/octet-stream');res.end(req.url==='/image'?image:Buffer.from(`original:${req.url}`)); });
    const fixture = `<!doctype html><html><meta charset="utf-8"><body><div id="app"></div><script type="module">
      import {createApp,h,reactive,nextTick} from 'vue';import {useVueFlow} from '@vue-flow/core';import GeneralCanvas from '/src/components/GeneralCanvas.vue';import '/src/style.css';
      document.documentElement.dataset.theme='dark';localStorage.setItem('langjuart.viewport.export-test',JSON.stringify({x:530,y:90,zoom:.65}));
      const state=reactive({canvasDocument:${JSON.stringify(board)},messages:[],busy:false});window.errors=[];
      createApp({setup(){const flow=useVueFlow('design-canvas');window.focusNode=async id=>{const n=flow.findNode(id);await flow.setViewport({x:530-n.position.x*.65,y:90,zoom:.65});await nextTick()};window.select=ids=>flow.getNodes.value.forEach(n=>n.selected=ids.includes(n.id));return()=>h(GeneralCanvas,{...state,apiBaseUrl:'http://fixture.invalid',projectId:'export-test',onCanvasError:e=>window.errors.push(e)})}}).mount('#app');
      window.exportBrowser=async()=>{const {exportNode}=await import('/src/nodeExport.ts');await exportNode({kind:'html',title:'浏览器 PDF',html:'<h1>Browser PDF</h1>'},'pdf')};window.ready=true;
    </script><style>html,body,#app{height:100%;margin:0}*{transition:none!important}</style></body></html>`;
    server.middlewares.use('/export-check', async (_req,res) => {res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/export-check',fixture));});
    await server.listen();
    const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
    try {process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});} finally {await server.close();}
  })().catch(error=>{console.error(error);process.exitCode=1});
} else {
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();
    const {registerHtmlExport,renderHtmlPdf}=await import(pathToFileURL(path.join(root,'dist/desktop/htmlExport.js')).href);registerHtmlExport();
    const win=new BrowserWindow({show:false,width:1600,height:1100,webPreferences:{preload:path.join(root,'dist/desktop/preload.js'),sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    const js=code=>win.webContents.executeJavaScript(code,true).catch(error=>{console.error('Failed script:',code);throw error}), downloads=[];
    const wait=async(code,label)=>{for(let i=0;i<200;i++){if(await js(code).catch(()=>false))return;await pause(50)}throw new Error('Timeout: '+label)};
    const menu=()=>js(`Array.from(document.querySelectorAll('.canvas-context-menu button'),b=>({text:b.textContent.trim(),disabled:b.disabled}))`);
    const context=async(id,x,y)=>{await js(`focusNode(${JSON.stringify(id)})`);await pause(100);await js(`document.querySelector('.vue-flow__node[data-id="${id}"] .design-node-surface').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:${x||900},clientY:${y||230}}))`);await pause(80);};
    const click=async text=>{await js(`Array.from(document.querySelectorAll('.canvas-context-menu button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}).click()`);};
    win.webContents.session.on('will-download',(_event,item)=>{const file=path.join(output,item.getFilename());item.setSavePath(file);item.once('done',(_e,state)=>downloads.push({state,name:item.getFilename(),file}));});
    const download=async(label,name)=>{const count=downloads.length;await click(label);for(let i=0;i<600&&downloads.length===count;i++)await pause(50);assert.equal(downloads[count]?.state,'completed',JSON.stringify(await js('window.errors')));assert.equal(downloads[count].name,name);return fs.readFileSync(downloads[count].file);};
    try {
      await win.loadURL('http://127.0.0.1:5331/export-check');await wait('window.ready','mount');await pause(500);
      for(const [kind,label,ext] of [['image','保存图像','png'],['video','保存视频','mp4'],['audio','保存音频','wav'],['text','保存文本','txt'],['document','保存素材','pdf'],['3d','保存 3D 模型','glb']]) {
        await context(kind);assert.equal((await menu())[0].text,label);const content=await download(label,`保存测试-${kind}.${ext}`);assert.deepEqual(content,kind==='image'?image:Buffer.from(kind==='text'?'完整文本\n第二行。':`original:/${kind}`));
      }
      await js(`select(['image','video'])`);await context('video');assert.equal((await menu())[0].text,'保存视频','right-click targets the clicked item within multi-selection');
      for(const kind of ['empty','generating']){await context(kind);assert.equal((await menu())[0].disabled,true);}
      await context('broken');await click('保存图像');await wait('window.errors.length===1','error visible');assert.match(await js('window.errors[0]'),/读取失败/);assert.equal(downloads.length,6);await js('window.errors=[]');
      await context('html',1595,1095);assert.deepEqual((await menu()).slice(0,2).map(b=>b.text),['导出 HTML','导出 PDF']);
      assert.ok(await js(`(()=>{const r=document.querySelector('.canvas-context-menu').getBoundingClientRect();return r.bottom<=innerHeight&&r.right<=innerWidth})()`),'menu stays inside viewport');
      const saved=(await download('导出 HTML','保存测试-html.html')).toString();assert.ok(saved.includes('data:image/png;base64,'));assert.ok(!saved.includes('asset://'));assert.ok(saved.includes('onclick='));assert.ok(!saved.includes('aics:html-context-menu'));
      await js(`document.querySelector('.design-canvas-area').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:1200,clientY:900}))`);assert.ok(!(await menu()).some(b=>/保存|导出/.test(b.text)),'blank canvas does not export stale selection');await click('关闭菜单');
      // Chromium input inside the opaque iframe must open the canvas menu at the
      // right screen coordinate even when the node is scaled by Vue Flow.
      const frame=()=>win.webContents.mainFrame.frames.find(f=>f.url==='about:srcdoc');
      const rect=await js(`(()=>{const r=document.querySelector('iframe.design-html-preview').getBoundingClientRect();return{x:r.x,y:r.y}})()`);
      win.webContents.debugger.attach('1.3');
      for(const type of ['mousePressed','mouseReleased'])await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type,x:Math.round(rect.x+120),y:Math.round(rect.y+110),button:'right',buttons:type==='mousePressed'?2:0,clickCount:1});
      await wait(`!!document.querySelector('.canvas-context-menu')`,'iframe context menu');assert.equal((await menu())[0].text,'导出 HTML');
      const actual=await js(`(()=>{const r=document.querySelector('.canvas-context-menu').getBoundingClientRect();return{x:r.x,y:r.y}})()`);assert.ok(Math.abs(actual.x-rect.x-120)<3);assert.ok(Math.abs(actual.y-rect.y-110)<3);
      fs.writeFileSync(path.join(output,'html-menu.png'),(await win.webContents.capturePage()).toPNG());
      await frame().executeJavaScript(`document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0}))`);await wait(`!document.querySelector('.canvas-context-menu')`,'iframe click dismisses menu');await context('html');
      const pdf=await download('导出 PDF','保存测试-html.pdf');assert.equal(pdf.subarray(0,5).toString(),'%PDF-');assert.ok(pdf.length>10000);
      assert.equal(await frame().executeJavaScript('typeof window.studio'),'undefined','canvas HTML cannot access native export bridge');
      await assert.rejects(renderHtmlPdf({html:'<h1>invalid width</h1>',width:NaN}),/参数/);
      const secure=await renderHtmlPdf({html:`<h1>Isolated PDF</h1><script>document.querySelector('h1').textContent = typeof window.studio + ' / ' + typeof require;fetch('http://127.0.0.1:5331/forbidden').catch(()=>{});</script>`,width:1440});fs.writeFileSync(path.join(output,'isolated.pdf'),secure);
      assert.deepEqual(await js('window.errors'),[]);
      // Browser fallback: replace only print itself to avoid opening a native
      // dialog during regression; readiness and sandboxed invocation stay real.
      const browser=new BrowserWindow({show:false,width:1600,height:1100,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
      await browser.loadURL('http://127.0.0.1:5331/export-check');for(let i=0;i<200;i++){if(await browser.webContents.executeJavaScript('!!window.ready').catch(()=>false))break;await pause(50)};await pause(400);
      await browser.webContents.executeJavaScript(`(()=>{
        const descriptor=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'srcdoc');
        Object.defineProperty(HTMLIFrameElement.prototype,'srcdoc',{...descriptor,set(value){
          descriptor.set.call(this,value.replace('<script>','<script>window.print=()=>window.dispatchEvent(new Event("afterprint"));'));
        }});
      })()`);
      await browser.webContents.executeJavaScript('window.exportBrowser().then(()=>window.browserPrinted=true).catch(e=>window.browserError=e.message)',true);
      assert.equal(await browser.webContents.executeJavaScript('window.browserPrinted'),true);
      assert.equal(await browser.webContents.executeJavaScript('document.querySelectorAll("iframe[title=\\\"浏览器 PDF.pdf\\\"]").length'),0);browser.destroy();
      console.log('PASS: all asset types, original bytes, correct multi-selection target, unavailable assets, failure feedback, edge positioning, sandboxed iframe right-click, self-contained HTML, real desktop PDF, isolated rendering and browser print fallback.');win.destroy();app.exit(0);
    } catch(error) {console.error(error);console.error(await js('window.errors').catch(()=>[]));fs.writeFileSync(path.join(output,'error.png'),(await win.webContents.capturePage()).toPNG());win.destroy();app.exit(1)}
  });
}
