// Real pointer/keyboard gestures against Vue Flow; all persistence is a fixture.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5331,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/selection-check',async (_req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/selection-check',fs.readFileSync(path.join(__dirname,'fixtures/canvas-workspace.html'),'utf8')));});
    const env = {...process.env}; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen();
      process.exitCode = await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code ?? 1));});
    } finally {await server.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
} else {
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async ()=>{
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:1500,height:1100,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false,partition:'canvas-selection-fixture'}});
    const js=code=>win.webContents.executeJavaScript(code).catch(error=>{throw new Error(code.slice(0,250)+': '+error.message);}), q=JSON.stringify;
    win.webContents.on('console-message', details => { if(details.level==='error') console.error('Renderer:',details.message); });
    const wait=async code=>{for(let i=0;i<100;i++){if(await js(code).catch(()=>false))return;await pause(40);}throw new Error('Timed out: '+code);};
    const key=async (keyCode,modifiers=[])=>{win.webContents.sendInputEvent({type:'keyDown',keyCode,modifiers});win.webContents.sendInputEvent({type:'keyUp',keyCode,modifiers});await pause(160);};
    const box=(id,child='')=>js(`(()=>{const r=document.querySelector(${q('.vue-flow__node[data-id="'+id+'"] '+child)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}})()`);
    const selected=()=>js('flow.getSelectedNodes.value.map(n=>n.id).sort()');
    const positions=()=>js('Object.fromEntries(state.board.nodes.map(n=>[n.id,{...n.position}]))');
    const viewport=()=>js('JSON.parse(JSON.stringify(flow.viewport.value))');
    const near=(a,b,label)=>assert.ok(Math.abs(a-b)<1.5,label+': '+a+' vs '+b);
    const checkToolbar=async()=>{
      const frames=await Promise.all((await selected()).map(id=>box(id))),toolbar=await js(`(()=>{const r=document.querySelector('.canvas-selection-toolbar').getBoundingClientRect();return {x:r.x,width:r.width,bottom:r.bottom}})()`);
      near(toolbar.x+toolbar.width/2,(Math.min(...frames.map(r=>r.x))+Math.max(...frames.map(r=>r.right)))/2,'toolbar centers on the whole selection');
      assert.ok(toolbar.bottom<Math.min(...frames.map(r=>r.y))-10,'toolbar stays above every selected node');
    };
    win.webContents.debugger.attach('1.3');
    const mouse=(type,x,y,held=false,modifiers=0,button='left')=>win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type,x,y,button:type==='mouseMoved'&&!held?'none':button,buttons:type==='mousePressed'||held?(button==='middle'?4:1):0,clickCount:type==='mouseMoved'?0:1,modifiers});
    const drag=async (start,end,modifiers=0,button='left')=>{
      await mouse('mouseMoved',start.x,start.y);await mouse('mousePressed',start.x,start.y,false,modifiers,button);
      for(let i=1;i<=10;i++){await mouse('mouseMoved',start.x+(end.x-start.x)*i/10,start.y+(end.y-start.y)*i/10,true,modifiers,button);await pause(22);}
      await mouse('mouseReleased',end.x,end.y,false,modifiers,button);await pause(220);
    };
    const marquee=async (ids,modifiers=0,reverse=false)=>{
      const boxes=await Promise.all(ids.map(id=>box(id)));
      const a={x:Math.min(...boxes.map(r=>r.x))-18,y:Math.min(...boxes.map(r=>r.y))-18},b={x:Math.max(...boxes.map(r=>r.right))+18,y:Math.max(...boxes.map(r=>r.bottom))+18};
      await drag(reverse?b:a,reverse?a:b,modifiers);
    };
    const reset=async zoom=>{
      await js(`state.epoch++;state.board={nodes:[{id:'a',type:'creative',position:{x:0,y:0},data:{kind:'image',title:'礼盒效果图',draft:true,previewSize:{width:220,height:160}}},{id:'b',type:'creative',position:{x:320,y:100},data:{kind:'html',title:'方案网页',html:'<h1>设计方案</h1><button>查看</button>',previewSize:{width:320,height:240}}},{id:'c',type:'creative',position:{x:820,y:240},data:{kind:'text',title:'说明',text:'方案说明：可选择复制的文字',previewSize:{width:210,height:170}}}],edges:[]};void 0`);
      await pause(650);await js(`document.querySelector('[aria-label="收起对话"]')?.click();select('a');void 0`);await pause(100);
      await key('Escape');await js(`flow.setViewport({x:150,y:170,zoom:${zoom}});patches=[];void 0`);await pause(180);
    };
    const checks=[];
    try {
      await win.loadURL('http://127.0.0.1:5331/selection-check');win.focus();win.webContents.focus();await wait('window.ready');
      // This suite's bottom-right gestures target the main canvas, not its navigator.
      await js(`document.querySelector('[aria-label="隐藏画布观察视图"]')?.click();void 0`);
      await js(`window.patches=[];const fixtureFetch=window.fetch;window.fetch=(url,options={})=>{if(options.method==='PATCH'){patches.push(JSON.parse(options.body));if(window.failNextPatch){window.failNextPatch=false;return Promise.resolve(new Response('fixture conflict',{status:409}));}}return fixtureFetch(url,options);};void 0`);
      for(const zoom of [.45,.85,1.25]) {
        await reset(zoom);const before=await positions(),view=await viewport();
        await marquee(['a','b'],0,zoom===1.25);
        assert.deepEqual(await selected(),['a','b'],'left marquee at '+zoom);
        assert.deepEqual(await viewport(),view,'selecting must not reframe the canvas');
        assert.equal(await js('patches.length'),0,'selection is local, no save');
        assert.ok(await js(`!!document.querySelector('.canvas-selection-toolbar')`));
        await checkToolbar();
        assert.equal(await js(`document.querySelectorAll('.canvas-selection-align button').length`),8);
        assert.ok(await js(`document.querySelector('.canvas-selection-align [aria-label="水平等距分布"]').disabled`));
        const header=await box('a','header');
        await drag({x:header.x+20*zoom,y:header.y+9*zoom},{x:header.x+20*zoom+75,y:header.y+9*zoom+45},1);
        const after=await positions();
        await checkToolbar();
        assert.ok(after.a.x>before.a.x+10 && after.a.y>before.a.y+10,'group actually moves');
        near(after.a.x-before.a.x,after.b.x-before.b.x,'group x offset');near(after.a.y-before.a.y,after.b.y-before.b.y,'group y offset');
        assert.deepEqual(after.c,before.c,'unselected node stays put');
        assert.equal(await js('patches.length'),1,'one batch persistence request');
        assert.deepEqual(await js('patches[0].upsertNodes.map(n=>n.id).sort()'),['a','b']);
        await key('z',['meta']);assert.deepEqual(await positions(),before,'one undo restores entire group');
        await key('z',['meta','shift']);assert.deepEqual(await positions(),after,'one redo restores entire group');
        await js('state.board=JSON.parse(JSON.stringify(state.board));void 0');await pause(100);assert.deepEqual(await positions(),after);
        checks.push('left marquee and persistent group drag at '+zoom+' zoom');
      }
      await reset(.85);await marquee(['a','b']);
      const groupStart=await js(`(()=>{const r=document.querySelector('.vue-flow__nodesselection-rect').getBoundingClientRect();return {x:r.x+22*.85,y:r.y-12*.85}})()`),beforeHandle=await positions();
      await drag(groupStart,{x:groupStart.x+45,y:groupStart.y+35},1);
      const afterHandle=await positions();assert.ok(afterHandle.a.x>beforeHandle.a.x+10,'selection handle moves group');near(afterHandle.a.x-beforeHandle.a.x,afterHandle.b.x-beforeHandle.b.x,'selection handle preserves spacing');await key('z',['meta']);assert.deepEqual(await positions(),beforeHandle);
      await marquee(['c'],8);
      assert.deepEqual(await selected(),['a','b','c'],'Shift marquee adds to selection');
      const node=await box('c','header');
      await mouse('mousePressed',node.x+15,node.y+6,false,8);await mouse('mouseReleased',node.x+15,node.y+6,false,8);await pause(180);
      assert.deepEqual(await selected(),['a','b'],'Shift click toggles one node');
      await key('Escape');assert.deepEqual(await selected(),[]);
      await marquee(['a','b','c']);
      const view=await viewport(),beforeAlign=await positions();
      const clickAlign=async label=>{await js(`document.querySelector('.canvas-selection-align [aria-label="${label}"]').click()`);await pause(180);};
      for(const [label,coordinate] of [['左对齐',r=>r.x],['水平居中',r=>r.x+r.width/2],['右对齐',r=>r.right],['顶对齐',r=>r.y],['垂直居中',r=>r.y+r.height/2],['底对齐',r=>r.bottom]]) {
        await clickAlign(label);const frames=await Promise.all(['a','b','c'].map(id=>box(id,'.design-node-surface')));frames.forEach(r=>near(coordinate(r),coordinate(frames[0]),label));
        assert.deepEqual(await viewport(),view,'alignment keeps viewport');await checkToolbar();await key('z',['meta']);assert.deepEqual(await positions(),beforeAlign);await checkToolbar();
      }
      for(const [label,axis,end] of [['水平等距分布','x','right'],['垂直等距分布','y','bottom']]) {
        await clickAlign(label);const frames=(await Promise.all(['a','b','c'].map(id=>box(id,'.design-node-surface')))).sort((a,b)=>a[axis]-b[axis]);
        near(frames[1][axis]-frames[0][end],frames[2][axis]-frames[1][end],label);await key('z',['meta']);assert.deepEqual(await positions(),beforeAlign);
      }
      await js(`document.querySelector('.vue-flow__nodesselection-rect')?.focus();void 0`);const beforeNudge=await positions();await key('Right');const nudged=await positions();for(const id of ['a','b','c'])near(nudged[id].x,beforeNudge[id].x+1,'group keyboard nudge');await key('z',['meta']);assert.deepEqual(await positions(),beforeNudge);
      checks.push('additive selection, toggle, eight alignment actions, equal spacing, keyboard nudge, undo/redo');
      await js(`failNextPatch=true;void 0`);const beforeFailure=await positions();await clickAlign('左对齐');assert.deepEqual(await positions(),beforeFailure,'failed batch save restores persisted board');assert.ok(await js(`errors.pop().includes('fixture conflict')`));
      await reset(.85);await js(`state.board={...state.board,lockedNodeIds:['c'],edges:[{id:'ac',source:'a',target:'c'}]};void 0`);await pause(150);await marquee(['a','b']);
      assert.equal(await js('flow.getSelectedEdges.value.length'),0,'marquee excludes incident edges');
      assert.ok(await js(`!document.querySelector('.canvas-selection-align [aria-label="左对齐"]').disabled`),'external locked node does not block alignment');
      await js(`state.board={...state.board,lockedNodeIds:['b']};void 0`);await pause(150);
      assert.ok(await js(`[...document.querySelectorAll('.canvas-selection-align button')].every(b=>b.disabled)`));
      const lockedBefore=await positions(),a=await box('a','header');await drag({x:a.x+20,y:a.y+8},{x:a.x+90,y:a.y+55});assert.deepEqual(await positions(),lockedBefore,'mixed locked selection cannot partially move');
      await js(`state.board={...state.board,lockedNodeIds:[]};document.querySelector('.design-canvas-area').focus();void 0`);await pause(100);await key('Escape');
      const blank={x:1250,y:850},pan=await viewport();await drag(blank,{x:1290,y:880},0,'middle');near((await viewport()).x,pan.x+40,'middle pan');assert.deepEqual(await selected(),[]);
      win.webContents.sendInputEvent({type:'keyDown',keyCode:'Space'});await pause(60);const space=await viewport();await drag(blank,{x:1280,y:870});win.webContents.sendInputEvent({type:'keyUp',keyCode:'Space'});near((await viewport()).x,space.x+30,'space left pan');assert.deepEqual(await selected(),[]);
      await reset(.85);
      const cancelBox=await box('a');await mouse('mousePressed',cancelBox.x-15,cancelBox.y-15);await mouse('mouseMoved',cancelBox.right+10,cancelBox.bottom+10,true);await pause(80);await key('Escape');await mouse('mouseReleased',cancelBox.right+10,cancelBox.bottom+10);await pause(100);
      assert.deepEqual(await selected(),[],'Escape cancels an active marquee');assert.ok(await js(`!document.querySelector('.vue-flow__selection')`));
      await marquee(['a','b']);
      for(const view of [{x:260,y:260,zoom:.6},{x:40,y:330,zoom:1.1}]) {
        await js(`flow.setViewport(${q(view)});void 0`);await pause(150);await checkToolbar();
      }
      for(const [width,theme] of [[1500,'dark'],[780,'light'],[430,'light']]) {
        win.setContentSize(width,1000);await js(`document.documentElement.dataset.theme='${theme}';flow.setViewport({x:${width/2-320*.85},y:240,zoom:.85});void 0`);await pause(250);await checkToolbar();
        assert.ok(await js(`(()=>{const el=document.querySelector('.canvas-selection-toolbar'),r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&el.scrollWidth<=el.clientWidth+1})()`),'toolbar fits '+width);
        fs.writeFileSync(`/private/tmp/aics-canvas-selection-${width}.png`,(await win.webContents.capturePage()).toPNG());
      }
      checks.push('locked group protection, failed-save recovery, middle/space pan, responsive toolbar centered above the full selection across moves, alignment, pan and zoom');
      assert.deepEqual(await js('window.errors'),[]);
      console.log(JSON.stringify({passed:true,checks},null,2));
    } catch(error) {console.error(error);fs.writeFileSync('/private/tmp/aics-canvas-selection-error.png',(await win.webContents.capturePage()).toPNG());process.exitCode=1;}
    finally {win.destroy();app.exit(process.exitCode||0);}
  });
}
