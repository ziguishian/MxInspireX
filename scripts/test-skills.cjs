// Built renderer lifecycle with isolated in-memory API, never a real project or model.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
if(!process.versions.electron){
  (async()=>{
    const {preview}=await import('vite');
    const server=await preview({configFile:path.join(root,'apps/renderer/vite.config.ts'),preview:{host:'127.0.0.1',port:5295,strictPort:true}});
    let skills=[],versions={},failedList=false,failedSave=false,saveKey;
    const api=require('node:http').createServer(async(req,res)=>{
      const url=new URL(req.url,'http://fixture.invalid'),p=url.pathname;
      const headers={'Content-Type':'application/json','Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET, POST, PATCH, DELETE, OPTIONS'};
      const respond=(data,status=200)=>{res.writeHead(status,headers);res.end(JSON.stringify(data));};
      if(req.method==='OPTIONS')return respond({});
      let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):{};
      if(p==='/__fixture/builtins' && req.method==='POST'){
        const directory=path.join(root,'services/api/app/builtin_skills');
        skills=JSON.parse(fs.readFileSync(path.join(directory,'manifest.json'),'utf8')).skills.map(entry=>{
          const local=JSON.parse(fs.readFileSync(path.join(directory,entry.name,'langju.json'),'utf8'));
          const markdown=fs.readFileSync(path.join(directory,entry.name,'SKILL.md'),'utf8');
          return {id:entry.name,name:entry.name,title:local.title,description:JSON.parse(markdown.match(/^description: (.+)$/m)[1]),instructions:markdown.split('---\n').slice(2).join('---\n'),version:1,currentVersion:1,enabled:true,deleted:false,requiredTools:local.requiredTools,missingTools:[],resources:[],contentHash:'fixture',createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),builtin:{name:entry.name,revision:entry.revision,modifiedLocally:false}};
        });
        versions=Object.fromEntries(skills.map(skill=>[skill.id,[structuredClone(skill)]]));return respond({ready:true});
      }
      if(p==='/api/skills/tools')return respond({tools:['generate_image','canvas_create_html']});
      if(p==='/api/skills' && req.method==='GET') {
        if(!failedList){failedList=true;return respond({detail:'模拟加载失败，请重试'},503);}
        const found=skills.filter(s=>(s.title+s.description+s.name).includes(url.searchParams.get('query')||''));
        return respond({skills:found,total:found.length,nextOffset:null});
      }
      if(p==='/api/skills/github/inspect') return respond({source:{owner:'example',repo:'skills',url:'https://github.com/example/skills',ref:'main',path:'skills/packaging',commit:'a'.repeat(40)},candidates:[{name:'packaging-design',title:'文创包装设计',path:'skills/packaging',description:'文旅纪念品包装方法',warnings:['包含脚本：原文件已保留，本应用不执行 Skill 自带脚本。']}]});
      if(p==='/api/skills/github/install') {
        assert.equal(body.ref,'a'.repeat(40),'install pins inspected commit');
        if(!failedSave){failedSave=true;saveKey=req.headers['idempotency-key'];return respond({detail:'模拟安装失败，请重试'},503);}
        assert.equal(req.headers['idempotency-key'],saveKey,'install retry keeps operation ID');
        const skill={id:'skill-fixture',name:'packaging-design',title:'文创包装设计',description:'适用于文旅纪念品包装设计',instructions:'# 包装设计方法\n依据材料和工艺资料完成交付',version:1,currentVersion:1,enabled:true,requiredTools:[],missingTools:[],deleted:false,contentHash:'hash1',createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),resources:[{path:'references/guide.txt',byteSize:10,sha256:'hash',mime:'text/plain'}],source:{owner:'example',repo:'skills',url:'https://github.com/example/skills',path:'skills/packaging',ref:'main',commit:body.ref},compatibilityWarnings:['包含脚本：原文件已保留，本应用不执行 Skill 自带脚本。']};
        skills.push(skill);versions[skill.id]=[structuredClone(skill)];return respond(skill,201);
      }
      if(p.startsWith('/api/skills/')){
        const id=p.split('/')[3],skill=skills.find(s=>s.id===id);if(!skill)return respond({detail:'已删除'},404);
        if(p.includes('/resources/')){res.writeHead(200,{'Content-Type':'text/plain','Access-Control-Allow-Origin':'*'});return res.end('材料与工艺参考');}
        if(p.endsWith('/export'))return respond({fixture:'export'});
        if(p.endsWith('/versions'))return respond({versions:versions[id].slice().reverse()});
        if(req.method==='PATCH'){
          if(body.expected_version!==skill.currentVersion)return respond({detail:'版本冲突'},409);
          Object.assign(skill,body,{version:skill.version+1,currentVersion:skill.currentVersion+1,updatedAt:new Date().toISOString()});
          if(body.required_tools)skill.requiredTools=body.required_tools;
          versions[id].push(structuredClone(skill));return respond(skill);
        }
        if(req.method==='DELETE'){skills=[];return respond({id,deleted:true});}
        const version=url.searchParams.get('version');return respond(version?{...versions[id].find(v=>v.version===Number(version)),currentVersion:skill.currentVersion}:skill);
      }
      if(p.includes('/agent-tools/')||p.includes('/design-tasks'))return respond({detail:'Unexpected Agent execution'},500);
      let data=[];
      if(p==='/health')data={status:'ok'};
      else if(/models|catalog/.test(p))data={models:[],modelCatalog:[],configured:false};
      else if(/usage|credits/.test(p))data={points:0,pending:0,byDay:{},byTask:{},daily:[],events:[],total:0};
      else if(/delivery.*claim/.test(p))data=null;
      respond(data);
    });
    try{
      await new Promise((resolve,reject)=>{api.once('error',reject);api.listen(5296,'127.0.0.1',resolve)});
      const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});
    }finally{await new Promise(resolve=>server.httpServer.close(resolve));api.close();}
  })().catch(error=>{console.error(error);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();const win=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false,partition:'skill-library-fixture'}});
    const base='http://127.0.0.1:5295',js=code=>win.webContents.executeJavaScript(code),q=JSON.stringify;
    win.webContents.session.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8765/*']},(details,callback)=>callback({redirectURL:details.url.replace('127.0.0.1:8765','127.0.0.1:5296')}));
    const wait=async(code,label)=>{for(let i=0;i<80;i++){if(await js(code).catch(()=>false))return;await pause(100);}throw new Error('Timeout: '+label);};
    const button=async(text,scope='document')=>{await js(`(()=>{const b=[...${scope}.querySelectorAll('button')].find(b=>b.textContent.trim()===${q(text)});if(!b)throw Error('Missing button '+${q(text)});b.click()})()`);await pause(200);};
    const field=async(selector,value)=>js(`(()=>{const el=document.querySelector(${q(selector)});el.value=${q(value)};el.dispatchEvent(new Event('input',{bubbles:true}))})()`);
    const shot=async(name)=>fs.writeFileSync('/tmp/aics-skills-'+name+'.png',(await win.webContents.capturePage()).toPNG());
    const errors=[];win.webContents.on('console-message',(_event,level,message)=>{if(level===3&&!/fixture|Failed to fetch|Failed to load resource|Content Security Policy|unsafe-eval/.test(message))errors.push(message)});
    try{
      await win.loadURL(base+'/skills');await wait('document.body.textContent.includes("模拟加载失败")','list failure');
      await button('重新加载');await wait('document.body.textContent.includes("尚未安装技能")','empty library');
      assert.equal(await js(`(()=>{const nav=document.querySelector('.top-left-nav-card'),b=nav.querySelector('[aria-label="技能库"]');const r=nav.getBoundingClientRect(),s=b.getBoundingClientRect();return s.bottom<=r.bottom && s.top>=r.top && !!b.querySelector('svg[class*=wrench]');})()`),true,'wrench is inside shared navigation');
      await button('新建技能');
      await wait('!!document.querySelector(".intake-composer-editor")','home conversation');
      assert.equal(await js('document.querySelector(".intake-composer-editor").textContent.includes("创建一个 Skill")'),true,'new skill prefilled in home');
      assert.equal(await js('!!document.querySelector(".skill-sheet")'),false,'no manual creation form');
      await win.loadURL(base+'/skills');await wait('!!document.querySelector(".skills-page")','back to skills');
      await button('从 GitHub 加载');
      assert.equal(await js(`(()=>{const b=document.querySelector(${q('[aria-label="关闭技能详情"]')});const r=b.getBoundingClientRect();return b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()`),true,'dialog above corner controls');
      await field('.skill-install-form input[type=url]','https://github.com/example/skills');await button('识别技能');
      await wait('!!document.querySelector(".skill-candidate")','GitHub candidate');await shot('github');
      await button('安装所选技能');await wait('document.body.textContent.includes("模拟安装失败")','install failure');
      assert.equal(await js('document.querySelector(".skill-install-form input[type=url]").value'), 'https://github.com/example/skills');
      await button('安装所选技能');await wait('!!document.querySelector(".skill-list-row") && !document.querySelector(".skill-sheet")','installed list');
      assert.equal(await js(`(()=>{const grid=document.querySelector('.skill-list'),card=document.querySelector('.skill-list-row');return getComputedStyle(grid).gridTemplateColumns.split(' ').length===3 && getComputedStyle(card).borderRadius==='16px' && !!card.querySelector('.skill-card-footer')})()`),true,'skills use the shared three-column card library');
      await shot('library');
      await js('document.querySelector(".skill-list-row").click()');await wait('!!document.querySelector(".skill-body")','detail');await shot('detail');
      assert.equal(await js('(async()=> (await fetch(document.querySelector(".skill-resources a").href)).status)()'),200);
      assert.equal(await js('(async()=> (await fetch(document.querySelector(".skill-detail-toolbar a").href)).status)()'),200);
      await button('停用');await wait('document.querySelector(".skill-status")?.textContent==="已停用"','disabled');
      await button('启用');await wait('document.querySelector(".skill-status")?.textContent==="已启用"','enabled');
      await js(`(()=>{const s=document.querySelector('.skill-detail-toolbar select');s.value='1';s.dispatchEvent(new Event('change',{bubbles:true}))})()`);
      await wait('document.body.textContent.includes("这是只读历史版本")','history');await button('返回当前版本');
      await wait('!document.body.textContent.includes("这是只读历史版本")','current');
      await button('在对话中修改');await wait('!!document.querySelector(".intake-composer-editor")','edit in chat');
      assert.equal(await js('document.querySelector(".intake-composer-editor").textContent.includes("skill-fixture")'),true);
      await win.loadURL(base+'/skills');await wait('!!document.querySelector(".skill-list-row")','list again');
      await field('[aria-label="搜索技能"]','没有此技能');await wait('document.body.textContent.includes("没有找到匹配")','search none');
      await field('[aria-label="搜索技能"]','包装');await wait('!!document.querySelector(".skill-list-row")','search result');
      await js('document.querySelector(".skill-list-row").click()');await wait('!!document.querySelector(".skill-body")','reopen');
      await button('卸载');await button('卸载技能');await wait('!document.querySelector(".skill-list-row") && !document.querySelector(".skill-sheet")','uninstalled');
      await js(`fetch('http://127.0.0.1:5296/__fixture/builtins',{method:'POST'})`);
      await win.loadURL(base+'/skills');await wait('document.querySelectorAll(".skill-list-row").length===6','six shipped skills');
      assert.equal(await js('[...document.querySelectorAll(".skill-source")].every(e=>e.textContent==="内置技能")'),true);
      const coverState=await js(`[...document.querySelectorAll('.skill-list-row')].map(card=>{const cover=card.querySelector('.skill-card-cover'),style=cover&&getComputedStyle(cover);return{classes:card.className,cover:!!cover,position:style?.backgroundPosition,image:style?.backgroundImage,cardBackground:getComputedStyle(card).backgroundColor,titleColor:getComputedStyle(card.querySelector('.skill-name strong')).color}})`);
      assert.equal(coverState.length,6,'six built-in skill cards render');
      assert.ok(coverState.every(item=>item.classes.includes('has-cover')&&item.cover&&item.image.includes('skill-card-sprite-v1.png')),JSON.stringify(coverState));
      assert.equal(new Set(coverState.map(item=>item.position)).size,6,'six built-in skills use distinct sprite frames');
      assert.equal(await js(`fetch(${q(base+'/assets/skill-card-sprite-v1.png')}).then(response=>response.ok)`),true,'generated skill sprite is packaged');
      await shot('builtins');
      const builtinRevision=JSON.parse(fs.readFileSync(path.join(root,'services/api/app/builtin_skills/manifest.json'),'utf8')).skills[0].revision;
      await js('document.querySelector(".skill-list-row").click()');await wait(`document.body.textContent.includes(${q('内置技能 · '+builtinRevision)})`,'builtin detail');
      await win.loadFile(path.join(root,'dist/renderer/index.html'),{hash:'/skills'});await wait('!!document.querySelector(".skill-library")','desktop route');
      assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:['browser and desktop routes','shared navigation and wrench','shared card library layout','six generated sprite covers','home conversation create/edit','GitHub inspect/install with pinned commit','failure/retry idempotency','resources/export','history','enable/disable','instant search','uninstall'],screenshots:['/tmp/aics-skills-github.png','/tmp/aics-skills-detail.png','/tmp/aics-skills-library.png','/tmp/aics-skills-builtins.png']}));
      win.destroy();app.exit(0);
    }catch(error){console.error(error);console.error(await js('document.body.innerText.slice(-2000)').catch(()=>''));await shot('error');win.destroy();app.exit(1);}
  });
}
