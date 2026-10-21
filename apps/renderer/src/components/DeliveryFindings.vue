<script setup lang="ts">
import { computed } from 'vue';
import { findingGroups, type DeliveryFinding } from '../features/deliveryFindings';
const props = defineProps<{ findings: DeliveryFinding[]; compact?: boolean; inspectable?: boolean }>();
const emit = defineEmits<{ inspect: [nodeId: string] }>();
const groups = computed(() => findingGroups(props.findings));
</script>

<template>
  <div v-if="groups.length" class="delivery-findings" :class="{ compact }" aria-label="生成状态与下一步">
    <details v-for="group in groups" :key="group.kind" :data-kind="group.kind" :open="!compact">
      <summary>{{ group.label }} · {{ group.items.length }} 项</summary>
      <ul>
        <li v-for="(item, index) in group.items" :key="`${item.code}-${item.nodeId}-${index}`">
          <p>{{ item.message }}</p>
          <p class="finding-next-action"><strong>下一步：</strong>{{ item.nextAction }}</p>
          <button v-if="inspectable && item.nodeId" type="button" @click.stop="emit('inspect', item.nodeId)">查看对应产物</button>
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.delivery-findings { display:grid; gap:8px; margin:10px 0; font-size:12px; line-height:1.6; overflow-wrap:anywhere; color:var(--theme-text-muted, #acacac); }
.delivery-findings details { border:1px solid var(--theme-border, #404040); border-radius:8px; padding:8px 10px; background:var(--theme-surface, #191919); }
.delivery-findings summary { cursor:pointer; font-weight:600; color:var(--theme-text, #e8e8e8); }
.delivery-findings [data-kind="problem"] summary { color:var(--theme-danger, #8c8c8c); }
.delivery-findings [data-kind="generation_unconfirmed"] summary { color:var(--theme-warning, #b7b7b7); }
.delivery-findings [data-kind="production_confirmation"] summary { color:var(--theme-warning, #b7b7b7); }
:global(html[data-theme="light"] .delivery-findings [data-kind="generation_unconfirmed"] summary),
:global(html[data-theme="light"] .delivery-findings [data-kind="production_confirmation"] summary) { color:#626262; }
.delivery-findings ul { list-style:none; margin:6px 0 0; padding:0; }
.delivery-findings li + li { border-top:1px solid var(--theme-border, #404040); margin-top:8px; padding-top:8px; }
.delivery-findings p { margin:4px 0; }
.finding-next-action strong { font-weight:500; }
.delivery-findings button { margin-top:4px; border:1px solid var(--theme-border, #404040); border-radius:6px; padding:4px 8px; background:var(--theme-surface-raised, #2b2b2b); color:var(--theme-text, #e8e8e8); cursor:pointer; font:inherit; }
.delivery-findings .finding-revise { margin-left:6px; border-color:var(--theme-accent, #ababab); color:var(--theme-accent, #c9c9c9); }
.delivery-findings.compact { margin:0; padding:8px 10px; font-size:11px; }
</style>
