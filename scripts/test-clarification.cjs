// Exercise the real canvas and Vue form in Chromium. No API or model calls.
const path = require('node:path'), fs = require('node:fs'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ appType:'custom', configFile:path.join(root,'apps/renderer/vite.config.ts'), server:{host:'127.0.0.1',port:5324,strictPort:true,hmr:false},logLevel:'error' });
    server.middlewares.use('/clarification-check',async (_req,res) => { res.setHeader('Content-Type','text/html'); res.end(await server.transformIndexHtml('/clarification-check',fs.readFileSync(path.join(__dirname,'fixtures/clarification.html'),'utf8'))); });
    const env={...process.env}; delete env.ELECTRON_RUN_AS_NODE;
    try {
      await server.listen();
      process.exitCode=await new Promise((resolve,reject) => { const child=require('node:child_process').spawn(require('electron'),[__filename],{env,stdio:'inherit'}); child.on('error',reject); child.on('exit',code=>resolve(code ?? 1)); });
    } finally { await server.close(); }
  })().catch(error=>{ console.error(error); process.exitCode=1; });
} else {
  const {app,BrowserWindow}=require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win=new BrowserWindow({show:false,width:1300,height:940,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false,partition:'clarification-fixture'}});
    const js=code=>win.webContents.executeJavaScript(code);
    const wait=async code=>{ for(let i=0;i<100;i++){if(await js(code).catch(()=>false)) return; await pause(40);} throw new Error('Timeout: '+code); };
    const click=selector=>js(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const type=text=>js(`(()=>{const el=document.querySelector('.clarification-custom-input');el.value=${JSON.stringify(text)};el.dispatchEvent(new Event('input',{bubbles:true}))})()`);
    const step=n=>wait(`document.querySelector('.clarification-header nav > span')?.textContent.trim()==='${n} / 3'`);
    const checks=[];
    try {
      await win.loadURL('http://127.0.0.1:5324/clarification-check'); await wait('window.ready');
      await js('localStorage.clear()'); await js('remount()'); await step(1);
      assert.equal(await js(`document.querySelectorAll('.clarification-title').length`),1);
      assert.equal(await js(`document.querySelectorAll('.design-chat-scroll .clarification-card').length`),0);
      assert.equal(await js(`getComputedStyle(document.querySelector('.design-clarification-dock')).position`),'absolute');
      const chatHeight = await js(`document.querySelector('.design-chat-scroll').getBoundingClientRect().height`);
      await js(`document.querySelector('.design-clarification-dock').style.display='none'`);
      assert.equal(await js(`document.querySelector('.design-chat-scroll').getBoundingClientRect().height`),chatHeight,'floating questions must not shrink chat history');
      await js(`document.querySelector('.design-clarification-dock').style.display=''`);
      assert.equal(await js(`document.querySelector('.design-chat-scroll').textContent.includes('不应重复显示')`),false);
      assert.ok(await js(`document.querySelector('.clarification-next').disabled`));
      await click('.clarification-option input');
      await click('.clarification-custom-option input'); await wait(`!!document.querySelector('.clarification-custom-input')`);
      await type('银发游客，保留舒适感');
      assert.equal(await js(`document.querySelectorAll('.clarification-option:not(.clarification-custom-option) input:checked').length`),0);
      await click('.clarification-next'); await step(2);
      await js(`document.querySelectorAll('.clarification-option input')[0].click();document.querySelectorAll('.clarification-option input')[1].click()`);
      await click('.clarification-custom-option input'); await type('还需要门票和导览牌');
      await click('.clarification-back'); await step(1);
      assert.equal(await js(`document.querySelector('.clarification-custom-input').value`),'银发游客，保留舒适感');
      await click('.clarification-next'); await step(2);
      assert.equal(await js(`document.querySelectorAll('.clarification-option input:checked').length`),3);
      await js('remount()'); await step(2);
      assert.equal(await js(`document.querySelector('.clarification-custom-input').value`),'还需要门票和导览牌');
      checks.push('逐题展示；单选自定义替换选项；多选可补充文字；返回及重新打开保留答案');
      for(const [width,height,theme] of [[1300,940,'dark'],[430,800,'light'],[900,580,'dark']]) {
        win.setContentSize(width,height); await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`); await pause(600);
        assert.ok(await js(`(()=>{const c=document.querySelector('.clarification-card'),b=c.getBoundingClientRect(),f=c.querySelector('footer').getBoundingClientRect(),p=document.querySelector('#design-composer-host').getBoundingClientRect();return c.scrollWidth<=c.clientWidth+1&&b.left>=0&&b.right<=innerWidth&&f.bottom<=p.top+1&&f.top>=b.top&&p.bottom<=innerHeight+1})()`),'card/footer/composer fit '+width+'x'+height);
        fs.writeFileSync(`/private/tmp/aics-clarification-${width}-${theme}.png`,(await win.webContents.capturePage()).toPNG());
      }
      checks.push('深浅主题、窄边栏和矮窗口：卡片悬浮在输入框上方，不压缩聊天区，内容独立滚动');
      await click('.clarification-next'); await step(3);
      assert.ok(await js(`!!document.querySelector('.clarification-custom-input')`));
      await type('白鹭文旅');
      await js(`document.querySelector('.clarification-next').click();document.querySelector('.clarification-next').click()`);
      assert.equal(await js('fixture.submitted.length'),1);
      const sent=await js('JSON.parse(JSON.stringify(fixture.submitted[0]))');
      assert.equal(sent.taskId,'clarification-fixture-1');
      assert.deepEqual(sent.entries.map(entry=>[entry.questionId,entry.questionIndex,entry.skipped]),[['audience',0,false],['deliverables',1,false],['brand',2,false]]);
      for(const text of ['银发游客，保留舒适感','Logo / 品牌标志；标准色与字体规范；还需要门票和导览牌','白鹭文旅']) assert.ok(sent.answers.includes(text));
      await js('fixture.busy=false'); await wait(`!document.querySelector('.clarification-next').disabled`);
      assert.equal(await js(`document.querySelector('.clarification-custom-input').value`),'白鹭文旅');
      await js('respond()'); await wait(`!document.querySelector('.clarification-card')`);
      await js('remount()'); await pause(150);
      assert.equal(await js(`!!document.querySelector('.clarification-card')`),false);
      await js('newQuestions()'); await step(1);
      assert.equal(await js(`document.querySelectorAll('.clarification-option input:checked').length`),0);
      await click('.clarification-skip'); await step(2); await click('.clarification-skip'); await step(3); await click('.clarification-skip');
      assert.ok((await js('fixture.submitted.at(-1).answers')).includes('暂时跳过，尚未确定。'));
      assert.equal(await js(`document.querySelector('.intake-composer-editor').textContent`),'输入框中的未发送草稿');
      checks.push('全部答案一次提交；防双击；提交未成功可重试；旧问题不重开；新任务无旧选择；跳过不冒充已确认');
      assert.ok(await js('fixture.submitted.at(-1).entries.every(entry=>entry.skipped && !entry.value)'));
      await js('showDelivery()'); await wait(`!!document.querySelector('.task-deliverables')`);
      await click('.task-deliverables summary'); await click('.task-decisions summary');
      assert.equal(await js(`document.querySelector('.task-deliverables summary').textContent.trim()`),'交付进度 2/4 项已生成');
      assert.equal(await js(`document.querySelector('.task-progress-label').textContent.trim()`),'仍有待交付项');
      assert.equal(await js(`document.querySelectorAll('.task-deliverables li').length`),4);
      assert.ok(await js(`document.querySelector('.task-deliverables').textContent.includes('等待：尺寸')`));
      assert.ok(await js(`document.querySelector('.task-decisions').textContent.includes('临时假设')`));
      for(const [width,theme] of [[430,'light'],[1300,'dark']]) {
        win.setContentSize(width,940); await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`); await pause(350);
        assert.ok(await js(`[...document.querySelectorAll('.task-progress,.task-deliverables li,.task-decisions')].every(el=>el.scrollWidth<=el.clientWidth+1)`),'delivery progress has no overflow');
        fs.writeFileSync(`/private/tmp/aics-delivery-${width}-${theme}.png`,(await win.webContents.capturePage()).toPNG());
      }
      checks.push('交付清单逐项区分已通过、待审查、缺项和阻塞；确认与假设可见；窄窗口无溢出');
      console.log(JSON.stringify({passed:true,checks},null,2));
    } catch(error) { console.error(error); process.exitCode=1; fs.writeFileSync('/private/tmp/aics-clarification-error.png',(await win.webContents.capturePage()).toPNG()); }
    finally {win.destroy();app.exit(process.exitCode||0);}
  });
}
