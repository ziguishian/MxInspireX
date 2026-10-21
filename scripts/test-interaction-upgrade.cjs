// Full renderer, isolated local API and IndexedDB. No real provider or workspace access.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/interaction-upgrade-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const projects = ['a','b'].map(id => ({ id, name: `项目 ${id}`, slug:id, brief:'', status:'draft', createdAt:'2026-10-10T01:00:00Z' }));
    const task = { id:'current', projectId:'a', agentKey:'design', userMessage:'制作蓝色方案', status:'succeeded', createdAt:'2026-10-10T02:00:00Z', updatedAt:'2026-10-10T02:00:00Z', trace:[{phase:'model_call',message:'模型调用',data:{totalModelCalls:3}}], output:{structured_data:{answer:'产物已保存，审查超时。',deliveryStatus:'needs_review',review:{status:'timed_out',unverifiedNodeIds:['v1']}}} };
    const canvasTask = { id:'canvas-task', projectId:'b', agentKey:'design', taskSurface:'canvas_node', canvasNodeId:'v1', status:'running', userMessage:'独立画布任务' };
    let board = { nodes:['v1','v2'].map((id,i) => ({ id,type:'creative',position:{x:i*340,y:0},data:{kind:'text',title:`方案 ${i+1}`,text:`版本 ${i+1} 的真实文字`,previewSize:{width:240,height:180}} })),edges:[] };
    const posts=[],updates=[],patches=[];
    const json=(res,data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json','Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'});res.end(JSON.stringify(data));};
    const server=require('node:http').createServer(async(req,res)=>{
      const p=new URL(req.url,'http://fixture.invalid').pathname;
      if(req.method==='OPTIONS')return json(res,{});
      let body={}; if(['POST','PATCH'].includes(req.method)){let raw='';for await(const chunk of req)raw+=chunk;body=raw?JSON.parse(raw):{};}
      if(p==='/fixture/state')return json(res,{task,posts,updates,patches,board});
      if(p==='/fixture/running'){task.status='running';task.output=null;return json(res,{});}
      if(p==='/fixture/unconfirmed'){task.status='failed';task.error={message:'image_result_unconfirmed'};task.output=null;return json(res,{});}
      if(p==='/fixture/canvas-finished'){canvasTask.status='succeeded';return json(res,{});}
      if(p==='/api/tasks/activity')return json(res,[task,canvasTask,...['queued','pending','failed','cancelled'].map(status=>({id:`other-${status}`,projectId:'b',agentKey:'design',status,userMessage:`不展示的${status}任务`}))]);
      if(p.endsWith('/updates')&&req.method==='POST'){updates.push(body);task.updates=[{id:body.requestId,text:body.text,appliedAt:null}];return json(res,task.updates[0]);}
      if(p.endsWith('/inspection'))return json(res,{task,nodes:board.nodes,receipts:[{tool:'generate_image',status:'running',updatedAt:'now'}],billing:[{id:'pending',model:'fixture-image',kind:'image',status:'pending'}],billingNote:'结果待确认，本地暂无金额不能证明未收费。'});
      if(p.endsWith('/tasks')&&req.method==='POST'){posts.push(body);return json(res,{...task,id:`post-${posts.length}`,status:'succeeded',userMessage:body.brief,output:{structured_data:{answer:'收到',deliveryStatus:'passed'}}});}
      if(p.endsWith('/canvas')&&req.method==='PATCH'){patches.push(body);for(const patch of body.upsertNodes||[]){const node=board.nodes.find(n=>n.id===patch.id);Object.assign(node,patch);}return json(res,board);}
      if(p.endsWith('/events'))return json(res,{},503);
      if(p==='/health')return json(res,{status:'ok'});
      if(p==='/api/projects')return json(res,projects);
      if(/^\/api\/projects\/[ab]$/.test(p))return json(res,projects.find(pr=>pr.id===p.split('/').at(-1)));
      if(p.endsWith('/tasks'))return json(res,p.includes('/a/')?[task]:[canvasTask]);
      if(/\/tasks\/[^/]+$/.test(p))return json(res,task);
      if(/\/(canvas|preview)$/.test(p))return json(res,board);
      if(p==='/api/providers')return json(res,[{key:'openrouter',label:'Fixture',configured:true,available:true}]);
      if(p==='/api/providers/model-catalog')return json(res,{models:['fixture-text'],textModels:['fixture-text'],modelCatalog:[{id:'fixture-text',kinds:['text']}]});
      if(p==='/api/model-settings')return json(res,{credits:{sellCnyPerCredit:.1,cnyPerUsd:7},media:{image:{standard:''},video:{standard:''}}});
      if(/usage|credits/.test(p))return json(res,{points:0,pending:0,byDay:{},byTask:{},daily:[],events:[],total:0});
      if(/delivery.*claim/.test(p))return json(res,null);
      return json(res,[]);
    });
    try{
      await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
      const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode=await new Promise((resolve,reject)=>{const child=require('node:child_process').spawn(require('electron'),[__filename,String(server.address().port)],{env,stdio:'inherit'});child.on('error',reject);child.on('exit',code=>resolve(code??1));});
    }finally{server.closeAllConnections();server.close();}
  })().catch(e=>{console.error(e);process.exitCode=1;});
}else{
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async()=>{
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:1500,height:1100,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false,partition:'interaction-upgrade-fixture'}});
    win.webContents.on('console-message',event=>{if(event.level==='error')console.error('Renderer:',event.message);});
    const base=`http://127.0.0.1:${process.argv[2]}`;
    win.webContents.session.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(details,callback)=>{if(details.url.startsWith('http://127.0.0.1:8765/'))callback({redirectURL:details.url.replace('http://127.0.0.1:8765',base)});else callback({cancel:!details.url.startsWith(base+'/')});});
    const js=code=>win.webContents.executeJavaScript(code,true),q=JSON.stringify;
    const wait=async code=>{for(let i=0;i<150;i++){if(await js(code).catch(()=>false))return;await pause(60);}throw new Error('Timeout: '+code);};
    const click=selector=>js(`document.querySelector(${q(selector)}).click()`);
    const clickText=(selector,text)=>js(`[...document.querySelectorAll(${q(selector)})].find(el=>el.textContent.trim()===${q(text)}).click()`);
    const state=()=>fetch(base+'/fixture/state').then(r=>r.json());
    const editor='.intake-composer-editor';
    const setDraft=async text=>{await js(`(()=>{const el=document.querySelector(${q(editor)});el.focus();el.textContent=${q(text)};el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));})()`);await pause(80);};
    const openProject=async()=>{await click('[aria-label="项目"]');await wait("!!document.querySelector('.project-card')");await js("[...document.querySelectorAll('.project-card')].find(el=>el.textContent.includes('项目 a')).click()");await wait("document.querySelectorAll('.vue-flow__node').length===2&&!!document.querySelector('.intake-composer-editor')");await pause(400);};
    const checks=[];
    try{
      await win.loadFile(path.join(root,'dist/renderer/index.html'));await wait("!!document.querySelector('.home-intake')");
      await js(`localStorage.setItem('langjuart.firstRequestCelebrated','true');new Promise((resolve,reject)=>{const req=indexedDB.open('langju-composer-drafts',1);req.onupgradeneeded=()=>req.result.createObjectStore('drafts');req.onsuccess=()=>{const tx=req.result.transaction('drafts','readwrite');tx.objectStore('drafts').put([{id:'queued-id',text:'下一项需求',createdAt:'now',draft:{text:'下一项需求',files:[new File(['ref'],'保留.txt',{type:'text/plain'})],results:[],assets:[],mentionedFiles:[],skills:[]}}],'message-queue:a');tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);};})`);
      await new Promise(resolve=>{win.webContents.once('did-finish-load',resolve);win.reload();});await wait("!!document.querySelector('.home-intake')");await openProject();
      await wait("!!document.querySelector('.composer-message-queue')");await pause(500);
      assert.equal((await state()).posts.length,0,'reopening needs_review must not send queued work');
      assert.ok(await js("document.querySelector('.composer-message-queue-header').textContent.includes('核实')"));
      checks.push('reopening a succeeded but unverified task keeps queue paused');
      await click('.queue-message-actions button[aria-label="编辑待发送消息"]');
      await js("(()=>{const el=document.querySelector('textarea[aria-label=\"编辑待发送消息\"]');el.value='修改后的下一项';el.dispatchEvent(new Event('input',{bubbles:true}));})()");
      await clickText('.queue-message-copy button','保存');await pause(100);
      assert.ok(await js("document.querySelector('.queue-message-copy').textContent.includes('修改后的下一项')"));
      assert.ok(await js("document.querySelector('.queue-message-copy').textContent.includes('1 个附件')"));
      checks.push('queue edits preserve attachment metadata and do not dispatch a paused queue');
      await click('.composer-message-queue-header button');await wait("!!document.querySelector('.request-inspector')");
      await clickText('.request-inspector nav button','计费状态');await wait("document.querySelector('.request-inspector').textContent.includes('金额待核算')");
      await clickText('.request-inspector footer button','刷新记录');await pause(100);assert.equal((await state()).posts.length,0);
      await click('.request-inspector [aria-label="关闭"]');
      assert.equal(await js("document.querySelector('.task-execution-details').open"),false);
      checks.push('inspection exposes pending billing without replay; technical metrics are collapsed');
      await click('.task-queue-fab');await wait("!!document.querySelector('.task-queue-card')");
      assert.ok(await js("document.querySelector('.task-queue-card').textContent.includes('独立画布任务')"));
      assert.equal(await js("document.querySelectorAll('.task-queue-card .task-queue-item').length"),1);
      assert.equal(await js("document.querySelector('.task-queue-count').textContent"),'1');
      for(const text of ['等待你处理','待发送','修改后的下一项','制作蓝色方案','不展示的'])assert.equal(await js(`document.querySelector('.task-queue-card').textContent.includes(${q(text)})`),false);
      await fetch(base+'/fixture/canvas-finished');
      await wait("!!document.querySelector('.task-queue-empty') && !document.querySelector('.task-queue-count')");
      assert.equal(await js("document.querySelectorAll('.task-queue-card .task-queue-item').length"),0);
      assert.ok(await js("document.querySelector('.task-queue-empty').textContent.includes('当前没有正在运行的任务')"));
      await click('.task-queue-card .assistant-collapse-button');
      checks.push('task entry shows and counts only running work, excluding queued, pending, failed and attention items; completion clears the badge');
      // Compare through the actual canvas action menu, then persist the adopted flag.
      await click('[aria-label="画布操作与快捷键"]');await clickText('.canvas-shortcuts header button','操作');
      await wait("[...document.querySelectorAll('.canvas-tool-options button')].some(el=>el.textContent==='作品版本对比')");
      await clickText('.canvas-tool-options button','作品版本对比');await wait("!!document.querySelector('.version-compare')");
      await js("(async()=>{for(const el of document.querySelectorAll('.version-picker input')){el.click();await new Promise(r=>setTimeout(r,20));}})()");await wait("document.querySelectorAll('.version-grid article').length===2");
      await clickText('.version-grid article:first-child button','采用此版');await wait("!!document.querySelector('.adopted-version-badge')");
      assert.equal((await state()).board.nodes[0].data.adopted,true);assert.equal((await state()).board.nodes[1].data.adopted,false);
      await clickText('.version-grid article:last-child button','从此版继续修改');await wait("!document.querySelector('.version-compare')");
      assert.ok(await js("document.querySelector('.intake-composer-editor').dataset.renderedText.includes('@node:v2')"));
      checks.push('side-by-side comparison saves adoption and binds continued edits to the chosen version');
      await setDraft('');await fetch(base+'/fixture/running');await click('[aria-label="返回首页"]');await openProject();
      await wait("!!document.querySelector('[aria-label=\"运行中发送方式\"]')");
      await setDraft('不要蓝色，改用绿色');await click('[aria-label="补充当前任务"]');await wait("document.querySelector('.task-supplements')?.textContent.includes('不要蓝色，改用绿色')");
      assert.equal((await state()).updates.length,1);assert.equal((await state()).posts.length,0);
      await js("(()=>{const el=document.querySelector('[aria-label=\"运行中发送方式\"]');el.value='queue';el.dispatchEvent(new Event('change',{bubbles:true}));})()");
      await setDraft('另一项独立需求');await click('[aria-label="加入待发送队列"]');await wait("document.querySelector('.composer-message-queue').textContent.includes('另一项独立需求')");
      assert.equal((await state()).updates.length,1);assert.equal((await state()).posts.length,0);
      checks.push('running composer distinguishes steering current work from adding the next task');
      const avatar=()=>js("(()=>{const r=document.querySelector('.design-chat-title .agent-avatar-sprite').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()");
      const before=await avatar();await pause(700);assert.deepEqual(await avatar(),before);
      await fetch(base+'/fixture/unconfirmed');await click('[aria-label="返回首页"]');await openProject();
      await wait("!!document.querySelector('.design-chat-title [data-state=\"error\"]')");
      await clickText('.design-message button','查看请求、产物与计费');await wait("!!document.querySelector('.request-inspector')");
      await wait("document.querySelector('.request-inspector').textContent.includes('制作蓝色方案')");
      assert.equal((await state()).posts.length,0);
      checks.push('uncertain generation opens request inspection and Xiaoju reflects the problem');
      assert.deepEqual(await avatar(),before,'state changes keep the header avatar in place');
      await click('.request-inspector [aria-label="关闭"]');await click('[aria-label="返回首页"]');await wait("!!document.querySelector('.home-intake')");
      await click('[aria-label="打开用户设置"]');await click('.user-menu-settings');await clickText('.settings-tab','外观');
      await js("[...document.querySelectorAll('.settings-switch')].find(el=>el.textContent.includes('减少动画')).querySelector('input').click()");
      await wait("document.documentElement.dataset.reduceAnimations==='true'");
      assert.equal(await js("getComputedStyle(document.querySelector('.home-composer-lumo-sprite')).animationName"),'none');
      assert.equal(await js("localStorage.getItem('langjuart.reduceAnimations')"),'true');
      checks.push('reduced animation preference stops mascot animation and persists locally');
      fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(checks,null,2));
      fs.writeFileSync(path.join(output,'result.png'),(await win.webContents.capturePage()).toPNG());
      console.log('PASS interaction upgrade\n'+checks.map(c=>'- '+c).join('\n'));
    }catch(e){fs.writeFileSync(path.join(output,'failure.png'),(await win.webContents.capturePage()).toPNG());console.error(e);process.exitCode=1;}
    finally{win.destroy();app.exit(process.exitCode||0);}
  });
}
