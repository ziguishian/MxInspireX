import {it,expect} from 'vitest';
import {run} from './mxinspirex.mjs';
import {packageCli} from './package-cli.mjs';
import {mkdtemp,readFile,writeFile,mkdir,rm,stat} from 'node:fs/promises';
import path from 'node:path';
import {Readable} from 'node:stream';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';

async function invoke(args,fetcher,extra={}){
  let text='';const code=await run(args,{stdout:{write:s=>text+=s},env:{},fetcher,...extra});
  return {code,...JSON.parse(text)};
}
const json=data=>Response.json(data);
it('discovers commands offline and rejects unsupported flags without network',async()=>{
  const fail=()=>{throw Error('must not call')};
  expect((await invoke(['schema'],fail)).data.commands['tasks recover'].path).toContain('image-results');
  expect((await invoke(['tasks','create','--project','p','--prompt','x'],fail)).code).toBe(1);
  expect((await invoke(['health','--prompt','x'],fail)).code).toBe(1);
});
it('submits exact Unicode JSON once, preserves parameters and forces async',async()=>{
  const body={brief:' 中文，\n原样！ ',requestId:'stable-1',async:false,input:{canvasParams:{quality:'low',model:'user-model'}}};
  const calls=[];
  const result=await invoke(['tasks','create','--project','p','--file','-'],async(url,options)=>{calls.push({url:String(url),...options});return json({id:'t',status:'queued'})},{stdin:Readable.from([JSON.stringify(body)])});
  expect(result.code).toBe(0);expect(calls).toHaveLength(1);
  expect(JSON.parse(calls[0].body)).toEqual({...body,async:true,agentKey:'design'});
  expect(result.requestId).toBe('stable-1');
});
it('keeps request identity on lost or malformed responses and never retries',async()=>{
  for(const response of [()=>{throw Error('connection lost')},()=>new Response('bad',{status:502}),()=>new Response('not json')]){
    let calls=0;
    const result=await invoke(['tasks','create','--project','p','--request-id','same','--prompt','x'],()=>{calls++;return response()});
    expect(calls).toBe(1);expect(result.code).toBe(4);expect(result.requestId).toBe('same');
  }
});
it('reports conflicts without changing request identity',async()=>{
  const result=await invoke(['tasks','create','--project','p','--request-id','same','--prompt','changed'],()=>new Response('conflict',{status:409}));
  expect(result.code).toBe(1);expect(result.error.status).toBe(409);
});
it('polls only GET, returns failures/clarification honestly, and times out without cancelling',async()=>{
  const args=['tasks','wait','--project','p','--task','t'];let calls=0;
  const success=await invoke(args,(_url,options)=>{expect(options.method).toBe('GET');return json({status:++calls===1?'running':'succeeded'})},{sleep:async()=>{}});
  expect(success.code).toBe(0);expect(calls).toBe(2);
  for(const data of [{status:'failed'},{status:'cancelled'},{status:'succeeded',output:{structured_data:{clarification:{questions:['用途？']}}}}, {status:'succeeded',output:{structured_data:{deliveryStatus:'needs_review'}}}]){
    expect((await invoke(args,()=>json(data))).code).toBe(2);
  }
  const timed=await invoke([...args,'--wait-timeout','1'],async(_url,options)=>{expect(options.method).toBe('GET');await new Promise(r=>setTimeout(r,5));return json({status:'running'})});
  expect(timed.code).toBe(3);
});
it('recovers only the given original receipt',async()=>{
  await invoke(['tasks','recover','--project','p','--task','t','--receipt','r'],(url,options)=>{
    expect(String(url)).toBe('http://127.0.0.1:8765/api/projects/p/tasks/t/image-results/r/recover');expect(options.method).toBe('POST');return json({status:'succeeded'});
  });
});
it('uploads bytes and downloads without overwriting existing files',async()=>{
  const dir=await mkdtemp(path.resolve('.tmp/cli-files-'));
  try{
    const file=path.join(dir,'中文.png');await writeFile(file,Buffer.from([0,1,2,255]));
    const up=await invoke(['assets','upload','--project','p','--file',file,'--kind','image'],async(_url,options)=>{
      expect(options.body.get('kind')).toBe('image');expect(options.body.get('file').name).toBe('中文.png');
      expect(Buffer.from(await options.body.get('file').arrayBuffer())).toEqual(Buffer.from([0,1,2,255]));return json({id:'a'});
    });expect(up.code).toBe(0);
    const target=path.join(dir,'download.png');let calls=0;
    const args=['assets','download','--project','p','--asset','a','--output',target];
    const fetcher=()=>{calls++;return new Response(Buffer.from([0,1,2,255]))};
    expect((await invoke(args,fetcher)).code).toBe(0);
    expect((await invoke(args,fetcher)).code).toBe(1);expect(calls).toBe(1);
    expect(await readFile(target)).toEqual(Buffer.from([0,1,2,255]));
  }finally{await rm(dir,{recursive:true,force:true})}
});
it('ships platform CLI launchers and the same standalone client',async()=>{
  const root=process.cwd(),dir=await mkdtemp(path.resolve('.tmp/cli-package-'));
  try{
    packageCli(root,dir,'win32');expect(await readFile(path.join(dir,'mxinspirex-cli.cmd'),'utf8')).toContain('ELECTRON_RUN_AS_NODE=1');
    expect(await readFile(path.join(dir,'resources/app/cli/mxinspirex.mjs'),'utf8')).toBe(await readFile('scripts/mxinspirex.mjs','utf8'));
    await mkdir(path.join(dir,'Contents/MacOS'),{recursive:true});packageCli(root,dir,'darwin');
    const launcher=path.join(dir,'Contents/MacOS/mxinspirex-cli');expect(await readFile(launcher,'utf8')).toContain('"$@"');
    if(process.platform!=='win32')expect((await stat(launcher)).mode&0o111).not.toBe(0);
  }finally{await rm(dir,{recursive:true,force:true})}
});
it('runs as a real process against HTTP with JSON-only stdout',async()=>{
  const server=createServer((req,res)=>{expect(req.url).toBe('/health');res.setHeader('content-type','application/json');res.end(JSON.stringify({status:'ok'}))});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    const result=await new Promise((resolve,reject)=>{
      const child=spawn(process.execPath,['scripts/mxinspirex.mjs','health','--url',`http://127.0.0.1:${server.address().port}`],{windowsHide:true});
      let out='',err='';child.stdout.on('data',s=>out+=s);child.stderr.on('data',s=>err+=s);child.on('error',reject);child.on('exit',code=>resolve({code,out,err}));
    });expect(result.code).toBe(0);expect(result.err).toBe('');expect(JSON.parse(result.out)).toEqual({ok:true,data:{status:'ok'}});
  }finally{await new Promise(resolve=>server.close(resolve))}
});
