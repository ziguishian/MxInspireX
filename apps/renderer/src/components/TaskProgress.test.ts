import { describe, expect, it } from 'vitest';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import TaskProgress from './TaskProgress.vue';
import { deliveryProgress, taskProgress, type ExecutionInfo } from '../features/taskProgress';

const render = (info: ExecutionInfo) => renderToString(createSSRApp(TaskProgress, { info, status: 'succeeded' }));

describe('精简后的任务回复', () => {
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
      expect(html).toContain('用时');
      expect(html).not.toContain('本轮交付完成');
      expect(html).not.toContain('作品已保存');
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
    for (const text of ['生成异常', '生成结果待确认', '文件缺失', '恢复文件', '原请求可能仍有结果或费用，请先核对记录。', '下一步：', '查看对应产物']) expect(html).toContain(text);
    for (const text of ['已发现问题','尚未核实','审查超过20秒','提供成品尺寸']) expect(html).not.toContain(text);
  });
  it('回复不再展开需求、记忆、假设和已确认条件', async () => {
    const html = await render({
      brief: { summary: '28.8米观光船，不超过4.5米', assumptions: ['暂用木色'], openQuestions: ['营运航区？'], sourceTaskId: 'task', status: 'derived' },
      memory: { analyzed: true, selected: [], memoryRevision: 1 } as unknown as ExecutionInfo['memory'],
      decisions: [{ label: '长度', value: '28.8米', status: 'confirmed' }, { label: '材质', value: '未定', status: 'skipped' }],
    });
    expect(html).toContain('本轮已完成');
    for (const text of ['本轮设计需求', '本轮使用的对话信息', '本轮沿用的需求', '暂定假设', '暂用木色', '待确认事项', '营运航区？', '已确认', '已跳过']) expect(html).not.toContain(text);
    expect(html).not.toContain('<details open');
  });
  it('不渲染旧需求说明，包括其中的 HTML', async () => {
    expect(await render({})).not.toContain('本轮设计需求');
    const html = await render({ brief: { summary: '<script>alert(1)</script>', assumptions: [], openQuestions: [], sourceTaskId: 'task', status: 'derived' } });
    expect(html).not.toContain('alert(1)');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('待确认事项');
  });
  it('保留模型轮次和恢复统计，但不打印到回复', async () => {
    const info: ExecutionInfo = { trace: [
      { phase: 'model_call', data: { stage: 'design', inputTokens: 1000, outputTokens: 80 } },
      { phase: 'model_call', data: { stage: 'compaction', inputTokens: 24000, outputTokens: 8000 } },
      { phase: 'recovery_attempt', data: { attempt: 1, limit: 2, stageTotal: 2, stageLimit: 6 } },
      { phase: 'context_compaction', data: { mode: 'local', beforeTokens: 24000, afterTokens: 8000, succeeded: true } },
    ] };
    expect(taskProgress(info, 'succeeded').modelProgress).toMatchObject({ calls: 2, agentRounds: 1, compactionCalls: 1, recoveryStageTotal: 2, recoveryStageLimit: 6, correctionAttempt: 1, correctionLimit: 2, localContext: { beforeTokens: 24000, afterTokens: 8000 } });
    const html = await render(info);
    for (const text of ['模型调用', '失败恢复', '上下文已精简', '执行详情']) expect(html).not.toContain(text);
  });
  it('保留缓存命中和写入统计，跳过原生压缩不计为调用', async () => {
    const info: ExecutionInfo = {trace:[
      {phase:'model_call',data:{inputTokens:1000,cacheReported:true,cachedTokens:400,cacheWriteReported:true,cacheWriteTokens:200}},
      {phase:'context_compaction',data:{mode:'native',status:'skipped',reason:'当前入口使用本地精简'}},
    ]};
    const stats = taskProgress(info, 'succeeded').modelProgress;
    expect(stats.cache?.label).toContain('缓存命中 40.0%');
    expect(stats.cache?.writeLabel).toBe('缓存写入 200 tokens');
    expect(stats.nativeContext?.status).toBe('skipped');
    expect(stats.compactionCalls).toBe(0);
    expect(await render(info)).not.toContain('缓存命中');
  });
  it('缺少统计不冒充未命中，原生压缩进行中不冒充失败', async () => {
    const info: ExecutionInfo = {trace:[{phase:'model_call',data:{inputTokens:100}},
      {phase:'context_compaction',data:{mode:'native',status:'started'}}]};
    const stats = taskProgress(info, 'succeeded').modelProgress;
    expect(stats.cache?.label).toContain('入口未返回');
    expect(stats.cache?.label).not.toContain('缓存未命中');
    expect(stats.nativeContext?.status).toBe('started');
    expect(await render(info)).not.toContain('原生压缩');
  });
  it('累计统计在事件滚动截断后保留，并说明部分入口没有返回缓存数据', async () => {
    const info: ExecutionInfo = {trace:[{phase:'model_call',data:{totalModelCalls:80,totalInputTokens:10000,
      cacheReportedCalls:70,cacheObservedInputTokens:8000,totalCachedTokens:4000,totalCacheWriteTokens:2000,cacheWriteReportedCalls:70}},
      {phase:'context_compaction',data:{mode:'local',beforeTokens:24000,afterTokens:8000}},
      {phase:'context_compaction',data:{mode:'native',status:'failed',succeeded:false,reason:'原始历史保留，本任务不再重试'}}]};
    const stats = taskProgress(info, 'succeeded').modelProgress;
    expect(stats.calls).toBe(81);
    expect(stats.cache?.label).toContain('缓存命中 50.0%');
    expect(stats.cache?.partial).toBe(true);
    expect(stats.localContext?.afterTokens).toBe(8000);
    expect(stats.nativeContext?.reason).toBe('原始历史保留，本任务不再重试');
    expect(await render(info)).not.toContain('模型调用');
  });
  it('已有正文时不重复显示保存提示，无正文时保留一次', async () => {
    const html = await renderToString(createSSRApp(TaskProgress, { info: {}, status: 'succeeded', hasReply: true }));
    expect(html).toContain('本轮已完成');
    expect(html).not.toContain('本轮结果已保存');
    expect((await render({})).match(/本轮结果已保存/g)).toHaveLength(1);
  });
});
