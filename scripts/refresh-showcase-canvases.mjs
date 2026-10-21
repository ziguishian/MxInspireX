#!/usr/bin/env node
import { readFile,writeFile,mkdir,realpath } from 'node:fs/promises';
import { dirname,join,resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compactShowcaseSlugs,enrichShowcase,compactLayout,validateCompact } from './compact-showcase-layout.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');const args=process.argv.slice(2);
const option=(key,fallback='')=>{const i=args.indexOf(key);return i<0?fallback:args[i+1]};
if(!option('--workspace'))throw new Error('请指定 --workspace。');
const workspace=await realpath(resolve(option('--workspace'))),out=join(root,'.tmp/showcase-canvas-refresh');await mkdir(out,{recursive:true});
const prepare=args.includes('--prepare'),preview=args.includes('--preview');
const heights=prepare?null:JSON.parse(await readFile(join(out,'text-heights.json'),'utf8'));
const api=option('--api','http://127.0.0.1:8765').replace(/\/$/,'');
const request=async(path,init)=>{const r=await fetch(api+path,init);if(!r.ok)throw new Error(`${path}: ${r.status} ${await r.text()}`);return r.json()};
const projects=prepare||preview?null:await request('/api/projects');const plans=[];
for(const slug of compactShowcaseSlugs){
 const project=projects?projects.find(p=>p.slug===slug):JSON.parse(await readFile(join(workspace,slug,'project.json'),'utf8'));
 if(!project?.brief?.startsWith('已保存的演示案例：')||await realpath(dirname(project.rootPath))!==workspace)throw new Error('项目与工作区不一致。');
 const board=projects?await request(`/api/projects/${project.id}/canvas`):JSON.parse(await readFile(join(project.rootPath,'canvas/board.json'),'utf8'));
 const enriched=enrichShowcase(slug,board);const next=prepare?enriched:compactLayout(enriched,heights);
 const metrics=prepare?null:validateCompact(next);
 const beforeBox={width:Math.max(...board.nodes.map(n=>n.position.x+(n.data.previewSize?.width||360))),height:Math.max(...board.nodes.map(n=>n.position.y+(n.data.previewSize?.height||400)))-Math.min(...board.nodes.map(n=>n.position.y))};
 plans.push({slug,project,board,next,metrics,beforeBox});
}
const fixture=plans.map(({slug,project,next})=>({slug,name:project.name,nodes:next.nodes.map(n=>({id:n.id,title:n.data.title,kind:n.data.kind,text:n.data.text,position:n.position,size:n.data.previewSize,assetPath:n.data.asset?.pathRelative?join(project.rootPath,n.data.asset.pathRelative):undefined}))}));
await writeFile(join(out,prepare?'text-input.json':'layout-preview.json'),JSON.stringify(fixture));
if(prepare){console.log('四案文字已扩写，待真实 Vue 排版测量。');process.exit(0)}
if(!preview){
 const backup=join(out,'backups',String(Date.now()));await mkdir(backup,{recursive:true});
 for(const plan of plans)await writeFile(join(backup,plan.slug+'.json'),JSON.stringify(plan.board));
 for(const {project,board,next,slug} of plans){
  const changed=next.nodes.filter(n=>JSON.stringify(n)!==JSON.stringify(board.nodes.find(old=>old.id===n.id)));
  const patch={upsertNodes:changed,upsertEdges:[],removeNodeIds:[],removeEdgeIds:[],expectedNodes:Object.fromEntries(changed.map(n=>{const old=board.nodes.find(old=>old.id===n.id);return[n.id,{position:old.position,data:old.data}]})),expectedEdges:{}};
  await request(`/api/projects/${project.id}/canvas`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify(patch)});
  const after=await request(`/api/projects/${project.id}/canvas`);validateCompact(after);
  if(after.nodes.length!==board.nodes.length||JSON.stringify(after.edges)!==JSON.stringify(board.edges))throw new Error('节点或连线数量改变。');
  for(const old of board.nodes){const n=after.nodes.find(n=>n.id===old.id);for(const key of ['assetId','html','htmlAssets','imageAssetIds','showcaseOrder','showcaseProvenance'])if(JSON.stringify(n.data[key])!==JSON.stringify(old.data[key]))throw new Error(`原始内容改变：${slug}/${key}`)}
 }
}
const report=plans.map(p=>({slug:p.slug,before:p.beforeBox,after:p.metrics,heightReduction:Math.round((1-p.metrics.height/p.beforeBox.height)*100)}));
await writeFile(join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
