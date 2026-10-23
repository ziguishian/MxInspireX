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
describe('精简回复中的历史信息边界',()=>{
  it('只显示完成状态，不打印来源、角色、版本、质量和尺寸',async()=>{
    const html=await render(memory);
    expect(html).toContain('本轮已完成');
    for(const value of ['本轮使用的对话信息','这是原 Logo','原 Logo','v2','gpt-image-1','质量 high','1536 × 1024','参考保真 high','/api/projects/one/assets/logo/content'])expect(html).not.toContain(value);
    expect(html).not.toContain('task-memory');
  });
  it('does not advertise high when the adapter has no quality control',async()=>{
    const unsupported=structuredClone(memory);
    unsupported.progress![0].imageQuality={model:'fixed-model',tier:'final',requestedQuality:'high',status:'unsupported'};
    const html=await render(unsupported);
    expect(html).toContain('本轮已完成');
    expect(html).not.toContain('接口未声明可调质量');
    expect(html).not.toContain('质量 high');
  });
  it('降级路由留在记录中，不在回复中打印',async()=>{
    const fallback=structuredClone(memory);
    fallback.progress![0].imageRoute={mode:'auto',tier:'final',primaryModel:'sunburst',finalModel:'gpt-image-2',fallbackUsed:true,
      candidates:[{model:'sunburst',status:'safe_rejected'},{model:'gpt-image-2',status:'succeeded'}]};
    expect(await render(fallback)).not.toContain('首选不可用');
    expect(await render(fallback)).not.toContain('gpt-image-2');
    fallback.progress![0].imageRoute!.fallbackUsed=false;
    expect(await render(fallback)).not.toContain('首选不可用');
  });
  it('不展示空记忆面板，也不渲染引用中的用户 HTML',async()=>{
    expect(await render({...memory,selected:[]})).not.toContain('本轮没有选用历史信息');
    const changed=structuredClone(memory);changed.selected[0].source.quote='<script>bad()</script>';
    const html = await render(changed);
    expect(html).toContain('本轮已完成');
    expect(html).not.toContain('bad()');
    expect(html).not.toContain('<script>');
  });
});
