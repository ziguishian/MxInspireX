// Real Chromium coverage of the asset library, using only disposable local media.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const assert = require('node:assert/strict'), { spawn, execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const apiUrl = 'http://127.0.0.1:5312', pageUrl = 'http://127.0.0.1:5311/asset-library-check';
const webpage = `<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#e8eee7;color:#153c30;font:20px system-ui}main{padding:6vw}small{letter-spacing:4px}h1{font-size:clamp(32px,6vw,76px);margin:28px 0}p{max-width:36em;line-height:1.8}button{border:0;border-radius:99px;background:#294e3b;color:white;padding:16px 28px;font:inherit}.swatch{height:120px;border-radius:18px;background:linear-gradient(120deg,#a5bc9c,#294e3b);margin-top:40px}</style><main><small>LOCAL DESIGN / 01</small><h1>让自然，走进日常。</h1><p>网页产物预览 · 布局与交互保留在同一张画布中。</p><button onclick="this.textContent='已点击'">探索空间</button><div class="swatch"></div></main>`;
if (!process.versions.electron) {
  (async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aics-asset-library-'));
    const ffmpeg = execFileSync(path.join(root, process.platform === 'win32' ? 'services/api/.venv/Scripts/python.exe' : 'services/api/.venv/bin/python'), ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { encoding: 'utf8' }).trim();
    execFileSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24', '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path.join(dir, 'video.mp4')]);
    execFileSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', path.join(dir, 'audio.wav')]);
    const audio = fs.readFileSync(path.join(dir, 'audio.wav'));
    const model = Buffer.from('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n');
    const video = fs.readFileSync(path.join(dir, 'video.mp4'));
    const image = fs.readFileSync(path.join(root, 'apps/renderer/public/assets/home-design-examples-v1.png'));
    const base = { projectId: 'fixture', projectName: '预览验证', byteSize: 1024, createdAt: '2026-09-14' };
    const assets = [
      { ...base, id: 'image', kind: 'image', mime: 'image/png', pathRelative: '参考图片.png', byteSize: image.length },
      { ...base, id: 'retry', kind: 'image', mime: 'image/png', pathRelative: '重试图片.png', byteSize: image.length },
      { ...base, id: 'video', kind: 'video', mime: 'video/mp4', pathRelative: '空间 漫游.mp4', byteSize: video.length },
      { ...base, id: 'upload', kind: 'document', mime: 'text/html', pathRelative: '上传网页.html', byteSize: Buffer.byteLength(webpage) },
      { ...base, id: 'audio', kind: 'audio', mime: 'audio/wav', pathRelative: '录音.wav' },
      { ...base, id: 'model', kind: '3d', mime: 'model/obj', pathRelative: '模型.obj' },
    ];
    let revision = '1', failDocument = false, retryImageRequests = 0;
    const api = require('node:http').createServer((req, res) => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
      res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
      if (req.method === 'OPTIONS') { res.statusCode = 204; return res.end(); }
      const json = data => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };
      if (req.url === '/fixture/fail') { failDocument = true; return json({}); }
      if (req.url === '/fixture/update') { revision = '2'; return json({}); }
      if (req.url === '/fixture/image-attempts') return json({ count: retryImageRequests });
      if (req.url === '/api/references/from-asset' && req.method === 'POST') return json({ id: 'reference-image' });
      if (req.url === '/api/library/html') return json([{ ...base, id: 'canvas-html-page', htmlNodeId: 'page', kind: 'html', mime: 'text/html', pathRelative: revision === '1' ? '自然空间.html' : '更新页面.html', revision, byteSize: Buffer.byteLength(webpage) }]);
      if (req.url === '/api/projects/fixture/canvas/html/page') {
        if (failDocument) { failDocument = false; res.statusCode = 503; return json({}); }
        return json({ html: webpage, title: '自然空间' });
      }
      const id = new URL(req.url, 'http://fixture.invalid').pathname.match(/\/assets\/(\w+)\/content$/)?.[1];
      if (id === 'retry') {
        retryImageRequests += 1;
        if (retryImageRequests === 1) { res.statusCode = 503; return json({}); }
        if (retryImageRequests === 2) return setTimeout(() => {
          if (res.destroyed) return;
          res.setHeader('Content-Type', 'image/png');
          res.setHeader('Content-Length', image.length);
          res.end(image);
        }, 1_500);
      }
      const bytes = id === 'audio' ? audio : id === 'model' ? model : id === 'video' ? video : ['image', 'retry'].includes(id) ? image : id === 'upload' ? Buffer.from(webpage) : null;
      if (!bytes) { res.statusCode = 404; return json({}); }
      res.setHeader('Content-Type', id === 'audio' ? 'audio/wav' : id === 'model' ? 'model/obj' : id === 'video' ? 'video/mp4' : ['image', 'retry'].includes(id) ? 'image/png' : 'text/html');
      res.setHeader('Accept-Ranges', 'bytes');
      const range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
      if (range) {
        const start = Number(range[1]), end = Math.min(range[2] ? Number(range[2]) : bytes.length - 1, bytes.length - 1);
        res.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${bytes.length}`, 'Content-Length': end - start + 1 });
        return res.end(bytes.subarray(start, end + 1));
      }
      res.setHeader('Content-Length', bytes.length); res.end(bytes);
    });
    const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5311, strictPort: true, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/asset-library-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/asset-library-check', `<!doctype html><html data-theme="dark"><meta charset="utf-8"><body><div id="app"></div><script type="module">
        import {createApp,h,provide,ref,nextTick} from 'vue';import {createMemoryHistory,createRouter} from 'vue-router';import AssetsPage from '/src/pages/AssetsPage.vue';import {assetLibraryServices} from '/src/features/pageServices.ts';import '/src/style.css';
        const assets=ref(${JSON.stringify(assets)});window.deleted=[];window.opened=[];
        window.refresh=()=>{assets.value=[...assets.value]};
        window.addPages=()=>{assets.value.push(...Array.from({length:200},(_,i)=>({projectId:'fixture',projectName:'触底加载验证',id:'extra-'+i,kind:'document',mime:'application/pdf',pathRelative:'页面外资料-'+(i+1)+'.pdf',byteSize:100,createdAt:'2026-09-01'})))};
        const testApp=createApp({setup(){provide(assetLibraryServices.key,{loadState:{loading:ref(false),error:ref(''),retry(){}},globalAssets:assets,apiBaseUrl:${JSON.stringify(apiUrl)},assetDisplayName:asset=>asset.pathRelative,requestDeleteAsset:asset=>{window.deleted.push(asset.id);assets.value=assets.value.filter(item=>item.id!==asset.id)},openProject:id=>window.opened.push(id)});return()=>h(AssetsPage)}});
        testApp.use(createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]}));testApp.mount('#app');await nextTick();window.ready=true;
      </script><style>html,body{margin:0;min-width:0}#app{padding:40px;max-width:1080px;margin:auto}</style></body></html>`));
    });
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen(); await new Promise(resolve => api.listen(5312, '127.0.0.1', resolve));
      process.exitCode = await new Promise((resolve, reject) => { const child = spawn(require('electron'), [__filename, dir], { env, stdio: 'inherit' }); child.on('error', reject); child.on('exit', code => resolve(code ?? 1)); });
    } finally { await server.close(); api.closeAllConnections(); api.close(); fs.rmSync(dir, { recursive: true, force: true }); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const {registerHtmlExport}=await import(pathToFileURL(path.join(root,'dist/desktop/htmlExport.js')).href);registerHtmlExport();
    const win = new BrowserWindow({ show: false, width: 1280, height: 960, webPreferences: { preload: path.join(root,'dist/desktop/preload.js'), sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'asset-library-fixture' } });
    win.webContents.on('console-message', (_event, details) => { if (['warning', 'error'].includes(details.level)) console.error('Renderer:', details.message); });
    win.webContents.on('did-fail-load', (_event, code, description) => console.error('Load failed:', code, description));
    const js = code => win.webContents.executeJavaScript(code, true), downloads = [];
    const wait = async (code, label) => { for (let i = 0; i < 120; i++) { if (await js(code).catch(() => false)) return; await pause(50); } throw new Error('Timeout: ' + label); };
    const click = async selector => { await js(`document.querySelector(${JSON.stringify(selector)}).click()`); await pause(80); };
    const open = name => click(`[aria-label="放大预览 ${name}"]`);
    const frame = () => win.webContents.mainFrame.frames.filter(f => f.url === 'about:srcdoc').at(-1);
    const shot = async name => fs.writeFileSync(path.join(os.tmpdir(), `aics-asset-library-${name}.png`), (await win.webContents.capturePage()).toPNG());
    win.webContents.session.on('will-download', (_event, item) => {
      const file = path.join(process.argv[2], `download-${downloads.length}`); item.setSavePath(file);
      item.once('done', (_e, state) => downloads.push({ state, name: item.getFilename(), file }));
    });
    const download = async expectedName => {
      const n = downloads.length; await click('.asset-download-button');
      for (let i = 0; i < 100 && downloads.length === n; i++) await pause(50);
      assert.equal(downloads[n]?.state, 'completed'); assert.equal(downloads[n]?.name, expectedName);
      return fs.readFileSync(downloads[n].file);
    };
    try {
      await win.loadURL(pageUrl); win.focus(); win.webContents.focus(); await wait('window.ready', 'mount');
      await wait(`document.querySelectorAll('.asset-preview-trigger').length===7`, 'all media cards');
      await wait(`!!document.querySelector('[aria-label="放大预览 重试图片.png"] .library-thumbnail-loading')`, 'image loading skeleton');
      assert.equal(await js(`document.querySelector('[aria-label="放大预览 重试图片.png"] .library-thumbnail-loading').textContent.includes('正在加载预览')`), true);
      assert.ok((await js(`getComputedStyle(document.querySelector('[aria-label="放大预览 重试图片.png"] .library-thumbnail-loading'),'::before').animationName`)).includes('library-thumbnail-shimmer'));
      assert.equal(await js(`getComputedStyle(document.querySelector('[aria-label="放大预览 重试图片.png"] img')).opacity`), '0');
      assert.equal(await js(`getComputedStyle(document.querySelector('[aria-label="放大预览 重试图片.png"] img')).transform`), 'none');
      assert.ok(await js(`Number(getComputedStyle(document.querySelector('[aria-label="放大预览 重试图片.png"] .library-thumbnail-loading')).zIndex)>Number(getComputedStyle(document.querySelector('[aria-label="放大预览 重试图片.png"] img')).zIndex)`));
      assert.ok(await js(`(()=>{const card=document.querySelector('[aria-label="放大预览 重试图片.png"]').getBoundingClientRect(),host=document.querySelector('[aria-label="放大预览 重试图片.png"] .library-media-thumbnail').getBoundingClientRect();return Math.abs(card.width-host.width)<1})()`));
      await shot('loading');
      await wait(`document.querySelector('[aria-label="放大预览 重试图片.png"] img')?.naturalWidth>0 && !document.querySelector('[aria-label="放大预览 重试图片.png"] .library-media-thumbnail').classList.contains('is-loading')`, 'failed image request retry and decode');
      await wait(`Number(getComputedStyle(document.querySelector('[aria-label="放大预览 重试图片.png"] img')).opacity)>.99`, 'decoded image fade in');
      assert.equal(await js(`document.querySelector('[aria-label="放大预览 重试图片.png"] img').loading`), 'eager');
      assert.equal((await (await fetch(apiUrl + '/fixture/image-attempts')).json()).count, 2);
      assert.equal(await js(`!!document.querySelector('[aria-label="收藏 参考图片.png 到参考库"] svg')`), true);
      await click('[aria-label="收藏 参考图片.png 到参考库"]');
      await wait(`document.querySelector('[aria-label="已收藏 参考图片.png"]')?.getAttribute('aria-pressed')==='true'`, 'star collection state');
      await js(`document.querySelector('[aria-label="放大预览 参考图片.png"]').closest('article').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:1250,clientY:950}))`);
      await wait(`!!document.querySelector('.asset-save-menu')`, 'library card save menu');
      assert.equal(await js(`document.querySelector('.asset-save-menu button').textContent.trim()`),'保存图像');
      const cardCount=downloads.length;await click('.asset-save-menu button');
      for(let i=0;i<100&&downloads.length===cardCount;i++)await pause(50);
      assert.equal(downloads[cardCount]?.name,'参考图片.png');
      assert.deepEqual(fs.readFileSync(downloads[cardCount].file),fs.readFileSync(path.join(root,'apps/renderer/public/assets/home-design-examples-v1.png')));

      await wait(`document.querySelector('.library-media-thumbnail video')?.readyState>=2`, 'decoded video thumbnail');
      await wait(`document.querySelectorAll('.library-media-thumbnail iframe').length===2`, 'HTML thumbnails');
      assert.ok(await js(`(()=>{const img=document.querySelector('[aria-label="放大预览 参考图片.png"] img'),r=img.getBoundingClientRect();return Math.abs(r.width/r.height-img.naturalWidth/img.naturalHeight)<.01})()`));
      assert.equal(await js(`getComputedStyle(document.querySelector('.global-library-grid')).display`), 'grid');
      assert.equal(await js(`getComputedStyle(document.querySelector('.global-library-grid')).gridTemplateColumns.split(' ').length`), 4);
      assert.ok(await js(`Array.from(document.querySelectorAll('.global-library-card')).every(card=>getComputedStyle(card).gridRowEnd.startsWith('span'))`));
      assert.equal(await js(`getComputedStyle(document.querySelector('[aria-label="放大预览 参考图片.png"]').closest('article').querySelector('.global-library-card-info')).opacity`), '0');
      assert.equal(await js(`getComputedStyle(document.querySelector('.global-library-card-info'),'::before').backdropFilter`), 'none');
      assert.equal(await js(`getComputedStyle(document.querySelector('[aria-label="已收藏 参考图片.png"]')).opacity`), '0');
      const hoverPoint=await js(`(()=>{const r=document.querySelector('[aria-label="放大预览 参考图片.png"]').closest('article').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);
      win.webContents.sendInputEvent({type:'mouseMove',...hoverPoint});
      await wait(`Number(getComputedStyle(document.querySelector('[aria-label="放大预览 参考图片.png"]').closest('article').querySelector('.global-library-card-info')).opacity)>.98`, 'asset information hover reveal');
      await wait(`Number(getComputedStyle(document.querySelector('[aria-label="已收藏 参考图片.png"]')).opacity)>.98`, 'asset star hover reveal');
      assert.ok((await js(`getComputedStyle(document.querySelector('[aria-label="放大预览 参考图片.png"]').closest('article').querySelector('.global-library-card-info')).willChange`)).includes('transform'));
      assert.equal(await js(`document.querySelector('.library-video-duration').textContent`), '0:03');
      const hover = value => js(`document.querySelector('[data-kind="video"]').dispatchEvent(new PointerEvent(${JSON.stringify(value ? 'pointerenter' : 'pointerleave')}))`);
      await hover(true); await wait(`document.querySelector('.library-media-thumbnail video').currentTime>.3`, 'hover playback');
      assert.equal(await js(`document.querySelector('.library-media-thumbnail video').muted`), true);
      await hover(false); assert.equal(await js(`document.querySelector('.library-media-thumbnail video').paused`), true);
      await shot('cards');
      await hover(true); await open('空间 漫游.mp4');
      await wait(`document.querySelector('.asset-preview-stage video')?.readyState>=2`, 'video modal');
      assert.equal(await js(`document.querySelector('.library-media-thumbnail video').paused`), true);
      assert.equal(await js(`document.querySelector('.asset-preview-stage video').controls`), true);
      await js(`window.oldPlayer=document.querySelector('.asset-preview-stage video');window.oldPlayer.play()`);
      await wait(`window.oldPlayer.currentTime>.25`, 'expanded playback'); await shot('video');
      assert.deepEqual(await download('空间 漫游.mp4'), fs.readFileSync(path.join(process.argv[2], 'video.mp4')));
      await click('.asset-preview-close'); assert.equal(await js('window.oldPlayer.paused'), true);
      assert.equal(await js(`!!document.querySelector('.asset-preview-stage video')`), false);
      await open('录音.wav');
      await wait("document.querySelector('.asset-preview-stage audio')?.readyState >= 1", 'audio metadata');
      await js("window.testAudio=document.querySelector('.asset-preview-stage audio');window.testAudio.play()");
      assert.equal(await js('window.testAudio.paused'), false);
      await download('录音.wav');
      await click('.asset-preview-close');
      assert.equal(await js('window.testAudio.paused'), true, 'closing stops audio');
      await open('模型.obj');
      await wait("!!document.querySelector('.asset-preview-stage canvas') && document.querySelector('.asset-preview-stage').getAttribute('aria-busy')==='false'", '3D model rendered');
      await download('模型.obj');
      await click('.asset-preview-close');
      await open('自然空间.html'); await wait(`!!document.querySelector('.asset-preview-stage iframe') && document.querySelector('.asset-preview-stage').getAttribute('aria-busy')==='false'`, 'canvas HTML modal');
      assert.equal(await frame().executeJavaScript(`document.querySelector('h1').textContent`), '让自然，走进日常。');
      assert.equal(await js(`document.querySelector('.asset-preview-stage iframe').getAttribute('sandbox')`), 'allow-scripts');
      await frame().executeJavaScript(`document.querySelector('button').click()`);
      assert.equal(await frame().executeJavaScript(`document.querySelector('button').textContent`), '已点击');
      assert.equal(await frame().executeJavaScript(`(()=>{try{return !!parent.document.body}catch{return false}})()`), false);
      assert.equal(await frame().executeJavaScript(`fetch('${apiUrl}/api/library/html').then(()=>true,()=>false)`), false);
      await shot('html'); assert.equal((await download('自然空间.html')).toString(), webpage);
      await frame().executeJavaScript(`document.body.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}))`);
      await wait(`!!document.querySelector('.asset-save-menu')`, 'HTML preview context menu');
      assert.deepEqual(await js(`Array.from(document.querySelectorAll('.asset-save-menu button'), b=>b.textContent.trim()).slice(0,2)`), ['导出 HTML','导出 PDF']);
      assert.ok(await js(`document.querySelector('dialog[open]').contains(document.querySelector('.asset-save-menu'))`));
      await js(`document.querySelectorAll('.asset-save-menu button')[2].click()`);
      const pdfCount=downloads.length;await click('.asset-pdf-button');
      await wait(`!document.querySelector('.asset-pdf-button').disabled`, 'library PDF export');
      for(let i=0;i<100&&downloads.length===pdfCount;i++)await pause(50);
      assert.equal(downloads[pdfCount]?.name,'自然空间.pdf');assert.equal(fs.readFileSync(downloads[pdfCount].file).subarray(0,5).toString(),'%PDF-');

      await click('.asset-preview-close');
      await open('上传网页.html'); await wait(`!!document.querySelector('.asset-preview-stage iframe') && document.querySelector('.asset-preview-stage').getAttribute('aria-busy')==='false'`, 'uploaded HTML');
      assert.equal((await download('上传网页.html')).toString(), webpage); await click('.asset-preview-close');
      await fetch(apiUrl + '/fixture/fail'); await open('自然空间.html');
      await wait(`document.querySelector('.asset-preview-status')?.textContent.includes('暂时无法预览')`, 'HTML error state');
      await click('.asset-preview-status button'); await wait(`!!document.querySelector('.asset-preview-stage iframe')`, 'retry HTML');
      win.setSize(480, 640); await js(`document.documentElement.dataset.theme='light'`); await pause(180);
      assert.ok(await js(`(()=>{const r=document.querySelector('dialog[open]').getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight})()`));
      assert.ok(await js(`document.querySelector('.asset-download-button').getBoundingClientRect().bottom<=innerHeight`)); await shot('mobile');
      await js(`document.querySelector('.asset-preview-close').focus()`); win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Escape' }); win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Escape' });
      await wait(`!document.querySelector('dialog[open]')`, 'Escape close');
      await fetch(apiUrl + '/fixture/update'); await js('window.refresh()');
      await wait(`!!document.querySelector('[aria-label="放大预览 更新页面.html"]')`, 'updated HTML catalogue');
      await click('[aria-label="打开所属项目 预览验证"]'); assert.deepEqual(await js('window.opened'), ['fixture']);
      assert.deepEqual(await js('window.deleted'), []); assert.equal(win.webContents.getURL(), pageUrl);
      win.setSize(1280,960);await js(`document.documentElement.dataset.theme='dark';window.addPages()`);
      await wait(`document.querySelectorAll('.global-library-card').length>=24`,'initial asset batch');
      await pause(400);
      const pageItems=()=>js(`Array.from(document.querySelectorAll('.global-library-card strong'),el=>el.textContent)`);
      const initialCount=(await pageItems()).length;assert.ok(initialCount<204);
      assert.equal(await js(`!!document.querySelector('.project-pagination')`),false);
      await js(`window.scrollTo(0,document.documentElement.scrollHeight)`);await pause(120);
      await wait(`document.querySelectorAll('.global-library-card').length>${initialCount}`,'next asset batch at bottom');
      await wait(`getComputedStyle(document.querySelector('.library-back-to-top')).display!=='none'`,'back to top after scrolling');
      await click('.library-back-to-top');
      await wait(`window.scrollY<10`,'back to page top');
      const setFilter=async value=>{await js(`(()=>{const select=document.querySelector('[aria-label="资产类型"]');select.value=${JSON.stringify(value)};select.dispatchEvent(new Event('change',{bubbles:true}))})()`);await pause(100)};
      await setFilter('video');assert.equal((await pageItems()).length,1);
      assert.ok(await js(`document.querySelector('.infinite-scroll-status').textContent.includes('已加载全部 1 个资产')`));
      await setFilter('all');
      await js(`(()=>{const search=document.querySelector('input[type="search"]');search.value='页面外资料-200';search.dispatchEvent(new Event('input',{bubbles:true}))})()`);await pause(100);
      assert.deepEqual(await pageItems(),['页面外资料-200.pdf']);
      await js(`(()=>{const search=document.querySelector('input[type="search"]');search.value='不存在的资产';search.dispatchEvent(new Event('input',{bubbles:true}))})()`);await pause(100);
      assert.equal((await pageItems()).length,0);assert.equal(await js(`!!document.querySelector('.project-pagination')`),false);
      await js(`(()=>{const search=document.querySelector('input[type="search"]');search.value='';search.dispatchEvent(new Event('input',{bubbles:true}))})()`);await pause(100);
      await setFilter('all');await open('空间 漫游.mp4');await wait(`!!document.querySelector('.asset-preview-stage video')`,'preview after incremental loading');await click('.asset-preview-close');
      await js(`document.querySelector('.infinite-scroll-status').scrollIntoView({block:'center'})`);await shot('infinite-scroll');
      win.setSize(390,740);await js(`document.querySelector('.infinite-scroll-status').scrollIntoView({block:'center'})`);await pause(100);
      assert.ok(await js(`(()=>{const r=document.querySelector('.infinite-scroll-status').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()`));
      console.log('PASS: star collection, card and preview save menus, HTML/PDF export, media previews/downloads; image retry, natural image ratio, masonry layout, incremental bottom loading, back to top, search/type reset, preview after loading, mobile status.');
    } catch (error) { console.error(error); await shot('error'); process.exitCode = 1; }
    finally { win.destroy(); app.exit(process.exitCode || 0); }
  });
}
