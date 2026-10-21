import { describe, expect, it } from 'vitest';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import TaskProgress from './TaskProgress.vue';
import { deliveryProgress, taskProgress, type ExecutionInfo } from '../features/taskProgress';

const render = (info: ExecutionInfo) => renderToString(createSSRApp(TaskProgress, { info, status: 'succeeded' }));

describe('整理后的设计需求', () => {
  it('重新提交沿用消息顺序但从本次执行开始计时', () => {
    const info = {createdAt:'2026-10-21T12:00:00Z', trace:[{phase:'queued',at:'2026-10-21T12:10:00Z'}]};
    expect(taskProgress(info, 'running', Date.parse('2026-10-21T12:10:12Z')).totalMs).toBe(12000);
  });
  it('最终审查结果覆盖批次生成时的旧状态', () => {
    const item = { id: 'poster', title: '海报', kind: 'image', status: 'passed' as const };
    const info: ExecutionInfo = { deliveryStatus: 'passed', reviewStatus: 'passed', deliverables: [item],
      batch: { version: 1, intent: 'initial', status: 'ready', number: 1, itemIds: ['poster'], previousItemIds: [], currentProgress: [{ ...item, status: 'ready' }] } };
    expect(deliveryProgress(info).rows[0].status).toBe('passed');
    expect(taskProgress(info, 'succeeded').label).toBe('本轮完成');
    expect(deliveryProgress({ ...info, deliveryStatus: 'pending' }).rows[0].status).toBe('ready');
    expect(deliveryProgress({ ...info, deliveryStatus: 'needs_review', deliverables: [{ ...item, status: 'needs_review' }] }).rows[0].status).toBe('needs_review');
  });
  it('等待参考或澄清时不把旧任务的通过标记展示为已交付', async () => {
    for (const waiting of [{ referenceSelection: true }, { clarification: true }]) {
      const html = await renderToString(createSSRApp(TaskProgress, { info: { deliveryStatus: 'passed', reviewStatus: 'passed' }, status: 'succeeded', ...waiting }));
      expect(html).toContain('等待你的确认');
      expect(html).not.toContain('交付通过');
      expect(html).not.toContain('审查通过');
      if ('referenceSelection' in waiting) expect(html).toContain('等待选择参考');
    }
  });
  it('shows operational failures while omitting legacy quality-review findings', async () => {
    const html = await render({ deliveryStatus: 'needs_review', reviewStatus: 'timed_out', findings: [
      { kind: 'problem', code: 'file_missing', message: '文件缺失', nextAction: '恢复文件', nodeId: 'one' },
      { kind: 'unverified', code: 'review_timeout', message: '最终审查超过20秒', nextAction: '查看已有产物' },
      { kind: 'production_confirmation', code: 'size', message: '包装尺寸未确认', nextAction: '提供成品尺寸' },
      { kind: 'generation_unconfirmed', code: 'timeout', message: '图片响应超时，可能已计费', nextAction: '先核对原请求' },
    ] });
    for (const text of ['生成异常', '生成结果待确认', '文件缺失', '恢复文件', '先核对原请求', '下一步：', '查看对应产物']) expect(html).toContain(text);
    for (const text of ['已发现问题','尚未核实','审查超过20秒','提供成品尺寸']) expect(html).not.toContain(text);
  });
  it('与记忆、已确认条件同时展示，并区分假设和未决问题', async () => {
    const html = await render({
      brief: { summary: '28.8米观光船，不超过4.5米', assumptions: ['暂用木色'], openQuestions: ['营运航区？'], sourceTaskId: 'task', status: 'derived' },
      memory: { analyzed: true, selected: [], memoryRevision: 1 } as unknown as ExecutionInfo['memory'],
      decisions: [{ label: '长度', value: '28.8米', status: 'confirmed' }, { label: '材质', value: '未定', status: 'skipped' }],
    });
    for (const text of ['本轮设计需求', '本轮使用的对话信息', '本轮沿用的需求', '暂定假设', '暂用木色', '待确认事项', '营运航区？', '已确认', '已跳过']) expect(html).toContain(text);
    expect(html).not.toContain('<details open');
  });
  it('旧任务和简单修改不显示空的整理面板，说明按文本转义', async () => {
    expect(await render({})).not.toContain('本轮设计需求');
    const html = await render({ brief: { summary: '<script>alert(1)</script>', assumptions: [], openQuestions: [], sourceTaskId: 'task', status: 'derived' } });
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('待确认事项');
  });
  it('展示模型轮次、失败恢复与上下文压缩统计', async () => {
    const html = await render({ trace: [
      { phase: 'model_call', data: { stage: 'design', inputTokens: 1000, outputTokens: 80 } },
      { phase: 'model_call', data: { stage: 'compaction', inputTokens: 24000, outputTokens: 8000 } },
      { phase: 'recovery_attempt', data: { attempt: 1, limit: 2, stageTotal: 2, stageLimit: 6 } },
      { phase: 'context_compaction', data: { mode: 'local', beforeTokens: 24000, afterTokens: 8000, succeeded: true } },
    ] });
    const text = html.replace(/<!--[\s\S]*?-->/g, '');
    expect(text).toContain('模型调用 2 次 · Agent 轮次 1 · 压缩调用 1');
    expect(text).toContain('失败恢复 2/6 · 参数修正 1/2');
    expect(text).toContain('上下文已精简（估算） 24,000 → 8,000');
  });
  it('展示缓存命中和写入，兼容入口跳过原生压缩不计为调用', async () => {
    const html = await render({trace:[
      {phase:'model_call',data:{inputTokens:1000,cacheReported:true,cachedTokens:400,cacheWriteReported:true,cacheWriteTokens:200}},
      {phase:'context_compaction',data:{mode:'native',status:'skipped',reason:'当前入口使用本地精简'}},
    ]});
    expect(html).toContain('缓存命中 40.0%');
    expect(html).toContain('缓存写入 200 tokens');
    expect(html).toContain('原生压缩未启用');
    expect(html).toContain('当前入口使用本地精简');
    expect(html).not.toContain('压缩调用 1');
  });
  it('缺少统计不冒充未命中，原生压缩进行中不冒充失败', async () => {
    const html = await render({trace:[{phase:'model_call',data:{inputTokens:100}},
      {phase:'context_compaction',data:{mode:'native',status:'started'}}]});
    expect(html).toContain('缓存命中统计：入口未返回');
    expect(html).not.toContain('缓存未命中');
    expect(html).toContain('原生压缩进行中');
    expect(html).not.toContain('原生压缩未完成');
  });
  it('累计统计在事件滚动截断后保留，并说明部分入口没有返回缓存数据', async () => {
    const html = await render({trace:[{phase:'model_call',data:{totalModelCalls:80,totalInputTokens:10000,
      cacheReportedCalls:70,cacheObservedInputTokens:8000,totalCachedTokens:4000,totalCacheWriteTokens:2000,cacheWriteReportedCalls:70}},
      {phase:'context_compaction',data:{mode:'local',beforeTokens:24000,afterTokens:8000}},
      {phase:'context_compaction',data:{mode:'native',status:'failed',succeeded:false,reason:'原始历史保留，本任务不再重试'}}]});
    expect(html).toContain('模型调用 81 次');
    expect(html).toContain('缓存命中 50.0%');
    expect(html).toContain('部分调用未返回统计');
    expect(html).toContain('上下文已精简');
    expect(html).toContain('原始历史保留，本任务不再重试');
  });
});
