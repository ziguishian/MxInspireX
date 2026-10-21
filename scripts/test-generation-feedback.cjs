const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),output=path.join(root,'.tmp/generation-feedback-check');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const raw='OpenRouter 图像接口 HTTP 400: Gemini could not generate an image (STOP)';
if(!process.versions.electron){
  (async()=>{
    fs.mkdirSync(output,{recursive:true});
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5363,strictPort:false,hmr:false},logLevel:'error'});
    server.middlewares.use('/feedback-check',async(_req,res)=>{
      let html=fs.readFileSync(path.join(__dirname,'fixtures/canvas-workspace.html'),'utf8');
      html=html.replace("messages:[{role:'assistant',content:'这是一段直接回答。'}],busy:false", "messages:state.messages || [{role:'assistant',content:'这是一段直接回答。'}],busy:state.busy || false,error:state.error,progress:state.progress");
      res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/feedback-check',html));
    });
    try{
      await server.listen();
      const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
      const port=server.httpServer.address().port;
      process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename,`http://127.0.0.1:${port}/feedback-check`],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});
    }finally{await server.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    const js=code=>win.webContents.executeJavaScript(code,true);
    try{
      await win.loadURL(process.argv[2]);
      for(let i=0;i<100&&!await js('Boolean(window.ready)');i++)await pause(50);
      await js(`(async()=>{
        const {designSteps}=await import('/src/designPresentation.ts');
        const raw=${JSON.stringify(raw)};
        state.board={nodes:[{id:'failed',type:'creative',position:{x:0,y:0},data:{kind:'image',title:'生成图像',generating:false,error:raw}}],edges:[]};
        state.epoch++;
        state.messages=[{role:'assistant',status:'running',content:'已保留其他方案。\\n\\n本次生成失败：'+raw,steps:designSteps([{phase:'tool',message:'调用工具：generate_image'},{phase:'error',message:'工具失败：generate_image · '+raw}],'running')}];
        state.busy=true;state.error=raw;state.progress=raw;
      })()`);
      await js(`new Promise((resolve,reject)=>{const avatar=document.querySelector('.agent-avatar-sprite'),style=getComputedStyle(avatar,'::after'),image=new Image();image.onload=resolve;image.onerror=reject;image.src=style.backgroundImage.slice(5,-2)})`);
      await pause(800);
      const check=await js(`(()=>{
        const label=document.querySelector('.design-message-agent'),avatar=label.querySelector('.agent-avatar-sprite').getBoundingClientRect(),name=label.querySelector('strong').getBoundingClientRect();
        return{name:label.textContent.trim(),right:name.left>=avatar.right,aligned:Math.abs((name.top+name.height/2)-(avatar.top+avatar.height/2))<3,
          visible:document.querySelector('.design-chat-panel').innerText+' '+document.querySelector('.design-media-error').innerText,
          titleLeak:[...document.querySelectorAll('[title]')].some(el=>el.title.includes('HTTP')),avatarImage:getComputedStyle(label.querySelector('.agent-avatar-sprite'),'::after').backgroundImage,avatarSize:getComputedStyle(label.querySelector('.agent-avatar-sprite'),'::after').backgroundSize,rawPreserved:state.board.nodes[0].data.error};
      })()`);
      assert.equal(check.name,'小居');assert(check.right&&check.aligned);
      assert.equal(await js(`document.querySelector('.design-chat-title strong').textContent`),'小居');
      assert(check.avatarImage.includes('lumo-composer-mountain-cloud-v2.png'));assert.equal(check.avatarSize,'300% 200%');
      assert(check.visible.includes('本轮执行未完成'));assert(check.visible.includes('已保留其他方案'));
      for(const text of ['HTTP','OpenRouter','Gemini','STOP','400'])assert(!check.visible.includes(text),text);
      assert(!check.titleLeak);assert.equal(check.rawPreserved,raw);
      fs.writeFileSync(path.join(output,'dark.png'),(await win.webContents.capturePage()).toPNG());
      await js("document.documentElement.dataset.theme='light'");await pause(100);
      fs.writeFileSync(path.join(output,'light.png'),(await win.webContents.capturePage()).toPNG());
      console.log(JSON.stringify({passed:true,checks:['小居 name aligned beside the mountain-cloud avatar','node, execution, reply, progress and error banner show readable failure','no raw error in tooltips; diagnostic data preserved']}));
      win.destroy();app.exit(0);
    }catch(error){console.error(error);fs.writeFileSync(path.join(output,'error.png'),(await win.webContents.capturePage()).toPNG());win.destroy();app.exit(1);}
  });
}
