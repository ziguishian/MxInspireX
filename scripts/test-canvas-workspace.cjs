// Isolated Chromium regression: real Vue Flow and prompt controls, fixture API only.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(r=>setTimeout(r,ms));
if(!process.versions.electron){
  (async()=>{
    const {createServer}=await import('vite');
    const server=await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5296,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/workspace-check',async(req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/workspace-check',fs.readFileSync(path.join(__dirname,'fixtures/canvas-workspace.html'),'utf8')))});
    try { await server.listen(); } catch(error) { await server.close(); throw error; } const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
    try{process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename,'http://127.0.0.1:5296/workspace-check'],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});}finally{await server.close();}
  })().catch(e=>{console.error(e);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();const win=new BrowserWindow({show:false,width:1500,height:1050,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    win.webContents.session.webRequest.onBeforeRequest({urls:['http://fixture.invalid/*/content']},(_details,callback)=>callback({redirectURL:new URL('/assets/langju-agent-sprite.png',process.argv[2]).href}));
    const js=code=>win.webContents.executeJavaScript(code).catch(error=>{throw new Error(code.slice(0,250)+': '+error.message);}),q=JSON.stringify;
    const click=selector=>js(`document.querySelector(${q(selector)}).click()`);
    const visible=selector=>js(`!!document.querySelector(${q(selector)})?.getClientRects().length`);
    const rect=selector=>js(`(()=>{const r=document.querySelector(${q(selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}})()`);
    const field=async(selector,value)=>{await js(`(()=>{const el=document.querySelector(${q(selector)});el.value=${q(value)};el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));})()`);await pause(60);};
    const panel='.vue-flow__node[data-id="primary"] .canvas-prompt-panel';
    const key=async(keyCode,modifiers=[])=>{win.webContents.sendInputEvent({type:'keyDown',keyCode,modifiers});win.webContents.sendInputEvent({type:'keyUp',keyCode,modifiers});await pause(160);};
    win.webContents.debugger.attach('1.3');
    const mouse=(type,x,y,button='left',held=false,count=1)=>win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type,x,y,button: type==='mouseMoved'&&!held?'none':button,buttons:type==='mousePressed'||held?(button==='middle'?4:1):0,clickCount:type==='mouseMoved'?0:count});
    const results=[];
    try{
      await win.loadURL(process.argv[2]);win.focus();win.webContents.focus();
      for(let i=0;i<100&&!await js('!!window.ready');i++)await pause(100);
      await pause(300);
      // Keep the fixed gesture coordinates on the main canvas; overview
      // navigation and its visible layout are covered by test-canvas-overview.
      await js(`document.querySelector('[aria-label="隐藏画布观察视图"]')?.click();void 0`);
      for(let i=0;i<3;i++){
        await click('[aria-label="收起对话"]');await pause(500);
        assert.ok(!await visible('[aria-label="对话输入框"]'));assert.ok(!await visible('.design-chat-scroll'));
        assert.ok(await visible('.canvas-agent-toggle .agent-avatar-sprite'));assert.ok(await visible('.canvas-compact-tools'));
        const dock=await rect('.canvas-compact-dock');assert.ok(dock.width<=60,'collapsed chat only occupies the tool rail');
        const home=await rect('.canvas-compact-dock .canvas-home-button'),tools=await rect('.canvas-compact-tools'),avatar=await rect('.canvas-agent-toggle'),help=await rect('.support-fab');
        assert.ok(Math.abs(home.y-dock.y)<1,'home stays at the top');
        assert.ok(Math.abs((tools.y+tools.height/2)-(dock.y+dock.height/2))<1,'tools stay vertically centered');
        assert.ok(Math.abs(avatar.bottom-help.bottom)<1,'avatar aligns with the bottom help button');
        assert.equal(await js('getComputedStyle(document.querySelector(".canvas-agent-toggle")).borderRadius'),await js('getComputedStyle(document.querySelector(".support-fab")).borderRadius'));
        await click('[aria-label="展开对话"]');await pause(500);
        assert.ok(await visible('[aria-label="对话输入框"]'));assert.equal(await js('document.querySelector("[aria-label=对话输入框]").value'),'保留输入中的设计需求');
      }results.push('collapse shows avatar and vertical tools; expand preserves mounted composer and draft');
      const before=await js('flow.viewport.value.zoom');
      await mouse('mousePressed',1350,800);await mouse('mouseReleased',1350,800);await mouse('mousePressed',1350,800,'left',false,2);await mouse('mouseReleased',1350,800,'left',false,2);await pause(150);
      assert.ok(await visible('.canvas-action-menu'));assert.equal(await js('flow.viewport.value.zoom'),before);assert.equal(await js('document.querySelectorAll(".canvas-action-menu button").length'),8);
      await click('.canvas-action-menu button');await pause(200);assert.equal(await js('state.board.nodes.length'),3);results.push('double-click adds a node without zooming');
      for(const kind of ['image','video','audio','text','upload','html']){
        await js(`reset(${q(kind)})`);await pause(200);await key('ESC');assert.ok(!await visible(panel));
        await js('select()');await pause(250);
        const p=await rect(panel);
        assert.ok(Math.abs(p.width-480)<2,kind+': composer stays 480 screen pixels wide');
        const originalView=await js('({...flow.viewport.value})');
        await js('flow.setMinZoom(.05)');
        for(const zoom of [.05,.2,.5,1,2,8]) {
          await js(`(()=>{const card=document.querySelector('.vue-flow__node[data-id="primary"] .design-asset-node');return flow.setViewport({x:850-card.offsetWidth*${zoom}/2,y:280-card.offsetHeight*${zoom},zoom:${zoom}})})()`);await pause(120);
          const metrics=await js(`(()=>{const panel=document.querySelector(${q(panel)}),card=panel.previousElementSibling.getBoundingClientRect(),r=panel.getBoundingClientRect(),button=panel.querySelector('.prompt-submit').getBoundingClientRect(),field=panel.querySelector('textarea');return {width:r.width,height:r.height,gap:r.top-card.bottom,center:r.x+r.width/2-card.x-card.width/2,button:button.width,text:parseFloat(getComputedStyle(field).fontSize)*r.width/panel.offsetWidth,hit:panel.contains(document.elementFromPoint(button.x+button.width/2,button.y+button.height/2))}})()`);
          assert.ok(Math.abs(metrics.width-480)<2 && Math.abs(metrics.height-p.height)<2,kind+': stable panel dimensions at '+zoom);
          assert.ok(Math.abs(metrics.gap-10)<1 && Math.abs(metrics.center)<1,kind+': panel follows the node at '+zoom);
          assert.ok(metrics.button>=30 && metrics.text>=12.9 && metrics.hit,kind+': readable and clickable at '+zoom);
          assert.ok(Math.abs((await js('flow.viewport.value.zoom'))-zoom)<.001,'requested zoom is applied');
          if(zoom===.2 && kind==='image') {
            const settings=await rect(panel+' .prompt-settings-toggle');
            await mouse('mousePressed',settings.x+settings.width/2,settings.y+settings.height/2);await mouse('mouseReleased',settings.x+settings.width/2,settings.y+settings.height/2);await pause(120);
            assert.ok(await visible(panel+' .prompt-options'),'parameter menu opens through a real click at 20%');
            fs.writeFileSync('/tmp/aics-node-controls-20-percent.png',(await win.webContents.capturePage()).toPNG());
            await click(panel+' [aria-label="关闭参数"]');
          }
        }
        await js(`flow.setMinZoom(.2);flow.setViewport(${q(originalView)})`);await pause(120);
        assert.equal(await js(`!!document.querySelector(${q(panel+' .prompt-reference-image')})`),false);
        await click(panel+' header button');await click(panel+' .prompt-assistance button');assert.ok((await js(`document.querySelector(${q(panel+' textarea')}).value`)).length>5);
        await click(panel+' header button:nth-child(2)');await click(panel+' .prompt-assistance button');await click(panel+' header button:nth-child(2)');
        await click(panel+' .prompt-expand');assert.ok(await js(`document.querySelector(${q(panel)}).classList.contains('is-expanded')`));await click(panel+' .prompt-expand');
        const modelKind=kind==='upload'?'image':kind==='html'?'text':kind;
        await field(panel+' .prompt-select select','test-'+modelKind);
        if(['image','upload','video'].includes(kind)){
          await click(panel+' .prompt-settings-toggle');
          await field(panel+' .prompt-advanced-grid select','9:16');
          if(kind!=='video')await field(panel+' [aria-label="图像背景"]','transparent');
          else await field(panel+' .prompt-advanced-grid input',8);
          await click(panel+' [aria-label="关闭参数"]');
          await click(panel+' .prompt-footer-tool');await field(panel+' .prompt-advanced-grid input','电影感');await click(panel+' [aria-label="关闭参数"]');
          await js(`(()=>{const input=document.querySelector(${q(panel+' input[type=file]')}),dt=new DataTransfer();dt.items.add(new File(['fixture'],'reference.png',{type:'image/png'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);await pause(160);
          assert.ok(await visible(panel+' .prompt-reference-image'));
        }
        if(kind==='audio'){
          await click(panel+' .prompt-settings-toggle');await field(panel+' .prompt-advanced-grid input[type=number]',0);await click(panel+' .prompt-submit');assert.ok(await visible(panel+' [role=alert]'));await field(panel+' .prompt-advanced-grid input[type=number]',1.5);await click(panel+' [aria-label="关闭参数"]');
        }
        await field(panel+' textarea','测试内容 '+kind);await click(panel+' .prompt-submit');await pause(150);
        const output=await js('JSON.parse(JSON.stringify(generated.at(-1)))');assert.equal(output[0],kind==='upload'?'image':kind);assert.equal(output[3].model,'test-'+modelKind);
        if(['image','upload'].includes(kind)){assert.equal(output[3].background,'transparent');assert.equal(output[3].source_asset_id,'uploaded-reference');assert.equal(output[3].style,'电影感');assert.equal(Object.hasOwn(output[3],'referenceModes'),false);assert.equal(await visible(panel+' .prompt-reference-modes'),false);}
        if(kind==='video')assert.equal(output[3].duration,8);
        if(kind==='audio')assert.equal(output[3].speed,1.5);
        // Every blank-node task owns its loading state locally, including
        // image and upload-created image placeholders.
        assert.equal(await visible('.vue-flow__node[data-id="primary"] .design-media-loading'),true);
        await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='primary'?{...n,data:{...n.data,generating:false,draft:false,text:'已生成'}}:n)};void 0`);await pause(160);
        assert.equal(await js('state.board.nodes.length'),2);results.push(kind+' prompt controls, parameters, upload and generation placeholder');
      }
      await js('reset("image")');await pause(180);await js('select()');await pause(180);
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='primary'?{...n,data:{...n.data,params:{source_asset_id:'uploaded-to-card'}}}:n)};void 0`);await pause(100);
      assert.ok(await visible(panel+' .prompt-reference-image'));results.push('upload to card updates mounted reference preview');
      await js('document.querySelector(".design-canvas-area").focus()');await key('RIGHT',['shift']);assert.equal(await js('state.board.nodes[0].position.x'),10);await key('z',['meta']);assert.equal(await js('state.board.nodes[0].position.x'),0);await key('z',['meta','shift']);assert.equal(await js('state.board.nodes[0].position.x'),10);
      await key('a',['meta']);assert.equal(await js('flow.getSelectedNodes.value.length'),2);await key('d',['meta']);assert.equal(await js('state.board.nodes.length'),4);await key('z',['meta']);assert.equal(await js('state.board.nodes.length'),2);results.push('select all, nudge, duplicate, undo and redo');
      await js('reset("image")');await pause(200);
      await js("state.board={...state.board,nodes:[...state.board.nodes,{id:'third',type:'creative',position:{x:600,y:420},data:{kind:'text',text:'第三个节点'}}]};void 0");await pause(750);
      const handle=id=>'.vue-flow__node[data-id="'+id+'"] .vue-flow__handle';
      const drag=async(from,to)=>{const a=await rect(from),b=await rect(to);await mouse('mouseMoved',a.x+a.width/2,a.y+a.height/2);await mouse('mousePressed',a.x+a.width/2,a.y+a.height/2);for(let i=1;i<=8;i++){await mouse('mouseMoved',a.x+a.width/2+(b.x+b.width/2-a.x-a.width/2)*i/8,a.y+a.height/2+(b.y+b.height/2-a.y-a.height/2)*i/8,'left',true);await pause(25);}await mouse('mouseReleased',b.x+b.width/2,b.y+b.height/2);await pause(200);};
      await drag(handle('primary')+'-right',handle('neighbor')+'-left');assert.equal(await js('state.board.edges.length'),1);
      await drag('.vue-flow__edgeupdater-target',handle('third')+'-left');assert.equal(await js('state.board.edges[0].target'),'third');results.push('connect and reconnect workflow edges through actual pointer gestures');
      // Connected references are live inputs, not a frozen preview copied into a draft.
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='primary'?{...n,data:{kind:'image',title:'主体参考',assetId:'source-a'}}:n.id==='third'?{...n,data:{kind:'image',title:'生成结果',draft:true}}:n)};void 0`);await pause(450);
      await js(`select('third')`);await pause(250);
      const connectedPanel='.vue-flow__node[data-id="third"] .canvas-prompt-panel';
      assert.ok(await visible(connectedPanel+' [data-reference-node="primary"] img'));
      assert.ok(await js(`document.querySelector(${q(connectedPanel+' [data-reference-node="primary"] img')}).naturalWidth>0`));
      await drag(handle('neighbor')+'-right',handle('third')+'-left');await js(`select('third')`);await pause(250);
      assert.equal(await js(`document.querySelectorAll(${q(connectedPanel+' .prompt-linked-reference')}).length`),2);
      assert.equal(await visible(connectedPanel+' .prompt-reference-modes'),false);
      assert.ok((await js(`document.querySelector(${q(connectedPanel+' .prompt-reference-status')}).textContent`)).includes('已连接 2'));
      await field(connectedPanel+' textarea','保持主体，参考文字生成');await click(connectedPanel+' .prompt-submit');await pause(180);
      let connectedOutput=await js('JSON.parse(JSON.stringify(generated.at(-1)))');
      assert.deepEqual(connectedOutput[3].source_asset_ids,['source-a']);assert.deepEqual(connectedOutput[3].reference_node_ids,['primary','neighbor']);assert.equal(connectedOutput[3].canvasNodeId,'third');assert.equal(Object.hasOwn(connectedOutput[3],'referenceModes'),false);assert.ok(connectedOutput[1].includes('参考内容'));
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='third'?{...n,data:{...n.data,generating:false}}:n.id==='primary'?{...n,data:{...n.data,assetId:'source-b'}}:n)};void 0`);await pause(250);
      assert.ok((await js(`document.querySelector(${q(connectedPanel+' [data-reference-node="primary"] img')}).src`)).includes('source-b'));
      fs.writeFileSync('/tmp/aics-connected-references.png',(await win.webContents.capturePage()).toPNG());
      await js(`flow.addSelectedEdges([flow.findEdge(state.board.edges.find(e=>e.source==='primary').id)])`);await pause(120);await click('.canvas-edge-delete');await pause(250);await js(`select('third')`);await pause(150);
      assert.equal(await js(`document.querySelectorAll(${q(connectedPanel+' [data-reference-node="primary"]')}).length`),0);
      await click(connectedPanel+' .prompt-submit');await pause(150);connectedOutput=await js('JSON.parse(JSON.stringify(generated.at(-1)))');assert.deepEqual(connectedOutput[3].source_asset_ids,[]);assert.deepEqual(connectedOutput[3].reference_node_ids,['neighbor']);
      results.push('connected thumbnails and text preview; same inputs submitted; live output replacement and edge deletion remove stale references');
      const pan=await js('JSON.parse(JSON.stringify(flow.viewport.value))');
      await mouse('mousePressed',1350,800,'middle');await mouse('mouseMoved',1380,830,'middle',true);await mouse('mouseReleased',1380,830,'middle');await pause(150);
      assert.ok(Math.abs((await js('flow.viewport.value.x'))-pan.x-30)<2);results.push('middle-button canvas pan');
      const toolbar=await rect('.canvas-toolbar-actions'),support=await rect('.support-fab');assert.ok(toolbar.right<support.x);assert.equal(Math.round(toolbar.height),Math.round(support.height));
      for(const selector of ['[aria-label="缩小画布"]','[aria-label="放大画布"]','[aria-label="画布操作与快捷键"]'])assert.ok(await js(`(()=>{const el=document.querySelector(${q(selector)}),r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})()`));
      await click('[aria-label="画布操作与快捷键"]');await click('.canvas-shortcuts header button:nth-child(2)');assert.ok((await js('document.querySelector(".canvas-shortcuts").textContent')).includes('双击'));results.push('corner controls unobstructed and shortcuts tab usable');
      await click('[aria-label="关闭画布工具"]');
      await js('document.querySelector(".design-canvas-area").focus()');await key('ESC');
      win.setContentSize(390,844);await pause(500);
      for(const minimized of [false,true]) {
        if(minimized) {await click('[aria-label="收起对话"]');await pause(500);}
        const chat=await rect(minimized?'.canvas-agent-toggle':'.design-chat-panel'),controls=await rect('.canvas-toolbar-actions');
        assert.ok(minimized ? controls.x>=chat.right : controls.y>=chat.bottom,'narrow window: controls overlap chat or avatar');
        if(minimized) assert.ok(!await visible('[aria-label="对话输入框"]'));
        else assert.ok((await rect('[aria-label="对话输入框"]')).bottom<=chat.bottom,'narrow window: composer clipped');
        assert.ok(controls.x>=0&&controls.right<=390,'narrow window: controls clipped');
      }
      results.push('390px window keeps avatar dock/full composer clear of corner controls');
      await js(`select('third')`);await pause(400);
      const narrowPanel=await rect(connectedPanel),narrowDock=await rect('.canvas-compact-dock');
      assert.ok(Math.abs(narrowPanel.width-268)<1,'narrow panel leaves room for the centered toolbar without shrinking text');
      assert.ok(narrowPanel.x>=narrowDock.right+27 && narrowPanel.right<=363 && narrowPanel.y>=79 && narrowPanel.bottom<=769,'narrow panel is framed beside the tool rail');
      assert.ok((await rect(connectedPanel+' .prompt-submit')).width>=30,'narrow submit remains full size');
      fs.writeFileSync('/tmp/aics-node-controls-narrow.png',(await win.webContents.capturePage()).toPNG());
      results.push('node controls stay readable at 5–800% zoom and fit a 390px window');
      win.setContentSize(1500,1050);await pause(300);
      // Initial load fits the board; subsequent arrivals focus only new/changed outputs.
      const allVisible=(ids=null)=>js(`(()=>{
        const area=document.querySelector('.design-canvas-area').getBoundingClientRect(),chat=document.querySelector(document.querySelector('.design-workspace').classList.contains('chat-minimized')?'.canvas-compact-dock':'.design-chat-panel').getBoundingClientRect();
        return [...document.querySelectorAll('.design-asset-node,.design-asset-node>header,.canvas-prompt-panel')].filter(el=>el.getClientRects().length && (!${JSON.stringify(ids)} || ${JSON.stringify(ids)}.includes(el.closest('.vue-flow__node')?.dataset.id))).every(el=>{
          const r=el.getBoundingClientRect();
          return r.left>=area.left+20 && r.right<=area.right-20 && r.top>=area.top+65 && r.bottom<=area.bottom-75
            && (r.right<=chat.left || r.left>=chat.right+15 || r.bottom<=chat.top-15 || r.top>=chat.bottom);
        });
      })()`);
      await js(`localStorage.setItem('langjuart.viewport.workspace-interaction-fixture',JSON.stringify({x:-9999,y:-9999,zoom:2}));reset('image')`);await pause(850);
      assert.ok(await allVisible(),'initial board must override an offscreen saved viewport');
      await js(`state.board={nodes:[],edges:[]};void 0`);await pause(180);
      await js(`state.board={nodes:[{id:'first-output',position:{x:1400,y:900},data:{kind:'image',generating:true}}],edges:[]};void 0`);await pause(850);
      assert.ok(await allVisible(['first-output']),'first generating placeholder must be focused');
      await js(`state.board={...state.board,nodes:[...state.board.nodes,{id:'next-output',position:{x:9000,y:-4200},data:{kind:'image',generating:true}}]};void 0`);await pause(850);
      assert.ok(await allVisible(['next-output']),'new output must be focused without including distant old content');
      assert.ok(await js('flow.viewport.value.zoom>.2'),'new content stays readable instead of shrinking the whole board');
      assert.equal(await visible('.canvas-new-results'),false);
      await js(`state.board={...state.board,nodes:[...state.board.nodes,{id:'batch-one',position:{x:4500,y:3800},data:{kind:'image',generating:true}},{id:'batch-two',position:{x:4860,y:3900},data:{kind:'image',generating:true}}]};void 0`);await pause(850);
      assert.ok(await allVisible(['batch-one','batch-two']),'outputs arriving together are focused as one new batch');
      await js(`select('next-output')`);await pause(500);
      await js(`flow.setViewport({x:-6000,y:-6000,zoom:1})`);
      const portrait='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="900"><rect width="300" height="900" fill="seagreen"/></svg>');
      await js(`state.board={...state.board,nodes:state.board.nodes.map(n=>n.id==='next-output'?{...n,data:{kind:'image',generating:false,localFile:${q(portrait)}}}:n)};void 0`);await pause(850);
      assert.ok(await allVisible(['next-output']),'same-node completion and natural portrait size focus the updated output');
      const beforePan=await js('({...flow.viewport.value})');
      await mouse('mousePressed',1350,800,'middle');await mouse('mouseMoved',1390,830,'middle',true);await mouse('mouseReleased',1390,830,'middle');await pause(150);
      const manual=await js('({...flow.viewport.value})');assert.ok(Math.abs(manual.x-beforePan.x-40)<2);
      await js(`state.board=JSON.parse(JSON.stringify(state.board));void 0`);await pause(850);
      assert.deepEqual(await js('({...flow.viewport.value})'),manual,'unchanged polling must preserve manual pan');
      win.setContentSize(390,844);await pause(200);
      await js(`state.board={...state.board,nodes:[...state.board.nodes,{id:'mobile-output',position:{x:1400,y:1500},data:{kind:'text',text:'移动端新成果'}}]};void 0`);await pause(1000);
      assert.ok(await visible('[aria-label="展开对话"]'));
      assert.ok(await allVisible(['mobile-output']),'new output focus avoids the avatar dock and bottom controls');
      results.push('initial overview then focus only new/changed outputs; same-node media completion; manual pan survives polling; avatar dock avoided');
      assert.equal(await js('document.querySelectorAll(".design-canvas-heading").length'),0);assert.deepEqual(await js('window.errors'),[]);
      fs.writeFileSync('/tmp/aics-workspace-verified.png',(await win.webContents.capturePage()).toPNG());console.log(JSON.stringify({passed:true,checks:results}));win.destroy();app.exit(0);
    }catch(e){console.error(e);console.error(await js('window.errors').catch(()=>[]));fs.writeFileSync('/tmp/aics-workspace-error.png',(await win.webContents.capturePage()).toPNG());win.destroy();app.exit(1);}
  });
}
