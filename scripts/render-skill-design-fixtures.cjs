// Render actual generated SVG source files with Chromium, without a server or network.
const fs = require('node:fs'), path = require('node:path');
const folder = path.join(__dirname, '../docs/examples/builtin-skills');
if (!process.versions.electron) {
  const env = {...process.env}; delete env.ELECTRON_RUN_AS_NODE;
  const result = require('node:child_process').spawnSync(require('electron'), [__filename,...process.argv.slice(2)], {env, stdio:'inherit'});
  process.exit(result.status ?? 1);
} else {
  const {app,BrowserWindow} = require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();
    const win = new BrowserWindow({show:false,width:1000,height:1200,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
    win.webContents.session.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']}, (_details, callback)=>callback({cancel:true}));
    try {
      if(process.argv.includes('--gallery')){
        const assert=require('node:assert/strict');
        win.setContentSize(1440,1100);
        await win.loadFile(path.join(folder,'index.html'));
        await win.webContents.executeJavaScript('Promise.all([...document.images].map(image=>image.decode()))');
        assert.equal(await win.webContents.executeJavaScript('document.querySelectorAll("[data-category]").length'),5);
        fs.writeFileSync(path.join(folder,'gallery-preview.png'),(await win.webContents.capturePage()).toPNG());
        for(const category of ['logo','ip','notebook','wayfinding','xhs']){
          await win.webContents.executeJavaScript(`document.querySelector('[data-filter="${category}"]').click()`);
          assert.equal(await win.webContents.executeJavaScript('document.querySelectorAll("[data-category]:not([hidden])").length'),1);
        }
        const links=await win.webContents.executeJavaScript('[...document.querySelectorAll("a[href]")].map(a=>a.getAttribute("href"))');
        assert.ok(links.every(name=>fs.existsSync(path.join(folder,name))),'Every local download/link exists');
        console.log('Gallery passed: all images decoded, five filters, local downloads.');
        win.destroy();app.exit(0);return;
      }
      for(const name of fs.readdirSync(folder).filter(n=>n.endsWith('.svg'))) {
        const source=fs.readFileSync(path.join(folder,name),'utf8');
        const viewBox=source.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
        if(!viewBox)throw new Error('Missing fixed viewbox '+name);
        const height=1100, width=Math.round(height*Number(viewBox[1])/Number(viewBox[2]));
        win.setContentSize(width,height);
        await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(`<style>body{margin:0;background:white}img{display:block;width:100vw;height:100vh}</style><img id="art" src="data:image/svg+xml;base64,${Buffer.from(source).toString('base64')}">`));
        await win.webContents.executeJavaScript('document.getElementById("art").decode()');
        const image=await win.webContents.capturePage();
        fs.writeFileSync(path.join(folder,name.replace('.svg','-preview.png')),image.toPNG());
        console.log('Rendered '+name);
      }
      win.destroy();app.exit(0);
    } catch(error){console.error(error);win.destroy();app.exit(1)}
  });
}
