import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { effectScope, ref } from 'vue';
import type { Project } from '../../../../../packages/contracts/project';
import type { Board } from '../../canvasEditing';
import { designDemoCases, demoNodeId, demoProjectBrief } from './designDemoCases';
import { useDesignDemoPlayback } from './designDemoPlayback';
import { designExamples, readyShowcaseSlugs } from './designExamples';

const scopes:ReturnType<typeof effectScope>[]=[];
beforeEach(()=>{
  vi.useFakeTimers();
  vi.stubGlobal('FileReader', class { result=''; onload?:()=>void; onerror?:()=>void; readAsDataURL(blob:Blob){this.result='data:image/webp;base64,aW1hZ2U=';queueMicrotask(()=>this.onload?.());} });
});
afterEach(()=>{scopes.forEach(s=>s.stop());scopes.length=0;vi.useRealTimers();vi.unstubAllGlobals();});
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
function setup(){
  const projects=ref<Project[]>([]),projectId=ref<string|null>(null),visible=ref(true),board=ref<Board>({nodes:[],edges:[]});
  const boards=new Map<string,Board>(),assetRows=new Map<string,any[]>();let failNext=false;
  const transport=vi.fn(async(url:any,init?:RequestInit)=>{
    const path=String(url).replace('http://demo','');let result:any;
    if(path.includes('/assets/design-demos/'))return {ok:true,blob:async()=>new Blob(['image'],{type:'image/webp'})} as Response;
    if(path==='/api/projects'&&init?.method==='POST'){
      const id=`project-${projects.value.length+1}`;result={id,...JSON.parse(String(init.body))};boards.set(id,{nodes:[],edges:[]});assetRows.set(id,[]);
    }else if(/^\/api\/projects\/[^/]+$/.test(path)&&init?.method==='PUT'){
      const id=path.split('/').at(-1)!;
      result={...projects.value.find(project=>project.id===id),...JSON.parse(String(init.body))};
    }else{
      const [,id,area]=path.match(/^\/api\/projects\/([^/]+)\/(canvas|assets)/)||[];if(!id)throw new Error(`Unexpected API: ${path}`);
      if(area==='canvas'){
        result=structuredClone(boards.get(id));
        if(init?.method==='PATCH'){
          if(failNext){failNext=false;return {ok:false,status:500} as Response;}
          const patch=JSON.parse(String(init.body));
          result.nodes=result.nodes.filter((n:any)=>!patch.removeNodeIds?.includes(n.id));
          result.edges=result.edges.filter((n:any)=>!patch.removeEdgeIds?.includes(n.id));
          for(const node of patch.upsertNodes||[]){result.nodes=result.nodes.filter((n:any)=>n.id!==node.id);result.nodes.push(node);}
          boards.set(id,structuredClone(result));
        }
      }else{
        result=assetRows.get(id)!;
        if(init?.method==='POST'){
          const file=(init.body as FormData).get('file') as File;
          const asset={id:`asset-${result.length}`,pathRelative:file.name,metadata:{originalName:file.name}};result.push(asset);result=asset;
        }
      }
    }
    return {ok:true,json:async()=>structuredClone(result)} as Response;
  }) as unknown as typeof fetch;
  const scope=effectScope();scopes.push(scope);
  const playback=scope.run(()=>useDesignDemoPlayback({apiBaseUrl:'http://demo',projects,projectId,visible:()=>visible.value,board,selectProject:id=>{projectId.value=id;board.value={nodes:[],edges:[]};},updateBoard:b=>{board.value=b;},saved:vi.fn(),fetch:transport}))!;
  return {playback,board,boards,assetRows,visible,projectId,projects,transport,fail:()=>{failNext=true;}};
}
describe('explicit homepage demo playback',()=>{
  it('replaces porcelain and brocade cards with supplied complete projects, requiring imported boards',()=>{
    expect(designExamples.map(example=>example.projectSlug)).toEqual(['showcase-ci','showcase-shan-ming','showcase-ce-ma','showcase-jin','showcase-ma-ti']);
    expect(designExamples.filter(example=>example.requiresImport).map(example=>example.id)).toEqual(['ci','shan-ming','ce-ma','jin','ma-ti']);
    expect(designExamples.every(example=>example.cover.match(/^\/?assets\/(?:tourism-home|showcase-products)\/[a-z-]+\.(?:png|jpg)$/)&&example.slides.length===1)).toBe(true);
    expect(readyShowcaseSlugs([
      { slug: 'showcase-de-shou-gong', brief: '已保存的演示案例：德寿宫', previewRevision: 'empty' },
      { slug: 'showcase-ma-ti', brief: '普通用户项目', previewRevision: '123-456' },
      { slug: 'showcase-song-jin', brief: '已保存的演示案例：宋锦', previewRevision: '123-456' },
    ])).toEqual(['showcase-song-jin']);
  });
  it('presents a complete project conversation while artwork arrives in stages',async()=>{
    const s=setup(),run=s.playback.open('culture-museum');await flush();
    expect(s.playback.messages.value.map(message=>message.role)).toEqual(['user','assistant']);
    expect(s.playback.messages.value.at(-1)?.content).toContain('确认三个重点');
    await vi.advanceTimersByTimeAsync(1600);await flush();
    const afterBrief=s.playback.messages.value;
    expect(afterBrief.map(message=>message.role)).toEqual(['user','assistant','user','assistant','user','assistant']);
    expect(afterBrief.some(message=>message.content.includes('完整方案已放入画布'))).toBe(true);
    expect(afterBrief.some(message=>message.steps?.some(step=>step.id==='plan'&&step.status==='completed'))).toBe(true);
    await vi.runAllTimersAsync();await run;
    const complete=s.playback.messages.value.map(message=>message.content).join('\n');
    expect(complete).toContain('展示页面与交付说明已整理完成');
    expect(complete).toContain('下一步可直接在输入框补充修改方向');
  });
  it('reveals individual deliverables only after their delay, and never submits real generation',async()=>{
    const s=setup(),run=s.playback.open('culture-museum');await flush();
    expect(s.playback.playing.value).toBe(true);expect(s.board.value.nodes).toHaveLength(0);
    expect(s.playback.canvasDocument.value.nodes).toHaveLength(1); // ephemeral loading frame
    await vi.advanceTimersByTimeAsync(1599);expect(s.board.value.nodes).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);expect(s.board.value.nodes).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(3199);expect(s.board.value.nodes).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);expect(s.board.value.nodes).toHaveLength(2);
    await vi.runAllTimersAsync();await run;
    expect(s.playback.done.value).toBe(true);expect(s.board.value.nodes).toHaveLength(10);
    expect(s.projects.value[0]!.name).toBe('茶香随行 · 日常文创套系');
    expect(s.playback.messages.value.map(message=>message.content).join('\n')).not.toMatch(/演示|预制|回放/);
    expect(s.board.value.nodes.filter(node=>node.data.kind==='text').map(node=>node.data.text).join('\n')).not.toMatch(/演示|预制|回放/);
    expect(s.board.value.nodes.find(n=>n.data.kind==='html').data.html).toContain('data:image/webp;base64,');
    const manufacturing=s.board.value.nodes.find(node=>node.data.demo?.itemId==='manufacturing');
    expect(manufacturing?.data.title).toContain('制造图');
    expect(manufacturing?.data.productionNotes).toContain('裁切');
    expect(manufacturing?.data.params).toMatchObject({aspectRatio:'1:1'});
    expect(s.playback.messages.value.every(m=>!m.taskId)).toBe(true);
    expect(vi.mocked(s.transport).mock.calls.every(([url])=>!String(url).match(/tasks|agent-tools|billing|credits|intake/))).toBe(true);
  });
  it('pauses on navigation and resumes without repeating saved assets or completed nodes',async()=>{
    const s=setup(),run=s.playback.open('culture-gift');await flush();await vi.advanceTimersByTimeAsync(1600);
    s.visible.value=false;await flush();await vi.runAllTimersAsync();await run;
    expect(s.boards.get(s.projectId.value!)!.nodes).toHaveLength(1);expect(s.playback.playing.value).toBe(false);
    s.visible.value=true;await flush();expect(s.playback.playing.value).toBe(false);
    const resume=s.playback.play();await flush();await vi.runAllTimersAsync();await resume;
    expect(s.playback.completed.value).toHaveLength(11);
    expect(s.board.value.nodes.some(n=>n.data.kind==='3d')).toBe(true);
    const count=s.assetRows.get(s.projectId.value!)!.length;
    const replay=s.playback.replay();await flush();await vi.runAllTimersAsync();await replay;
    expect(s.assetRows.get(s.projectId.value!)!).toHaveLength(count);
  });
  it('retains other canvas work on replay and exposes recoverable local save failures',async()=>{
    const s=setup(),run=s.playback.open('culture-pattern');await flush();await vi.advanceTimersByTimeAsync(1600);s.fail();
    await vi.runAllTimersAsync();await run;
    expect(s.playback.error.value).toContain('保存失败');expect(s.playback.completed.value).toHaveLength(1);
    const finish=s.playback.play(true);await flush();await finish;expect(s.playback.done.value).toBe(true);
    const id=s.projectId.value!;s.boards.get(id)!.nodes.push({id:'user-node',type:'creative',position:{x:4000,y:0},data:{kind:'text',text:'保留用户工作'}});
    const replay=s.playback.replay();await flush();await vi.runAllTimersAsync();await replay;
    expect(s.board.value.nodes.find(n=>n.id==='user-node').data.text).toBe('保留用户工作');
    expect(s.playback.completed.value).toHaveLength(10);
  });
  it('restores a saved demo as paused; each card has a complete, distinct case',async()=>{
    const s=setup();
    for(const demo of designDemoCases){
      expect(demo.items.filter(i=>i.kind==='image')).toHaveLength(7);
      const manufacturing=demo.items.find(i=>i.id==='manufacturing');
      expect(manufacturing).toMatchObject({kind:'image',isEngineering:true});
      expect(manufacturing?.title).toContain('制造图');
      expect(manufacturing?.productionNotes).toBeTruthy();
      expect(demo.items.some(i=>i.kind==='html')).toBe(true);
      expect(demo.items.filter(i=>i.kind==='text')).toHaveLength(2);
      expect(demo.items.every(i=>i.delayMs>=1600)).toBe(true);
    }
    s.projects.value=[{id:'saved',name:'保存的演示',brief:demoProjectBrief(designDemoCases[3]!)} as Project];s.projectId.value='saved';await flush();
    expect(s.playback.active.value?.id).toBe('culture-ip');expect(s.playback.playing.value).toBe(false);
    expect(vi.mocked(s.transport)).not.toHaveBeenCalled();
  });
  it('removes the former presentation-only title suffix from saved case projects',async()=>{
    const s=setup(),demo=designDemoCases[0]!;
    const plan=demo.items[0]!,showcase=demo.items.find(item=>item.kind==='html')!;
    s.boards.set('saved',{nodes:[
      {id:demoNodeId(demo,plan),type:'creative',position:{x:0,y:0},data:{kind:'text',demo:{version:1,caseId:demo.id,itemId:plan.id},text:'这是演示预制案例',productionNotes:'本地演示预制产物'}},
      {id:demoNodeId(demo,showcase),type:'creative',position:{x:0,y:0},data:{kind:'html',demo:{version:1,caseId:demo.id,itemId:showcase.id},html:'朗居 · 系列设计演示案例',productionNotes:'本地演示预制产物'}},
    ],edges:[]});
    s.projects.value=[{id:'saved',name:`${demo.name} · 演示`,brief:demoProjectBrief(demo)} as Project];
    await flush();await flush();
    expect(s.projects.value[0]!.name).toBe(demo.name);
    expect(s.projects.value[0]!.brief).not.toMatch(/演示|预制|回放/);
    const migrated=s.boards.get('saved')!;
    expect(migrated.nodes.map(node=>node.data.text || node.data.html || node.data.productionNotes).join('\n')).not.toMatch(/演示|预制|回放/);
    expect(vi.mocked(s.transport).mock.calls.some(([url,init])=>String(url).endsWith('/api/projects/saved')&&init?.method==='PUT')).toBe(true);
  });
});
