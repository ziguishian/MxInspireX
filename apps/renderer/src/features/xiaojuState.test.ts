import { expect, it } from 'vitest';
import { xiaojuState } from './xiaojuState';
it('ties Xiaoju to real work rather than elapsed time', () => {
  expect(xiaojuState()).toBe('idle');
  expect(xiaojuState({ status: 'running' })).toBe('thinking');
  expect(xiaojuState({ status: 'running', execution: { trace: [{ phase: 'progress', message: '正在生成图像' }] } })).toBe('generating');
  expect(xiaojuState({ status: 'succeeded', clarification: {} })).toBe('waiting');
  expect(xiaojuState({ status: 'succeeded', execution: { findings: [{}] } })).toBe('error');
  expect(xiaojuState({ status: 'failed' })).toBe('error');
  expect(xiaojuState({ status: 'succeeded' })).toBe('completed');
});
