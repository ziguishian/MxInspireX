// Real canvas API persistence + actual renderer reload/navigation/composer.
// Generation is captured at the component boundary; no provider is invoked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const api = process.env.AICS_TEST_API_URL || 'http://127.0.0.1:8765';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function request(url, method = 'GET', body) {
  const response = await fetch(url, { method, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  if (!response.ok) throw new Error(`${method} ${url}: ${response.status} ${await response.text()}`);
  return response.status === 204 ? null : response.json();
}
if (!process.versions.electron) {
  (async () => {
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5391, strictPort: false, hmr: false, proxy: { '/real-api': { target: api, rewrite: value => value.replace(/^\/real-api/, '') } } }, logLevel: 'error' });
    server.middlewares.use('/edge-persistence', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/edge-persistence', fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8')));
    });
    let project;
    try {
      await server.listen();
      project = await request(`${api}/api/projects`, 'POST', { name: `edge-persistence-test-${Date.now()}` });
      const nodes = [
        { id: 'source-a', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'text', title: 'Reference A', text: 'SOURCE_A_UNIQUE red teapot' } },
        { id: 'source-b', type: 'creative', position: { x: 0, y: 360 }, data: { kind: 'text', title: 'Reference B', text: 'SOURCE_B_UNIQUE yellow background' } },
        { id: 'target', type: 'creative', position: { x: 600, y: 180 }, data: { kind: 'image', title: 'Output', draft: true } },
      ];
      await request(`${api}/api/projects/${project.id}/canvas`, 'PATCH', { upsertNodes: nodes, removeNodeIds: [], upsertEdges: ['a', 'b'].map(s => ({ id: `edge-${s}`, source: `source-${s}`, target: 'target', sourceHandle: 'output', targetHandle: 'input', type: 'canvas-bezier' })), removeEdgeIds: [] });
      const url = `http://127.0.0.1:${server.httpServer.address().port}/edge-persistence?${new URLSearchParams({ project: project.id, api: '/real-api' })}`;
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, url], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally {
      if (project) await request(`${api}/api/projects/${project.id}`, 'DELETE');
      await server.close();
    }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    const win = new BrowserWindow({ show: false, width: 1700, height: 1100, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = code => win.webContents.executeJavaScript(code, true);
    const wait = async (code) => { for (let i = 0; i < 120; i++) { if (await js(code)) return; await pause(50); } throw Error(`Timeout: ${code}`); };
    const url = new URL(process.argv[2]);
    const boardUrl = `${api}/api/projects/${url.searchParams.get('project')}/canvas`;
    const key = async keyCode => { win.webContents.sendInputEvent({ type: 'keyDown', keyCode }); win.webContents.sendInputEvent({ type: 'keyUp', keyCode }); await pause(100); };
    const references = async expected => {
      await js(`select('target')`);
      await wait('!!document.querySelector(".canvas-prompt-panel textarea")');
      await wait(`document.querySelectorAll('.prompt-linked-reference').length===${expected.length}`);
      assert.deepEqual(await js(`Array.from(document.querySelectorAll('.prompt-linked-reference'),e=>e.dataset.referenceNode).sort()`), expected);
    };
    const generate = async expected => {
      await references(expected);
      const count = await js('generated.length');
      await js(`(()=>{const input=document.querySelector('.canvas-prompt-panel textarea');input.value='Create one design';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await wait('!document.querySelector(".prompt-submit").disabled');
      await js(`document.querySelector('.prompt-submit').click()`);
      await wait(`generated.length===${count + 1}`); await pause(250);
      assert.equal(await js('generated.length'), count + 1, 'exactly one generation submission');
      const output = await js('JSON.parse(JSON.stringify(generated.at(-1)))');
      assert.deepEqual(output[3].reference_node_ids.slice().sort(), expected);
      for (const s of ['a', 'b']) assert.equal(output[1].includes(`SOURCE_${s.toUpperCase()}_UNIQUE`), expected.includes(`source-${s}`), 'prompt matches live upstream references');
      // The real composer persists a loading placeholder before emitting.
      // End this captured (non-provider) submission so the next case can run.
      const target = (await request(boardUrl)).nodes.find(node => node.id === 'target');
      await request(boardUrl, 'PATCH', { upsertNodes: [{ id: target.id, data: { ...target.data, generating: false, draft: true } }], removeNodeIds: [], upsertEdges: [], removeEdgeIds: [] });
      await js('leaveProject()'); await js('enterProject()'); await wait('!!document.querySelector(".vue-flow__node[data-id=target]")');
    };
    const deleteA = async () => {
      await js(`flow.removeSelectedNodes(flow.getSelectedNodes.value);flow.addSelectedEdges([flow.findEdge('edge-a')]);document.querySelector('.design-canvas-area').focus()`);
      await key('DELETE');
      await wait('state.board.edges.length===1');
      assert.deepEqual((await request(boardUrl)).edges.map(e => e.id), ['edge-b']);
    };
    try {
      await win.loadURL(url.href); win.focus(); win.webContents.focus(); await wait('!!window.ready');
      const original = (await request(boardUrl)).nodes;
      await references(['source-a', 'source-b']); await deleteA();
      await references(['source-b']); await generate(['source-b']);
      // A true document reload must reconstruct edges from the server.
      const loaded = new Promise(resolve => win.webContents.once('did-finish-load', resolve));
      win.webContents.reload(); await loaded; await wait('!!window.ready');
      await references(['source-b']); await generate(['source-b']);
      assert.deepEqual((await request(boardUrl)).edges.map(e => e.id), ['edge-b']);
      console.log('PASS: deletion survives document reload and project re-entry; removed input absent from generation');
      // Restore the baseline on the server, then create a fresh UI undo entry.
      await request(boardUrl, 'PATCH', { upsertNodes: [], removeNodeIds: [], upsertEdges: [{ id: 'edge-a', source: 'source-a', target: 'target', sourceHandle: 'output', targetHandle: 'input', type: 'canvas-bezier' }], removeEdgeIds: [] });
      await js('leaveProject()'); await js('enterProject()'); await references(['source-a', 'source-b']);
      await deleteA(); await js('leaveProject()'); await wait('!document.querySelector(".design-canvas-area")');
      await js('enterProject()'); await references(['source-b']);
      await js(`document.querySelector('[aria-label="收起对话"]').click()`);
      await wait('!!document.querySelector("[aria-label=撤销]")');
      await js(`document.querySelector('[aria-label="撤销"]').click()`);
      await wait('state.board.edges.length===2'); await generate(['source-a', 'source-b']);
      const restored = await request(boardUrl);
      assert.deepEqual(restored.edges.map(e => e.id).sort(), ['edge-a', 'edge-b']);
      assert.deepEqual(restored.nodes.filter(node => node.id !== 'target'), original.filter(node => node.id !== 'target'), 'deletion, reload, undo and generation preserve upstream content');
      assert.equal(restored.nodes.length, original.length, 'no duplicate output nodes');
      await win.loadURL(url.href); await wait('!!window.ready'); await references(['source-a', 'source-b']);
      assert.deepEqual(await js('window.errors'), []);
      console.log('PASS: undo after re-entry restores persisted edges and all generation references exactly once; original nodes unchanged');
      win.destroy(); app.exit(0);
    } catch (error) {
      console.error(error); console.error(await js('window.errors').catch(() => []));
      console.error(JSON.stringify({ patch: await js('window.lastPatch'), saved: await request(boardUrl) }));
      const output = path.join(root, '.tmp'); fs.mkdirSync(output, { recursive: true });
      fs.writeFileSync(path.join(output, 'edge-persistence-error.png'), (await win.webContents.capturePage()).toPNG());
      win.destroy(); app.exit(1);
    }
  });
}
