import { describe, expect, it } from 'vitest';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import TaskProgress from '../components/TaskProgress.vue';
import type { ConversationMemorySnapshot } from '../../../../packages/contracts/conversationMemory';

const memory: ConversationMemorySnapshot = {
  sessionId:'project:one',memoryRevision:3,analyzed:true,topic:'博览会',referenceSnapshots:[],
  selected:[{id:'logo',key:'asset:logo',version:2,content:'博览会原 Logo',category:'asset',scope:'topic',topic:'博览会',status:'confirmed',active:true,source:{taskId:'first',quote:'这是原 Logo'},assetId:'logo',role:'logo'}],
  progress:[{nodeId:'cup',title:'水杯',status:'succeeded',dimensions:{width:1536,height:1024},imageQuality:{model:'gpt-image-1',tier:'final',requestedQuality:'high',status:'applied',quality:'high',inputFidelity:'high'}}],
};
const render = (value:ConversationMemorySnapshot) => renderToString(createSSRApp(TaskProgress,{status:'succeeded',info:{memory:value,assetBaseUrl:'/api/projects/one/assets'}}));
describe('conversation information in execution records',()=>{
  it('shows actual source, role, version, quality and output dimensions',async()=>{
    const html=await render(memory);
    for(const value of ['本轮使用的对话信息','这是原 Logo','原 Logo','v2','gpt-image-1','质量 high','1536 × 1024','参考保真 high','/api/projects/one/assets/logo/content'])expect(html).toContain(value);
    expect(html).toMatch(/<details class="task-memory"[^>]*>/);
    expect(html).not.toMatch(/<details class="task-memory"[^>]* open/);
  });
  it('does not advertise high when the adapter has no quality control',async()=>{
    const unsupported=structuredClone(memory);
    unsupported.progress![0].imageQuality={model:'fixed-model',tier:'final',requestedQuality:'high',status:'unsupported'};
    const html=await render(unsupported);
    expect(html).toContain('接口未声明可调质量');
    expect(html).not.toContain('质量 high');
  });
  it('shows a message only when the image route actually fell back',async()=>{
    const fallback=structuredClone(memory);
    fallback.progress![0].imageRoute={mode:'auto',tier:'final',primaryModel:'sunburst',finalModel:'gpt-image-2',fallbackUsed:true,
      candidates:[{model:'sunburst',status:'safe_rejected'},{model:'gpt-image-2',status:'succeeded'}]};
    expect(await render(fallback)).toContain('首选不可用，已使用 gpt-image-2');
    fallback.progress![0].imageRoute!.fallbackUsed=false;
    expect(await render(fallback)).not.toContain('首选不可用');
  });
  it('shows an empty selection honestly and escapes quoted user text',async()=>{
    expect(await render({...memory,selected:[]})).toContain('本轮没有选用历史信息');
    const changed=structuredClone(memory);changed.selected[0].source.quote='<script>bad()</script>';
    expect(await render(changed)).toContain('&lt;script&gt;');
  });
});
