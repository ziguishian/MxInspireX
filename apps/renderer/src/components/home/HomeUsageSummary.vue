<script setup lang="ts">
import { computed } from 'vue';
import CountUp from '../motion/CountUp.vue';
import { creditSummary, creditLoadError, creditUsageNote, tokenUsageLabel, actualBillLabel } from '../../features/credits';
import { formatTokens, formatCny } from '../../modelEconomy';

const metrics = computed(() => {
  const summary = creditSummary.value;
  return [
    { id: 'tokens', label: '累计 Token', text: tokenUsageLabel(summary), value: summary?.totalTokens, format: formatTokens },
    { id: 'cost', label: '已确认扣费', text: actualBillLabel(summary), value: summary?.costCny, format: formatCny },
  ];
});
</script>

<template>
  <section class="home-usage" aria-label="工作区累计用量" :title="creditUsageNote">
    <dl>
      <div v-for="metric in metrics" :key="metric.id">
        <dt>{{ metric.label }}</dt>
        <dd><CountUp v-if="metric.text !== '—' && metric.value !== undefined" :to="metric.value" :format="metric.format" :duration="800" /><span v-else>—</span></dd>
      </div>
    </dl>
    <p v-if="creditLoadError">用量暂不可用</p>
  </section>
</template>

<style scoped>
.home-usage { color:var(--theme-text-muted); text-align:center; font-size:var(--ui-font-micro); line-height:1.6; pointer-events:auto; }
.home-usage dl { display:flex; justify-content:center; flex-wrap:wrap; gap:4px 20px; margin:0; }
.home-usage dl > div { display:flex; align-items:baseline; gap:6px; white-space:nowrap; }
.home-usage dt { font-weight:400; }
.home-usage dd { margin:0; color:var(--theme-text); font-weight:500; font-variant-numeric:tabular-nums; }
.home-usage p { margin:3px 0 0; color:var(--theme-text-subtle); font-size:inherit; }
@media (max-width:600px) {
  .home-usage dl { gap:3px 12px; }
}
</style>
