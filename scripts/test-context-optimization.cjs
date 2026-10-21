// Isolated renderer verification. No sidecar, credentials or model requests.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),output=path.join(root,'.tmp/context-optimization-check');
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output,{recursive:true});
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),
      server:{host:'127.0.0.1',port:5368,strictPort:false,hmr:false},logLevel:'error'});
    server.middlewares.use('/context-check',async (_req,res) => {
      const html=`<!doctype html><html data-theme="dark"><meta charset="utf-8"><style>
        body{padding:24px;margin:0;background:var(--theme-bg,#151911);color:var(--theme-text)}
        #app{max-width:460px;margin:auto;padding:16px;border:1px solid var(--theme-border);box-sizing:border-box}
        </style><div id="app"></div><script type="module">
        import {createApp,h,reactive} from 'vue';
        import TaskProgress from '/src/components/TaskProgress.vue';import '/src/style.css';
        window.state=reactive({info:{trace:[]},status:'succeeded'});
        createApp({render:()=>h(TaskProgress,{info:state.info,status:state.status})}).mount('#app');window.ready=true;
        </script></html>`;
      res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/context-check',html));
    });
    try {
      await server.listen();
      const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode=await new Promise((resolve,reject) => {
        const child=require('node:child_process').spawn(require('electron'),[__filename,`http://127.0.0.1:${server.httpServer.address().port}/context-check`],{env,stdio:'inherit'});
        child.on('error',reject);child.on('exit',code=>resolve(code??1));
      });
    } finally {await server.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
} else {
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:640,height:640,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    const js=code=>win.webContents.executeJavaScript(code,true);
    const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    try {
      await win.loadURL(process.argv[2]);
      for(let i=0;i<100&&!await js('Boolean(window.ready)');i++) await pause(50);
      await js(`state.info={trace:[
        {phase:'model_call',data:{stage:'design',inputTokens:10000,cacheReported:true,cachedTokens:4000,cacheWriteReported:true,cacheWriteTokens:2000}},
        {phase:'context_compaction',data:{mode:'local',beforeTokens:24000,afterTokens:8000,status:'succeeded',reason:'保留当前需求和有效约束，旧正文按需读取'}},
        {phase:'context_compaction',data:{mode:'native',status:'skipped',reason:'当前入口未确认支持原生压缩，使用本地精简与按需读取'}}]}`);
      await pause(100);
      const text=await js('document.body.innerText');
      for(const label of ['缓存命中 40.0%','缓存写入 2,000 tokens','上下文已精简（估算）','原生压缩未启用','使用本地精简与按需读取']) assert(text.includes(label),label);
      assert(!text.includes('压缩调用 1'));
      for(const theme of ['dark','light']) {
        await js(`document.documentElement.dataset.theme='${theme}'`);await pause(80);
        fs.writeFileSync(path.join(output,theme+'.png'),(await win.webContents.capturePage()).toPNG());
      }
      win.setSize(340,640);await pause(100);
      assert.equal(await js('document.documentElement.scrollWidth>window.innerWidth'),false,'narrow layout must wrap');
      await js(`state.status='running';state.info={trace:[{phase:'model_call',data:{inputTokens:1000,cacheReported:true,cachedTokens:0}},
        {phase:'context_compaction',data:{mode:'native',status:'started'}}]}`);await pause(80);
      assert((await js('document.body.innerText')).includes('缓存未命中'));
      assert((await js('document.body.innerText')).includes('原生压缩进行中'));
      await js(`state.status='succeeded';state.info={trace:[{phase:'model_call',data:{inputTokens:1000}},
        {phase:'context_compaction',data:{mode:'native',status:'failed',succeeded:false,reason:'原始历史保留，本任务不再重试'}}]}`);await pause(80);
      const failed=await js('document.body.innerText');
      assert(failed.includes('缓存命中统计：入口未返回'));
      assert(!failed.includes('缓存未命中'));
      assert(failed.includes('原生压缩未完成')&&failed.includes('本任务不再重试'));
      console.log(JSON.stringify({passed:true,screenshots:output,checks:['cache reads/writes and missing telemetry','native started/skipped/failed','local estimates','dark/light and narrow layout']}));
      win.destroy();app.exit(0);
    } catch(error) {console.error(error);fs.writeFileSync(path.join(output,'error.png'),(await win.webContents.capturePage()).toPNG());win.destroy();app.exit(1);}
  });
}
