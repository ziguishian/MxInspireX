// Check the artwork's rendered baseline, not only the fixed DOM rectangles.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const html = `<!doctype html><html><body><main>
  <span class="home-composer-lumo-sprite" style="display:inline-block;width:122.6667px;height:122.6667px"></span>
  <span class="design-chat-title"><span class="agent-avatar-sprite"></span></span>
  <span class="agent-avatar-sprite"></span><span class="agent-avatar-sprite large"></span>
  </main><script type="module">import '/src/style.css';window.ready=true;</script></body></html>`;

if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'),
      server: { host: '127.0.0.1', port: 5374, strictPort: false, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/sprite-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/sprite-check', html));
    });
    try {
      await server.listen();
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename,
          `http://127.0.0.1:${server.httpServer.address().port}/sprite-check`], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1000, height: 600,
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    try {
      await win.loadURL(process.argv[2]);
      const checks = await win.webContents.executeJavaScript(`(async()=>{
        if(!window.ready)throw new Error('Sprite fixture not mounted');
        const targets=[...document.querySelector('main').querySelectorAll('.home-composer-lumo-sprite,.agent-avatar-sprite')];
        const image=new Image();
        image.src=getComputedStyle(targets[0]).backgroundImage.slice(5,-2);
        await image.decode();
        const measure=(style,edge)=>{
          const canvas=document.createElement('canvas');canvas.width=canvas.height=Math.ceil(edge);
          const ctx=canvas.getContext('2d');
          const x=parseFloat(style.backgroundPositionX)/100*(edge-edge*3);
          const y=parseFloat(style.backgroundPositionY)/100*(edge-edge*2);
          const clip=parseFloat(style.clipPath.match(/inset\\(([^ ]+)/)[1])/100*edge;
          ctx.beginPath();ctx.rect(0,clip,edge,edge-clip);ctx.clip();
          ctx.drawImage(image,x,y,edge*3,edge*2);
          const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
          let left=canvas.width,top=canvas.height,right=-1,bottom=-1,mass=0,cx=0,cy=0;
          for(let py=0;py<canvas.height;py++)for(let px=0;px<canvas.width;px++){
            const alpha=pixels[(py*canvas.width+px)*4+3];
            if(alpha>=128){left=Math.min(left,px);right=Math.max(right,px);top=Math.min(top,py);bottom=Math.max(bottom,py);}
            mass+=alpha;cx+=px*alpha;cy+=py*alpha;
          }
          return{left,top,right,bottom,cx:cx/mass,cy:cy/mass};
        };
        const results=[];
        for(const el of targets){
          const pseudo=el.classList.contains('agent-avatar-sprite')?'::after':null;
          // Exercise all registered artwork frames; production idle only blinks.
          if(!pseudo)el.style.animation='xiaoju-sprite-expression 12s steps(1,end) infinite';
          const animation=el.getAnimations({subtree:true}).find(a=>a.animationName==='xiaoju-sprite-expression');
          if(!animation)throw new Error('Expression animation missing: '+el.className+' / '+getComputedStyle(el,pseudo).animationName+' / '+el.getAnimations({subtree:true}).map(a=>a.animationName).join(','));
          animation.pause();
          const frames=[];
          for(const time of [0,3540,4560,7800,9720,11160]){
            animation.currentTime=time;
            const style=getComputedStyle(el,pseudo);
            frames.push({position:style.backgroundPosition,transform:style.transform,
              source:measure(style,512),rendered:measure(style,parseFloat(style.width))});
          }
          results.push({className:el.parentElement.className+' / '+el.className,frames});
        }
        return results;
      })()`);
      const range = values => Math.max(...values) - Math.min(...values);
      for (const check of checks) {
        assert.equal(new Set(check.frames.map(frame => frame.position)).size, 6, 'keep all six expressions');
        assert.ok(check.frames.every(frame => frame.transform === 'none'), 'expressions never move or scale the sprite');
        for (const coordinate of ['left', 'top', 'right', 'bottom']) {
          assert.ok(range(check.frames.map(frame => frame.source[coordinate])) <= 2, 'source registration: ' + coordinate);
          assert.ok(range(check.frames.map(frame => frame.rendered[coordinate])) <= 1, 'rendered baseline: ' + coordinate);
        }
        assert.ok(range(check.frames.map(frame => frame.source.cy)) < 1, 'body center stays fixed');
      }
      fs.mkdirSync(path.join(root, '.tmp/xiaoju-sprite-check'), { recursive: true });
      fs.writeFileSync(path.join(root, '.tmp/xiaoju-sprite-check/measurements.json'), JSON.stringify(checks, null, 2));
      console.log(JSON.stringify({ passed: true, sizes: ['homepage', '24px', '44px', '88px'],
        checks: ['six expressions', 'no position or scale animation', 'artwork moves at most one rendered pixel'] }));
    } catch (error) { console.error(error); process.exitCode = 1; }
    finally { win.destroy(); app.exit(process.exitCode || 0); }
  });
}
