// Real built composer, isolated API and simulated task submissions. No models.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..'), pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    const { preview } = await import('vite');
    const renderer = await preview({ configFile: path.join(root, 'apps/renderer/vite.config.ts'), preview: { host: '127.0.0.1', port: 5297, strictPort: true } });
    const project = { id: 'skill-mention-project', name: '技能引用测试', brief: '', status: 'draft', slug: 'skill-mention-project', createdAt: new Date().toISOString() };
    const titles = ['Logo 样机与品牌延展', '文旅 IP 形象设计', '笔记本图像设计', '景区导览系统设计', '小红书图文创作'];
    const skills = titles.map((title, index) => ({ id: `skill-${index}`, name: `sample-${index}`, title, description: title + '的适用场景与交付方法', version: 1, currentVersion: 1, enabled: true, deleted: false, missingTools: [], requiredTools: [] }));
    skills.push({ ...skills[0], id: 'disabled', title: '停用技能', enabled: false });
    skills.push({ ...skills[0], id: 'missing', name: 'missing', title: '缺少依赖', description: '测试不可用依赖', missingTools: ['absent_tool'] });
    let created = false, failed = false, submissions = [], tasks = [], rejectSubmission = false;
    const api = require('node:http').createServer(async (req, res) => {
      const url = new URL(req.url, 'http://fixture.invalid'), p = url.pathname;
      const respond = (data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' }); res.end(JSON.stringify(data)); };
      if (req.method === 'OPTIONS') return respond({});
      if (p === '/fixture/state') return respond({ submissions });
      if (p === '/fixture/reject') { rejectSubmission = url.searchParams.get('value') === 'true'; return respond({}); }
      if (p === '/api/skills') {
        const query = url.searchParams.get('query') || '', offset = Number(url.searchParams.get('offset') || 0);
        if (query === '失败' && !failed) { failed = true; return respond({ detail: '技能读取失败，请重试' }, 503); }
        if (query === 'Logo') await pause(550);
        const found = skills.filter(s => s.enabled && (query === '失败' || (s.title + s.name + s.description).toLowerCase().includes(query.toLowerCase())));
        return respond({ skills: found.slice(offset, offset + 2), total: found.length, nextOffset: offset + 2 < found.length ? offset + 2 : null });
      }
      if (p === '/api/intake') { for await (const _ of req) {} created = true; return respond({ project, files: [] }); }
      if (p.endsWith('/tasks') && req.method === 'POST') {
        let raw = ''; for await (const chunk of req) raw += chunk;
        const body = JSON.parse(raw);
        if (rejectSubmission) return respond({ detail: '技能已停用，请删除 # 标签或启用后重试' }, 400);
        submissions.push(body);
        const task = { id: `task-${tasks.length + 1}`, status: 'succeeded', agentKey: 'design', userMessage: body.brief, references: body.input, trace: [], output: { structured_data: { answer: '已收到技能引用测试。' } } };
        tasks.push(task); return respond(task);
      }
      if (p === '/health') return respond({ status: 'ok' });
      if (p === '/api/providers') return respond([{ key: 'openrouter', label: 'Fixture', configured: true, available: true }]);
      if (p === '/api/providers/model-catalog') return respond({ models: ['fixture-text'], textModels: ['fixture-text'], modelCatalog: [{ id: 'fixture-text', kinds: ['text'] }] });
      if (p === '/api/model-settings') return respond({ credits: { sellCnyPerCredit: .1, cnyPerUsd: 7 }, media: { image: { standard: '' }, video: { standard: '' } } });
      if (p === '/api/projects') return respond(created ? [project] : []);
      if (p === `/api/projects/${project.id}`) return respond(project);
      if (p.endsWith('/tasks')) return respond(tasks);
      if (/\/(canvas|preview)$/.test(p)) return respond({ nodes: [], edges: [] });
      if (/usage|credits/.test(p)) return respond({ points: 0, pending: 0, byDay: {}, byTask: {}, daily: [], events: [], total: 0 });
      if (/delivery.*claim/.test(p)) return respond(null);
      respond([]);
    });
    try {
      await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, String(api.address().port)], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await renderer.httpServer.close(); api.closeAllConnections(); api.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1280, height: 920, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, partition: 'skill-mentions-fixture' } });
    const api = `http://127.0.0.1:${process.argv[2]}`, base = 'http://127.0.0.1:5297', js = code => win.webContents.executeJavaScript(code), q = JSON.stringify;
    win.webContents.session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] }, (details, callback) => {
      if (details.url.startsWith('http://127.0.0.1:8765/')) callback({ redirectURL: details.url.replace('http://127.0.0.1:8765', api) });
      else callback({ cancel: ![base + '/', api + '/'].some(prefix => details.url.startsWith(prefix)) });
    });
    const wait = async (code, label) => { for (let i = 0; i < 90; i++) { if (await js(code).catch(() => false)) return; await pause(100); } throw Error('Timeout: ' + label); };
    const text = async value => { await js(`(()=>{const el=document.querySelector('.intake-composer-editor');el.focus();el.textContent=${q(value)};const range=document.createRange();range.selectNodeContents(el);range.collapse(false);const s=getSelection();s.removeAllRanges();s.addRange(range);el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));})()`); };
    const key = async (key, options = {}) => js(`document.querySelector('.intake-composer-editor').dispatchEvent(new KeyboardEvent('keydown',{key:${q(key)},bubbles:true,cancelable:true,...${JSON.stringify(options)}}))`);
    const append = async value => { await js(`(()=>{const el=document.querySelector('.intake-composer-editor');el.focus();const n=document.createTextNode(${q(value)});el.append(n);const range=document.createRange();range.setStart(n,n.length);range.collapse(true);const s=getSelection();s.removeAllRanges();s.addRange(range);el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));})()`); };
    const fixture = route => fetch(api + route).then(r => r.json());
    const shot = async name => fs.writeFileSync(`/tmp/aics-skill-mentions-${name}.png`, (await win.webContents.capturePage()).toPNG());
    const errors = []; win.webContents.on('console-message', (_e, level, message) => { if (level === 3 && !/Failed to load|Content Security|unsafe-eval/.test(message)) errors.push(message); });
    try {
      await win.loadURL(base); await wait('!!document.querySelector(".intake-composer-editor")', 'homepage');
      await text('#'); await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===2', '# picker');
      assert.equal(await js('document.querySelector(".skill-mention-menu").textContent.includes("停用技能")'), false);
      await js('document.querySelector(".skill-mention-more").click()'); await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===4', 'pagination');
      assert.equal(await js('(()=>{const r=document.querySelector(".skill-mention-menu").getBoundingClientRect();return r.top>=40 && r.bottom<innerHeight;})()'), true, 'menu remains inside viewport');
      await shot('menu');
      await key('ArrowDown'); await key('Enter'); await wait('document.querySelector(".intake-inline-skill")?.textContent.includes("文旅")', 'keyboard selection');
      assert.equal(await js('document.querySelector(".intake-inline-skill").dataset.mentionToken'), '#skill:skill-1');
      await append('制作一个 IP。 #Logo'); await pause(200); await text('#文旅');
      await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===1 && document.querySelector(".skill-mention-menu").textContent.includes("文旅")', 'latest Chinese search');
      await pause(650); assert.equal(await js('document.querySelector(".skill-mention-menu").textContent.includes("Logo")'), false, 'stale response discarded');
      await key('Escape'); assert.equal(await js('!!document.querySelector(".skill-mention-menu")'), false);
      await text('#缺少'); await wait('!!document.querySelector(".skill-mention-menu button[disabled]")', 'dependency unavailable');
      await key('Enter'); assert.equal(await js('!!document.querySelector(".intake-inline-skill")'), false);
      await text('#失败'); await wait('document.querySelector(".skill-mention-menu")?.textContent.includes("技能读取失败")', 'load failure');
      await js('document.querySelector(".skill-mention-menu [role=alert] button").click()'); await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===2', 'retry');
      await text('#不存在'); await wait('document.querySelector(".skill-mention-menu")?.textContent.includes("没有匹配")', 'empty search');
      await text('#'); await js('document.querySelector(".intake-composer-editor").dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}))');
      await text('#文旅'); await key('Enter', { isComposing: true });
      assert.equal(await js('!!document.querySelector(".intake-inline-skill")'), false, 'IME enter does not select');
      await js('document.querySelector(".intake-composer-editor").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true,data:"文旅"}))');
      await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===1', 'IME query finished');
      await key('Tab'); await wait('!!document.querySelector(".intake-inline-skill")', 'tab selection');
      await append('设计一个原创 IP。 #Logo'); await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===1', 'second skill');
      await js('document.querySelector(".skill-mention-menu [role=option]").click()'); await wait('document.querySelectorAll(".intake-inline-skill").length===2', 'mouse selection');
      await pause(300); await new Promise(resolve => { win.webContents.once('did-finish-load', resolve); win.reload(); }); await wait('document.querySelectorAll(".intake-inline-skill").length===2', 'draft recovery');
      // Delete a whole chip, leaving the other selection in the submitted scope.
      await js('(()=>{const el=document.querySelector(".intake-composer-editor");el.focus();const r=document.createRange();r.selectNodeContents(el);r.collapse(false);const s=getSelection();s.removeAllRanges();s.addRange(r);})()');
      for (let index=0;index<2;index++) { win.webContents.sendInputEvent({type:'keyDown',keyCode:'Backspace'});win.webContents.sendInputEvent({type:'keyUp',keyCode:'Backspace'});await pause(100); }
      await wait('document.querySelectorAll(".intake-inline-skill").length===1', 'native backspace removes chip');
      await shot('selected');
      await fixture('/fixture/reject?value=true');
      await js('document.querySelector(".composer-send").click()'); await wait('document.body.textContent.includes("技能已停用")', 'submission failure');
      assert.equal(await js('document.querySelector(".intake-inline-skill")?.textContent.includes("文旅")'), true, 'failed send preserves draft');
      await fixture('/fixture/reject?value=false'); await js('document.querySelector(".composer-send").click()');
      await wait('!!document.querySelector(".message-skill-chip")', 'sent skill chip');
      const state = await fixture('/fixture/state');
      assert.equal(state.submissions.length, 1); assert.deepEqual(state.submissions[0].input.referencedSkills.map(s => s.id), ['skill-1']);
      assert.ok(state.submissions[0].brief.includes('#skill:skill-1')); assert.ok(!state.submissions[0].brief.includes('#skill:skill-0'));
      await text('#笔记本'); await wait('document.querySelector(".skill-mention-menu")?.textContent.includes("笔记本图像设计")', 'project composer');
      await key('Enter'); await append('做一个封面'); await js('document.querySelector(".composer-send").click()');
      await wait('document.querySelectorAll(".message-skill-chip").length===2', 'project submission');
      assert.equal((await fixture('/fixture/state')).submissions[1].input.referencedSkills[0].id, 'skill-2');
      await shot('conversation');
      await win.loadFile(path.join(root, 'dist/renderer/index.html')); await wait('!!document.querySelector(".intake-composer-editor")', 'desktop composer');
      await text('#Logo'); await wait('document.querySelectorAll(".skill-mention-menu [role=option]").length===1', 'desktop picker');
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ passed: true, checks: ['home and project composer', 'browser and desktop routes', 'Chinese search and IME', 'stale response cancellation', 'pagination', 'keyboard and mouse selection', 'dependency state', 'load failure/retry/empty', 'draft recovery', 'remove selection', 'failed send preserves draft', 'canonical task payload', 'historical display'], screenshots: ['menu', 'selected', 'conversation'].map(name => `/tmp/aics-skill-mentions-${name}.png`) }));
      win.destroy(); app.exit(0);
    } catch (error) { console.error(error); console.error(await js('document.body.innerText.slice(-2000)').catch(() => '')); await shot('error'); win.destroy(); app.exit(1); }
  });
}
