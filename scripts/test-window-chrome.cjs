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
      for(const label of ['MxInspireX','累计 Token'])assert.ok(state.chrome.includes(label));
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
  }catch(e){console.error(e);app.exit(1);return}finally{app.quit()}
});
