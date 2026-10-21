// Real App + isolated API: edit a historical turn without appending messages.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), output = path.join(root, '.tmp/message-editing-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const project = { id: 'editing-fixture', name: '编辑对话测试', brief: '', status: 'draft', slug: 'editing-fixture', createdAt: '2026-09-15T01:00:00Z' };
    let reject = false, edits = [], posts = 0;
    let tasks = ['前面的要求', '@1 制作蓝色海报', '后续消息'].map((text, index) => ({ id: ['before', 'original', 'after'][index], conversationTurnId: ['before', 'original', 'after'][index],
      agentKey: 'design', userMessage: text, createdAt: `2026-09-15T01:00:0${index}Z`, updatedAt: `2026-09-15T01:00:0${index}Z`, status: index === 1 ? 'failed' : 'succeeded',
      error: index === 1 ? { message: 'fixture failure' } : null, trace: [], output: { structured_data: { answer: ['之前的回复', '过期回复', '后续回复'][index] } },
      references: index === 1 ? { referencedFiles: [{ documentId: 'original-doc', index: 1, filename: '原始参考.txt', mime: 'text/plain', projectId: project.id }] } : {} }));
    const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' }); res.end(JSON.stringify(data)); };
    const server = require('node:http').createServer(async (req, res) => {
      const url = new URL(req.url, 'http://fixture.invalid'), p = url.pathname;
      if (req.method === 'OPTIONS') return json(res, {});
      if (p === '/fixture/state') return json(res, { tasks, edits, posts });
      if (p === '/fixture/reject') { reject = url.searchParams.get('value') === 'true'; return json(res, {}); }
      if (p === '/fixture/finish') { const task = tasks.find(t => t.status === 'queued'); if (task) Object.assign(task, { status: 'succeeded', output: { structured_data: { answer: '修改后的新回复' } } }); return json(res, {}); }
      const target = p.match(/\/tasks\/([^/]+)$/);
      if (target && req.method === 'PATCH') {
        let raw = ''; for await (const chunk of req) raw += chunk;
        const body = JSON.parse(raw), index = tasks.findIndex(t => t.id === target[1]);
        if (reject) return json(res, { detail: '保存修改失败，请重试' }, 409);
        if (index < 0) return json(res, { detail: '不存在' }, 404);
        const old = tasks[index], task = { ...old, id: `edit-${edits.length + 1}`, replacesTaskId: old.id, userMessage: body.brief, status: 'queued', error: null, output: null,
          references: body.input, trace: [{ phase: 'queued', message: '消息已修改，正在重新处理', at: new Date().toISOString() }] };
        edits.push(body); tasks[index] = task; return json(res, task);
      }
      if (p.endsWith('/tasks') && req.method === 'POST') { posts++; return json(res, { detail: '编辑不能追加提交' }, 400); }
      if (target) return json(res, tasks.find(t => t.id === target[1]));
      if (p.endsWith('/events')) return json(res, {}, 503); // Exercise persisted snapshot fallback.
      if (p === '/health') return json(res, { status: 'ok' });
      if (p === '/api/providers') return json(res, [{ key: 'openrouter', label: 'Fixture', configured: true, available: true }]);
      if (p === '/api/providers/model-catalog') return json(res, { models: ['fixture-text'], textModels: ['fixture-text'], modelCatalog: [{ id: 'fixture-text', kinds: ['text'] }] });
      if (p === '/api/model-settings') return json(res, { credits: { sellCnyPerCredit: .1, cnyPerUsd: 7 }, media: { image: { standard: '' }, video: { standard: '' } } });
      if (p === '/api/projects') return json(res, [project]);
      if (p === `/api/projects/${project.id}`) return json(res, project);
      if (p.endsWith('/tasks')) return json(res, [...tasks].reverse());
      if (/\/(canvas|preview)$/.test(p)) return json(res, { nodes: [], edges: [] });
      if (/usage|credits/.test(p)) return json(res, { points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 });
      if (/delivery.*claim/.test(p)) return json(res, null);
      return json(res, []);
    });
    try {
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, String(server.address().port)], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { server.closeAllConnections(); server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1440, height: 1000, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'message-editing-fixture' } });
    const base = `http://127.0.0.1:${process.argv[2]}`;
    win.webContents.session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] }, (details, callback) => {
      if (details.url.startsWith('http://127.0.0.1:8765/')) callback({ redirectURL: details.url.replace('http://127.0.0.1:8765', base) });
      else callback({ cancel: !details.url.startsWith(base + '/') });
    });
    const js = code => win.webContents.executeJavaScript(code, true);
    const wait = async (code, label) => { for (let i = 0; i < 120; i++) { if (await js(code).catch(() => false)) return; await pause(80); } throw new Error('Timeout: ' + label); };
    const fixture = route => fetch(base + route).then(res => res.json());
    const setText = text => js(`(()=>{const el=document.querySelector('.user-message-editor');el.value=${JSON.stringify(text)};el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    const users = () => js("[...document.querySelectorAll('.design-message.user')].map(el=>({id:el.dataset.taskId,text:el.querySelector('.user-message-bubble').textContent}))");
    try {
      await win.loadFile(path.join(root, 'dist/renderer/index.html'));
      await wait("!!document.querySelector('.home-intake')", 'homepage');
      await js("localStorage.setItem('langjuart.firstRequestCelebrated','true');localStorage.setItem('langjuart.firstUseCompleted','true');document.querySelector('.sidebar-nav-item[aria-label=项目]').click()");
      await wait("!!document.querySelector('.project-card')", 'project catalogue');
      await js("document.querySelector('.project-card').click()");
      await wait("document.querySelectorAll('.design-message.user').length===3", 'restored conversation');
      assert.equal(await js("(()=>{const bubble=document.querySelector('.design-message.user .user-message-bubble'),surface=bubble?.querySelector('.user-message-surface'),actions=bubble?.querySelector('.user-message-actions');return !!surface&&surface.nextElementSibling===actions&&!surface.contains(actions)})()"), true, 'user actions sit below the bubble surface');
      assert.equal(await js("!!document.querySelector('.design-message.assistant [aria-label=\"复制回复\"]')"), true, 'assistant replies expose a copy action');
      await js("(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.__copiedReply=value}}});document.querySelector('.design-message.assistant[data-task-id=before] [aria-label=\"复制回复\"]').click()})()");
      await wait("window.__copiedReply==='之前的回复'", 'assistant reply copied');
      await js("(()=>{const composer=document.querySelector('.intake-composer'),transfer=new DataTransfer();transfer.items.add(new File(['drag fixture'],'拖拽测试.txt',{type:'text/plain'}));window.__composerFileTransfer=transfer;composer.dispatchEvent(new DragEvent('dragenter',{bubbles:true,cancelable:true,dataTransfer:transfer}))})()");
      await wait("!!document.querySelector('.composer-file-drop-hint')", 'composer drop hint');
      await js("(()=>{const composer=document.querySelector('.intake-composer'),transfer=window.__composerFileTransfer;composer.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer}));composer.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}))})()");
      await wait("!!document.querySelector('[aria-label=\"移除附件 拖拽测试.txt\"]')", 'dropped composer attachment');
      await js("document.querySelector('[aria-label=\"移除附件 拖拽测试.txt\"]').click()");
      await js("(()=>{const input=document.querySelector('.file-tool input[type=file]'),transfer=new DataTransfer();transfer.items.add(new File(['image fixture'],'自动判断.png',{type:'image/png'}));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}))})()");
      await wait("!!document.querySelector('[aria-label=\"移除附件 自动判断.png\"]')", 'image composer attachment');
      assert.equal(await js("!!document.querySelector('.composer-reference-modes,[aria-label=\"图片用途\"]')"), false, 'composer has no manual image-purpose UI');
      await js("document.querySelector('[aria-label=\"移除附件 自动判断.png\"]').click()");
      await js("(()=>{const el=document.querySelector('.intake-composer-editor');el.textContent='不要覆盖的草稿';el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));document.querySelector('.design-message.assistant[data-task-id=original] .design-canvas-result').click()})()");
      await wait("!!document.querySelector('.user-message-editor')", 'failure action edits original in place');
      await setText('@原始参考.txt 制作红色海报');
      await fixture('/fixture/reject?value=true');
      await js("document.querySelector('.message-resend').click()");
      await wait("document.querySelector('.user-message-action-error')?.textContent.includes('修改尚未保存')", 'failed edit retained');
      assert.equal((await users()).length, 3);
      assert.equal(await js("document.querySelector('.user-message-editor').value"), '@原始参考.txt 制作红色海报');
      await fixture('/fixture/reject?value=false');
      await js("document.querySelector('.message-resend').click()");
      await wait("!!document.querySelector('.design-message.user[data-task-id=edit-1]') && !document.querySelector('.user-message-editor')", 'edited turn accepted');
      assert.deepEqual((await users()).map(x => x.id), ['before', 'edit-1', 'after']);
      assert.equal(await js("document.querySelectorAll('.design-message.assistant').length"), 3);
      assert.equal(await js("document.querySelector('.design-message.assistant[data-task-id=edit-1]').classList.contains('has-error')"), false);
      assert.equal(await js("document.querySelector('.design-message.assistant[data-task-id=edit-1]').textContent.includes('过期回复')"), false);
      assert.equal(await js("document.querySelector('.intake-composer-editor').textContent"), '不要覆盖的草稿');
      const submitted = (await fixture('/fixture/state')).edits[0];
      assert.equal(submitted.brief, '@1 制作红色海报');
      assert.equal(submitted.input.referencedFiles[0].documentId, 'original-doc');
      await fixture('/fixture/finish');
      await wait("document.querySelector('.design-message.assistant[data-task-id=edit-1]').textContent.includes('修改后的新回复')", 'new reply replaces old status');
      await win.webContents.reload();
      await wait("document.querySelectorAll('.design-message.user').length===3", 'reopen edited history');
      assert.deepEqual((await users()).map(x => x.id), ['before', 'edit-1', 'after']);
      await js("document.querySelector('.design-message.user[data-task-id=edit-1] [aria-label=编辑并重新提交]').click()");
      await setText('@原始参考.txt 制作绿色海报');
      await js("document.querySelector('.message-resend').click()");
      await wait("!!document.querySelector('.design-message.user[data-task-id=edit-2]')", 'second edit');
      assert.deepEqual((await users()).map(x => x.id), ['before', 'edit-2', 'after']);
      await fixture('/fixture/finish');
      await wait("document.querySelector('.design-message.assistant[data-task-id=edit-2]').textContent.includes('修改后的新回复')", 'second edit completed');
      const state = await fixture('/fixture/state'); assert.equal(state.tasks.length, 3); assert.equal(state.posts, 0); assert.equal(state.edits.length, 2);
      fs.writeFileSync(path.join(output, 'edited.png'), (await win.webContents.capturePage()).toPNG());
      console.log(JSON.stringify({ passed: true, checks: ['user actions below bubble', 'assistant reply copy', 'composer file drop', 'automatic image-purpose UI', 'original position', 'old status cleared', 'new reply', 'failure retains edit', 'original attachments', 'composer draft intact', 'reload', 'repeated edit', 'no POST submissions'] }));
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); console.error(await js("({url:location.href,route:sessionStorage.getItem('langjuart.desktopRoute'),text:document.body.innerText.slice(0,700)})")); fs.writeFileSync(path.join(output, 'error.png'), (await win.webContents.capturePage()).toPNG()); win.destroy(); app.exit(1);
    }
  });
}
