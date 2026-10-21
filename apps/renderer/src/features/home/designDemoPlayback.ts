import { computed, onScopeDispose, ref, watch, type Ref } from 'vue';
import type { Project } from '../../../../../packages/contracts/project';
import type { Board } from '../../canvasEditing';
import { boardChanges, cleanBoard } from '../../canvasEditing';
import type { ConversationMessage } from '../pageServices';
import type { DesignStep } from '../../designPresentation';
import { designDemoCases, demoCaseForBrief, demoNodeId, demoProjectBrief, demoShowcaseHtml, normalizeDemoProjectBrief, type DemoItem, type DesignDemoCase } from './designDemoCases';

type Options = {
  apiBaseUrl: string; projects: Ref<Project[]>; projectId: Ref<string | null>;
  visible: () => boolean; board: Ref<Board>; selectProject: (id:string)=>void;
  updateBoard: (board:Board)=>void; saved: (id:string)=>void;
  fetch?: typeof fetch;
};
const toDataUrl = (blob:Blob) => new Promise<string>((resolve,reject)=>{
  const reader=new FileReader(); reader.onload=()=>resolve(String(reader.result)); reader.onerror=()=>reject(new Error('项目图片读取失败')); reader.readAsDataURL(blob);
});
/** No task, tool, Provider, queue, Session or billing endpoint is used here. */
export function useDesignDemoPlayback(options: Options) {
  const transport=options.fetch || fetch;
  const active=computed(()=> options.visible() ? demoCaseForBrief(options.projects.value.find(p=>p.id===options.projectId.value)?.brief) : undefined);
  const playing=ref(false), preparing=ref(false), error=ref('');
  const pending=ref<DemoItem|null>(null);
  const assets=new Map<string,Record<string,any>>();
  const blobs=new Map<string,Promise<Blob>>();
  let epoch=0, commandEpoch=0, opening=false, operation:Promise<void>|undefined;
  let naming=false;
  let cancelDelay:(()=>void)|undefined;
  const completed=computed(()=>active.value ? active.value.items.filter(item=>options.board.value.nodes.some(node=>node.id===demoNodeId(active.value!,item) && node.data?.demo?.version===1 && !node.data?.draft)) : []);
  const total=computed(()=>active.value?.items.length || 0);
  const done=computed(()=>Boolean(total.value && completed.value.length===total.value));
  const progress=computed(()=>error.value ? '方案已暂停，请重试' : preparing.value ? '正在准备方案…' : done.value ? `整套方案已保存 · ${total.value} 项产物` : playing.value && pending.value ? `正在制作${pending.value.title.replace(/^\d+｜/,'')} · ${completed.value.length}/${total.value}` : `方案已暂停 · ${completed.value.length}/${total.value} 项`);
  const messages=computed<ConversationMessage[]>(()=>{
    const demo=active.value; if(!demo)return [];
    const completedIds=new Set(completed.value.map(item=>item.id));
    const planReady=completedIds.has('plan');
    const visuals=demo.items.filter(item=>item.kind==='image');
    const visualsReady=visuals.every(item=>completedIds.has(item.id));
    const showcaseReady=completedIds.has('showcase');
    const handoffReady=completedIds.has('handoff');
    const answer=`面向${demo.audience}。希望保留${demo.palette.slice(0,2).join('与')}的气质，先确认完整概念方案；方向确定后，再继续完成产品、包装和传播应用。`;
    const messages:ConversationMessage[]=[
      {conversationTurnId:'request',role:'user',content:demo.request},
      {conversationTurnId:'clarification',role:'assistant',status:'succeeded',content:`开始前我先确认三个重点：\n\n1. 这套作品优先服务哪些人和使用场景？\n2. 希望保留怎样的视觉气质与色彩感受？\n3. 本轮先确认完整方案，还是先制作某一件产品？\n\n确认后，我会将范围、品类和交付顺序整理到画布。`},
    ];
    if(!planReady)return messages;
    messages.push(
      {conversationTurnId:'clarification-answer',role:'user',content:answer},
      {conversationTurnId:'brief',role:'assistant',status:'succeeded',content:`已确认。我将「${demo.name}」定位为：${demo.concept}\n\n完整方案已放入画布，包含设计主张、产品组合、视觉语言与落地边界。接下来会先完成系列主视觉和重点产品，再整理展示页面与打样说明。`,steps:[{id:'plan',label:'完整设计方案',status:'completed'}]},
      {conversationTurnId:'production-request',role:'user',content:'方向没问题，请按这个方案继续完成整套产品、包装、纹样和传播视觉；完成后把展示页与打样事项一并整理。'},
    );
    const creationItems=demo.items.filter(item=>item.id!=='plan'&&item.id!=='showcase'&&item.id!=='handoff');
    const creationSteps:DesignStep[]=creationItems.filter(item=>completedIds.has(item.id)||pending.value?.id===item.id).map(item=>({id:item.id,label:item.title.replace(/^\d+｜/,''),status:completedIds.has(item.id)?'completed':'running'}));
    if(creationSteps.length)messages.push({conversationTurnId:'production',role:'assistant',status:visualsReady?'succeeded':'running',content:visualsReady?'系列产品与传播视觉已整理到画布。我会继续把这些内容组织为可查看的展示页，并补充打样与交付事项。':`正在按确认的范围制作系列产品与传播视觉。${progress.value}`,steps:creationSteps});
    if(!visualsReady)return messages;
    messages.push({conversationTurnId:'handoff-request',role:'user',content:'产品和视觉方向可以，继续补齐展示页面、文件留档和打样说明。'});
    const deliveryItems=demo.items.filter(item=>item.id==='showcase'||item.id==='handoff');
    const deliverySteps:DesignStep[]=deliveryItems.filter(item=>completedIds.has(item.id)||pending.value?.id===item.id).map(item=>({id:item.id,label:item.title.replace(/^\d+｜/,''),status:completedIds.has(item.id)?'completed':'running'}));
    if(deliverySteps.length)messages.push({conversationTurnId:'delivery',role:'assistant',status:showcaseReady&&handoffReady?'succeeded':'running',content:showcaseReady&&handoffReady?'展示页面与交付说明已整理完成。':'正在整理系列展示页面、可查看文件和打样说明。',steps:deliverySteps});
    if(done.value)messages.push({conversationTurnId:'complete',role:'assistant',status:'succeeded',content:`「${demo.name}」已完成并保存到画布。可以分别查看方案、产品图、包装、纹样和系列展示页${demo.items.some(item=>item.kind==='3d')?'，也可以旋转查看礼盒结构模型':''}。\n\n下一步可直接在输入框补充修改方向，或依据交付与打样说明推进选款、材质和工艺确认。`});
    return messages;
  });
  const canvasDocument=computed(()=>{
    const board=options.board.value, demo=active.value, item=pending.value;
    if(!demo||!item||!playing.value)return board;
    const id=demoNodeId(demo,item);
    return {...board,lockedNodeIds:[...(board as any).lockedNodeIds||[],id],nodes:[...board.nodes.filter(n=>n.id!==id),{id,type:'creative',position:item.position,data:{kind:item.kind,title:item.title,previewSizingVersion:2,previewSize:item.previewSize,generating:true,draft:true,params:{aspectRatio:'16:9'},demo:{version:1,caseId:demo.id,itemId:item.id}}}]};
  });
  async function api<T>(path:string,init?:RequestInit):Promise<T> {
    const response=await transport(`${options.apiBaseUrl}${path}`,init);
    if(!response.ok)throw new Error(`方案保存失败（${response.status}），已完成产物会保留。`);
    return response.json();
  }
  const json=(value:unknown,method='POST'):RequestInit=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  const getBoard=(id:string)=>api<Board>(`/api/projects/${encodeURIComponent(id)}/canvas`);
  function displayBoard(id:string,board:Board){ if(options.projectId.value===id)options.updateBoard(board); }
  async function normalizeProjects(){
    if(naming)return;
    naming=true;
    try {
      for(const project of options.projects.value){
        const demo=demoCaseForBrief(project.brief);
        if(!demo)continue;
        const legacyTitle=project.name === `${demo.name} · 演示`;
        const brief=normalizeDemoProjectBrief(project.brief || '',demo);
        const legacyPresentation=legacyTitle || brief !== project.brief;
        let updated=project;
        if(legacyPresentation){
          updated=await api<Project>(`/api/projects/${encodeURIComponent(project.id)}`,json({ ...(legacyTitle ? {name:demo.name} : {}), ...(brief !== project.brief ? {brief} : {}) },'PUT'));
          options.projects.value=options.projects.value.map(item=>item.id===updated.id?updated:item);
        }
        if(!legacyPresentation)continue;
        const board=await getBoard(updated.id);
        const after={...board,nodes:board.nodes.map(node=>{
          const item=demo.items.find(candidate=>candidate.id===node.data?.demo?.itemId || node.id===demoNodeId(demo,candidate));
          if(!item)return node;
          const data={...node.data}; let changed=false;
          if(item.text && /演示|预制|回放/.test(String(data.text || ''))){data.text=item.text;changed=true;}
          if(typeof data.html==='string' && /演示|预制|回放/.test(data.html)){data.html=data.html.replaceAll('系列设计演示案例','系列设计方案');changed=true;}
          if(/演示|预制|回放/.test(String(data.productionNotes || ''))){data.productionNotes='材质、尺寸及量产条件需在打样阶段确认。';changed=true;}
          return changed ? {...node,data} : node;
        })};
        const changes=boardChanges(board,after);
        if(changes.upsertNodes?.length){
          const saved=await api<Board>(`/api/projects/${encodeURIComponent(updated.id)}/canvas`,json(changes,'PATCH'));
          displayBoard(updated.id,saved);
        }
      }
    } catch { /* A title update is presentational; the project stays usable if it cannot be saved. */ }
    finally { naming=false; }
  }
  const wait=(ms:number,token:number)=>new Promise<boolean>(resolve=>{
    const finish=(value:boolean)=>{clearTimeout(timer); if(cancelDelay===cancel)cancelDelay=undefined; resolve(value);};
    const cancel=()=>finish(false); const timer=setTimeout(()=>finish(epoch===token),ms); cancelDelay=cancel;
  });
  function pause(){ commandEpoch++; epoch++; playing.value=false; pending.value=null; cancelDelay?.(); }
  const demoAssetExtension=(key:string)=>key==='giftbox'?'glb':key.startsWith('engineering-')?'png':'webp';
  function blob(key:string) {
    if(!blobs.has(key))blobs.set(key,transport(`${import.meta.env.BASE_URL}assets/design-demos/${key}.${demoAssetExtension(key)}`).then(response=>{if(!response.ok)throw new Error('项目资源缺失，请重新安装完整资源。');return response.blob();}).catch(e=>{blobs.delete(key);throw e;}));
    return blobs.get(key)!;
  }
  async function asset(projectId:string,key:string){
    const cacheKey=`${projectId}:${key}`; if(assets.has(cacheKey))return assets.get(cacheKey)!;
    const filename=`langju-demo-v1-${key}.${demoAssetExtension(key)}`;
    const existing=await api<Record<string,any>[]>(`/api/projects/${projectId}/assets`);
    let result=existing.find(item=>item.metadata?.originalName===filename || item.pathRelative?.endsWith(`-${filename}`));
    if(!result){const form=new FormData();form.append('kind',key==='giftbox'?'3d':'image');form.append('file',await blob(key),filename);result=await api<Record<string,any>>(`/api/projects/${projectId}/assets/upload`,{method:'POST',body:form});}
    assets.set(cacheKey,result);return result;
  }
  async function finalNode(projectId:string,demo:DesignDemoCase,item:DemoItem){
    const data:Record<string,any>={kind:item.kind,title:item.title,previewSizingVersion:2,previewSize:item.previewSize,draft:false,demo:{version:1,caseId:demo.id,itemId:item.id},productionNotes:item.productionNotes || '材质、尺寸及量产条件需在打样阶段确认。'};
    if(item.asset){data.asset=await asset(projectId,item.asset);data.assetId=data.asset.id;data.params={aspectRatio:item.isEngineering?'1:1':'16:9'};}
    if(item.text)data.text=item.text;
    if(item.kind==='html'){
      const images=await Promise.all(demo.items.filter(i=>i.kind==='image'&&!i.isEngineering).map(async image=>({title:image.title.replace(/^\d+｜/,''),url:await toDataUrl(await blob(image.asset!))})));
      data.html=demoShowcaseHtml(demo,images);
    }
    return {id:demoNodeId(demo,item),type:'creative',position:item.position,data};
  }
  async function run(projectId:string,demo:DesignDemoCase,token:number,instant=false){
    try {
      let board=await getBoard(projectId); if(epoch!==token)return; displayBoard(projectId,board);
      for(const item of demo.items){
        if(epoch!==token)return;
        if(board.nodes.some(n=>n.id===demoNodeId(demo,item)&&n.data?.demo?.version===1&&!n.data?.draft))continue;
        pending.value=item;
        if(!instant && !await wait(item.delayMs,token))return;
        const node=await finalNode(projectId,demo,item); if(epoch!==token)return;
        // Read just before the incremental write. Never replace the user's board snapshot.
        board=await getBoard(projectId); if(epoch!==token)return;
        if(!board.nodes.some(n=>n.id===node.id)){
          board=await api<Board>(`/api/projects/${projectId}/canvas`,json({upsertNodes:[node],expectedNodes:{[node.id]:null}},'PATCH'));
        }
        displayBoard(projectId,board);
      }
      if(epoch===token){playing.value=false;pending.value=null;options.saved(projectId);}
    }catch(e){if(epoch===token){error.value=e instanceof Error?e.message:'方案制作中断';playing.value=false;pending.value=null;}}
  }
  async function play(instant=false){
    pause(); const command=commandEpoch; await operation; if(command!==commandEpoch)return;
    const demo=active.value,id=options.projectId.value; if(!demo||!id)return;
    error.value='';playing.value=true; const token=++epoch;
    operation=run(id,demo,token,instant);await operation;
  }
  async function replay(){
    pause(); const command=commandEpoch; await operation; if(command!==commandEpoch)return;
    const demo=active.value,id=options.projectId.value; if(!demo||!id)return;
    preparing.value=true; error.value='';const token=++epoch;
    try{
      const board=cleanBoard(await getBoard(id));if(epoch!==token)return;
      const ownIds=new Set(demo.items.map(item=>demoNodeId(demo,item)));
      const after={nodes:board.nodes.filter(n=>!ownIds.has(n.id)),edges:board.edges.filter(e=>!ownIds.has(e.source)&&!ownIds.has(e.target))};
      const saved=await api<Board>(`/api/projects/${id}/canvas`,json(boardChanges(board,after),'PATCH'));displayBoard(id,saved);
      if(epoch===token){preparing.value=false;await play();}
    }catch(e){error.value=e instanceof Error?e.message:'重新播放失败';}
    finally{preparing.value=false;}
  }
  async function open(caseId:string){
    if(preparing.value)return;
    const demo=designDemoCases.find(c=>c.id===caseId);if(!demo)return;
    pause();const command=commandEpoch;await operation;if(command!==commandEpoch)return;opening=true;preparing.value=true;error.value='';
    try{
      let project=options.projects.value.find(p=>demoCaseForBrief(p.brief)?.id===caseId);
      if(!project){project=await api<Project>('/api/projects',json({name:demo.name,brief:demoProjectBrief(demo),currency:'CNY'}));options.projects.value=[project,...options.projects.value];}
      if(command!==commandEpoch)return;
      options.selectProject(project.id);
      // selectProject resets the previous canvas synchronously before this load.
      const board=await getBoard(project.id);if(command!==commandEpoch)return;displayBoard(project.id,board);
      preparing.value=false;opening=false;await replay();
    }catch(e){error.value=e instanceof Error?e.message:'无法打开项目';}
    finally{preparing.value=false;opening=false;}
  }
  watch(active,(next,previous)=>{if(next!==previous&&!opening)pause();},{flush:'sync'});
  watch(options.projects,()=>{void normalizeProjects();},{immediate:true});
  onScopeDispose(pause);
  return {active,playing,preparing,error,pending,completed,total,done,progress,messages,canvasDocument,pause,play,replay,open};
}
