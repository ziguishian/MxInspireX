// Project-card previews in real Chromium, with disposable local media only.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const assert = require('node:assert/strict'), { spawn, execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const origin = 'http://127.0.0.1:5313';
const html = title => `<style>body{margin:0;background:#e4efd5;color:#254231;font:24px system-ui}main{padding:70px}h1{font-size:72px}img{width:180px;height:100px}button{padding:20px;background:#284633;color:white}</style><main><small>DESIGN / WEB</small><h1>${title}</h1><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=="><p>项目画布中的网页内容</p><button>打开页面</button></main>`;
if (!process.versions.electron) {
  (async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aics-project-previews-'));
    const ffmpeg = execFileSync(path.join(root, 'services/api/.venv/bin/python'), ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { encoding: 'utf8' }).trim();
    execFileSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path.join(dir, 'video.mp4')]);
    const video = fs.readFileSync(path.join(dir, 'video.mp4'));
    const image = fs.readFileSync(path.join(root, 'apps/renderer/public/assets/home-design-examples-v1.png'));
    const node = (id, kind, data = {}, position = { x: 0, y: 0 }) => ({ id, position, data: { kind, title: id, ...data } });
    const boards = [
      { revision: '1', nodes: [node('图片', 'image', { assetId: 'image' }), node('视频', 'upload', { assetId: 'video', asset: { mime: 'video/mp4' }, previewSize: { width: 360, height: 240 } }, { x: 350, y: 0 }), node('说明', 'text', { text: '图片、视频与文本保持原来的位置。' }, { x: 350, y: 300 })], edges: [{ id: 'edge', source: '图片', target: '视频' }] },
      { revision: '1', nodes: [node('page', 'html', { htmlNodeId: 'page', previewSize: { width: 960, height: 640 } })], edges: [] },
      { revision: '1', nodes: [node('uploaded', 'upload', { assetId: 'html', asset: { mime: 'text/html', pathRelative: 'index.html' }, previewSize: { width: 960, height: 640 } })], edges: [] },
      { revision: '1', nodes: [node('missing', 'video', { assetId: 'missing' }), node('audio', 'audio', { assetId: 'audio' }, { x: 350, y: 0 }), node('empty', 'html', { htmlNodeId: null }, { x: 0, y: 300 })], edges: [] },
      // Old backend records have no htmlNodeId or revision metadata.
      { nodes: [node('legacy', 'html')], edges: [] },
    ];
    let revision = 1, requests = [];
    const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5313, strictPort: true, hmr: false }, logLevel: 'error' });
    server.middlewares.use((req, res, next) => {
      const json = data => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };
      if (req.url === '/fixture/requests') return json(requests);
      if (req.url === '/fixture/update') { revision++; return json({}); }
      if (!req.url.startsWith('/api/')) return next();
      requests.push(req.url);
      if (req.url.includes('/canvas/html/')) {
        const id = decodeURIComponent(req.url.split('/').at(-1));
        if (id === 'empty') { res.statusCode = 404; return json({}); }
        return json({ html: html(id === 'legacy' ? '兼容原有项目' : revision === 1 ? '让自然走进日常' : '更新后的页面') });
      }
      const id = req.url.match(/\/assets\/(\w+)\/content$/)?.[1];
      const bytes = id === 'video' ? video : id === 'image' ? image : id === 'html' ? Buffer.from(html('上传的网页')) : null;
      if (!bytes) { res.statusCode = 404; return json({}); }
      res.setHeader('Content-Type', id === 'video' ? 'video/mp4' : id === 'image' ? 'image/png' : 'text/html');
      res.setHeader('Accept-Ranges', 'bytes');
      const range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
      if (range) {
        const start = Number(range[1]), end = Math.min(range[2] ? Number(range[2]) : bytes.length - 1, bytes.length - 1);
        res.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${bytes.length}`, 'Content-Length': end - start + 1 });
        return res.end(bytes.subarray(start, end + 1));
      }
      res.setHeader('Content-Length', bytes.length); res.end(bytes);
    });
    server.middlewares.use('/project-preview-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/project-preview-check', `<!doctype html><html data-theme="dark"><meta charset="utf-8"><body><div id="app"></div><script type="module">
        import {createApp,h,ref,nextTick} from 'vue';import ProjectCard from '/src/components/projects/ProjectCard.vue';import '/src/style.css';
        const boards=ref(${JSON.stringify(boards)});window.opened=[];window.loads=[];
        window.refresh=async()=>{await fetch('/fixture/update');boards.value[0]={...boards.value[0],revision:'2'};boards.value[1]={...boards.value[1],revision:'2'};await nextTick()};
        createApp({setup(){return()=>h('div',{class:'fixtures'},boards.value.map((board,i)=>h('div',{class:i===4?'offscreen':'',id:'card-'+i},[h(ProjectCard,{project:{id:'p'+i,name:['混合画布','网页设计','上传网页','状态提示','历史项目'][i],brief:'项目缩略图验证',previewRevision:board.revision},board,apiBaseUrl:location.origin,loadPreview:async p=>window.loads.push(p.id),rename:async()=>{},onOpen:id=>window.opened.push(id)})])))}}).mount('#app');await nextTick();window.ready=true;
      </script><style>html,body{margin:0;min-width:0}#app{padding:40px;max-width:1100px;margin:auto}.fixtures{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.project-card-cover{height:260px!important}.offscreen{grid-column:1;margin-top:1600px}</style></body></html>`));
    });
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen();
      process.exitCode = await new Promise((resolve, reject) => { const child = spawn(require('electron'), [__filename], { env, stdio: 'inherit' }); child.on('error', reject); child.on('exit', code => resolve(code ?? 1)); });
    } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1280, height: 1000, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'project-preview-fixture' } });
    const js = code => win.webContents.executeJavaScript(code, true);
    const wait = async (code, label) => { for (let i = 0; i < 160; i++) { if (await js(code).catch(() => false)) return; await pause(50); } throw new Error('Timeout: ' + label); };
    const shot = async name => fs.writeFileSync(path.join(os.tmpdir(), `aics-project-previews-${name}.png`), (await win.webContents.capturePage()).toPNG());
    try {
      await win.loadURL(origin + '/project-preview-check'); await wait('window.ready', 'mount');
      await wait(`document.querySelector('#card-0 video')?.readyState>=2 && document.querySelector('#card-0 video').currentTime>0`, 'decoded still frame');
      await wait(`document.querySelector('#card-0 img')?.naturalWidth>0`, 'image inside SVG');
      await wait(`document.querySelectorAll('iframe').length===2 && [...document.querySelectorAll('[data-kind="html"]')].every(el=>el.getAttribute('aria-busy')==='false')`, 'canvas and uploaded HTML');
      assert.equal(await js(`document.querySelector('#card-0 video').paused && document.querySelector('#card-0 video').muted && !document.querySelector('#card-0 video').controls`), true);
      assert.equal(await js(`getComputedStyle(document.querySelector('#card-0 video')).objectFit`), 'contain');
      assert.equal(await js(`document.querySelector('[data-node-id="视频"] rect').getAttribute('width')`), '360');
      assert.equal(await js(`document.querySelector('[data-node-id="视频"]').getAttribute('transform')`), 'translate(350,0)');
      assert.ok(await js(`document.querySelector('#card-0 .project-board-preview > path').getAttribute('d').startsWith('M300,')`));
      const frames = win.webContents.mainFrame.frames.filter(frame => frame.url === 'about:srcdoc');
      assert.equal(frames.length, 2);
      assert.deepEqual((await Promise.all(frames.map(frame => frame.executeJavaScript('document.querySelector("h1").textContent')))).sort(), ['上传的网页', '让自然走进日常'].sort());
      for (const frame of frames) {
        assert.equal(await frame.executeJavaScript('innerWidth'), 1440);
        assert.equal(await frame.executeJavaScript('document.querySelector("img").naturalWidth'), 1);
        assert.equal(await frame.executeJavaScript('(()=>{try{return !!parent.document.body}catch{return false}})()'), false);
        assert.equal(await frame.executeJavaScript(`fetch('${origin}/fixture/requests').then(()=>true,()=>false)`), false);
      }
      await wait(`document.querySelector('#card-3 .library-thumbnail-status')?.textContent.includes('暂时无法预览')`, 'missing media fallback');
      assert.ok(await js(`document.querySelector('#card-3').textContent.includes('音频') && document.querySelector('#card-3').textContent.includes('暂无网页')`));
      assert.equal(await js(`!!document.querySelector('#card-4 iframe')`), false);
      assert.ok(!(await (await fetch(origin + '/fixture/requests')).json()).some(url => url.endsWith('/legacy') || url.endsWith('/empty')));
      await shot('cards');
      // Clicking the webpage still opens the project; iframe content is inert.
      const target = await js(`(()=>{const r=document.querySelector('#card-1 iframe').getBoundingClientRect();return {x:Math.round(r.x+30),y:Math.round(r.y+50)}})()`);
      win.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...target });
      win.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...target });
      await wait(`window.opened.includes('p1')`, 'card opens from webpage click');
      await js('window.refresh()');
      await wait(`document.querySelector('#card-1 iframe')?.srcdoc.includes('更新后的页面')`, 'revision refresh');
      await wait(`[...document.querySelectorAll('#card-0 .library-media-thumbnail')].every(el=>el.getAttribute('aria-busy')==='false')`, 'image and video settle after canvas edit');
      await js(`document.querySelector('#card-4').scrollIntoView({block:'center'})`);
      await wait(`!!document.querySelector('#card-4 iframe')`, 'legacy lazy preview');
      await wait(`!document.querySelector('#card-0 video') && !document.querySelector('#card-1 iframe')`, 'offscreen media released');
      await js('scrollTo(0,0)'); await wait(`document.querySelector('#card-0 video')?.readyState>=2`, 'video remount after scrolling');
      await wait(`document.querySelector('#card-1 iframe')?.srcdoc.includes('更新后的页面')`, 'updated page remount');
      win.setSize(700, 1000); await js(`document.documentElement.dataset.theme='light'`); await pause(200);
      const updatedFrame = win.webContents.mainFrame.frames.find(frame => frame.url === 'about:srcdoc');
      assert.equal(await updatedFrame.executeJavaScript('innerWidth'), 1440, 'card width must not change webpage breakpoint');
      await shot('light');
      console.log('PASS: image/video/HTML in SVG; still frame, saved sizes and edges; uploaded HTML; sandbox; card clicks; revision refresh; lazy loading and cleanup; legacy previews; light theme.');
    } catch (error) { console.error(error); await shot('error'); process.exitCode = 1; }
    finally { win.destroy(); app.exit(process.exitCode || 0); }
  });
}
