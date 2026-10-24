// Offline component/interaction regression. No model calls or user workspace.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {spawnSync, spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const fixture = path.join(root, '.tmp', 'web-interaction-fixture.html');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(path.dirname(fixture), {recursive:true});
    const source = `<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>body{padding:24px}.item[hidden]{display:none}</style></head><body>
      <div class="nav" role="tablist"><button id="first" class="nav-link active" data-bs-toggle="tab" data-bs-target="#one">一</button><button id="second" class="nav-link" data-bs-toggle="tab" data-bs-target="#two">二</button></div>
      <div class="tab-content"><div id="one" class="tab-pane active">第一页</div><div id="two" class="tab-pane">第二页</div></div>
      <button id="expand" data-bs-toggle="collapse" data-bs-target="#details">展开</button><div id="details" class="collapse">详情</div>
      <label for="filter">筛选</label><select id="filter"><option value="all">全部</option><option value="a">A</option></select><div class="item" data-kind="a">A</div><div class="item" data-kind="b">B</div>
      <form id="form"><label for="email">邮箱</label><input id="email" type="email" required><button type="submit">本地演示</button><output id="feedback"></output></form>
      <audio id="player" controls src="asset://sound"></audio>
      <video id="videoPlayer" controls muted src="asset://clip"></video>
      <script>filter.onchange=()=>document.querySelectorAll('.item').forEach(item=>item.hidden=filter.value!=='all'&&item.dataset.kind!==filter.value);form.onsubmit=event=>{event.preventDefault();feedback.textContent='已完成本地演示，未发送到服务器'};</script></body></html>`;
    const python = process.env.AICS_PYTHON || path.join(root,'services/api/.venv', process.platform==='win32'?'Scripts/python.exe':'bin/python');
    const result = spawnSync(python, ['-X','utf8','-c',
      "import sys,io,wave,base64,subprocess,imageio_ffmpeg;from pathlib import Path;sys.path.insert(0,'services/api');from app.web_framework import apply_web_framework;from app.html_assets import resolve_html_assets;s=io.BytesIO();w=wave.open(s,'wb');w.setparams((1,2,8000,0,'NONE',''));w.writeframes(b'\\0\\0'*8000);w.close();p=Path('.tmp/web-interaction-video.mp4');subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-loglevel','error','-f','lavfi','-i','color=c=blue:s=32x32:r=10','-t','1','-pix_fmt','yuv420p',str(p)],check=True);print(resolve_html_assets({'html':apply_web_framework(sys.stdin.read(),'bootstrap'),'htmlAssets':{'sound':'data:audio/wav;base64,'+base64.b64encode(s.getvalue()).decode(),'clip':'data:video/mp4;base64,'+base64.b64encode(p.read_bytes()).decode()}}))"],
      {cwd:root,input:source,encoding:'utf8',maxBuffer:2*1024*1024});
    assert.equal(result.status, 0, result.stderr); fs.writeFileSync(fixture,result.stdout);
    const {createServer} = await import('vite');
    const server = await createServer({appType:'custom',configFile:path.join(root,'apps/renderer/vite.config.ts'),server:{host:'127.0.0.1',port:5328,strictPort:true,hmr:false},logLevel:'error'});
    server.middlewares.use('/fixture',(_req,res)=>{res.setHeader('Content-Type','text/html;charset=utf-8');res.end(result.stdout)});
    server.middlewares.use('/web-check',async(_req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/web-check',`<iframe id="preview" style="width:100%;height:700px"></iframe><script type="module">import {htmlPreviewDocument,HTML_PREVIEW_SANDBOX} from '/src/htmlPreview.ts';preview.sandbox=HTML_PREVIEW_SANDBOX;preview.srcdoc=htmlPreviewDocument(await(await fetch('/fixture')).text());</script>`))});
    try {
      await server.listen(); const env={...process.env}; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode=await new Promise((resolve,reject)=>{const child=spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1))});
    } finally { await server.close(); }
  })().catch(error=>{console.error(error);process.exitCode=1});
} else {
  const {app,BrowserWindow}=require('electron');
  app.setPath('userData',fs.mkdtempSync(path.join(root,'.tmp','web-interaction-profile-')));
  app.whenReady().then(async()=>{
    const win=new BrowserWindow({show:false,width:1440,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    try {
      for (const mode of ['preview','export']) {
        if(mode==='preview') await win.loadURL('http://127.0.0.1:5328/web-check'); else await win.loadFile(fixture);
        let frame;
        for(let i=0;i<100;i++){frame=mode==='preview'?win.webContents.mainFrame.frames.find(f=>f.url==='about:srcdoc'):win.webContents.mainFrame;if(frame&&await frame.executeJavaScript('!!document.querySelector("#player")').catch(()=>false))break;await pause(50)}
        assert.ok(frame,mode+' frame missing');
        const js=code=>frame.executeJavaScript(code);
        assert.equal(await js('typeof bootstrap.Tab'),'function');
        await js('second.click();expand.click();filter.value="a";filter.dispatchEvent(new Event("change"))');
        await pause(450);
        assert.equal(await js('two.classList.contains("active")&&details.classList.contains("show")'),true);
        assert.equal(await js('document.querySelectorAll(".item:not([hidden])").length'),1);
        assert.equal(await js('form.checkValidity()'),false);
        await js('email.value="test@example.com";form.requestSubmit()');
        assert.equal(await js('feedback.textContent'),'已完成本地演示，未发送到服务器');
        assert.equal(await js('player.readyState>=2 && player.duration>0'),true);
        await js('player.play()');
        for(let i=0;i<40 && !await js('player.currentTime>0');i++) await pause(50);
        assert.equal(await js('player.currentTime>0'),true); await js('player.pause()');
        assert.equal(await js('videoPlayer.readyState>=2 && videoPlayer.videoWidth===32'),true);
        await js('videoPlayer.play()');
        for(let i=0;i<40 && !await js('videoPlayer.currentTime>0');i++) await pause(50);
        assert.equal(await js('videoPlayer.currentTime>0'),true); await js('videoPlayer.pause()');
        assert.equal(await js('typeof window.studio'), 'undefined');
        console.log('PASS '+mode+': offline framework, tabs, collapse, filtering, form validation/feedback, real audio/video playback.');
      }
    } catch(error){console.error(error);process.exitCode=1}
    finally {win.destroy();app.exit(process.exitCode||0)}
  });
}
