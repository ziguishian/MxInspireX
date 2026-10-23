import { describe, expect, it } from 'vitest';
import { canvasReply, completedDeliveryReply, designLiveText, designSteps } from './designPresentation';

describe('public Agent execution history', () => {
  it('does not show a rejected image preflight as completed generation', () => {
    const steps = designSteps([
      {phase:'tool',message:'调用工具：generate_image'},
      {phase:'error',message:'工具失败：generate_image · 缺少 visualDirection，预检未通过，请求尚未提交'},
    ], 'running');
    expect(steps.filter(step => step.tool === 'generate_image').map(step => step.status)).toEqual(['adjusted']);
  });
  it('shows HTML argument streaming as one active step until the tool takes over', () => {
    const trace = [{ phase: 'generation', message: '正在生成网页…' }, { phase: 'generation', message: '正在生成网页…' }];
    expect(designSteps(trace, 'running')).toHaveLength(1);
    expect(designSteps(trace, 'running')[0].status).toBe('running');
    expect(designSteps(trace, 'cancelled')[0].status).toBe('cancelled');
    expect(designSteps([...trace, { phase: 'tool', message: '调用工具：canvas_create_html' }], 'running').map(step => step.status)).toEqual(['completed', 'running']);
  });
  const start = [
    { phase: 'provider', message: 'endpoint https://private-provider.invalid' },
    { phase: 'reasoning', message: 'private reasoning must not be displayed' },
    { phase: 'tool', message: '调用工具：generate_image' },
    { phase: 'tool', message: '调用工具：knowledge_search' },
  ];
  it('keeps parallel calls separate and marks completion as events arrive', () => {
    expect(designSteps(start, 'running').map(step => step.status)).toEqual(['running', 'running']);
    const next = [...start, { phase: 'tool', message: '工具完成：knowledge_search' }];
    expect(designSteps(next, 'running').map(step => step.status)).toEqual(['running', 'completed']);
    expect(designSteps([...next, { phase: 'error', message: '工具失败：generate_image · provider error' }], 'failed')
      .map(step => step.status)).toEqual(['adjusted', 'completed', 'failed']);
    expect(JSON.stringify(designSteps(start, 'running'))).not.toContain('private');
  });
  it('replays repeated calls without losing steps and handles cancellation', () => {
    const trace = [start[2], { phase: 'tool', message: '工具完成：generate_image' }, start[2]];
    expect(designSteps(trace, 'cancelled').map(step => step.status)).toEqual(['completed', 'cancelled']);
  });
  it('shows a readable failure without printing protocol details', () => {
    const failed = { phase: 'tool', message: '工具失败：web_search · HTTP 400：搜索参数不兼容' };
    for (const trace of [[failed], [{ phase: 'tool', message: '调用工具：web_search' }, failed]]) {
      const steps = designSteps(trace, 'failed');
      expect(steps[0].status).toBe('adjusted');
      expect(steps.filter(step=>step.status==='failed')).toHaveLength(1);
      expect(steps[0].label).toContain('联网搜索：');
      expect(steps[0].label).not.toContain('HTTP');
      expect(steps[0].label).not.toContain('400');
    }
  });
  it('shows recovered attempts as neutral adjustments and keeps the actual model visible', () => {
    const steps = designSteps([
      { phase: 'route', message: '使用模型：gpt-5.6-luna · 简短问候直接答复' },
      { phase: 'agent', message: '朗居设计 Agent 开始处理' },
      { phase: 'route_failed', message: 'gpt-5.6-luna 调用失败：503 临时服务故障' },
      { phase: 'retry', message: 'gpt-5.6-luna · 临时服务故障，第 1 次重试' },
      { phase: 'route', message: '使用模型：gpt-5.6-luna' },
      { phase: 'agent', message: '朗居设计 Agent 开始处理' },
      { phase: 'agent', message: '朗居设计 Agent 已完成' },
      { phase: 'succeeded', message: '任务完成' },
    ], 'succeeded');
    expect(steps[1].status).toBe('adjusted');
    expect(steps[2].status).toBe('adjusted');
    expect(steps.some(step=>step.status==='failed')).toBe(false);
    expect(steps[3].label).toContain('第 1 次重试');
    expect(steps[5].status).toBe('completed');
    expect(steps[0].label).toContain('gpt-5.6-luna');
  });
  it('does not complete an interrupted stage when a terminal failure arrives', () => {
    expect(designSteps([
      { phase: 'agent', message: '研究 Agent 开始处理' },
      { phase: 'failed', message: '连接中断' },
    ], 'failed').map(step => step.status)).toEqual(['cancelled', 'failed']);
  });
  it('keeps public explanations without completing in-flight tools', () => {
    const steps = designSteps([...start,
      {phase:'progress',message:'正在基于引用图像调整配色。'},
      {phase:'narration',message:'我会保留主体的构图。'},
      {phase:'thinking',message:'private reasoning must not be displayed'},
    ], 'running');
    expect(steps.slice(0,2).map(step=>step.status)).toEqual(['running','running']);
    expect(steps.filter(step=>step.kind==='summary').map(step=>step.label)).toEqual(['正在基于引用图像调整配色。','我会保留主体的构图。']);
    expect(JSON.stringify(steps)).not.toContain('private');
  });
  it('keeps rejected attempts neutral through correction, with one final error only if unresolved', () => {
    const trace=[{phase:'tool',message:'调用工具：generate_image'},
      {phase:'error',message:'工具失败：generate_image · HTTP 400 invalid size'},
      {phase:'progress',message:'已按海报用途调整尺寸。'},
      {phase:'tool',message:'调用工具：generate_image'}];
    const running=designSteps(trace,'running');
    expect(running.filter(step=>step.status==='failed')).toHaveLength(0);
    expect(running.at(-1)?.status).toBe('running');
    const success=designSteps([...trace,{phase:'tool',message:'工具完成：generate_image'},{phase:'succeeded',message:'完成'}],'succeeded');
    expect(success.filter(step=>step.status==='failed')).toHaveLength(0);
    const failed=designSteps([...trace,{phase:'error',message:'工具失败：generate_image · HTTP 504 timeout'},{phase:'failed',message:'未完成'}],'failed');
    expect(failed.filter(step=>step.status==='failed')).toHaveLength(1);
    expect(failed.at(-1)?.label).toContain('无法连接');
    expect(trace[1].message).toContain('HTTP 400');
  });
  it('preserves interrupted drafts in execution history with a failed task state', () => {
    const steps = designSteps([{phase:'text',message:'我会根据引用的'}, {phase:'failed',message:'连接中断'}], 'failed');
    expect(steps.some(step=>step.status==='failed')).toBe(true);
    expect(steps.find(step=>step.kind==='summary')?.label).toContain('我会根据引用的');
  });
  it('uses complete response snapshots and tolerates a polling gap', () => {
    const previous = designLiveText([{phase:'text',message:'我会根据引用的'}]);
    expect(designLiveText([],undefined,previous)).toBe(previous);
    expect(designLiveText([], '已完成配色修改。',previous)).toBe('已完成配色修改。');
    expect(designLiveText([{phase:'text',message:previous},{phase:'text',message:'我会根据引用的图像调整配色。'}])).toBe('我会根据引用的图像调整配色。');
  });
});

