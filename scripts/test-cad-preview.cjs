const fs = require('node:fs');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');
if (!process.versions.electron) {
  const root = path.join(__dirname, '..');
  const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'cad-preview-'));
  try {
    require('esbuild').buildSync({ stdin: { contents: "export * from './apps/renderer/src/features/cadViewer'; export { Box3, Vector3 } from 'three';", resolveDir: root, loader: 'ts' }, outfile: path.join(dir, 'probe.js'), bundle: true, format: 'iife', globalName: 'CadProbe', platform: 'browser' });
    const python = process.env.AICS_PYTHON || path.join(root, 'services/api/.venv/bin/python');
    execFileSync(python, ['-m', 'app.cad_worker'], { cwd: dir, timeout: 180000, env: { ...process.env, PYTHONPATH: path.join(root, 'services/api') }, input: JSON.stringify({ source: 'result = cq.Workplane("XY").box(80,50,8).faces(">Z").workplane().pushPoints([[-30,-15],[30,-15],[-30,15],[30,15]]).hole(5)' }) });
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    const result = spawnSync(require('electron'), [__filename, dir, path.join(root, '.tmp/cad-preview.jpg')], { env, encoding: 'utf8', timeout: 60000 });
    process.stdout.write(result.stdout || '');
    if (result.status !== 0) process.stderr.write(result.stderr || String(result.error || 'CAD Chromium check failed'));
    process.exitCode = result.status === 0 ? 0 : 1;
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
} else {
  const { app, BrowserWindow } = require('electron');
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    try {
      await win.loadURL('data:text/html,<body>CAD preview check</body>');
      await win.webContents.executeJavaScript(fs.readFileSync(path.join(process.argv[2], 'probe.js'), 'utf8') + ';void 0');
      const glb = fs.readFileSync(path.join(process.argv[2], 'model.glb')).toString('base64');
      const result = await win.webContents.executeJavaScript(`(async()=>{
        const url='data:model/gltf-binary;base64,${glb}';
        const model = await CadProbe.loadGlb(url);
        const size = new CadProbe.Box3().setFromObject(model).getSize(new CadProbe.Vector3()).toArray();
        CadProbe.disposeModel(model);
        const preview = await CadProbe.probeCad(url);
        const corrupt = await CadProbe.probeCad('data:model/gltf-binary;base64,bm90LWEtbW9kZWw=');
        return {size, preview, corrupt};
      })()`);
      const assert = require('node:assert/strict');
      assert.equal(result.preview.passed, true, JSON.stringify(result.preview));
      assert.equal(result.preview.frames.length, 3);
      assert.equal(result.corrupt.passed, false);
      [.08, .008, .05].forEach((expected, i) => assert.ok(Math.abs(result.size[i] - expected) < 1e-5, JSON.stringify(result.size)));
      fs.mkdirSync(path.dirname(process.argv[3]), { recursive: true });
      fs.writeFileSync(process.argv[3], Buffer.from(result.preview.frames[0].split(',')[1], 'base64'));
      console.log(JSON.stringify({ passed: true, sizeMeters: result.size, actualViews: result.preview.frames.length, corruptRejected: true, screenshot: process.argv[3] }));
      app.exit(0);
    } catch (error) { console.error(error); app.exit(1); }
  });
}
