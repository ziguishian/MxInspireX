// All canvas node frames: real Vue Flow, Chromium pointer capture and persistence.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { createRequire } = require('node:module'), { pathToFileURL } = require('node:url');
const root = path.join(__dirname, '..'), local = createRequire(path.join(root, 'package.json'));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import(pathToFileURL(local.resolve('vite')).href);
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5293, strictPort: true, hmr: false }, logLevel: 'error' });
    const wav = Buffer.alloc(44 + 1600);
    wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8); wav.writeUInt32LE(16, 16);
    wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28);
    wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(1600, 40);
    const audio = `data:audio/wav;base64,${wav.toString('base64')}`;
    const model = `data:text/plain;base64,${Buffer.from('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n').toString('base64')}`;
    const html = `<html><body><div id="app"></div><script type="module">
      import {createApp,h,reactive,nextTick} from 'vue';import {useVueFlow} from '@vue-flow/core';
      import GeneralCanvas from '/src/components/GeneralCanvas.vue';import '/src/style.css';
      document.documentElement.dataset.theme='light';
      localStorage.setItem('langjuart.viewport.resize-check',JSON.stringify({x:650,y:160,zoom:.7}));
      let board={nodes:[],edges:[]};const state=reactive({canvasDocument:board,epoch:0});
      window.errors=[];window.changes=[];const nativeFetch=window.fetch.bind(window);
      window.fetch=async(url,options)=>{
        if(!String(url).startsWith('http://fixture.invalid/'))return nativeFetch(url,options);
        if(options?.method==='PATCH'){
          const change=JSON.parse(options.body);window.changes.push(change);
          for(const patch of change.upsertNodes){const index=board.nodes.findIndex(n=>n.id===patch.id);board.nodes[index]={...board.nodes[index],...patch};}
        }return Response.json(board);
      };
      createApp({setup(){const flow=useVueFlow('design-canvas');
        window.setView=async(view)=>{await flow.setViewport(view);await nextTick()};
        window.getView=()=>({...flow.viewport.value});
        window.getNode=()=>JSON.parse(JSON.stringify(flow.findNode('primary')));
        window.selectNode=()=>flow.addSelectedNodes([flow.findNode('primary')]);
        return()=>h(GeneralCanvas,{key:state.epoch,canvasDocument:state.canvasDocument,messages:[],busy:false,apiBaseUrl:'http://fixture.invalid',projectId:'resize-check',onCanvasChange:doc=>{board=doc;state.canvasDocument=doc},onCanvasError:error=>window.errors.push(error)});
      }}).mount('#app');
      const raster=document.createElement('canvas');raster.width=200;raster.height=100;raster.getContext('2d').fillRect(0,0,200,100);const image=raster.toDataURL('image/png');
      const stream=raster.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),chunks=[];
      const recorded=new Promise(resolve=>{recorder.ondataavailable=event=>chunks.push(event.data);recorder.onstop=()=>resolve(URL.createObjectURL(new Blob(chunks,{type:'video/webm'})))});
      recorder.start();setTimeout(()=>{recorder.stop();stream.getTracks().forEach(track=>track.stop())},350);
      const video=await recorded;
      window.prepare=async(kind)=>{
        const data={kind,title:kind+' 尺寸测试'};
        if(kind==='image')Object.assign(data,{kind:'upload',localFile:image,asset:{mime:'image/png',metadata:{imageOutput:{warning:'测试较长的图片状态说明，连接点仍应保持在图片内容的垂直中心，不受这段文字影响。'}}}});
        if(kind==='video')Object.assign(data,{localFile:video,asset:{mime:'video/webm'}});
        if(kind==='audio')Object.assign(data,{localFile:${JSON.stringify(audio)},asset:{mime:'audio/wav'}});
        if(kind==='3d')Object.assign(data,{localFile:${JSON.stringify(model)},asset:{pathRelative:'sample.obj'}});
        if(kind==='document')Object.assign(data,{localFile:'data:text/plain,hello',asset:{mime:'application/pdf'}});
        if(kind==='text')Object.assign(data,{text:'这是需要自动换行和滚动查看的长文本内容。'.repeat(100),textStyle:{fontSize:18}});
        if(kind==='failed')Object.assign(data,{kind:'image',error:'fixture failure'});
        if(kind==='html')Object.assign(data,{html:'<h1>旧网页尺寸</h1>',htmlPreviewSize:{width:700,height:450}});
        board={nodes:[{id:'primary',type:'creative',position:{x:0,y:0},data},{id:'neighbor',type:'creative',position:{x:1100,y:80},data:{kind:'text',text:'保持不变'}}],edges:[{id:'edge',source:'primary',target:'neighbor',sourceHandle:'output',targetHandle:'input'}]};
        state.canvasDocument=board;await nextTick();
      };
      window.restore=async()=>{state.canvasDocument=JSON.parse(JSON.stringify(board));state.epoch++;await nextTick()};
      window.reloadMedia=async()=>{board.nodes[0].data.localFile=image+'#replacement';state.canvasDocument=JSON.parse(JSON.stringify(board));await nextTick()};
      window.setLocked=async(locked)=>{state.canvasDocument={...board,lockedNodeIds:locked?['primary']:[]};await nextTick()};
      window.ready=true;
    </script><style>html,body,#app{height:100%;margin:0}*{transition:none!important}</style></body></html>`;
    server.middlewares.use('/resize-check', async (_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(await server.transformIndexHtml('/resize-check', html)); });
    await server.listen(); const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(local('electron'), [__filename, 'http://127.0.0.1:5293/resize-check'], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = local('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1700, height: 1200, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code);
    const prefix = '.vue-flow__node[data-id="primary"] ';
    const box = selector => js(`(()=>{const r=document.querySelector(${JSON.stringify(prefix + selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}})()`);
    win.webContents.debugger.attach('1.3');
    const mouse = (type, x, y, held = false) => win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type, x: Math.round(x), y: Math.round(y), button: type === 'mouseMoved' && !held ? 'none' : 'left', buttons: type === 'mousePressed' || held ? 1 : 0, clickCount: type === 'mouseMoved' ? 0 : 1 });
    const key = async (keyCode, modifiers = []) => { win.webContents.sendInputEvent({ type: 'keyDown', keyCode, modifiers }); win.webContents.sendInputEvent({ type: 'keyUp', keyCode, modifiers }); await pause(180); };
    const near = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 2, `${label}: ${actual} ≠ ${expected}`);
    const frameSize = async () => { const surface = await box('.design-node-surface'), view = await js('getView()'); return { width: surface.width / view.zoom, height: surface.height / view.zoom }; };
    try {
      await win.loadURL(process.argv[2]); win.focus(); win.webContents.focus();
      for (let i = 0; i < 100 && !(await js('!!window.ready')); i++) await pause(100);
      const results = [];
      for (const kind of ['image', 'video', 'audio', 'text', 'upload', '3d', 'document', 'failed', 'html']) {
        await mouse('mouseMoved', 20, 20); await js('document.activeElement?.blur()');
        await js(`prepare(${JSON.stringify(kind)})`); await pause(400);
        for (let i = 0; i < 50 && await js(`document.querySelector(${JSON.stringify(prefix + '[aria-busy]')})?.getAttribute('aria-busy')==='true'`); i++) await pause(100);
        await js('selectNode()'); await pause(200); await js('setView({x:650,y:160,zoom:.7})'); await pause(150);
        const original = await js('getNode()'), start = await frameSize(), viewport = await js('getView()');
        const grip = await box('.design-node-resize');
        assert.equal(await js(`getComputedStyle(document.querySelector(${JSON.stringify(prefix + '.design-node-resize')})).opacity`), '0', kind + ': selected node shows resize control without hover');
        const surfaceBefore = await box('.design-node-surface');
        for (const side of ['left', 'right']) {
          const handle = await box('.vue-flow__handle-' + side);
          near(handle.y + handle.height / 2, surfaceBefore.y + surfaceBefore.height / 2, kind + ' initial ' + side + ' handle centered on content');
        }
        const header = await box('header');
        await mouse('mouseMoved', header.x + 10, header.y + 5); await pause(80);
        await mouse('mouseMoved', surfaceBefore.x + surfaceBefore.width / 2, surfaceBefore.y + 1); await pause(100);
        await mouse('mouseMoved', surfaceBefore.x + surfaceBefore.width / 2, surfaceBefore.y + surfaceBefore.height / 2); await pause(150);
        assert.equal(await js(`getComputedStyle(document.querySelector(${JSON.stringify(prefix + '.design-node-resize')})).opacity`), '1', kind + ': hover reveals resize control');
        assert.ok((await box('.design-node-resize svg')).width / viewport.zoom <= 12.1, kind + ': resize icon stays compact');
        if (kind === 'image') {
          const article = await box('.design-asset-node');
          fs.writeFileSync('/tmp/aics-node-hover-check.png', (await win.webContents.capturePage({ x: Math.floor(article.x - 15), y: Math.floor(article.y - 10), width: Math.ceil(article.width + 30), height: Math.ceil(article.height + 20) })).toPNG());
        }
        await mouse('mouseMoved', grip.x + grip.width / 2, grip.y + grip.height / 2);
        await mouse('mousePressed', grip.x + grip.width / 2, grip.y + grip.height / 2);
        await mouse('mouseMoved', grip.x + grip.width / 2 + 70, grip.y + grip.height / 2 + 56, true); await pause(100);
        assert.deepEqual(await js('getView()'), viewport, kind + ': viewport jumped during resize');
        await mouse('mouseReleased', grip.x + grip.width / 2 + 70, grip.y + grip.height / 2 + 56); await pause(220);
        const resized = await js('getNode()'); near(resized.data.previewSize.width, start.width + 100, kind + ' width'); near(resized.data.previewSize.height, start.height + 80, kind + ' height');
        assert.deepEqual(resized.position, original.position, kind + ': resize moved node');
        await mouse('mouseMoved', grip.x + 160, grip.y + 130); await pause(100);
        assert.deepEqual((await js('getNode()')).data.previewSize, resized.data.previewSize, kind + ': continued resizing after release');
        const article = await box('.design-asset-node'), handle = await box('.vue-flow__handle-right'); near(handle.x + handle.width / 2, article.right + 6 * (await js('getView()')).zoom, kind + ' connection handle');
        const surfaceAfter = await box('.design-node-surface'), leftHandle = await box('.vue-flow__handle-left');
        near(handle.y + handle.height / 2, surfaceAfter.y + surfaceAfter.height / 2, kind + ' resized handle centered on content');
        near(handle.y + handle.height / 2, leftHandle.y + leftHandle.height / 2, kind + ' handles aligned');
        await mouse('mouseMoved', 20, 20); await js('document.activeElement?.blur()'); await pause(80);
        assert.equal(await js(`getComputedStyle(document.querySelector(${JSON.stringify(prefix + '.design-node-resize')})).opacity`), '0', kind + ': leaving hides resize control');
        const endpoint = await js(`(()=>{const path=document.querySelector('.vue-flow__edge-path');const p=path.getPointAtLength(0),screen=new DOMPoint(p.x,p.y).matrixTransform(path.getScreenCTM());return {x:screen.x,y:screen.y}})()`);
        assert.ok(Math.abs(endpoint.x - handle.x - handle.width / 2) <= handle.width / 2 + 2, kind + ': edge detached from resized handle');
        near(endpoint.y, handle.y + handle.height / 2, kind + ' connection path');
        const size = await frameSize(); near(size.width, resized.data.previewSize.width, kind + ' displayed width'); near(size.height, resized.data.previewSize.height, kind + ' displayed height');
        if (kind === 'image' || kind === 'video') assert.equal(await js(`getComputedStyle(document.querySelector(${JSON.stringify(prefix + (kind === 'image' ? 'img' : 'video'))})).objectFit`), 'contain');
        if (kind === 'text') assert.equal(await js(`(()=>{const p=document.querySelector(${JSON.stringify(prefix + '.design-asset-caption')});p.scrollTop=80;return p.scrollTop>0&&p.scrollWidth<=p.clientWidth&&getComputedStyle(p).fontSize==='18px'})()`), true);
        if (kind === '3d') { const viewer = await box('.cad-model-viewer'); near(viewer.height, (await box('.design-node-surface')).height, '3D fills frame'); }
        if (kind === 'audio' || kind === 'video') assert.equal(await js(`document.querySelector(${JSON.stringify(prefix + kind)}).readyState>=1`), true, kind + ' metadata loaded');
        await js('document.querySelector(".design-canvas-area").focus()');
        await key('z', ['meta']); assert.deepEqual((await js('getNode()')).data.previewSize, original.data.previewSize, kind + ' undo');
        await key('z', ['meta', 'shift']); assert.deepEqual((await js('getNode()')).data.previewSize, resized.data.previewSize, kind + ' redo');
        await js('restore()'); await pause(250); assert.deepEqual((await js('getNode()')).data.previewSize, resized.data.previewSize, kind + ' restored size');
        if (kind === 'image') { await js('reloadMedia()'); await pause(150); assert.deepEqual((await js('getNode()')).data.previewSize, resized.data.previewSize); }
        await key('TAB'); await js(`document.querySelector(${JSON.stringify(prefix + '.design-node-resize')}).focus()`); await pause(80);
        assert.equal(await js(`getComputedStyle(document.querySelector(${JSON.stringify(prefix + '.design-node-resize')})).opacity`), '1', kind + ': keyboard focus reveals resize control');
        await key('RIGHT');
        assert.equal((await js('getNode()')).data.previewSize.width, resized.data.previewSize.width + 20, kind + ' keyboard sizing');
        await js('setLocked(true)'); await pause(100); assert.equal(await js(`document.querySelector(${JSON.stringify(prefix + '.design-node-resize')}).disabled`), true); await js('setLocked(false)');
        results.push({ kind, size: resized.data.previewSize });
      }
      assert.deepEqual(await js('window.errors'), []);
      fs.writeFileSync('/tmp/aics-node-resize-check.png', (await win.webContents.capturePage()).toPNG());
      console.log(JSON.stringify({ passed: true, nodes: results, persistedChanges: await js('window.changes.length') }));
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); console.error(await js('window.errors').catch(() => []));
      fs.writeFileSync('/tmp/aics-node-resize-error.png', (await win.webContents.capturePage()).toPNG()); win.destroy(); app.exit(1);
    }
  });
}
