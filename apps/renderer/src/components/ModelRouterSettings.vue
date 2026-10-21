<script setup lang="ts">
import { ref } from 'vue';
import { creditSummary as summary, creditUsageNote, creditLoadError, tokenUsageLabel, actualBillLabel, estimatedBillLabel, type CreditSummary } from '../features/credits';
import { formatTokens } from '../modelEconomy';
import CreditPricing from './CreditPricing.vue';
const props = defineProps<{ apiBaseUrl: string }>();
const syncing = ref(false);
const syncNote = ref('');
async function reconcile() {
  if (syncing.value) return;
  syncing.value = true;
  syncNote.value = '';
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/billing/evolink/reconcile`, { method: 'POST' });
    if (!response.ok) throw new Error('查询暂不可用，请稍后重试。未确认的费用仍保留待对账。');
    const result = await response.json();
    const refreshed = await fetch(`${props.apiBaseUrl}/api/credits`);
    if (refreshed.ok) { summary.value = await refreshed.json() as CreditSummary; creditLoadError.value = ''; }
    syncNote.value = result.pending == null ? `查询间隔未到，请在 ${result.retryAfter} 秒后重试。`
      : !result.checked && !result.pending ? '暂无待对账的 EvoLink 请求。'
      : `查询 ${result.checked} 笔，确认 ${result.confirmed} 笔，仍有 ${result.pending} 笔待对账。${result.missingTaskId ? '缺少异步任务编号的请求需在服务商后台核对。' : ''}`;
  } catch (error) { syncNote.value = error instanceof Error ? error.message : '查询暂不可用，请稍后重试。'; }
  finally { syncing.value = false; }
}
</script>

<template>
  <section class="settings-pane usage-settings">
    <p>本工作区的实际 Token 与人民币费用，持续更新。</p>
    <dl class="usage-overview">
      <div><dt>Token 总消耗</dt><dd>{{ tokenUsageLabel(summary) }}</dd><small>服务商已返回的用量</small></div>
      <div><dt>已确认扣费 · RMB</dt><dd>{{ actualBillLabel(summary) }}</dd><small>仅汇总服务商返回的费用</small></div>
    </dl>
    <p class="usage-note" role="status">{{ creditUsageNote }}</p>
    <div class="billing-reconcile">
      <button type="button" class="ghost-button" :disabled="syncing" @click="reconcile">{{ syncing ? '正在查询扣费…' : '同步 EvoLink 扣费' }}</button>
      <p>仅查询原任务费用，不重新生成。未返回金额的请求保持待对账。</p>
      <p v-if="syncNote" role="status">{{ syncNote }}</p>
    </div>
    <template v-if="summary">
      <section class="usage-breakdown" aria-label="实时分类消耗">
        <h3>分类用量</h3>
        <p v-if="summary.updatedAt">更新于 {{ new Date(summary.updatedAt).toLocaleTimeString() }} · 可见页面每 3 秒刷新</p>
        <div class="usage-table-scroll"><table>
          <thead><tr><th>类别</th><th>调用数</th><th>Token</th><th>已确认扣费 · RMB</th><th>参考估算 · RMB<small>非实际扣款</small></th><th>待对账</th></tr></thead>
          <tbody><tr v-for="item in summary.byKind" :key="item.kind">
            <th>{{ item.label }}<small v-if="item.inputTokens || item.outputTokens">输入 {{ formatTokens(item.inputTokens) }} / 输出 {{ formatTokens(item.outputTokens) }}</small></th>
            <td>{{ item.requests }}</td><td>{{ tokenUsageLabel(item) }}<small v-if="item.tokenUnreported">{{ item.tokenUnreported }} 笔用量不完整</small></td>
            <td>{{ actualBillLabel(item) }}</td><td>{{ estimatedBillLabel(item) }}</td>
            <td>{{ item.awaitingReconciliation }} 笔</td>
          </tr></tbody>
        </table></div>
      </section>
    </template>
    <p class="usage-note">Token 仅统计真实返回值，包含已报告的缓存用量，不重复累加。优先读取人民币扣费；美元费用按请求时的汇率快照折算。参考估算不计入已确认扣费，EvoLink 缺失费用时不以模型单价补算。最终以服务商账单为准。</p>
    <p v-if="creditLoadError" role="alert" class="error-message">{{ creditLoadError }}</p>
    <CreditPricing :api-base-url="apiBaseUrl" />
  </section>
</template>

<style scoped>
.usage-settings { display:grid; gap:20px; padding-top:14px; line-height:1.6; }
.usage-settings h3 { margin:0 0 6px; font-size:var(--ui-font-section); }
.usage-settings p { margin:0; color:var(--theme-text-muted); font-size:var(--ui-font-caption); }
.billing-reconcile { display:grid; justify-items:start; gap:8px; }
.usage-overview { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); margin:0; border:1px solid var(--theme-border); border-radius:var(--ui-radius-card); background:var(--theme-surface); overflow:hidden; }
.usage-overview > div { min-width:0; padding:20px; }
.usage-overview > div + div { border-left:1px solid var(--theme-border); }
.usage-overview dt, .usage-overview small { color:var(--theme-text-muted); font-size:var(--ui-font-caption); }
.usage-overview dd { margin:6px 0; font-size:var(--ui-font-page); font-weight:600; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.usage-table-scroll { margin-top:12px; overflow:auto; }
.usage-breakdown table { width:100%; border-collapse:collapse; font-size:var(--ui-font-control); }
.usage-breakdown th, .usage-breakdown td { padding:12px 8px; border-bottom:1px solid var(--theme-border); text-align:left; vertical-align:top; }
.usage-breakdown th { font-weight:500; }
.usage-breakdown td { white-space:nowrap; font-variant-numeric:tabular-nums; }
.usage-breakdown small { display:block; color:var(--theme-text-muted); font-size:var(--ui-font-caption); font-weight:400; }
@media(max-width:520px) { .usage-overview { grid-template-columns:1fr; } .usage-overview > div + div { border-left:0; border-top:1px solid var(--theme-border); } }
</style>
