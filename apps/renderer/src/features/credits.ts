import { computed, ref } from 'vue';
import { formatCny, formatTokens } from '../modelEconomy';

// Keep the endpoint compatible with existing workspaces; display only Token and RMB.
export type UsageMetrics = { requests: number; inputTokens: number; outputTokens: number; totalTokens: number; tokenUnreported: number; costCny: number; estimatedCostCny: number; pricedRequests: number; unpriced: number; reportedRequests: number; awaitingReconciliation: number; evolinkPending: number };
export type CreditCategory = UsageMetrics & { kind: string; label: string };
export type CreditSummary = UsageMetrics & { updatedAt?: string; tokenByDay: Record<string, number>; tokenByTask: Record<string, number>; byKind: CreditCategory[] };
export const creditSummary = ref<CreditSummary>();
export const creditLoadError = ref('');
export function tokenUsageLabel(value?: UsageMetrics) {
  if (!value || (value.requests > 0 && value.tokenUnreported === value.requests && value.totalTokens === 0)) return '—';
  return formatTokens(value.totalTokens);
}
export function actualBillLabel(value?: UsageMetrics) {
  if (!value || (value.requests > 0 && value.reportedRequests === 0)) return '—';
  return formatCny(value.costCny);
}
export function estimatedBillLabel(value?: UsageMetrics) {
  if (!value || value.pricedRequests <= value.reportedRequests) return '—';
  return formatCny(value.estimatedCostCny);
}
export const creditUsageNote = computed(() => {
  const value = creditSummary.value;
  if (creditLoadError.value) return value ? '更新暂不可用 · 显示上次读取的数据' : '用量暂不可用';
  if (!value) return '正在读取实际用量…';
  const notes = [value.reportedRequests ? `已确认扣费 ${formatCny(value.costCny)}` : value.requests ? '尚未取得实际扣费' : '暂无调用'];
  if (value.pricedRequests > value.reportedRequests) notes.push(`参考估算 ${formatCny(value.estimatedCostCny)}（非扣款）`);
  if (value.awaitingReconciliation) notes.push(`${value.awaitingReconciliation} 笔待对账`);
  if (value.tokenUnreported) notes.push(`${value.tokenUnreported} 笔未返回完整 Token`);
  return notes.join(' · ');
});
