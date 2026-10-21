// Verify built page navigation in Chromium. API data is isolated from the workspace.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
if(!process.versions.electron){
  (async()=>{
    const {preview}=await import('vite');
    const server=await preview({configFile:path.join(root,'apps/renderer/vite.config.ts'),preview:{host:'127.0.0.1',port:5297,strictPort:true}});
    const referenceImage=fs.readFileSync(path.join(root,'apps/renderer/public/assets/home-design-examples-v1.png'));
    const tallReferenceImage=execFileSync(path.join(root,'services/api/.venv/bin/python'),['-c',"import io,sys;from PIL import Image;o=io.BytesIO();Image.new('RGB',(180,1080),'#78966d').save(o,'PNG');sys.stdout.buffer.write(o.getvalue())"]);
    const api=require('node:http').createServer((req,res)=>{
      const p=new URL(req.url,'http://fixture.invalid').pathname;
      const referenceId=p.match(/^\/api\/references\/(fixture-reference|tall-reference)\/(thumbnail|content)$/)?.[1];
      if(referenceId){
        const bytes=referenceId==='tall-reference'?tallReferenceImage:referenceImage;
        res.writeHead(200,{'Content-Type':'image/png','Access-Control-Allow-Origin':'*','Content-Length':bytes.length});res.end(bytes);return;
      }
      const project={id:'fixture-project',name:'路由验证项目',brief:'仅用于浏览器回归',status:'draft',slug:'fixture-project',createdAt:'2026-09-12T00:00:00Z',updatedAt:'2026-09-12T00:00:00Z'};
      let data=[];
      if(p==='/health')data={status:'ok'};
      else if(p==='/api/projects')data=[project];
      else if(p==='/api/projects/fixture-project')data=project;
      else if(p==='/api/references')data={items:[{id:'fixture-reference',title:'参考卡片验证',thumbnailUrl:'/api/references/fixture-reference/thumbnail',contentUrl:'/api/references/fixture-reference/content',width:1254,height:1254,saved:true,analysisStatus:'ready',industries:['文旅'],designTypes:['视觉设计'],tags:['自然','现代']},{id:'tall-reference',title:'长图参考验证',thumbnailUrl:'/api/references/tall-reference/thumbnail',contentUrl:'/api/references/tall-reference/content',width:180,height:1080,saved:true,analysisStatus:'ready',industries:['文旅'],designTypes:['海报'],tags:['长图']}],total:2};
      else if(p==='/api/references/categories')data=[];
      else if(/\/(canvas|preview)$/.test(p))data={nodes:[{id:'route-node',type:'creative',position:{x:40,y:40},data:{kind:'text',title:'正确项目的画布',text:'当前路由的项目内容'}}],edges:[]};
      else if(/models|catalog/.test(p))data={models:[],modelCatalog:[],configured:false};
      else if(/usage|credits/.test(p))data={points:0,pending:0,byDay:{},byTask:{},daily:[],events:[],total:0};
      else if(/delivery.*claim/.test(p))data=null;
      res.writeHead(200,{'Content-Type':'application/json','Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET, POST, PATCH, DELETE, OPTIONS'});res.end(JSON.stringify(data));
    });
    try{
      await new Promise((resolve,reject)=>{api.once('error',reject);api.listen(5298,'127.0.0.1',resolve)});
      const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});
    }finally{await new Promise(resolve=>server.httpServer.close(resolve));api.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();const win=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false,partition:'page-navigation-fixture'}});
    const session=win.webContents.session,base='http://127.0.0.1:5297';
    session.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8765/*']},(details,callback)=>callback({redirectURL:details.url.replace('127.0.0.1:8765','127.0.0.1:5298')}));
    const js=code=>win.webContents.executeJavaScript(code),q=JSON.stringify;
    const wait=async(code,label)=>{for(let i=0;i<80;i++){if(await js(code).catch(()=>false))return;await pause(100);}throw new Error('Timeout: '+label);};
    const ready=()=>wait('!!document.querySelector(".shell")','App mounted');
    const click=async(selector)=>{await wait(`!!document.querySelector(${q(selector)})`,selector);const point=await js(`(()=>{const r=document.querySelector(${q(selector)}).getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);win.focus();win.webContents.focus();win.webContents.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,...point});win.webContents.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,...point});await pause(300);};
    const label=selector=>`[aria-label="${selector}"]`;
    const errors=[];win.webContents.on('console-message',(_event,level,message)=>{if(level===3&&!/fixture|Failed to fetch|Failed to load resource|Content Security Policy|unsafe-eval/.test(message))errors.push(message)});
    const checks=[];
    try{
      await win.loadURL(base+'/');await ready();
      await js("localStorage.setItem('langjuart.activeProjectId','fixture-project')");
      await win.loadURL(base+'/');await ready();await pause(400);
      assert.equal(win.webContents.getURL(),base+'/');assert.ok(await js('!!document.querySelector(".home-intake")'));checks.push('homepage stays at / despite remembered project');
      for(const [url,title,selector] of [['/projects','我的项目','.projects-page'],['/assets','资产库','.library-page'],['/references','参考库','.reference-page'],['/schedules','定时任务','.schedule-panel'],['/account','设置','.account-overview'],['/settings/appearance','设置','.settings-workspace-form'],['/help','使用说明','.help-page'],['/projects/fixture-project','设计工作区','.design-workspace']]){
        await win.loadURL(base+url);await ready();await wait(`document.title.includes(${q(title)})`,title);
        if(url==='/projects/fixture-project')await wait('document.body.textContent.includes("当前路由的项目内容")','matching project hydrated');
        else assert.ok(await js(`!!document.querySelector(${q(selector)})`),url+' page component');
        if(['/projects','/assets','/references'].includes(url)){
          assert.ok(await js(`!!document.querySelector('.library-back-to-top')`));
          assert.equal(await js(`getComputedStyle(document.querySelector('.library-back-to-top')).display`),'none');
        }
        if(url==='/schedules'){
          const layout=await js(`(()=>{const page=document.querySelector('.schedule-panel'),host=document.querySelector('.canvas-panel'),style=getComputedStyle(page),hostStyle=getComputedStyle(host);return {maxWidth:style.maxWidth,width:page.getBoundingClientRect().width,availableWidth:host.clientWidth-parseFloat(hostStyle.paddingLeft)-parseFloat(hostStyle.paddingRight)}})()`);
          assert.equal(layout.maxWidth,'1600px');
          assert.ok(Math.abs(layout.width-layout.availableWidth)<1);
          checks.push('schedule page shares the full-width collection container');
        }
        if(url==='/projects'){
          assert.ok(await js(`document.querySelector('.project-card-copy')?.parentElement?.classList.contains('project-card-cover')`));
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-copy')).position`),'absolute');
          assert.ok(await js(`getComputedStyle(document.querySelector('.project-card-copy'),'::before').backgroundImage.includes('linear-gradient')`));
          await wait(`!!document.querySelector('.project-board-preview')`,'project board preview');
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-board-preview')).backgroundImage`),'none');
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-copy')).opacity`),'0');
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-titlebar')).opacity`),'1');
          assert.ok(await js(`document.querySelector('.project-card-titlebar').textContent.includes('路由验证项目')`));
          assert.ok(await js(`getComputedStyle(document.querySelector('.project-card-titlebar')).backgroundImage.includes('linear-gradient')`));
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-copy'),'::before').backdropFilter`),'none');
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-actions')).opacity`),'0');
          const point=await js(`(()=>{const r=document.querySelector('.project-card').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);
          win.webContents.sendInputEvent({type:'mouseMove',...point});await pause(260);
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-copy')).opacity`),'1');
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-titlebar')).opacity`),'0');
          assert.equal(await js(`getComputedStyle(document.querySelector('.project-card-actions')).opacity`),'1');
          await js(`(()=>{const page=document.querySelector('.collection-page'),scroll=document.querySelector('.canvas-panel');page.style.minHeight='2400px';scroll.scrollTop=900;scroll.dispatchEvent(new Event('scroll'))})()`);
          await wait(`getComputedStyle(document.querySelector('.library-back-to-top')).display!=='none'`,'project back to top');
          await js(`document.querySelector('.library-back-to-top').click()`);
          await wait(`document.querySelector('.canvas-panel').scrollTop<10`,'project returned to top');
          checks.push('project card keeps its title visible and reveals full details and menu on hover');
        }
        if(url==='/references'){
          await wait(`document.querySelector('.reference-image img')?.naturalWidth>0`,'reference image');
          await wait(`document.querySelector('img[alt="长图参考验证"]')?.naturalHeight===1080`,'tall reference image');
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-body')).position`),'absolute');
          assert.ok(await js(`getComputedStyle(document.querySelector('.reference-tile-body'),'::before').backgroundImage.includes('linear-gradient')`));
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-body')).opacity`),'0');
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-delete')).position`),'absolute');
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-delete')).opacity`),'0');
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-body'),'::before').backdropFilter`),'none');
          assert.ok(await js(`(()=>{const img=document.querySelector('.reference-image img'),r=img.getBoundingClientRect();return Math.abs(r.width/r.height-img.naturalWidth/img.naturalHeight)<.01})()`));
          assert.ok(await js(`(()=>{const img=document.querySelector('img[alt="长图参考验证"]'),box=img.parentElement,ir=img.getBoundingClientRect(),br=box.getBoundingClientRect();return getComputedStyle(box).aspectRatio==='auto'&&getComputedStyle(box).overflow==='visible'&&Math.abs(ir.height-br.height)<1&&Math.abs(ir.width/ir.height-img.naturalWidth/img.naturalHeight)<.01})()`));
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-grid')).gridTemplateColumns.split(' ').length`),4);
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-grid')).gridAutoFlow`),'dense');
          const point=await js(`(()=>{const r=document.querySelector('.reference-tile').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);
          win.webContents.sendInputEvent({type:'mouseMove',...point});await pause(260);
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-body')).opacity`),'1');
          assert.equal(await js(`getComputedStyle(document.querySelector('.reference-tile-delete')).opacity`),'1');
          assert.ok(await js(`(()=>{const tile=document.querySelector('.reference-tile').getBoundingClientRect(),button=document.querySelector('.reference-tile-delete').getBoundingClientRect();return Math.abs(tile.right-button.right-10)<2&&Math.abs(button.top-tile.top-10)<2})()`));
          await click('.reference-tile-delete');
          assert.ok(await js(`!!document.querySelector('.reference-delete-dialog[role="alertdialog"]')`));
          assert.equal(await js(`!!document.querySelector('.reference-detail')`),false);
          await click('.reference-delete-cancel');
          await wait(`!document.querySelector('.reference-delete-dialog')`,'reference delete dialog closed');
          checks.push('four-column reference masonry preserves images and reveals a confirmed delete action on hover');
        }
        const resolvedUrl=url==='/account'?'/settings/account':url;
        assert.equal(win.webContents.getURL(),base+resolvedUrl);
        await wait('!!document.querySelector(".brand-home-button svg")','home icon on deep link');
        win.reload();await pause(200);await ready();await wait(`document.title.includes(${q(title)})`,title+' after reload');
        assert.equal(win.webContents.getURL(),base+resolvedUrl);checks.push(url+' direct load and refresh');
      }
      await click(label('项目'));await wait('location.pathname==="/projects"','projects navigation');
      await click(label('资产'));await wait('location.pathname==="/assets"','assets navigation');
      win.webContents.navigationHistory.goBack();await wait('location.pathname==="/projects"','back');
      win.webContents.navigationHistory.goForward();await wait('location.pathname==="/assets"','forward');checks.push('browser Back and Forward');
      await win.loadURL(base+'/#/projects/fixture-project');await ready();await wait('!!document.querySelector(".design-workspace")','old project bookmark');assert.equal(win.webContents.getURL(),base+'/projects/fixture-project');
      await win.loadURL(base+'/#/');await ready();assert.equal(win.webContents.getURL(),base+'/');checks.push('legacy hash bookmarks migrate to clean paths');
      await win.loadURL(base+'/not-a-page');await ready();await wait('document.title.includes("页面不存在")','404');assert.equal(win.webContents.getURL(),base+'/not-a-page');checks.push('unknown route shows 404');
      // The same page modules work under file:// without navigating to fake directories.
      const entry=path.join(root,'dist/renderer/index.html');
      await win.loadFile(entry,{hash:'/projects/fixture-project'});await ready();await wait('!!document.querySelector(".design-workspace")','desktop legacy bookmark');
      assert.ok(!win.webContents.getURL().includes('#'));
      await click(label('资产'));await wait('document.title.includes("资产库")','desktop assets');
      win.reload();await pause(200);await ready();await wait('document.title.includes("资产库")','desktop restored route');
      await click(label('返回首页'));await wait('!!document.querySelector(".home-intake")','desktop home');win.reload();await pause(200);await ready();await wait('!!document.querySelector(".home-intake")','desktop restored home');
      assert.ok(!win.webContents.getURL().includes('#'));checks.push('desktop file navigation and reload without hash');
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify({passed:true,checks}));win.destroy();app.exit(0);
    }catch(error){console.error(error);console.error('URL:',win.webContents.getURL());console.error(await js('document.body.innerText.slice(0,500)').catch(()=>''));console.error(errors);fs.writeFileSync('/tmp/aics-page-navigation-error.png',(await win.webContents.capturePage()).toPNG());win.destroy();app.exit(1);}
  });
}
