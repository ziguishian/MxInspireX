// Smoke-test packaged data and offline font outlining in a real frozen process.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{pathToFileURL}=require('node:url');
const root=path.join(__dirname,'..'),folder=path.join(root,'dist/sidecar/dist/aics-api');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  const {verifySidecarBuild,verifyStandaloneWorker}=await import(pathToFileURL(path.join(root,'scripts/agent-runtime-build.mjs')).href);
  const {worker}=verifySidecarBuild(root,folder);verifyStandaloneWorker(worker);
  const workspace=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'aics-frozen-skills-'));
  const listener=require('node:net').createServer();
  await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
  const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
  const base=`http://127.0.0.1:${port}`;
  let child,logs='';
  const request=async(p,method='GET',body)=>{
    const response=await fetch(base+p,{method,headers:{'content-type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    const value=await response.json();assert.ok(response.ok,JSON.stringify(value));return value;
  };
  const start=async()=>{
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('AICS_')));
    child=spawn(path.join(folder,process.platform==='win32'?'aics-api.exe':'aics-api'),[],{env:{...env,AICS_WORKSPACE_ROOT:workspace,AICS_TEST_MODE:'1',AICS_API_PORT:String(port),AICS_API_HOST:'127.0.0.1'},stdio:['ignore','pipe','pipe']});
    child.stdout.on('data',data=>logs+=data);child.stderr.on('data',data=>logs+=data);
    for(let n=0;n<400;n++){
      if(child.exitCode!==null)throw new Error('Frozen API exited: '+logs.slice(-4000));
      try{if((await fetch(base+'/health')).ok)return;}catch{}
      await pause(100);
    }
    throw new Error('Frozen API startup timeout: '+logs.slice(-4000));
  };
  const stop=async()=>{
    if(!child || child.exitCode!==null)return;
    const ended=new Promise(resolve=>child.once('exit',resolve));child.kill('SIGTERM');
    const timer=setTimeout(()=>child.kill('SIGKILL'),8000);await ended;clearTimeout(timer);
  };
  try{
    await start();
    const library=await request('/api/skills');assert.equal(library.total,5);
    assert.ok(library.skills.every(s=>s.builtin && !s.missingTools.length));
    const project=await request('/api/projects','POST',{name:'冻结版内置技能验证',brief:'本地矢量检查，无模型调用'});
    const artwork=await request(`/api/projects/${project.id}/agent-tools/canvas_create_svg`,'POST',{
      svg:'<svg xmlns="http://www.w3.org/2000/svg" width="154mm" height="216mm" viewBox="0 0 154 216"><rect width="154" height="216" fill="#F5F1E8"/><text x="25" y="40" font-family="Noto Sans SC" font-size="6">青屿手记</text></svg>',outline_text:true,
      print_spec:{trim_width_mm:148,trim_height_mm:210,bleed_mm:3,safe_margin_mm:5}});
    assert.equal(artwork.textOutlines.glyphs,4);assert.equal(artwork.printPreflight.status,'structure_checked');
    const first=library.skills[0];
    await request('/api/skills/'+first.id,'PATCH',{expected_version:1,enabled:false});
    await stop();await start();
    const after=await request('/api/skills/'+first.id);assert.equal(after.enabled,false);assert.equal(after.version,2);
    assert.equal((await request('/api/skills?include_disabled=true')).total,5);
    console.log(JSON.stringify({passed:true,checks:['isolated SDK worker','frozen bundle and font checksums','five installed skills','real offline Chinese outlines','print metadata','restart preserves user state']}));
  }finally{await stop();fs.rmSync(workspace,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
