import { describe, expect, it } from 'vitest';
import { taskOutcome } from './taskOutcome';
const base = { plan: [{id:'a',title:'图片',kind:'image'},{id:'b',title:'清单',kind:'text'}], deliverables: [{id:'a',title:'图片',kind:'image',status:'pending' as const},{id:'b',title:'清单',kind:'text',status:'needs_review' as const}], deliveryStatus:'needs_review',reviewStatus:'unavailable' };
describe('task outcome', () => {
  it('does not advertise nonexistent artwork after an early failure', () => {
    expect(taskOutcome({}, 'failed').detail).not.toContain('查看作品');
    const result = taskOutcome({failureReason:'other side closed'}, 'failed');
    expect(result.detail).toContain('文本模型未返回完整结果');
    expect(result.action).toBe('inspect');
    expect(result.canCompleteMissing).toBe(false);
    expect(result.tone).toBe('red');
  });
  it('does not request delivery verification for a completed ordinary reply', () => {
    expect(taskOutcome({}, 'succeeded').title).toBe('本轮已完成');
    expect(taskOutcome({}, 'succeeded').canCompleteMissing).toBe(false);
  });
  it('summarizes partial delivery and routes balance failure to settings', () => {
    const value = taskOutcome({...base,failureReason:'HTTP 403 余额不足'},'succeeded');
    expect(value.title).toBe('已保存 1/2 项'); expect(value.action).toBe('settings'); expect(value.canCompleteMissing).toBe(true); expect(value.tone).toBe('yellow');
  });
  it('never offers generation again for an unconfirmed request', () => {
    const value = taskOutcome({...base,findings:[{kind:'generation_unconfirmed',code:'unknown',message:'待确认',nextAction:'核对'}]},'succeeded');
    expect(value.canCompleteMissing).toBe(false); expect(value.action).toBe('inspect');
  });
  it('does not claim successful delivery merely because execution ended', () => {
    expect(taskOutcome(base,'succeeded').title).not.toBe('本轮交付完成');
    expect(taskOutcome({...base,deliveryStatus:'passed'},'succeeded').tone).toBe('yellow');
  });
});
