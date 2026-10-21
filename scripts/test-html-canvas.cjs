// Production Vue Flow and sandboxed iframe regression with real Chromium input.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {createRequire}=require('node:module'),{pathToFileURL}=require('node:url');
const root=path.join(__dirname,'..'),local=createRequire(path.join(root,'package.json'));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
if(!process.versions.electron){
 (async()=>{
  const {createServer}=await import(pathToFileURL(local.resolve('vite')).href);
  const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5292,strictPort:true,hmr:false},logLevel:'error'});
  const page='<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;font:24px sans-serif;background:#eff5f1}main{padding:40px;min-height:1800px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:30px}.panel{padding:40px;background:#fff}h1{font-size:60px}button{padding:24px;font:24px sans-serif}img{width:100px;height:100px;image-rendering:pixelated}@media(max-width:800px){.columns{grid-template-columns:1fr}h1{font-size:32px}}</style><main><h1>桌面网页 · 本地图像</h1><div class="columns"><div class="panel"><button onclick="this.textContent=\'已点击\'">点击交互</button><img alt="透明图" src="asset://image-one"></div><div class="panel">按上下文复用图像</div></div></main>';
  const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==';
  const html=`<html><body><div id="app"></div><script type="module">
   import {createApp,h,reactive,nextTick} from 'vue';import {useVueFlow} from '@vue-flow/core';
   import GeneralCanvas from '/src/components/GeneralCanvas.vue';import {probeHtml} from '/src/deliveryValidation.ts';import '/src/style.css';
   document.documentElement.dataset.theme='light';
   localStorage.setItem('langjuart.viewport.html-check',JSON.stringify({x:500,y:120,zoom:.7}));
   let board={nodes:[{id:'webpage',type:'creative',position:{x:0,y:0},data:{kind:'html',title:'网页节点测试',html:${JSON.stringify(page)},htmlAssets:{'image-one':${JSON.stringify(image)}}}}],edges:[]};
   const state=reactive({canvasDocument:board,messages:[],busy:false});window.changes=[];window.errors=[];
   window.fetch=async(url,options)=>{if(options?.method==='PATCH'){const change=JSON.parse(options.body);window.changes.push(change);for(const patch of change.upsertNodes){const index=board.nodes.findIndex(n=>n.id===patch.id);board.nodes[index]={...board.nodes[index],...patch};}}return Response.json(board);};
   createApp({setup(){const flow=useVueFlow('design-canvas');window.setView=async(view)=>{await flow.setViewport(view);await nextTick()};window.getNode=()=>JSON.parse(JSON.stringify(flow.findNode('webpage')));return()=>h(GeneralCanvas,{...state,apiBaseUrl:'http://fixture.invalid',projectId:'html-check',onCanvasChange:doc=>{board=doc;state.canvasDocument=doc},onCanvasError:error=>window.errors.push(error)});}}).mount('#app');
   window.reMount=async()=>{state.canvasDocument=JSON.parse(JSON.stringify(board));await nextTick()};
   window.verifyImages=()=>probeHtml(${JSON.stringify(page)},{'image-one':${JSON.stringify(image)}});
   window.verifyBrokenImage=()=>probeHtml('<h1>缺图</h1><img src="data:image/png;base64,YQ==">');
   window.ready=true;
  </script><style>html,body,#app{height:100%;margin:0}*{transition:none!important}</style></body></html>`;
  server.middlewares.use('/html-check',async(_req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/html-check',html))});
  await server.listen();const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
  try{process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(local('electron'),[__filename,'http://127.0.0.1:5292/html-check'],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1))});}finally{await server.close()}
 })().catch(error=>{console.error(error);process.exitCode=1});
}else{
 const {app,BrowserWindow}=local('electron');
 app.whenReady().then(async()=>{
  app.dock?.hide();const win=new BrowserWindow({show:false,width:1600,height:1100,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
  const js=code=>win.webContents.executeJavaScript(code);
  const box=selector=>js(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}})()`);
  win.webContents.debugger.attach('1.3');
  const input=(type,x,y,extra={})=>win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:({mouseDown:'mousePressed',mouseUp:'mouseReleased',mouseMove:'mouseMoved',mouseWheel:'mouseWheel'})[type],x:Math.round(x),y:Math.round(y),button:extra.button||'none',buttons:extra.buttons??(type==='mouseDown'?1:0),clickCount:extra.clickCount||0,...(type==='mouseWheel'?{deltaX:extra.deltaX,deltaY:extra.deltaY}:{})});
  const frame=()=>win.webContents.mainFrame.frames.find(f=>f.url==='about:srcdoc');
  try{
   await win.loadURL(process.argv[2]);win.focus();win.webContents.focus();for(let i=0;i<100;i++){if(await js('!!window.ready'))break;await pause(100)}await pause(500);
   assert.ok(frame(),'iframe mounted');
   assert.equal(await frame().executeJavaScript('innerWidth'),1440);
   assert.equal(await frame().executeJavaScript('document.querySelector("img").naturalWidth'),1);
   const before=await box('.design-asset-node'),handle=await box('.vue-flow__handle-right');
   assert.ok(Math.abs(handle.x+handle.width/2-before.right)<8,JSON.stringify({before,handle}));
   const header=await box('.design-asset-node > header');
   await input('mouseMove',header.x+80,header.y+8);await pause(100);
   await input('mouseDown',header.x+80,header.y+8,{button:'left',clickCount:1});
   assert.equal(await js('getComputedStyle(document.querySelector("iframe")).pointerEvents'),'none','protect before crossing drag threshold');
   await input('mouseMove',header.x+110,header.y+45,{button:'left',buttons:1});await pause(100);
   assert.equal(await js('getComputedStyle(document.querySelector("iframe")).pointerEvents'),'none');
   await input('mouseMove',header.x+150,header.y+130,{button:'left',buttons:1});await pause(50);
   await input('mouseUp',header.x+150,header.y+130,{button:'left',clickCount:1});await pause(300);
   assert.notEqual(await js('getComputedStyle(document.querySelector("iframe")).pointerEvents'),'none');
   const released=(await js('window.getNode()')).position;
   await input('mouseMove',header.x+190,header.y+180);await pause(100);
   assert.deepEqual((await js('window.getNode()')).position,released,'node follows mouse after release');
   assert.ok(released.x!==0 || released.y!==0,'drag persisted');
   const button=await frame().executeJavaScript('(()=>{const r=document.querySelector("button").getBoundingClientRect();return {x:r.x+20,y:r.y+20}})()');
   const iframe=await box('iframe');const scale=iframe.width/1440;
   await input('mouseMove',iframe.x+button.x*scale,iframe.y+button.y*scale);await pause(100);
   await input('mouseDown',iframe.x+button.x*scale,iframe.y+button.y*scale,{button:'left',clickCount:1});await pause(60);await input('mouseUp',iframe.x+button.x*scale,iframe.y+button.y*scale,{button:'left',clickCount:1});await pause(150);
   assert.equal(await frame().executeJavaScript('document.querySelector("button").textContent'),'已点击');
   await input('mouseWheel',iframe.x+200,iframe.y+200,{deltaY:220,deltaX:0,canScroll:true});await pause(200);
   assert.ok(await frame().executeJavaScript('scrollY>0'),'iframe scrolls');
   assert.deepEqual((await js('window.getNode()')).position,released,'iframe interaction moved node');
   await js('window.setView({x:500,y:120,zoom:.5})');await pause(200);
   assert.equal(await frame().executeJavaScript('innerWidth'),1440,'canvas zoom changed webpage breakpoint');
   const grip=await box('.design-html-resize');
   await input('mouseDown',grip.x+grip.width/2,grip.y+grip.height/2,{button:'left',clickCount:1});await input('mouseMove',grip.x+grip.width/2-280,grip.y+grip.height/2-40,{button:'left',buttons:1});await pause(100);
   await input('mouseUp',grip.x+grip.width/2-280,grip.y+grip.height/2-40,{button:'left',clickCount:1});await pause(350);
   const resized=await js('window.getNode()');
   assert.equal(resized.data.previewSize.width,400);
   assert.equal(await frame().executeJavaScript('innerWidth'),600);
   assert.equal((await frame().executeJavaScript('getComputedStyle(document.querySelector(".columns")).gridTemplateColumns')).split(' ').length,1);
   const edgeAfter=await box('.vue-flow__handle-right'),after=await box('.design-asset-node');
   assert.ok(Math.abs(edgeAfter.x+edgeAfter.width/2-after.right)<8);
   await js('window.reMount()');await pause(120);assert.equal((await js('window.getNode()')).data.previewSize.width,400);
   await js('document.querySelector(".design-html-resize").focus()');win.webContents.sendInputEvent({type:'keyDown',keyCode:'RIGHT'});win.webContents.sendInputEvent({type:'keyUp',keyCode:'RIGHT'});await pause(150);
   assert.equal((await js('window.getNode()')).data.previewSize.width,420);
   const valid=await js('window.verifyImages()');assert.equal(valid.passed,true,JSON.stringify(valid));
   const invalid=await js('window.verifyBrokenImage()');assert.equal(invalid.passed,false,'broken raster was accepted');
   assert.deepEqual(await js('window.errors'),[]);
   await js('window.setView({x:500,y:120,zoom:.7})');await frame().executeJavaScript('scrollTo(0,0)');await pause(300);
   fs.writeFileSync('/tmp/aics-html-canvas-check.png',(await win.webContents.capturePage()).toPNG());
   console.log(JSON.stringify({passed:true,desktopWidth:1440,responsiveWidth:600,released,resized:resized.data.previewSize,persistedChanges:await js('window.changes.length'),valid,invalid}));
   win.destroy();app.exit(0);
  }catch(error){console.error(error);console.error(await js('window.errors').catch(()=>[]));fs.writeFileSync('/tmp/aics-html-canvas-error.png',(await win.webContents.capturePage()).toPNG());win.destroy();app.exit(1)}
 });
}
