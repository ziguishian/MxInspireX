import { describe, expect, it } from 'vitest';
import { canRecoverOriginal, receiptState, recoveryHint } from './taskRecovery';

describe('original result recovery', () => {
  const jobs = [{ id: 'accepted', saved: false }, { id: 'saved', saved: true }];
  it.each(['running', 'queued', 'cancelled', '', 'unknown'])('blocks recovery for %s', status => {
    expect(canRecoverOriginal({ task: { status }, recoverableImages: jobs }, 'accepted')).toBe(false);
  });
  it.each(['failed', 'succeeded'])('recovers only unsaved accepted jobs after %s', status => {
    const data = { task: { status }, recoverableImages: jobs };
    expect(canRecoverOriginal(data, 'accepted')).toBe(true);
    expect(canRecoverOriginal(data, 'saved')).toBe(false);
    expect(canRecoverOriginal(data, 'unknown')).toBe(false);
    expect(recoveryHint(data)).toContain('不重新生成');
  });
  it('does not equate a missing receipt or failure with no charge', () => {
    expect(canRecoverOriginal(undefined, 'accepted')).toBe(false);
    expect(recoveryHint({ task: { status: 'failed' } })).toContain('失败不代表未收费');
    expect(receiptState({ status: 'running' })).toBe('结果尚未确认');
    expect(receiptState({ status: 'rejected', submitted: false })).toBe('本工具请求未提交');
    expect(receiptState({ status: 'rejected', submitted: null })).not.toContain('未提交');
  });
});
