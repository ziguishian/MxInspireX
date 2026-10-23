const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
if(!process.versions.electron){
  (async()=>{
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5298,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/design-check',async(req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/design-check',fs.readFileSync(path.join(__dirname,'fixtures/canvas-workspace.html'),'utf8').replace("modelOptions:['test-image']","modelOptions:['test-image','gpt-image-2.5-flare','gpt-image-2.5-sunburst']")))});
    await server.listen();const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
    try{process.exitCode=await new Promise(resolve=>require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'}).on('exit',code=>resolve(code??1)));}finally{await server.close();}
  })().catch(e=>{console.error(e);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.setPath('userData',path.join(root,'.tmp/design-nodes-profile'));
  app.whenReady().then(async()=>{
    const win=new BrowserWindow({show:false,width:1400,height:950,webPreferences:{backgroundThrottling:false}});
    const js=s=>win.webContents.executeJavaScript(s),wait=()=>new Promise(r=>setTimeout(r,300));
    try{
      await win.loadURL('http://127.0.0.1:5298/design-check');
      for(let i=0;i<50&&!await js('!!window.ready');i++)await wait();
      await js(`state.board={nodes:[{id:'p',type:'creative',position:{x:0,y:0},data:{kind:'text',editor:'palette',title:'色板',colors:['#FF0000'],text:'配色',draft:false}}],edges:[]};state.epoch++;void 0`);await wait();
      assert.equal(await js('document.querySelectorAll("input[type=color]").length'),1);
      await js(`const color=document.querySelector('input[type=color]');color.value='#00ff00';color.dispatchEvent(new Event('input',{bubbles:true}));color.dispatchEvent(new Event('change',{bubbles:true}));`);await wait();
      assert.equal(await js(`state.board.nodes[0].data.colors[0]`),'#00ff00');
      await js(`state.board={nodes:[{id:'primary',type:'creative',position:{x:0,y:0},data:{kind:'video',draft:true}},{id:'s',type:'creative',position:{x:800,y:0},data:{kind:'text',editor:'storyboard',title:'分镜',text:'old',shots:[{description:'远景',duration:2,camera:''},{description:'特写',duration:3,camera:'推近'}]}}],edges:[{id:'e',source:'s',target:'primary'}]};state.epoch++;void 0`);await wait();await js('select()');await wait();
      assert.equal(await js('document.querySelectorAll(".shot-row").length'),2);
      await js(`const p=document.querySelector('.canvas-prompt-panel textarea');p.value='按分镜生成视频';p.dispatchEvent(new Event('input',{bubbles:true}));`);
      await js(`document.querySelector('.canvas-prompt-panel form')?.requestSubmit()`);await wait();
      // Exercise the form's actual send control if the composer is not a form.
      if(!await js('generated.length')){await js(`document.querySelector('.canvas-prompt-panel .prompt-submit')?.click()`);await wait();}
      assert.equal(await js('generated.length'),1);
      assert.equal(await js('generated[0][3].duration'),5);
      assert.ok((await js('generated[0][1]')).includes('特写'));
      await js(`generated.length=0;state.board={nodes:[{id:'source',type:'creative',position:{x:0,y:0},data:{kind:'image',title:'原图',assetId:'original',asset:{id:'original',mime:'image/png'},draft:false}}],edges:[]};state.epoch++;void 0`);await wait();
      await js(`document.querySelector('.vue-flow__node').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:700,clientY:300}));`);await wait();
      assert.ok(await js(`Array.from(document.querySelectorAll('.canvas-context-menu button')).some(b=>b.textContent.includes('矢量'))`));
      await js(`const b=Array.from(document.querySelectorAll('.canvas-context-menu button')).find(b=>b.textContent.includes('一键抠图'));b.click();b.click();`);await wait();
      assert.equal(await js('generated.length'),1);
      assert.equal(await js('generated[0][3].model'),'gpt-image-2.5-flare');
      assert.equal(await js('generated[0][3].background'),'transparent');
      assert.deepEqual(await js('generated[0][3].source_asset_ids'),['original']);
      assert.equal(await js(`state.board.nodes.find(n=>n.id==='source').data.assetId`),'original');
      assert.deepEqual(await js('errors'),[]);
      console.log('PASS palette editing, storyboard video submission, cutout single submit and original preservation');
      win.destroy();app.exit(0);
    }catch(error){console.error(error);win.destroy();app.exit(1);}
  });
}
