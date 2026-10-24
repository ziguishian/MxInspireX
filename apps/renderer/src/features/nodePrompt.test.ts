import { describe, it, expect } from 'vitest';
import { mergeVisibleInputs } from './nodePrompt';
import { designLiveText } from '../designPresentation';

describe('visible node prompt inputs', () => {
  it('shows submitted conversation prompts during generation without duplication', () => {
    const trace = [{phase:'generation_prompt',message:'图像提示词：\n最终原文'}];
    const visible = designLiveText(trace, '生成中');
    expect(visible).toBe('图像提示词：\n最终原文\n\n生成中');
    expect(designLiveText(trace, undefined, visible)).toBe(visible);
  });
  it('merges once and respects edits/deletion across remounts', () => {
    const first = mergeVisibleInputs('用户原文', {}, [['style', '视觉风格：水彩']]);
    expect(first.prompt).toBe('用户原文\n\n视觉风格：水彩');
    expect(mergeVisibleInputs(first.prompt, first.seen, [['style', '视觉风格：水彩']]).prompt).toBe(first.prompt);
    expect(mergeVisibleInputs('用户删掉了风格', JSON.parse(JSON.stringify(first.seen)), [['style', '视觉风格：水彩']]).prompt).toBe('用户删掉了风格');
  });
  it('updates and removes untouched connected text', () => {
    const first = mergeVisibleInputs('原文', {}, [['node:a', '上游文字']]);
    const updated = mergeVisibleInputs(first.prompt, first.seen, [['node:a', '新上游文字']]);
    expect(updated.prompt).toBe('原文\n\n新上游文字');
    expect(mergeVisibleInputs(updated.prompt, updated.seen, []).prompt).not.toContain('上游文字');
  });
});
