import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:net';

const app = path.resolve(process.argv[2]);
const windows = existsSync(path.join(app, 'MxinspireX.exe'));
const executable = path.join(app, windows ? 'MxinspireX.exe' : 'Contents/MacOS/MxinspireX');
const worker = path.join(app, windows ? 'resources/app/services/api/app/openai_agent_worker.mjs' : 'Contents/Resources/app/services/api/app/openai_agent_worker.mjs');
const temp = mkdtempSync(path.join(tmpdir(), 'langju-release-check-'));
const env = { ...process.env, AICS_TEST_MODE: '1', AICS_WORKSPACE_ROOT: path.join(temp, 'workspace') };
delete env.ELECTRON_RUN_AS_NODE;
const preload = `globalThis.fetch=async()=>{const c=(delta,finish_reason)=>'data: '+JSON.stringify({id:'fixture',object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\\n\\n';return new Response(c({role:'assistant',content:'发布包 Agent 正常'},null)+c({},'stop')+'data: [DONE]\\n\\n',{headers:{'content-type':'text/event-stream'}})};await import(${JSON.stringify(pathToFileURL(worker).href)});`;
const stdout = execFileSync(executable, ['--input-type=module', '--eval', preload], { cwd: temp, env: { ...env, ELECTRON_RUN_AS_NODE: '1' }, encoding: 'utf8', timeout: 30000,
  input: JSON.stringify({ api: 'chat_completions', apiKey: 'fixture', model: 'fixture', baseUrl: 'https://fixture.invalid/v1', context: { brief: '你好', constraints: { simpleConversation: true, agentCollaboration: false, executionFlow: 'direct' } } }) });
const result = stdout.split('\n').filter(x => x.startsWith('{')).map(x => JSON.parse(x)).find(x => x.type === 'result');
assert.equal(result?.result.structured_data.answer, '发布包 Agent 正常');

