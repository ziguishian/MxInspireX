#!/usr/bin/env node
// Dependency-free client of the existing local task API. Never retries writes.
import {parseArgs} from 'node:util';
import {readFile, open, unlink} from 'node:fs/promises';
import {realpathSync} from 'node:fs';
import {basename, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {pipeline} from 'node:stream/promises';

export const commands = {
  'health': {method:'GET', path:'/health', options:[]},
  'projects list': {method:'GET', path:'/api/projects', options:[]},
  'projects get': {method:'GET', path:'/api/projects/{project}', options:['project']},
  'projects create': {method:'POST', path:'/api/projects', options:['name','brief']},
  'canvas get': {method:'GET', path:'/api/projects/{project}/canvas', options:['project']},
  'canvas html': {method:'GET', path:'/api/projects/{project}/canvas/html/{node}', options:['project','node']},
  'tasks list': {method:'GET', path:'/api/projects/{project}/tasks', options:['project']},
  'tasks create': {method:'POST', path:'/api/projects/{project}/tasks', options:['project','prompt','prompt-file','file','request-id']},
  'tasks get': {method:'GET', path:'/api/projects/{project}/tasks/{task}', options:['project','task']},
  'tasks wait': {method:'GET', path:'/api/projects/{project}/tasks/{task}', options:['project','task','wait-timeout','poll-interval']},
  'tasks cancel': {method:'POST', path:'/api/projects/{project}/tasks/{task}/cancel', options:['project','task']},
  'tasks inspect': {method:'GET', path:'/api/projects/{project}/tasks/{task}/inspection', options:['project','task']},
  'tasks recover': {method:'POST', path:'/api/projects/{project}/tasks/{task}/image-results/{receipt}/recover', options:['project','task','receipt']},
  'assets list': {method:'GET', path:'/api/projects/{project}/assets', options:['project']},
  'assets upload': {method:'POST', path:'/api/projects/{project}/assets/upload', options:['project','file','kind']},
  'assets download': {method:'GET', path:'/api/projects/{project}/assets/{asset}/content', options:['project','asset','output']},
};
const strings = ['url','timeout','project','name','brief','prompt','prompt-file','file','request-id','task','receipt','asset','node','output','kind','wait-timeout','poll-interval'];
const options = {...Object.fromEntries(strings.map(key=>[key,{type:'string'}])), help:{type:'boolean',short:'h'}};
class CliError extends Error {
  constructor(code,message,details={},exitCode=1){super(message);Object.assign(this,{code,details,exitCode});}
}
function required(values,key){
  if(typeof values[key]!=='string'||!values[key].trim()) throw new CliError('arguments',`Missing --${key}`);
  return values[key];
}
function number(value,fallback,label,min=1){
  const n=value===undefined?fallback:Number(value);
  if(!Number.isSafeInteger(n)||n<min||n>2147483647)throw new CliError('arguments',`Invalid --${label}`);
  return n;
}
export async function run(argv, {stdout=process.stdout,env=process.env,fetcher=fetch,stdin=process.stdin,sleep=ms=>new Promise(r=>setTimeout(r,ms))}={}) {
  const print=value=>stdout.write(JSON.stringify(value)+'\n');
  let requestId;
  try {
    const {values,positionals}=parseArgs({args:argv,options,allowPositionals:true});
    const command=positionals.join(' ');
    if(values.help || !command || command==='help' || command==='schema') {
      print({ok:true,data:{name:'mxinspirex',protocolVersion:1,usage:'mxinspirex <resource> <action> [options]',
        defaultUrl:'http://127.0.0.1:8765',globalOptions:['url','timeout','help'],commands,
        notes:['Requires a running desktop app or local API.','All output is JSON. --file - reads a UTF-8 JSON body from stdin.',
          'tasks create requires a stable request-id and never retries. async is always true.',
          'tasks recover only retrieves an accepted original operation; it does not generate again.'],
        exitCodes:{0:'success',1:'arguments/API error',2:'task needs attention',3:'wait timeout (task continues)',4:'submission outcome unknown; keep requestId'}}});
      return 0;
    }
    const spec=commands[command];
    if(!spec)throw new CliError('arguments',`Unknown command: ${command}. Use --help.`);
    for(const key of Object.keys(values)) if(!['url','timeout','help',...spec.options].includes(key))throw new CliError('arguments',`--${key} is not supported by ${command}`);
    const base=new URL(values.url || env.MXINSPIREX_API_URL || 'http://127.0.0.1:8765');
    if(!['http:','https:'].includes(base.protocol)||base.username||base.password||base.search||base.hash||base.pathname!=='/')throw new CliError('arguments','--url must be an HTTP(S) origin without credentials, query or path');
    const timeout=number(values.timeout,30000,'timeout');
    const path=spec.path.replace(/\{(\w+)\}/g,(_,key)=>encodeURIComponent(required(values,key)));
    const readText=async file=>{
      if(file!=='-') return readFile(file,'utf8');
      const chunks=[];for await(const chunk of stdin)chunks.push(Buffer.from(chunk));
      return Buffer.concat(chunks).toString('utf8');
    };
    let body;
    if(command==='projects create') body={name:required(values,'name'),brief:values.brief||''};
    if(command==='tasks create') {
      if(['prompt','prompt-file','file'].filter(key=>values[key]!==undefined).length!==1)throw new CliError('arguments','Provide exactly one of --prompt, --prompt-file or --file');
      body=values.file ? JSON.parse((await readText(values.file)).replace(/^\uFEFF/,'')) : {brief:values['prompt-file'] ? await readText(values['prompt-file']) : values.prompt};
      if(!body||typeof body!=='object'||Array.isArray(body)||typeof body.brief!=='string'||!body.brief.trim())throw new CliError('arguments','Task JSON must be an object with a non-empty brief');
      if(body.agentKey && body.agentKey!=='design')throw new CliError('arguments','Only the design Agent is supported');
      if(values['request-id'] && body.requestId && values['request-id']!==body.requestId)throw new CliError('arguments','--request-id conflicts with JSON requestId');
      requestId=required({'request-id':values['request-id']||body.requestId},'request-id');
      body={...body,agentKey:'design',async:true,requestId};
    }
    if(command==='assets upload') {
      const file=required(values,'file');if(file==='-')throw new CliError('arguments','Upload requires a file path');
      const kind=values.kind||'original';
      if(!['image','3d','cad','document','original'].includes(kind))throw new CliError('arguments','Unsupported asset kind');
      body=new FormData();body.set('kind',kind);body.set('file',new Blob([await readFile(file)]),basename(file));
    }
    let deadline=Infinity;
    const request=async()=>{
      let response;
      try {
        response=await fetcher(new URL(path,base),{method:spec.method,redirect:'error',signal:AbortSignal.timeout(Math.max(1,Math.min(timeout,deadline-Date.now()))),
          ...(body===undefined?{}:body instanceof FormData?{body}:{headers:{'content-type':'application/json'},body:JSON.stringify(body)})});
      } catch(error) {
        throw new CliError(requestId?'submission_unknown':'connection',error.message,{...(requestId?{requestId,instruction:'Do not create a new request ID. Inspect tasks; reuse this ID only with the identical payload.'}:{})},requestId?4:1);
      }
      if(!response.ok){
        const message=(await response.text()).slice(0,4000);
        const unknown=Boolean(requestId&&response.status>=500);
        throw new CliError(unknown?'submission_unknown':'http',message,{status:response.status,...(requestId?{requestId}:{})},unknown?4:1);
      }
      return response;
    };
    if(command==='assets download') {
      const output=resolve(required(values,'output'));
      // Reserve the explicit destination; never overwrite an existing file.
      const handle=await open(output,'wx');
      try { const response=await request();await pipeline(response.body,handle.createWriteStream()); }
      catch(error){await handle.close().catch(()=>{});await unlink(output).catch(()=>{});throw error;}
      print({ok:true,data:{path:output,assetId:values.asset}});return 0;
    }
    const waitMs=number(values['wait-timeout'],600000,'wait-timeout');
    const interval=number(values['poll-interval'],1000,'poll-interval',100);
    if(command==='tasks wait')deadline=Date.now()+waitMs;
    let lastTask;
    const timedOut=()=>{print({ok:false,data:lastTask||{id:values.task},error:{code:'wait_timeout',message:'Task continues on the server; poll the same task ID.'}});return 3;};
    while(true){
      let data;
      try {const response=await request();data=response.status===204?null:await response.json();}
      catch(error){if(command==='tasks wait'&&Date.now()>=deadline)return timedOut();if(requestId&&!(error instanceof CliError))throw new CliError('submission_unknown',error.message,{requestId},4);throw error;}
      if(command!=='tasks wait'){print({ok:true,data,...(requestId?{requestId}:{})});return 0;}
      if(!['queued','running'].includes(data?.status)){
        const result=data?.output?.structured_data||{};
        const ok=data?.status==='succeeded' && !result.clarification?.questions?.length
          && (!result.deliveryStatus || result.deliveryStatus==='passed');
        print({ok,data,...(!ok?{error:{code:'task_attention',message:'Inspect the task before taking further action; no retry was sent.'}}:{})});return ok?0:2;
      }
      lastTask=data;
      if(Date.now()>=deadline)return timedOut();
      await sleep(Math.min(interval,deadline-Date.now()));
    }
  }catch(error){print({ok:false,error:{code:error.code||'client',message:error.message,...error.details},...(requestId?{requestId}:{})});return error.exitCode||1;}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(realpathSync(process.argv[1])).href)process.exitCode=await run(process.argv.slice(2));
