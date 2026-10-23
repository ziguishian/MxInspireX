const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
if(!process.versions.electron){
  (async()=>{
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5299,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/design-check',async(req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/design-check',fs.readFileSync(path.join(__dirname,'fixtures/canvas-workspace.html'),'utf8').replace("modelOptions:['test-image']", "runWorkflowNode:async(...args)=>{window.generated.push(args);if(window.failStep)return false;const n=state.board.nodes.find(n=>n.id===args[3].canvasNodeId);n.data={...n.data,draft:false,assetId:'result-'+n.id,asset:{id:'result-'+n.id,mime:args[0]==='video'?'video/mp4':'image/png'}};await nextTick();return true;},modelOptions:['test-image']")))});
    await server.listen();const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
    try{process.exitCode=await new Promise(resolve=>require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'}).on('exit',code=>resolve(code??1)));}finally{await server.close();}
  })().catch(e=>{console.error(e);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.setPath('userData',path.join(root,'.tmp/workflow-profile'));
  app.whenReady().then(async()=>{
    const win=new BrowserWindow({show:false,width:1400,height:950,webPreferences:{backgroundThrottling:false}});
    const js=s=>win.webContents.executeJavaScript(s),wait=()=>new Promise(r=>setTimeout(r,300));
    try{
      await win.loadURL('http://127.0.0.1:5299/design-check');
      for(let i=0;i<50&&!await js('!!window.ready');i++)await wait();
      assert.equal(await js(`!!document.querySelector('.design-chat-header [aria-label="保存工作流"]')`),false);
      await js(`document.querySelector('[aria-label="收起对话"]').click()`);await wait();
      assert.ok(await js(`(()=>{const h=document.querySelector('.canvas-compact-header [aria-label="返回首页"]').getBoundingClientRect(),s=document.querySelector('.canvas-compact-header [aria-label="保存工作流"]').getBoundingClientRect();return h.width>0&&s.left>h.right&&Math.abs(h.top-s.top)<1&&h.width===s.width&&h.height===s.height})()`));
      await js(`document.querySelector('[aria-label="展开对话"]').click()`);await wait();
      for(let i=0;i<10&&await js(`document.querySelector('.canvas-compact-dock').getBoundingClientRect().height>0`);i++)await wait();
      assert.equal(await js(`document.querySelector('.canvas-compact-dock').getBoundingClientRect().height`),0);
      await js(`document.querySelector('.vue-flow__pane').dispatchEvent(new MouseEvent('dblclick',{bubbles:true,clientX:700,clientY:300}));`);await wait();
      assert.equal(await js(`document.activeElement.getAttribute('aria-label')`),'搜索节点');
      await js(`const search=document.activeElement;search.value='text';search.dispatchEvent(new Event('input',{bubbles:true}));`);await wait();
      assert.equal(await js(`document.querySelectorAll('.canvas-node-search-results button').length`),1);
      assert.equal(await js(`document.querySelector('.canvas-node-search-results button').textContent.trim()`),'文本');
      await js(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));`);await wait();
      assert.ok(await js(`state.board.nodes.some(n=>n.data.kind==='text')`));
      assert.equal(await js(`!!document.querySelector('.canvas-node-search')`),false);
      await js(`document.querySelector('.vue-flow__pane').dispatchEvent(new MouseEvent('dblclick',{bubbles:true,clientX:700,clientY:300}));`);await wait();
      await js(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));`);await wait();
      assert.equal(await js(`!!document.querySelector('.canvas-node-search')`),false);
      console.log('PASS canvas double-click search, autofocus, filtering, Enter add, Escape close');
      await js(`state.board={nodes:[{id:'input',type:'creative',position:{x:0,y:0},data:{kind:'text',text:'reference',title:'source'}},{id:'image',type:'creative',position:{x:500,y:0},data:{kind:'image',prompt:'make image'}},{id:'video',type:'creative',position:{x:1400,y:0},data:{kind:'video',prompt:'make video'}}],edges:[{id:'a',source:'input',target:'image'},{id:'b',source:'image',target:'video'}]};state.epoch++;void 0`);await wait();
      await js(`document.querySelector('[aria-label="增加运行次数"]').click();document.querySelector('[aria-label="运行工作流"]').click()`);
      for(let i=0;i<40 && await js(`!!document.querySelector('[aria-label="停止后续"]')`);i++)await wait();
      assert.equal(await js('generated.length'),4);
      assert.equal(await js("state.board.nodes.find(n=>n.id==='input').data.text"),'reference');
      assert.equal(await js("generated[1][3].source_asset_ids.length"),1);
      assert.notEqual(await js('generated[0][3].canvasNodeId'),await js('generated[2][3].canvasNodeId'));
      await js(`generated.length=0;window.failStep=true;document.querySelector('[aria-label="运行工作流"]').click()`);await wait();await wait();
      assert.equal(await js('generated.length'),1);
      assert.ok((await js('errors')).some(e=>e.includes('暂停')));
      await js(`window.failStep=false;errors.length=0;state.board={nodes:[{id:'folder',type:'creative',position:{x:0,y:0},data:{kind:'upload',workflowFolder:true,folderEntries:[],title:'文件夹'}}],edges:[]};state.epoch++;void 0`);await wait();
      await js(`const input=document.querySelector('input[webkitdirectory]'),dt=new DataTransfer();dt.items.add(new File(['first'],'first.txt',{type:'text/plain'}));dt.items.add(new File(['second'],'second.txt',{type:'text/plain'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));`);await wait();await wait();
      assert.equal(await js('state.board.nodes.length'),1);
      assert.equal(await js('state.board.nodes[0].data.folderEntries.length'),2);
      await js(`generated.length=0;state.board.nodes.push({id:'out',type:'creative',position:{x:700,y:0},data:{kind:'image',prompt:'make'}});state.board.edges.push({id:'link',source:'folder',target:'out'});state.epoch++;`);await wait();
      await js(`const count=document.querySelector('input[aria-label="运行次数"]');count.value='2';count.dispatchEvent(new Event('input',{bubbles:true}));count.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('[aria-label="运行工作流"]').click()`);
      for(let i=0;i<40&&await js(`!!document.querySelector('[aria-label="停止后续"]')`);i++)await wait();
      assert.equal(await js('generated.length'),4);
      assert.deepEqual(await js(`state.board.nodes.filter(n=>n.data.workflowRunId&&n.data.kind==='text').map(n=>n.data.text)`),['first','second','first','second']);
      assert.equal(await js(`state.board.nodes.find(n=>n.id==='folder').data.folderEntries.length`),2);
      console.log('PASS workflow repeated DAG, upstream output references, independent results, failure stop, folder batch upload');
      win.destroy();app.exit(0);
    }catch(error){console.error(error);win.destroy();app.exit(1);}
  });
}