const port = await new Promise(resolve => { const server = createServer(); server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)); }); });
const child = spawn(executable, [`--user-data-dir=${path.join(temp, 'profile')}`, `--remote-debugging-port=${port}`], { env, cwd: temp, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
let logs = ''; child.stdout.on('data', data => { logs += data; }); child.stderr.on('data', data => { logs += data; });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
try {
  let page;
  for (let i = 0; i < 120; i++) {
    const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json()).catch(() => []);
    page = tabs.find(x => x.type === 'page' && x.url.includes('index.html') && !x.url.includes('deliveryWorker'));
    if (page) break;
    await sleep(250);
  }
  assert.ok(page, logs.slice(-3000));
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  const pending = new Map(); let sequence = 0;
  socket.onmessage = event => { const item = JSON.parse(event.data); if (item.id) { pending.get(item.id)?.(item); pending.delete(item.id); } };
  const call = (method, params = {}) => new Promise(resolve => { const id = ++sequence; pending.set(id, resolve); socket.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expression => { const response = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); assert.ok(!response.result?.exceptionDetails, JSON.stringify(response)); return response.result.result.value; };
  let state;
  for (let i = 0; i < 100; i++) {
    state = await evaluate('({mounted:!!document.querySelector(".home-intake"),api:window.studio?.apiBaseUrl,desktop:window.studio?.isDesktop,title:document.title})');
    if (state.mounted && state.api) break;
    await sleep(200);
  }
  assert.ok(state.mounted && state.desktop, JSON.stringify(state));
  assert.ok(state.title.endsWith(' · MxinspireX'), 'Packaged renderer must display the current product name');
  let health;
  for (let i = 0; i < 120; i++) {
    health = await fetch(state.api + '/health').then(r => r.json()).catch(() => null);
    if (health?.status === 'ok') break;
    await sleep(250);
  }
  assert.equal(health?.status, 'ok', logs.slice(-2500));
  const projects = await fetch(state.api + '/api/projects').then(r => r.json());
  assert.equal(projects.length, 0, 'must use isolated workspace');
  const response = await fetch(state.api + '/api/projects', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: '发布包本地验证', brief: '测试工作区，无模型调用' }) });
  const project = await response.json();
  assert.ok(response.ok, JSON.stringify(project));
  // The project was inserted through the API, outside renderer state. Reload
  // to hydrate it exactly as a fresh launch would.
  await evaluate('window.__smokeReloadToken = 1');
  await call('Page.reload');
  for (let i = 0; i < 80; i++) {
    if (await evaluate('!window.__smokeReloadToken && !!document.querySelector(".home-intake")')) break;
    await sleep(200);
  }
  await evaluate('document.querySelector(\'[aria-label="项目"]\').click()');
  for (let i = 0; i < 60; i++) { if (await evaluate('!!document.querySelector(".project-card")')) break; await sleep(200); }
  // Current cards reveal their title on hover or keyboard focus.
  await evaluate('document.querySelector(".project-card")?.focus()');
  const projectVisible = `document.body.innerText.includes(${JSON.stringify(project.name)})`;
  for (let i = 0; i < 60; i++) { if (await evaluate(projectVisible)) break; await sleep(200); }
  assert.ok(await evaluate(projectVisible), await evaluate('document.body.innerText'));
  if (process.argv.includes('--cad')) {
    const base = state.api + '/api/projects/' + project.id;
    const request = async (route, body) => {
      const response = await fetch(base + route,{method:body ? 'POST' : 'GET',headers:{'content-type':'application/json'},body:body ? JSON.stringify(body) : undefined});
      const data = await response.json(); assert.ok(response.ok,JSON.stringify(data)); return data;
    };
    let build = await request('/cad/builds',{
      title:'发布包 CAD 底座',source:'result = cq.Workplane("XY").box(params["length"],50,8).faces(">Z").workplane().pushPoints([[-30,-15],[30,-15],[-30,15],[30,15]]).hole(5)',
      parameter_definitions:[{name:'length',label:'长度',type:'number',default:80,minimum:70,maximum:150}],expected_dimensions:{x:80,y:50,z:8},
    });
    const deadline=Date.now()+420000;
    while (!['succeeded','failed','cancelled'].includes(build.status) && Date.now()<deadline) { await sleep(500); build=await request('/cad/builds/'+build.id); }
    assert.equal(build.status,'succeeded',JSON.stringify(build));
    await evaluate(`sessionStorage.setItem('langjuart.desktopRoute',${JSON.stringify('/projects/'+project.id)})`);
    await call('Page.reload');
    const wait=async (expression,timeout=30000) => {
      const end=Date.now()+timeout;
      while (Date.now()<end) {if(await evaluate(expression).catch(()=>false)) return; await sleep(200);}
      throw new Error('Packaged CAD UI timeout: '+expression+'\n'+await evaluate('document.body.innerText'));
    };
    await wait(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.trim()==='参数与导出')`);
    await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='参数与导出').click()`);
    await wait(`document.querySelector('.cad-parameter input')?.value==='80' && !!document.querySelector('.cad-viewer-controls')`);
    await evaluate(`const input=document.querySelector('.cad-parameter input');input.value='100';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.cad-parameters form').requestSubmit()`);
    await wait(`document.querySelector('.cad-parameters')?.textContent.includes('100.00 × 50.00 × 8.00')`,420000);
    await evaluate(`document.querySelector('.cad-history button').click()`);
    await wait(`document.querySelectorAll('.cad-history option').length>=3`);
    await evaluate(`const select=document.querySelector('.cad-history select');select.value=select.options[select.options.length-1].value;select.dispatchEvent(new Event('change',{bubbles:true}))`);
    await evaluate(`document.querySelectorAll('.cad-history button')[1].click()`);
    await wait(`document.querySelector('.cad-parameter input')?.value==='80'`);
    const exported=await fetch(base+'/cad/models/'+build.result.assetId+'/export');
    assert.equal(Buffer.from(await exported.arrayBuffer()).subarray(0,2).toString(),'PK');
    console.log('Packaged CAD passed: native build, actual canvas GLB, parameter rebuild, history restore, bundle export.');
  }
  const screenshot = await call('Page.captureScreenshot', { format: 'png' });
  const image = path.join(temp, 'packaged-app.png');
  writeFileSync(image, Buffer.from(screenshot.result.data, 'base64'));
  console.log(JSON.stringify({ passed: true, app, cad:process.argv.includes('--cad'), checks: ['bundled Electron Node + standalone SDK', 'file renderer', 'sandboxed preload', 'frozen local API', 'isolated project creation', 'project navigation'], screenshot: image, workspace: temp }));
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ id: 999999, method: 'Browser.close' }));
  await new Promise(resolve => { if (child.exitCode !== null) resolve(); else { child.once('exit', resolve); setTimeout(resolve, 5000); } });
  socket?.close();
  if (child.exitCode === null) {
    if (windows) { try { execFileSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' }); } catch { /* Exited meanwhile. */ } }
    else child.kill('SIGTERM');
  }
  writeFileSync(path.join(temp, 'startup.log'), logs);
}
