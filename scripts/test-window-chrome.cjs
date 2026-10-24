const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.tmp', 'window-chrome-test');
fs.mkdirSync(output, {recursive:true});
app.setPath('userData', path.join(output, 'profile'));
let colors;
app.whenReady().then(async () => {
  const { titleBarColors } = await import('../dist/desktop/windowAppearance.js');
  const w = new BrowserWindow({show:false,width:1100,height:800,titleBarStyle:'hidden',titleBarOverlay:{color:'#181818',symbolColor:'#dddddd',height:34},webPreferences:{preload:path.join(root,'dist/desktop/preload.js'),sandbox:true,contextIsolation:true}});
  ipcMain.handle('window:set-titlebar-theme', (_event, value) => {colors=titleBarColors(value);if(colors)w.setTitleBarOverlay(colors)});
  ipcMain.handle('app:set-icon-appearance',()=>{});
  ipcMain.handle('app-update:state',()=>({status:'disabled',currentVersion:'test',percent:0,revision:0}));
  const { registerAppMenu } = await import('../dist/desktop/appMenu.js');
  registerAppMenu(event => event.sender === w.webContents && event.senderFrame === event.sender.mainFrame);
  let menuChoice='设置';
  Menu.prototype.popup=function(options){const item=this.items.find(item=>item.label===menuChoice);assert.ok(item);item.click();options.callback();};
  try {
    await w.loadFile(path.join(root,'dist/renderer/index.html'));
    const run=s=>w.webContents.executeJavaScript(s);
    for(const mode of ['dark','light','custom']){
      await run(`localStorage.setItem('langjuart.theme',${JSON.stringify(mode==='custom'?'dark':mode)});localStorage.setItem('aics.appearance',JSON.stringify(${JSON.stringify(mode==='custom'?{preset:'custom',custom:{dark:{background:'#223344',foreground:'#eeeeee',accent:'#ccddee'}}}:{preset:'neutral'})}));`);
      colors=undefined;
      await w.loadFile(path.join(root,'dist/renderer/index.html'));
      for(let i=0;i<100&&!colors;i++)await new Promise(r=>setTimeout(r,100));
      for(let i=0;i<100;i++){if(await run(`!!document.querySelector('.window-chrome')`))break;await new Promise(r=>setTimeout(r,100));}
      assert.ok(colors);
      assert.equal(colors.color,mode==='dark'?'#181818':mode==='light'?'#f3f2ef':'#223344');
      const state=await run(`({chrome:document.querySelector('.window-chrome')?.textContent,bg:getComputedStyle(document.querySelector('.window-chrome')).backgroundColor,favicon:document.querySelector('#app-favicon').href})`);
      for(const label of ['MxinspireX','累计 Token'])assert.ok(state.chrome.includes(label));
      assert.equal(await run(`document.querySelectorAll('.desktop-toolbar button').length`),0);
      assert.equal(await run(`document.querySelectorAll('.home-usage').length`),1);
      assert.equal(await run(`!!document.querySelector('.app-update-entry')`),false);
      assert.ok(state.favicon.endsWith(`mxinspirex-favicon-${mode === 'light' ? 'light' : 'dark'}.png`));
      assert.equal(state.bg,mode==='dark'?'rgb(24, 24, 24)':mode==='light'?'rgb(243, 242, 239)':'rgb(34, 51, 68)');
      fs.writeFileSync(path.join(output,`window-${mode}.png`),(await w.webContents.capturePage()).toPNG());
      console.log('PASS',mode,colors,state);
    }
    assert.equal(await run(`window.studio.showAppMenu('invalid')`),null);
    await run(`sessionStorage.setItem('langjuart.desktopRoute','/settings/appearance')`);
    await w.loadFile(path.join(root,'dist/renderer/index.html'));
    for(let i=0;i<80;i++){if(await run(`!!document.querySelector('.canvas-background-settings .appearance-mode-options')`))break;await new Promise(r=>setTimeout(r,50));}
    await run(`document.querySelectorAll('.canvas-background-settings .appearance-mode-options button')[1].click()`);
    assert.equal(await run(`JSON.parse(localStorage.getItem('aics.canvasBackground')).pattern`),'dots');
    await w.reload();await new Promise(r=>setTimeout(r,1500));
    assert.equal(await run(`document.querySelector('.canvas-background-settings .appearance-mode-options button[aria-pressed=true]')?.textContent`),'点状');
    console.log('PASS titlebar brand and persisted canvas background');
    w.webContents.debugger.attach('1.3');
    await w.webContents.debugger.sendCommand('Page.enable');
    await w.webContents.debugger.sendCommand('Page.setInterceptFileChooserDialog', { enabled:true });
    let chooserOpened = false;
    w.webContents.debugger.on('message', (_event, method) => { if(method==='Page.fileChooserOpened') chooserOpened=true; });
    const uploadButton = await run(`(()=>{const el=document.querySelector('.background-upload');el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await w.webContents.debugger.sendCommand('Input.dispatchMouseEvent', {type:'mousePressed',button:'left',clickCount:1,...uploadButton});
    await w.webContents.debugger.sendCommand('Input.dispatchMouseEvent', {type:'mouseReleased',button:'left',clickCount:1,...uploadButton});
    await new Promise(r=>setTimeout(r,250));
    assert.ok(chooserOpened, 'Clicking upload must open a native file chooser');
    const { root: documentNode } = await w.webContents.debugger.sendCommand('DOM.getDocument');
    const { nodeId: inputNode } = await w.webContents.debugger.sendCommand('DOM.querySelector', { nodeId: documentNode.nodeId, selector: '.background-file-input' });
    await w.webContents.debugger.sendCommand('DOM.setFileInputFiles', { nodeId: inputNode, files: [path.join(root, 'apps/renderer/public/assets/mxinspirex-favicon-light.png')] });
    for(let i=0;i<100;i++) { if(await run(`!!document.querySelector('.background-image-thumbnail img')`))break;await new Promise(r=>setTimeout(r,50)); }
    const uploadState = await run(`({image:JSON.parse(localStorage.getItem('aics.canvasBackground')).image,error:document.querySelector('.canvas-background-settings [role=alert]')?.textContent,preview:document.querySelector('.background-image-thumbnail img')?.naturalWidth})`);
    assert.ok(uploadState.image?.startsWith('data:image/webp;base64,'), JSON.stringify(uploadState));
    assert.equal(uploadState.preview,64);
    await w.reload(); await new Promise(r=>setTimeout(r,1000));
    assert.equal(await run(`document.querySelector('.background-image-thumbnail img')?.naturalWidth`),64);
    chooserOpened = false;
    await w.webContents.debugger.sendCommand('Emulation.setFocusEmulationEnabled', { enabled:true });
    await w.webContents.debugger.sendCommand('Page.setInterceptFileChooserDialog', { enabled:true });
    await run(`document.querySelector('.background-upload').focus()`);
    await w.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
    await w.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
    await new Promise(r=>setTimeout(r,250));
    assert.ok(chooserOpened, 'Keyboard activation must open a file chooser: '+JSON.stringify(await run(`({focused:document.activeElement?.outerHTML,error:document.querySelector('.canvas-background-settings [role=alert]')?.textContent})`)));
    const largeBytes = await run(`(async()=>{
      const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=1000;
      const ctx=canvas.getContext('2d'), image=ctx.createImageData(canvas.width,canvas.height);
      for(let start=0;start<image.data.length;start+=60000)crypto.getRandomValues(image.data.subarray(start,Math.min(start+60000,image.data.length)));
      for(let i=3;i<image.data.length;i+=4)image.data[i]=255;ctx.putImageData(image,0,0);
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      const transfer=new DataTransfer();transfer.items.add(new File([blob],'large-background.png',{type:'image/png'}));
      const input=document.querySelector('.background-file-input');input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));return blob.size;
    })()`);
    assert.ok(largeBytes>2*1024*1024, 'Fixture must exceed the old upload limit');
    for(let i=0;i<100;i++){if(await run(`!document.querySelector('.background-upload').disabled`))break;await new Promise(r=>setTimeout(r,50));}
    assert.equal(await run(`document.querySelector('.canvas-background-settings [role=alert]')?.textContent || ''`),'');
    const stored = await run(`JSON.parse(localStorage.getItem('aics.canvasBackground')).image`);
    assert.ok(stored.length<=1400000 && stored!==uploadState.image);
    await w.reload();await new Promise(r=>setTimeout(r,1000));
    assert.equal(await run(`JSON.parse(localStorage.getItem('aics.canvasBackground')).image`),stored);
    assert.ok(await run(`document.querySelector('.background-image-thumbnail img')?.naturalWidth>64`));
    await run(`document.querySelector('.background-remove').click()`);
    assert.equal(await run(`JSON.parse(localStorage.getItem('aics.canvasBackground')).image`),'');
    await w.reload(); await new Promise(r=>setTimeout(r,1000));
    assert.equal(await run(`!!document.querySelector('.background-image-thumbnail img')`),false);
    console.log('PASS actual file input upload, preview and reload persistence');
  }catch(e){console.error(e);app.exit(1);return}finally{app.quit()}
});
