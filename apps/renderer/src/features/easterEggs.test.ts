import { describe, expect, it } from 'vitest';
import { isCosmicFutureQuestion } from './easterEggs';

describe('cosmic future easter egg', () => {
  it.each(['这个世界会被设计成什么样？', '未来会怎么样', '你觉得未来会变成什么样呢？'])('matches %s', prompt => {
    expect(isCosmicFutureQuestion(prompt)).toBe(true);
  });

  it('does not hijack an ordinary future-facing design request', () => {
    expect(isCosmicFutureQuestion('帮我设计未来感海报')).toBe(false);
  });
});
