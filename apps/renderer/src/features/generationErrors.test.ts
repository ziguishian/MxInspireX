import { describe, it, expect } from 'vitest';
import { generationFailureText, publicAssistantMessage } from './generationErrors';
import { designSteps } from '../designPresentation';
import { taskErrorMessage } from './taskErrors';

const raw = 'OpenRouter 图像接口 HTTP 400: Gemini could not generate an image (STOP)';
describe('generation failure presentation', () => {
  it('removes provider diagnostics from nodes, steps, progress and assistant replies', () => {
    const trace = [{phase:'tool',message:'调用工具：generate_image'}, {phase:'error',message:`工具失败：generate_image · ${raw}`}];
    const text = [generationFailureText(raw), ...designSteps(trace,'running').map(step=>step.label),publicAssistantMessage(`已保存其他方案。\n\n本次生成失败：${raw}`)].join('\n');
    expect(text).toContain('已保存其他方案');
    expect(text).toContain('本轮执行未完成');
    for (const code of ['HTTP','400','OpenRouter','Gemini','STOP']) expect(text).not.toContain(code);
    expect(trace[1].message).toContain(raw); // Diagnostic source stays intact.
  });
  it('keeps actionable causes without exposing codes', () => {
    expect(generationFailureText('401 unauthorized')).toContain('检查模型设置');
    expect(generationFailureText('429 rate limit')).toContain('暂时繁忙');
    expect(generationFailureText('402 insufficient_quota')).toContain('额度不足');
    expect(generationFailureText('HTTP 504 timeout')).toContain('无法连接');
  });
  it('distinguishes unknown image results from retryable network failures', () => {
    for (const reason of [
      { errorCode: 'image_response_timeout' },
      '等待图像响应超时；生成结果待确认，可能已计费。',
      'generate_image 上次调用尚未确认结果，已阻止重复执行',
    ]) {
      const text = generationFailureText(reason);
      expect(text).toContain('可能已计费');
      expect(text).toContain('停止自动重试');
      expect(text).not.toContain('切换');
    }
    expect(taskErrorMessage({ errorCode: 'image_response_timeout' })).toContain('图像响应超时');
    expect(generationFailureText({ errorCode: 'image_response_invalid' })).toContain('无法保存为图片');
  });
  it('preserves successful generation when a later scope check fails', () => {
    const reason = '目标不在本轮引用、对话相关内容或本轮产物中。请先根据用户引用与上下文确定目标，不要读取或修改无关画布内容。';
    const steps = designSteps([
      {phase:'tool',message:'调用工具：generate_image'},
      {phase:'tool',message:'工具完成：generate_image'},
      {phase:'error',message:`工具失败：asset_inspect · ${reason}`},
      {phase:'failed',message:reason},
    ], 'failed');
    expect(steps.find(step => step.tool === 'generate_image')?.status).toBe('completed');
    const text = [steps.at(-1)?.label, taskErrorMessage({message:reason})].join('\n');
    expect(text).toContain('素材关联未通过');
    expect(text).toContain('可查看和下载');
    expect(text).not.toContain('生成未成功');
    expect(text).not.toContain('模型');
  });
  it('explains a returned SVG separately from an unknown request', () => {
    const reason = '图像服务返回了 SVG，未返回要求的 PNG/JPEG/WebP 图片。';
    const text = generationFailureText(reason);
    expect(text).toContain('已禁用的 SVG');
    expect(text).toContain('可能已计费');
    expect(text).toContain('停止自动重试');
    expect(text).not.toContain('未确认');
    const trace = [{phase:'tool',message:'调用工具：generate_image'}, {phase:'error',message:`工具失败：generate_image · ${reason}`}];
    expect(designSteps(trace,'running').map(step=>step.label).join(' ')).toContain('已禁用的 SVG');
  });
  it('removes error dumps while keeping normal prose and requested code', () => {
    expect(publicAssistantMessage('已保留成果。\n\n```json\n{"error":{"message":"raw failure"},"stack":"private/path"}\n```')).not.toContain('private/path');
    const code='布局建议：\n\n```css\n.card { color: red; }\n```';
    expect(publicAssistantMessage(code)).toBe(code);
  });
});
