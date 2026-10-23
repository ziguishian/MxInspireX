const {app,BrowserWindow}=require('electron');const assert=require('assert/strict');
app.setPath('userData',require('path').resolve('.tmp/ui-extras-profile'));
app.whenReady().then(async()=>{const w=new BrowserWindow({show:true,width:1100,height:800,webPreferences:{contextIsolation:true,sandbox:true}});try{await w.loadURL('http://127.0.0.1:5173');await new Promise(r=>setTimeout(r,1200));const result=await w.webContents.executeJavaScript(`(async()=>{
const main=await (await fetch('/src/main.ts')).text();const vueUrl=main.match(/from "([^"]+vue.js[^\"]*)"/)[1];const {createApp}=await import(vueUrl);
document.documentElement.style.setProperty('--desktop-titlebar-height','34px');
const root=document.createElement('div');document.body.append(root);
const Preview=(await import('/src/components/CanvasImagePreview.vue')).default;
let closed=false;const app=createApp(Preview,{src:'/assets/style-references/swiss.png',title:'Preview check',onClose:()=>closed=true});app.mount(root);
await new Promise(r=>setTimeout(r,600));const close=document.querySelector('.image-preview-close');const top=close.getBoundingClientRect().top;close.click();app.unmount();
return {top,closed};})()`);assert.ok(result.top>=34);assert.ok(result.closed);console.log('PASS image preview close below native titlebar',result);}catch(e){console.error(e);process.exitCode=1}finally{w.destroy();app.exit(process.exitCode||0)}});
