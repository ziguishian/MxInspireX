// Real Chromium pointer capture, Vue Flow gestures, autosave and reference wiring.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(r=>setTimeout(r,ms));
if(!process.versions.electron){
  (async()=>{
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5309,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/drawing-check',async(_req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/drawing-check',fs.readFileSync(path.join(__dirname,'fixtures/drawing-canvas.html'),'utf8')));});
    await server.listen();const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
    try{process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename,'http://127.0.0.1:5309/drawing-check'],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});}finally{await server.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();const win=new BrowserWindow({show:false,width:1550,height:1050,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    const js=code=>win.webContents.executeJavaScript(code),q=JSON.stringify;
    const click=selector=>js(`document.querySelector(${q(selector)}).click()`);
    const box=selector=>js(`(()=>{const r=document.querySelector(${q(selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()`);
    const wait=async(condition)=>{for(let i=0;i<80;i++){if(await js(condition))return;await pause(100);}throw new Error('Timed out: '+condition);};
    win.webContents.debugger.attach('1.3');
    const mouse=(type,x,y,held=false,button='left')=>win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type,x,y,button:type==='mouseMoved'&&!held?'none':button,buttons:type==='mousePressed'||held?(button==='right'?2:1):0,clickCount:type==='mouseMoved'?0:1});
    const paint=async()=>{const r=await box('[aria-label="布局画板绘画区"]');await mouse('mousePressed',r.x+r.width*.2,r.y+r.height*.2);await mouse('mouseMoved',r.x+r.width*.7,r.y+r.height*.6,true);await mouse('mouseReleased',r.x+r.width*.7,r.y+r.height*.6);};
    try{
      await win.loadURL(process.argv[2]);win.focus();win.webContents.focus();await wait('!!window.ready');await pause(300);
      await js(`document.querySelector('[aria-label="隐藏画布观察视图"]')?.click();void 0`);
      await mouse('mousePressed',1300,700,false,'right');await mouse('mouseReleased',1300,700,false,'right');
      await wait('!!document.querySelector(".canvas-context-menu")');
      await js(`Array.from(document.querySelectorAll('.canvas-context-menu button')).find(b=>b.textContent.includes('新增节点')).click()`);
      await js(`Array.from(document.querySelectorAll('.canvas-action-menu button')).find(b=>b.textContent.trim()==='画板').click()`);
      await wait('!!document.querySelector(".canvas-drawing-pad canvas")');await js('position(.7)');await pause(300);
      const origin=await js('JSON.stringify(flow.findNode("drawing").position)'),view=await js('JSON.stringify(flow.viewport.value)');
      await paint();await wait('saved.length===1');
      assert.equal(await js('JSON.stringify(flow.findNode("drawing").position)'),origin,'Drawing must not drag the node');
      assert.equal(await js('JSON.stringify(flow.viewport.value)'),view,'Drawing must not pan the canvas');
      const points=await js('saved[0].drawing.strokes[0].points');assert.ok(Math.abs(points[0][0]-204.8)<3&&Math.abs(points[0][1]-153.6)<3);
      assert.ok(await js(`(()=>{const c=document.querySelector('.canvas-drawing-pad canvas'),p=c.getContext('2d').getImageData(205,154,1,1).data;return p[0]<100})()`),'Visible stroke is rendered');
      await click('[aria-label="撤销笔迹"]');await wait('saved.length===2');assert.equal(await js('saved.at(-1).drawing.strokes.length'),0);
      await click('[aria-label="重做笔迹"]');await wait('saved.length===3');assert.equal(await js('saved.at(-1).drawing.strokes.length'),1);
      await click('.drawing-reference');assert.equal(await js('references.at(-1)'),'@asset:drawing-png-3');
      await js('restore()');await pause(300);await js('position(1.1)');await pause(250);
      assert.ok(await js(`document.querySelector('.drawing-reference').disabled===false`),'Saved board restores as a reference');
      await click('[aria-label="橡皮"]');await paint();await wait('saved.length===4');assert.equal(await js('saved.at(-1).drawing.strokes.at(-1).tool'),'eraser');
      await js('failNext=true');await click('[aria-label="画笔"]');await paint();await wait('!!document.querySelector(".drawing-error")');
      assert.equal(await js('document.querySelector(".drawing-reference").disabled'),true,'Unsaved strokes cannot reference a stale PNG');
      assert.ok(await js('!!localStorage.getItem("langju.drawing.drawing-check.drawing")'),'Failed save keeps local draft');
      await click('.drawing-status button');await wait('saved.length===5');
      await click('[aria-label="清空画板"]');await wait('saved.length===6');assert.equal(await js('state.board.nodes[0].data.assetId'),null);
      assert.equal(await js('state.board.nodes.length'),1,'Clear keeps the drawing node');
      await click('[aria-label="撤销笔迹"]');await wait('saved.length===7');
      await js('addTarget()');await pause(300);
      await js(`(()=>{const field=document.querySelector('.vue-flow__node[data-id="target"] textarea');field.value='按草图布局制作正式海报';field.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await click('.vue-flow__node[data-id="target"] .prompt-submit');await wait('generated.length===1');
      assert.deepEqual(await js('generated[0][3].source_asset_ids'),['drawing-png-7']);
      assert.equal(await js('state.board.nodes[0].data.editor'),'drawing');assert.deepEqual(await js('errors'),[]);
      await js('position(.8)');await pause(150);fs.writeFileSync('/tmp/aics-drawing-canvas.png',(await win.webContents.capturePage()).toPNG());
      assert.equal(await js('document.querySelector("[aria-label=清空画板]").textContent.trim()'),'清空');
      assert.equal(await js('document.querySelector("[aria-label=删除画板节点]").textContent.trim()'),'删除');
      await js('failDelete=true');await click('[aria-label="删除画板节点"]');await wait('errors.length===1');
      await wait('document.querySelector("[aria-label=删除画板节点]").disabled===false');
      assert.equal(await js('state.board.nodes.length'),2,'Failed deletion preserves both nodes');
      await js('saveDelay=1000');await paint();await wait('writing');
      await click('[aria-label="删除画板节点"]');await wait('!state.board.nodes.some(n=>n.id==="drawing")');
      assert.equal(await js('deletedWhileWriting'),false,'Deletion waits for the in-flight save');
      assert.deepEqual(await js('state.board.nodes.map(n=>n.id)'),['target'],'Deletes this board, not the selected target');
      assert.equal(await js('state.board.edges.length'),0,'Deletes incident edges');
      assert.equal(await js('localStorage.getItem("langju.drawing.drawing-check.drawing")'),null,'Deletes the local draft');
      const savesAfterDeletion=await js('saved.length');await pause(800);
      assert.equal(await js('saved.length'),savesAfterDeletion,'Unmount never saves a deleted board');
      console.log('PASS: drawing and references, clear preserves node, targeted delete with edges, failed-delete recovery, in-flight save ordering and draft cleanup');
    }catch(error){console.error(error);console.error(await js('JSON.stringify({nodes:state.board.nodes,saved,errors,status:document.querySelector(".drawing-status")?.textContent,undo:document.querySelector("[aria-label=撤销笔迹]")?.disabled})'));fs.writeFileSync('/tmp/aics-drawing-canvas-error.png',(await win.webContents.capturePage()).toPNG());process.exitCode=1;}finally{win.destroy();app.quit();}
  });
}
