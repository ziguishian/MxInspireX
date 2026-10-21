// Exercise the simplified settings page against a disposable API; no user
// settings or upstream model requests are touched.
const path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(r=>setTimeout(r,ms));
if(!process.versions.electron) {
  (async()=>{
    const {preview}=await import('vite');
    const server=await preview({configFile:path.join(root,'apps/renderer/vite.config.ts'),preview:{host:'127.0.0.1',port:5330,strictPort:true}});
    // Missing svgDrawing deliberately simulates saved settings from an older API.
    let settings={tiers:{},roles:{},media:{},maxEscalations:2,maxOutputTokens:4096,taskBudgetPoints:null,
      memory:{compactionEnabled:false},search:{provider:'openrouter',baseUrl:'',model:'',api:'responses'},
      credits:{pointsPerCny:100,multiplier:1,usdToCny:7.2},prices:{}};
    const api=require('node:http').createServer(async(req,res)=>{
      const p=new URL(req.url,'http://fixture.invalid').pathname;
      const respond=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json','Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET,PUT,POST,OPTIONS'});res.end(JSON.stringify(data));};
      if(req.method==='OPTIONS')return respond({});
      if(p==='/api/model-settings') {
        return respond(settings);
      }
      if(p.includes('agent-tools')||p.includes('design-tasks'))throw new Error('Settings must never call a model');
      if(p==='/health')return respond({status:'ok'});
      if(/models|catalog/.test(p))return respond({models:[],modelCatalog:[],configured:false});
      if(/usage|credits/.test(p))return respond({points:28545.41,pending:26,byDay:{},byTask:{},daily:[],events:[],total:28545.41});
      if(/delivery.*claim/.test(p))return respond(null);
      return respond([]);
    });
    try {
      await new Promise((resolve,reject)=>{api.once('error',reject);api.listen(5331,'127.0.0.1',resolve);});
      const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});
    } finally {await new Promise(resolve=>server.httpServer.close(resolve));api.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
} else {
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:1280,height:960,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,partition:'svg-settings-fixture'}});
    const js=code=>win.webContents.executeJavaScript(code);
    const wait=async code=>{for(let i=0;i<100;i++){if(await js(code).catch(()=>false))return;await pause(60);}throw new Error('Timeout: '+code);};
    win.webContents.session.webRequest.onBeforeRequest((details,callback)=>{
      if(details.url.startsWith('http://127.0.0.1:8765/'))return callback({redirectURL:details.url.replace('127.0.0.1:8765','127.0.0.1:5331')});
      if(/^https?:/.test(details.url)&&!/^http:\/\/127.0.0.1:533[01]\//.test(details.url))return callback({cancel:true});
      callback({});
    });
    try {
      await win.loadURL('http://127.0.0.1:5330');
      await wait('!!document.querySelector(".sidebar-user")');
      await js('document.querySelector(".sidebar-user").click()');
      await wait('!!document.querySelector(".user-menu-settings")');
      await js('document.querySelector(".user-menu-settings").click()');
      await wait('!!document.querySelector(".settings-tabs")');
      const modeSwitch='.provider-mode-switch';
      const compatibleUrl='label input[placeholder*="api.openai-proxy.org"]';
      await wait(`!!document.querySelector(${JSON.stringify(modeSwitch)})`);
      assert.equal(await js(`!!document.querySelector(${JSON.stringify(compatibleUrl)})`),false);
      assert.equal(await js('document.querySelectorAll(".detected-model-grid, .model-catalog-details").length'),0);
      assert.equal(await js('[...document.querySelectorAll("label")].some(e=>e.textContent.includes("Agent 执行方式"))'),true);
      await js(`document.querySelector(${JSON.stringify(modeSwitch)}).click()`);
      await wait(`!!document.querySelector(${JSON.stringify(compatibleUrl)})`);
      await js(`document.querySelector(${JSON.stringify(modeSwitch)}).click()`);
      await wait(`!document.querySelector(${JSON.stringify(compatibleUrl)})`);
      await js('[...document.querySelectorAll(".settings-tab")].find(e=>e.textContent.includes("路由与积分")).click()');
      await wait('!!document.querySelector(".credit-overview")');
      const overview=await js('document.querySelector(".router-settings").textContent');
      assert.match(overview,/28,545\.41/);
      assert.match(overview,/¥285\.45/);
      assert.match(overview,/¥1/);
      assert.match(overview,/100 积分/);
      assert.equal(await js('document.querySelectorAll(".credit-metrics article").length'),2);
      assert.equal(await js('document.querySelectorAll(".credit-settlement li:not(.credit-flow-arrow)").length'),3);
      assert.equal(await js('document.querySelectorAll(".credit-routing-note > span:not(.credit-routing-icon)").length'),2);
      assert.match(await js('document.querySelector(".credit-pending").textContent'),/26 笔消费待计费/);
      assert.equal(await js('document.querySelectorAll(".credit-intro, .credit-rate-card").length'),0);
      assert.equal(await js('document.querySelectorAll(".router-settings input, .router-settings select, .router-settings details").length'),0);
      assert.equal(await js('document.body.textContent.includes("SVG 绘图")'),false);
      console.log('Settings: provider switch, conditional URL and structured credit dashboard passed.');
      win.destroy();app.exit(0);
    } catch(error){console.error(error);win.destroy();app.exit(1);}
  });
}
