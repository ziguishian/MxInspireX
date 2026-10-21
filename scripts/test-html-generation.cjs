// HTML generation feedback with the production canvas and an isolated task snapshot.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
if(!process.versions.electron){
 (async()=>{
  const {createServer}=await import('vite');
  const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5314,strictPort:true,hmr:false},logLevel:'error'});
  const html=`<html data-theme="dark"><body><div id="app"></div><script type="module">
   import {createApp,h,reactive,nextTick} from 'vue';import GeneralCanvas from '/src/components/GeneralCanvas.vue';import {designSteps} from '/src/designPresentation';import '/src/style.css';
   const started=new Date().toISOString();const state=reactive({busy:true,progress:'正在生成网页…',canvasDocument:{nodes:[{id:'page',type:'creative',position:{x:0,y:0},meta:{taskId:'task'},data:{kind:'html',title:'生成网页',generating:true}}],edges:[]},messages:[]});
   const trace=[{at:started,phase:'generation',message:'正在生成网页…'}];
   state.messages=[{role:'user',content:'设计一份完整网页方案',taskId:'task'},{role:'assistant',content:'',taskId:'task',status:'running',steps:designSteps(trace,'running'),execution:{trace,createdAt:started}}];
   window.complete=async()=>{state.busy=false;state.messages[1].status='succeeded';state.messages[1].steps=designSteps([...trace,{at:new Date().toISOString(),phase:'succeeded',message:'网页完成'}],'succeeded');state.canvasDocument={nodes:[{...state.canvasDocument.nodes[0],data:{kind:'html',title:'完整方案',generating:false,html:'<style>body{font:24px system-ui;background:#e6eee5;padding:50px;color:#173f2d}h1{font-size:56px}button{padding:12px 24px}</style><h1>让设计，发生。</h1><button onclick="this.textContent=\\\'已点击\\\'">查看方案</button>'}}],edges:[]};await nextTick()};
   window.cancel=async()=>{state.busy=false;state.messages[1].status='cancelled';state.messages[1].steps=designSteps(trace,'cancelled');state.canvasDocument={nodes:[],edges:[]};await nextTick()};
   createApp({setup(){return()=>h(GeneralCanvas,{...state,projectId:'html-generation-fixture',apiBaseUrl:'http://fixture.invalid'})}}).mount('#app');window.ready=true;
  </script><style>html,body,#app{height:100%;margin:0}</style></body></html>`;
  server.middlewares.use('/html-generation-check',async(_req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/html-generation-check',html))});
  try{await server.listen();const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1))})}finally{await server.close()}
 })().catch(error=>{console.error(error);process.exitCode=1});
}else{
 const {app,BrowserWindow}=require('electron');
 app.whenReady().then(async()=>{
  app.dock?.hide();const win=new BrowserWindow({show:false,width:1440,height:960,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
  const js=code=>win.webContents.executeJavaScript(code);
  const wait=async(code,label)=>{for(let i=0;i<100;i++){if(await js(code).catch(()=>false))return;await pause(50)}throw new Error('Timeout: '+label)};
  try{
   await win.loadURL('http://127.0.0.1:5314/html-generation-check');await wait('window.ready','mount');
   await wait(`!!document.querySelector('.design-media-loading')`,'canvas loading');await pause(500);
   assert.equal(await js(`document.querySelector('.design-media-loading').textContent.trim()`),'正在生成网页…');
   assert.ok(await js(`document.querySelector('.design-execution').open`));
   assert.equal(await js(`document.querySelector('.design-execution summary').textContent`),'思考中');
   assert.ok(await js(`!!document.querySelector('.design-step-list .running .spin-icon')`));
   assert.ok(await js(`document.querySelector('.design-run-progress').textContent.includes('正在生成网页')`));
   assert.ok(await js(`(()=>{const node=document.querySelector('.design-node-surface').getBoundingClientRect(),chat=document.querySelector('.design-chat-panel').getBoundingClientRect();return node.right>chat.right&&node.left<innerWidth&&node.bottom>0&&node.top<innerHeight})()`));
   fs.writeFileSync('/tmp/aics-html-generation-loading.png',(await win.webContents.capturePage()).toPNG());
   await js('window.complete()');await wait(`!!document.querySelector('.design-html-preview')`,'completed HTML');
   assert.equal(await js(`!!document.querySelector('.design-media-loading')`),false);
   assert.equal(await js(`!!document.querySelector('.design-run-progress')`),false);
   assert.equal(await js(`document.querySelector('.vue-flow__node').dataset.id`),'page');
   await win.loadURL('http://127.0.0.1:5314/html-generation-check');await wait('window.ready','reset');await js('window.cancel()');await wait(`document.querySelectorAll('.vue-flow__node').length===0`,'cancel placeholder');
   assert.equal(await js(`!!document.querySelector('.design-run-progress')`),false);
   console.log('PASS: visible HTML loading card, expanded thinking + spinning step + persistent status, same-node completed preview, cancellation clears loaders.');
  }catch(error){console.error(error);fs.writeFileSync('/tmp/aics-html-generation-error.png',(await win.webContents.capturePage()).toPNG());process.exitCode=1}
  finally{win.destroy();app.exit(process.exitCode||0)}
 });
}
