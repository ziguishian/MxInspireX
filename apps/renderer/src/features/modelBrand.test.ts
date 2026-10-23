import { describe, expect, it } from 'vitest';
import { modelBrand } from './modelBrand';
describe('model maker marks', () => {
  it.each([['openai/gpt-image-2', 'openai'], ['claude-sonnet-4', 'anthropic'], ['gemini-pro', 'google'], ['seedance-2', 'bytedance'], ['kling-v3', 'kuaishou'], ['qwen-plus', 'alibaba'], ['wan-2.6', 'alibaba'], ['flux-kontext', 'bfl'], ['grok-4', 'xai'], ['kimi-k2', 'moonshot'], ['glm-5', 'zhipu'], ['deepseek-chat', 'deepseek']])('identifies %s', (model, maker) => {
    expect(modelBrand(model, 'EvoLink').id).toBe(maker);
  });
  it('uses vendor metadata for custom names and a neutral fallback for unknown models', () => {
    expect(modelBrand('custom-model', 'Anthropic').id).toBe('anthropic');
    expect(modelBrand('custom-model', 'EvoLink').id).toBe('generic');
    expect(modelBrand('gpt-6', 'Google').id).toBe('openai');
  });
});
