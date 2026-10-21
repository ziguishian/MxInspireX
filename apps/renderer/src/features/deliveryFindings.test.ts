import { describe, expect, it } from 'vitest';
import { deliverableLabel, findingGroups, nodeDeliveryFindings, taskDeliveryFindings } from './deliveryFindings';
describe('generation status without automated quality findings', () => {
  it('ignores historical reviewer output and node review decorations', () => {
    expect(taskDeliveryFindings({review:{checks:[{status:'error',message:'标题错字'}]},
      deliveryFindings:[{kind:'unverified',code:'review_timeout',message:'审查超时'}]})).toEqual([]);
    expect(nodeDeliveryFindings({deliveryReview:{issues:['尚未核实']},productionNotes:['尺寸待确认']})).toEqual([]);
    expect(deliverableLabel({status:'ready'})).toBe('已生成');
    expect(deliverableLabel({status:'passed'})).toBe('已生成');
  });
  it('preserves unknown billing outcomes without suggesting resubmission', () => {
    for (const error of ['等待图像响应超时', 'ECONNRESET', '未知错误']) {
      const findings = nodeDeliveryFindings({status:'生成结果待确认',error},'pending');
      expect(findings[0].kind).toBe('generation_unconfirmed');
      expect(findings[0].nextAction).toContain('核对前不要重新提交');
    }
  });
  it('keeps real file and generation failures visible', () => {
    const findings = taskDeliveryFindings({delivery:{findings:[{kind:'problem',code:'file_missing',message:'文件丢失',nextAction:'恢复文件'}]}});
    expect(findingGroups(findings)[0].label).toBe('生成异常');
    expect(findings[0].message).toBe('文件丢失');
    expect(nodeDeliveryFindings({status:'生成失败',error:'image_response_invalid 图像响应内容异常'})[0].kind).toBe('problem');
  });
});