describe('media answers', () => {
  it('uses verified completion instead of an earlier video submission draft', () => {
    const output = { provenance: { executionFlow: 'delivery_review' }, structured_data: {
      answer: '视频已生成并保存到右侧画布。', delivery: { passed: true }, review: { passed: true, summary: '5 秒视频可播放，已通过验收。' },
    } };
    expect(completedDeliveryReply('succeeded', output)).toContain('视频已生成并保存');
    expect(completedDeliveryReply('succeeded', output)).not.toContain('仍在生成');
    expect(completedDeliveryReply('running', output)).toBeUndefined();
    output.structured_data.review.passed = false;
    expect(completedDeliveryReply('succeeded', output)).not.toContain('审查');
  });
  it('routes generated media to the canvas while preserving research citations and prose', () => {
    const answer = '可以在下面查看。\n![小狗](https://proxy.invalid/v1/assets/generated/dog.png)\n[视频](https://proxy.invalid/demo.mp4)\n参考 [博物馆](https://museum.example/history)';
    const result = canvasReply(answer, true);
    expect(result).toContain('在右侧画布查看');
    expect(result).toContain('[博物馆](https://museum.example/history)');
    expect(result).not.toContain('proxy.invalid');
    expect(canvasReply(answer, false)).toBe(answer);
  });
});
