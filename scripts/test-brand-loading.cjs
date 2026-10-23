const { app, BrowserWindow } = require('electron');
const path = require('path');
const fs = require('fs');
const assert = require('assert/strict');
const output = path.resolve('.tmp/brand-loading');
app.setPath('userData', path.join(output, 'profile'));
app.whenReady().then(async () => {
  const w = new BrowserWindow({ show: true, width: 800, height: 600 });
  try {
    await w.loadURL('http://127.0.0.1:5173/?deliveryWorker=1');
    w.show();
    w.focus();
    await w.webContents.executeJavaScript(`(async () => {
      const source = await (await fetch('/src/main.ts')).text();
      const vueUrl = source.match(/from "([^"]*vue[^\"]*)"/)[1];
      const {createApp} = await import(vueUrl);
      const {default: Loading} = await import('/src/components/BrandLoading.vue');
      const host = document.createElement('div'); host.id = 'loader-test';
      host.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#181818'; document.body.append(host);
      window.loaderTest = createApp(Loading, {fullscreen:true}); window.loaderTest.mount(host);
      document.documentElement.dataset.theme = 'dark';
      document.documentElement.dataset.reduceAnimations = 'false';
    })()`);
    await new Promise(resolve => setTimeout(resolve, 400));
    const snapshot = await w.webContents.executeJavaScript(`(() => {
      const host=document.querySelector('#loader-test');
      const animations=host.getAnimations({subtree:true});
      animations.forEach(a=>{a.pause();a.currentTime=1900;});
      return {count:animations.length,role:host.querySelector('[role=status]')?.getAttribute('aria-label'),mask:getComputedStyle(host.querySelector('.brand-loading-liquid')).maskImage};
    })()`);
    assert.equal(snapshot.count, 3);
    assert.equal(snapshot.role, '正在加载…');
    assert.ok(snapshot.mask.includes('mxinspirex-app-icon-dark.png'));
    assert.equal(await w.webContents.executeJavaScript(`getComputedStyle(document.querySelector('#loader-test .front')).fill`), 'rgb(255, 255, 255)');
    assert.equal(await w.webContents.executeJavaScript(`document.querySelector('#loader-test .brand-loading-mark').getBoundingClientRect().width`), 128);
    assert.equal(await w.webContents.executeJavaScript(`!!document.querySelector('#loader-test feMorphology')`), true);
    await new Promise(resolve => setTimeout(resolve, 150));
    fs.mkdirSync(output, {recursive:true});
    fs.writeFileSync(path.join(output,'half-filled.png'), (await w.webContents.capturePage()).toPNG());
    await w.webContents.executeJavaScript(`document.documentElement.dataset.reduceAnimations='true'`);
    await new Promise(resolve=>setTimeout(resolve,100));
    assert.equal(await w.webContents.executeJavaScript(`document.querySelector('#loader-test .brand-loading').classList.contains('is-animated')`),false);
    assert.equal(await w.webContents.executeJavaScript(`getComputedStyle(document.querySelector('#loader-test .brand-loading-rise')).animationName`),'none');
    await w.webContents.executeJavaScript('window.loaderTest.unmount()');
    assert.equal(await w.webContents.executeJavaScript(`!!document.querySelector('#loader-test [role=status]')`),false);
    console.log('PASS wave animation, alpha mask, reduced motion, cleanup');
  } catch(error) {console.error(error);process.exitCode=1;} finally {w.destroy();app.exit(process.exitCode || 0);}
});
