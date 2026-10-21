// Real Vue/ResizeObserver layout with an isolated canvas and no provider.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
if(!process.versions.electron){
  (async()=>{
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5332,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/layout-check',async(_req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/layout-check',fs.readFileSync(path.join(__dirname,'fixtures/canvas-workspace.html'),'utf8')));});
    const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
    try{await server.listen();process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});}
    finally{await server.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false,partition:'auto-layout-lock-fixture'}});
    const js=code=>win.webContents.executeJavaScript(code);
    const wait=async code=>{for(let i=0;i<100;i++){if(await js(code).catch(()=>false))return;await pause(50);}throw new Error('Timed out: '+code);};
    try{
      await win.loadURL('http://127.0.0.1:5332/layout-check');await wait('window.ready');
      await js(`window.patches=[];window.race=false;const originalFetch=window.fetch;
        window.fetch=async(url,options={})=>{
          if(options.method==='PATCH'){
            const changes=JSON.parse(options.body);patches.push(changes);
            if(window.race){window.race=false;state.board={...state.board,lockedNodeIds:['a','b']};return Response.json({detail:'这个节点正被当前任务使用'},{status:409});}
          }
          return originalFetch(url,options);
        };
        state.epoch++;state.board={nodes:['a','b'].map((id,i)=>({id,type:'creative',position:{x:0,y:0},data:{kind:'text',title:id,text:'初始内容',autoPositioned:true,autoLayoutOrder:i}})),edges:[],lockedNodeIds:['a','b']};void 0`);
      await pause(600);
      assert.equal(await js('patches.length'),0,'locked automatic nodes cannot be patched');
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>({...n,data:{...n.data,text:'增加内容改变节点尺寸\\n'.repeat(10)}}))};void 0`);
      await pause(500);assert.equal(await js('patches.length'),0,'ResizeObserver must respect task locks');
      await js(`state.board={...state.board,lockedNodeIds:['a']};void 0`);
      await wait('patches.length>0');await pause(250);
      assert.ok(await js(`patches.every(p=>p.upsertNodes.every(n=>n.id==='b'))`),'locked nodes are obstacles, not movable targets');
      assert.deepEqual(await js(`JSON.parse(JSON.stringify(state.board.nodes.find(n=>n.id==='a').position))`),{x:0,y:0});
      assert.ok(await js(`(()=>{const p=state.board.nodes.find(n=>n.id==='b').position;return p.x!==0||p.y!==0})()`),'unlock triggers deferred repair');
      // A lock arriving after layout was calculated remains a quiet deferred
      // layout conflict, not a failed image generation or raw JSON error.
      await js(`state.board={...state.board,lockedNodeIds:['a','b'],nodes:state.board.nodes.map(n=>({...n,position:{x:0,y:0}}))};void 0`);await pause(250);
      await js(`patches.length=0;window.race=true;state.board={...state.board,lockedNodeIds:['a']};void 0`);
      await wait('patches.length===1 && !window.race');await pause(400);
      assert.equal(await js('patches.length'),1,'no automatic conflict retry loop');
      assert.deepEqual(await js('window.errors'),[],'lock race must not surface as a generation failure');
      await js(`state.board={...state.board,lockedNodeIds:[]};void 0`);await wait('patches.length>1');await pause(300);
      assert.deepEqual(await js('window.errors'),[]);
      console.log(JSON.stringify({passed:true,checks:['locked resize causes no writes','unlocked nodes avoid locked obstacles','unlock repairs layout','409 race stays quiet and defers until unlock']}));
    }catch(error){console.error(error);fs.writeFileSync('/private/tmp/langju-auto-layout-error.png',(await win.webContents.capturePage()).toPNG());process.exitCode=1;}
    finally{win.destroy();app.exit(process.exitCode||0);}
  });
}
