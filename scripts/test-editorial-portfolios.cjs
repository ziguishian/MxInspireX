// Isolated Chromium visual QA of the exported portfolio artifacts; no live workspace writes.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');const output=path.join(root,'.tmp/editorial-portfolios');
if(!process.versions.electron){
 const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
 const r=require('node:child_process').spawnSync(require('electron'),[__filename],{env,stdio:'inherit',timeout:120000});process.exitCode=r.status??1;
}else{
 const{app,BrowserWindow}=require('electron');
 app.whenReady().then(async()=>{
  app.dock?.hide();const results=[];
  const win=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
  try{
   for(const slug of ['showcase-ci','showcase-shan-ming','showcase-ce-ma','showcase-jin']){
    await win.loadFile(path.join(output,slug+'.html'));
    for(const width of [1440,390]){
     win.setContentSize(width,1000);
     await win.webContents.executeJavaScript(`(async()=>{await document.fonts.ready;await Promise.all([...document.images].filter(i=>i.hasAttribute('src')).map(i=>i.decode().catch(()=>{})));await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)})()`);
     const closed=await win.webContents.executeJavaScript(`(()=>{const images=[...document.images].filter(i=>i.hasAttribute('src'));const hero=document.querySelector('.hero');return{overflow:document.documentElement.scrollWidth>innerWidth+1,broken:images.filter(i=>!i.complete||!i.naturalWidth).map(i=>i.alt),height:document.documentElement.scrollHeight,images:images.length,edition:document.body.dataset.portfolioEdition,archiveOpen:document.querySelector('details').open,hero:hero.getBoundingClientRect().height}})()`);
     assert.equal(closed.overflow,false,slug+' horizontal overflow '+width);assert.deepEqual(closed.broken,[],slug+' broken images');assert.equal(closed.edition,'2');assert.equal(closed.archiveOpen,false);assert.ok(closed.hero>200);
     // Desktop long-page capture and three section samples keep images readable for review.
     if(width===1440){
      for(const [name,selector]of [['hero','.hero'],['identity','.identity'],['system','#system']]){
       await win.webContents.executeJavaScript(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({behavior:'instant',block:'start'});void 0`);
       await new Promise(r=>setTimeout(r,80));
       const png=await win.webContents.capturePage();fs.writeFileSync(path.join(output,slug+'-'+name+'.png'),png.toPNG());
      }
     }else{await win.webContents.executeJavaScript(`(async()=>{scrollTo({top:0,behavior:'instant'});await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)})()`);const png=await win.webContents.capturePage();fs.writeFileSync(path.join(output,slug+'-mobile.png'),png.toPNG());}
     const interactions=await win.webContents.executeJavaScript(`(()=>{const details=document.querySelector('details');details.open=true;const overflow=document.documentElement.scrollWidth>innerWidth+1;document.querySelector('[data-image]').click();const dialog=document.querySelector('dialog');const open=dialog.open;const source=dialog.querySelector('img').src;dialog.querySelector('.viewer-close').click();details.open=false;return{overflow,open,source:source.startsWith('data:image/'),closed:!dialog.open}})()`);
     assert.deepEqual(interactions,{overflow:false,open:true,source:true,closed:true});results.push({slug,width,...closed,interactions});
    }
   }
   fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(results,null,2));console.log('Four portfolios passed at 1440 / 390 px: all images loaded, no overflow, source archive and lightbox work.');
  }finally{win.destroy();app.quit()}
 }).catch(error=>{console.error(error);app.exit(1)});
}
