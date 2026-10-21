import { afterEach, expect, it } from 'vitest';
import { creditSummary, creditLoadError, creditUsageNote, actualBillLabel, estimatedBillLabel, tokenUsageLabel, type CreditSummary } from './credits';
const empty: CreditSummary = { requests:0, inputTokens:0, outputTokens:0, totalTokens:0, tokenUnreported:0, costCny:0, estimatedCostCny:0, pricedRequests:0, unpriced:0, reportedRequests:0, awaitingReconciliation:0, evolinkPending:0, tokenByDay:{}, tokenByTask:{}, byKind:[] };
afterEach(() => { creditSummary.value=undefined; creditLoadError.value=''; });
it('distinguishes no data, an empty workspace, unknown media tokens, and free calls', () => {
  expect(tokenUsageLabel()).toBe('—'); expect(actualBillLabel()).toBe('—');
  expect(tokenUsageLabel(empty)).toBe('0'); expect(actualBillLabel(empty)).toBe('¥0.00');
  const media={...empty,requests:1,tokenUnreported:1,unpriced:1};
  expect(tokenUsageLabel(media)).toBe('—'); expect(actualBillLabel(media)).toBe('—');
  expect(actualBillLabel({...media,reportedRequests:1,pricedRequests:1,unpriced:0})).toBe('¥0.00');
});
it('uses observed tokens independently of known or estimated billing', () => {
  const value={...empty,requests:3,totalTokens:12345,tokenUnreported:1,costCny:1.2,estimatedCostCny:.3,pricedRequests:2,unpriced:1,reportedRequests:1,awaitingReconciliation:2};
  expect(tokenUsageLabel(value)).toBe('12,345'); expect(actualBillLabel(value)).toBe('¥1.20'); expect(estimatedBillLabel(value)).toBe('¥0.30');
  creditSummary.value=value;
  expect(creditUsageNote.value).toContain('2 笔待对账');
  expect(creditUsageNote.value).toContain('参考估算 ¥0.30（非扣款）');
  expect(creditUsageNote.value).toContain('1 笔未返回完整 Token');
  creditLoadError.value='offline';
  expect(creditUsageNote.value).toContain('上次读取的数据');
});
it('never presents a reference quote as an actual debit', () => {
  const quoted = {...empty, requests:1, pricedRequests:1, estimatedCostCny:5, awaitingReconciliation:1};
  creditSummary.value = quoted;
  expect(actualBillLabel(quoted)).toBe('—');
  expect(estimatedBillLabel(quoted)).toBe('¥5.00');
  expect(creditUsageNote.value).toContain('尚未取得实际扣费');
  expect(creditUsageNote.value).toContain('1 笔待对账');
});
