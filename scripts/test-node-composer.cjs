// Exercise the actual Vue Flow node-bottom composer; no paid provider calls.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const output = path.join(root, '.tmp/node-composer-check');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
if (!process.versions.electron) {
  (async () => {
    fs.mkdirSync(output, { recursive: true });
    const { createServer } = await import('vite');
    const server = await createServer({ appType: 'custom', configFile: path.join(root, 'apps/renderer/vite.config.ts'), server: { host: '127.0.0.1', port: 5384, strictPort: false, hmr: false }, logLevel: 'error' });
    server.middlewares.use('/node-composer-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/node-composer-check', fs.readFileSync(path.join(__dirname, 'fixtures/canvas-workspace.html'), 'utf8')));
    });
    try {
      await server.listen();
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
      process.exitCode = await new Promise((resolve, reject) => {
        const child = require('node:child_process').spawn(require('electron'), [__filename, `http://127.0.0.1:${server.httpServer.address().port}/node-composer-check`], { env, stdio: 'inherit' });
        child.on('error', reject); child.on('exit', code => resolve(code ?? 1));
      });
    } finally { await server.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, width: 1700, height: 1100, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    const js = async code => {
      try { return await win.webContents.executeJavaScript(code, true); }
      catch (error) { throw new Error(`${code}: ${error.message}`); }
    };
    const wait = async code => {
      for (let i = 0; i < 120; i++) { if (await js(code)) return; await pause(50); }
      throw new Error(`Timeout: ${code}`);
    };
    const results = [];
    try {
      await win.loadURL(process.argv[2]); await wait('!!window.ready');
      for (const kind of ['image', 'upload', 'video', 'audio', 'text', 'html', 'cad']) {
        await js(`reset(${JSON.stringify(kind)})`);
        await js('select()');
        await wait('!!document.querySelector(".canvas-prompt-panel textarea")');
        await js(`(() => {const input=document.querySelector('.canvas-prompt-panel textarea');input.value='node composer ${kind}';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
        await wait('!document.querySelector(".prompt-submit").disabled');
        assert.match(await js('document.querySelector(".prompt-delivery-summary").textContent'), /本次生成：1 项/);
        const before = await js('generated.length');
        await js(`document.querySelector('.prompt-submit').click()`);
        await wait(`generated.length === ${before + 1}`);
        const event = await js('JSON.parse(JSON.stringify(generated.at(-1)))');
        assert.equal(event[0], kind === 'upload' ? 'image' : kind);
        assert.equal(event[3].canvasNodeId, 'primary');
        assert.equal(event[3].canvasProjectId, 'workspace-interaction-fixture');
        assert.deepEqual(event[3].reference_node_ids, []);
        assert.equal(await js('document.querySelector(".prompt-submit").disabled'), true);
        await js(`document.querySelector('.prompt-submit').click()`);
        assert.equal(await js('generated.length'), before + 1, 'double click must not submit twice');
        if (kind === 'audio') { assert.equal(event[3].voice, ''); assert.equal(event[3].speed, 1); }
        if (kind === 'video') { assert.equal(event[3].duration, 5); assert.equal(event[3].resolution, '720p'); }
        if (['text','html','cad'].includes(kind)) assert.equal(event[3].background, undefined);
        if (kind === 'cad') assert.equal(await js('!!document.querySelector(".prompt-settings-toggle")'), false);
        results.push({ kind, params: event[3] });
      }
      // Exercise a real connection, keeping the selected target out of its inputs.
      await js(`reset('image')`);
      await js(`state.board={...state.board,edges:[{id:'reference',source:'neighbor',target:'primary',sourceHandle:'output',targetHandle:'input'}]}; void 0;`);
      await js('select()');
      await wait('!!document.querySelector(".canvas-prompt-panel textarea")');
      await js(`(() => {const input=document.querySelector('.canvas-prompt-panel textarea');input.value='follow connected text';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await wait('!document.querySelector(".prompt-submit").disabled');
      await js(`document.querySelector('.prompt-submit').click()`);
      await wait('generated.length === 8');
      const linked = await js('JSON.parse(JSON.stringify(generated.at(-1)))');
      assert.deepEqual(linked[3].reference_node_ids, ['neighbor']);
      assert.ok(linked[1].includes('参考内容'));
      assert.match(await js('document.querySelector(".prompt-delivery-summary").textContent'), /含上游文字/);
      results.push({kind:'text-to-image', params:linked[3], prompt:linked[1]});
      for (const kind of ['video', 'image']) {
        await js(`reset(${JSON.stringify(kind)})`);
        await js(`(() => {
          const first={id:'first',type:'creative',position:{x:600,y:0},data:{kind:'image',title:'First image',assetId:'asset-first'}};
          const second={id:'second',type:'creative',position:{x:600,y:400},data:{kind:'upload',title:'Second image',assetId:'asset-second'}};
          const sources=${JSON.stringify(kind)}==='image'?[first,second]:[first];
          state.board={...state.board,nodes:[...state.board.nodes,...sources],edges:[
            ...sources.map(n=>({id:n.id,source:n.id,target:'primary',sourceHandle:'output',targetHandle:'input'})),
            {id:'duplicate',source:'first',target:'primary',sourceHandle:'output',targetHandle:'input'}
          ]};
        })()`);
        await js('select()');
        await wait('!!document.querySelector(".canvas-prompt-panel textarea")');
        await js(`(() => {const input=document.querySelector('.canvas-prompt-panel textarea');input.value='use connected images';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
        await wait('!document.querySelector(".prompt-submit").disabled');
        const before = await js('generated.length');
        await js(`document.querySelector('.prompt-submit').click();document.querySelector('.prompt-submit').click()`);
        await wait(`generated.length === ${before+1}`);
        const event = await js('JSON.parse(JSON.stringify(generated.at(-1)))');
        const ids = kind==='image'?['asset-first','asset-second']:['asset-first'];
        assert.ok((await js('document.querySelector(".prompt-delivery-summary").textContent')).includes(`${ids.length} 张参考图`));
        assert.deepEqual(event[3].source_asset_ids, ids);
        assert.deepEqual(event[3].reference_asset_ids, ids);
        assert.deepEqual(event[3].reference_node_ids, kind==='image'?['first','second']:['first']);
        assert.equal(event[3].source_asset_id, 'asset-first');
        assert.equal(await js('generated.length'), before+1);
        results.push({kind:kind==='image'?'multiple-images-to-image':'image-to-video',params:event[3]});
      }
      // Keep the composer mounted across edits, disconnect/reconnect and a
      // failed run. It must re-resolve live inputs, not replay the last payload.
      await js(`reset('image')`);
      await js(`state.board={...state.board,edges:[{id:'live',source:'neighbor',target:'primary'}]};void 0`);
      await js('select()');
      await wait('!!document.querySelector(".canvas-prompt-panel textarea")');
      await js(`(() => {const input=document.querySelector('.canvas-prompt-panel textarea');input.value='lifecycle check';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      const lifecycleStart = await js('generated.length');
      await js(`state.board.nodes.find(n=>n.id==='neighbor').data.text='UPDATED upstream text';void 0`);
      await wait('document.querySelector(".prompt-linked-reference").textContent.includes("UPDATED upstream text")');
      await js(`document.querySelector('.prompt-submit').click()`);
      await wait(`generated.length === ${lifecycleStart+1}`);
      const updated = await js('JSON.parse(JSON.stringify(generated.at(-1)))');
      assert.ok(updated[1].includes('UPDATED upstream text'));
      assert.ok(!updated[1].includes('参考内容'));
      await js(`(() => {
        const target=state.board.nodes.find(n=>n.id==='primary');
        target.data={...target.data,generating:false,error:'fixture failure',taskId:'failed-run'};
        state.board.nodes.push({id:'replacement',type:'creative',position:{x:1000,y:0},data:{kind:'image',assetId:'new-image',title:'Replacement'}});
        state.board.edges=[];
      })()`);
      await wait('!document.querySelector(".prompt-submit").disabled && !document.querySelector(".prompt-linked-reference")');
      assert.ok(!(await js('document.querySelector(".prompt-delivery-summary").textContent')).includes('含上游文字'));
      await js(`state.board.edges=[{id:'reconnected',source:'replacement',target:'primary'}];void 0`);
      await wait('document.querySelector(".prompt-linked-reference").textContent.includes("Replacement")');
      await js(`state.board.nodes.find(n=>n.id==='replacement').data.assetId='newest-image';void 0`);
      await wait('document.querySelector(".prompt-linked-reference img").src.includes("newest-image")');
      const sourcesBefore = await js('JSON.stringify(state.board.nodes.filter(n=>n.id!=="primary"))');
      await js(`document.querySelector('.prompt-submit').click();document.querySelector('.prompt-submit').click()`);
      await wait(`generated.length === ${lifecycleStart+2}`);
      const retried = await js('JSON.parse(JSON.stringify(generated.at(-1)))');
      assert.deepEqual(retried[3].reference_node_ids, ['replacement']);
      assert.deepEqual(retried[3].source_asset_ids, ['newest-image']);
      assert.ok(!retried[1].includes('UPDATED upstream text'));
      assert.equal(await js('JSON.stringify(state.board.nodes.filter(n=>n.id!=="primary"))'), sourcesBefore);
      // A late click after output exists cannot create another generation.
      await js(`Object.assign(state.board.nodes.find(n=>n.id==='primary').data,{generating:false,assetId:'saved-output',error:''});void 0`);
      await js(`document.querySelector('.prompt-submit')?.click()`);
      assert.equal(await js('generated.length'), lifecycleStart+2);
      assert.equal(await js('state.board.nodes.find(n=>n.id==="primary").data.assetId'), 'saved-output');
      results.push({kind:'upstream-edit-reconnect-retry',params:retried[3]});
      assert.ok((await js('errors')).every(error=>error.includes('已有内容的节点不能作为输出目标')));
      fs.writeFileSync(path.join(output, 'submissions.json'), JSON.stringify(results, null, 2));
      console.log('PASS: all 7 node composers, connected inputs, live upstream edits, reconnect, failure retry and preserved outputs');
      app.exit(0);
    } catch (error) { console.error(error); app.exit(1); }
  });
}
