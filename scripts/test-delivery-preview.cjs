// Exercise the production preview checks in the project's bundled Chromium.
const fs = require('node:fs');
const path = require('node:path');
if (!process.versions.electron) {
  const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'aics-preview-test-'));
  const bundle = path.join(dir, 'probe.js');
  try {
    require('esbuild').buildSync({ stdin:{contents:"export * from './apps/renderer/src/deliveryValidation'; export * from './apps/renderer/src/deliveryWorker';",resolveDir:path.join(__dirname,'..'),loader:'ts'}, outfile: bundle, bundle: true, format: 'iife', globalName: 'DeliveryProbe', platform: 'browser' });
    // Providers return H.264/AAC MP4s, not only MediaRecorder WebM streams.
    const { execFileSync } = require('node:child_process');
    const ffmpeg = execFileSync(path.join(__dirname, '../services/api/.venv/bin/python'), ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { encoding: 'utf8' }).trim();
    const mp4 = path.join(dir, 'video.mp4');
    execFileSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=32000', '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', mp4]);
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    const result = require('node:child_process').spawnSync(require('electron'), [__filename, bundle], { env, encoding: 'utf8', timeout: 60000 });
    process.stdout.write(result.stdout || '');
    if (result.status !== 0) process.stderr.write(result.stderr || String(result.error || 'Chromium test failed'));
    process.exitCode = result.status === 0 ? 0 : 1;
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    win.webContents.on('console-message', (_event, _level, message) => console.error('preview:', message));
    try {
      await win.loadURL('data:text/html,<body>Delivery verification test</body>');
      await win.webContents.executeJavaScript(fs.readFileSync(process.argv[2], 'utf8') + ';void 0');
      const checks = await win.webContents.executeJavaScript(`(async()=>{
        const good = await DeliveryProbe.probeHtml(${JSON.stringify('<h1>预览</h1><button onclick="this.textContent=\'成功\'">点击</button>')});
        const broken = await DeliveryProbe.probeHtml('<h1>预览</h1><button onclick="missingFunction()">点击</button>');
        const remote = await DeliveryProbe.probeHtml('<h1>预览</h1><script src="https://example.invalid/script.js"><\\/script>');
        const empty = await DeliveryProbe.probeHtml('   ');
        const header = new ArrayBuffer(44 + 16000), view = new DataView(header);
        const word = (at,s)=>[...s].forEach((c,i)=>view.setUint8(at+i,c.charCodeAt(0)));
        word(0,'RIFF');view.setUint32(4,header.byteLength-8,true);word(8,'WAVE');word(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,8000,true);view.setUint32(28,16000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,16000,true);
        const url=URL.createObjectURL(new Blob([header],{type:'audio/wav'}));
        const audio = await DeliveryProbe.probeMedia(url,'audio');URL.revokeObjectURL(url);
        const canvas=document.createElement('canvas');canvas.width=64;canvas.height=64;
        const stream=canvas.captureStream(0), recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}), chunks=[];
        recorder.ondataavailable=e=>chunks.push(e.data);
        const stopped=new Promise(r=>recorder.onstop=r);recorder.start();
        for(let i=0;i<10;i++){canvas.getContext('2d').fillStyle=i%2?'red':'blue';canvas.getContext('2d').fillRect(0,0,64,64);stream.getVideoTracks()[0].requestFrame();await new Promise(r=>setTimeout(r,100));}
        recorder.stop();await stopped;stream.getTracks().forEach(t=>t.stop());
        const videoUrl=URL.createObjectURL(new Blob(chunks,{type:'video/webm'}));
        const video=await DeliveryProbe.probeMedia(videoUrl,'video');URL.revokeObjectURL(videoUrl);
        const corrupt = await DeliveryProbe.probeMedia('data:video/mp4;base64,bm90LWEtdmlkZW8=','video');
        const mp4 = await DeliveryProbe.probeMedia('data:video/mp4;base64,${fs.readFileSync(path.join(path.dirname(process.argv[2]), 'video.mp4')).toString('base64')}','video');
        const normalFetch=window.fetch, normalTimeout=window.setTimeout;
        window.setTimeout=(callback,ms,...args)=>normalTimeout(callback,ms===20000?10:ms,...args);
        window.fetch=(_url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))));
        const timeout=await DeliveryProbe.probeMedia('http://fixture.invalid/stall','video');
        window.setTimeout=normalTimeout;
        window.fetch=()=>Promise.reject(new TypeError('Failed to fetch'));
        const transport=await DeliveryProbe.probeMedia('http://fixture.invalid/offline','video');
        window.fetch=normalFetch;
        const originalFetch=window.fetch, completed=[];let claimed=false,claimVersion;
        window.fetch=async(url,options)=>{
          if(String(url).endsWith('/delivery/claim')) {if(claimed)return Response.json([]);claimed=true;claimVersion=JSON.parse(options.body).probeVersion;return Response.json([{projectId:'project-a',nodeId:'a',kind:'html',fingerprint:'a',html:'<h1>A</h1>'},{projectId:'project-b',nodeId:'b',kind:'html',fingerprint:'b',html:'<h1>B</h1>'}]);}
          completed.push({url,...JSON.parse(options.body)});return Response.json({});
        };
        const stop=DeliveryProbe.startDeliveryWorker('http://fixture.invalid');
        for(let i=0;i<100&&completed.length<2;i++)await new Promise(r=>setTimeout(r,50));
        stop();window.fetch=originalFetch;
        return {good,broken,remote,empty,audio,video:{...video,frames:video.frames?.length},mp4:{...mp4,frames:mp4.frames?.length},timeout,transport,corrupt,background:{completed:completed.length,versioned:claimVersion===2&&completed.every(c=>c.probeVersion===2),passed:completed.every(c=>c.result.passed),projects:completed.map(c=>c.url.split('/projects/')[1].split('/')[0])}};
      })()`);
      const assert = require('node:assert/strict');
      assert.equal(checks.good.passed, true, JSON.stringify(checks.good));
      assert.equal(checks.good.buttonsTested, 1);
      assert.equal(checks.broken.passed, false);
      assert.equal(checks.remote.passed, false);
      assert.equal(checks.empty.passed, false);
      assert.equal(checks.audio.passed, true);
      assert.equal(checks.video.passed, true, JSON.stringify(checks.video));
      assert.equal(checks.video.frames, 3);
      assert.equal(checks.corrupt.passed, false);
      assert.equal(checks.corrupt.code, 'media_decode');
      assert.equal(checks.mp4.passed, true, JSON.stringify(checks.mp4));
      assert.equal(checks.mp4.frames, 3);
      assert.equal(checks.timeout.code, 'media_timeout');
      assert.equal(checks.transport.code, 'media_transport');
      assert.equal(checks.background.completed, 2);
      assert.equal(checks.background.versioned, true);
      assert.equal(checks.background.passed, true);
      assert.deepEqual(checks.background.projects.sort(), ['project-a','project-b']);
      console.log(JSON.stringify({ passed: 11, checks }));
      win.destroy(); app.exit(0);
    } catch (error) { console.error(error); win.destroy(); app.exit(1); }
  });
}
