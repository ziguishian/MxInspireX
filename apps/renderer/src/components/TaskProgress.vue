<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { durationLabel, taskProgress, type ExecutionInfo } from '../features/taskProgress';
import { taskOutcome } from '../features/taskOutcome';
import type { TaskIssue } from '../features/taskErrors';
import DeliveryFindings from './DeliveryFindings.vue';
const props = defineProps<{ info: ExecutionInfo; status: string; clarification?: boolean; referenceSelection?: boolean; hasReply?: boolean }>();
const emit = defineEmits<{ inspect: [nodeId: string]; action: [action: TaskIssue['action']] }>();
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | undefined;
watch(() => props.status, status => {
  clearInterval(timer); now.value = Date.now();
  if (!['succeeded', 'failed', 'cancelled'].includes(status)) timer = setInterval(() => { now.value = Date.now(); }, 1000);
}, { immediate: true });
onUnmounted(() => clearInterval(timer));
const waitingForInput = computed(() => Boolean(props.clarification || props.referenceSelection));
const progress = computed(() => {
  const value = taskProgress(props.info, props.status, now.value, props.clarification);
  return props.status === 'succeeded' && props.referenceSelection ? { ...value, label: '等待选择参考' } : value;
});
const outcome = computed(() => taskOutcome(props.info, props.status));
</script>
<template>
  <div class="task-progress" :class="{ stalled: progress.stalled, failed: status === 'failed' }">
    <div class="task-progress-title"><i v-if="progress.terminal && !waitingForInput" class="task-outcome-dot" :data-tone="outcome.tone" aria-hidden="true" /><span class="task-progress-label">{{ progress.terminal && !waitingForInput ? outcome.title : progress.label }}</span><span class="task-progress-separator" aria-hidden="true">·</span><span class="task-progress-time">用时 {{ durationLabel(progress.totalMs) }}</span></div>
    <template v-if="progress.terminal && !waitingForInput"><p v-if="outcome.tone !== 'green' || !hasReply" class="task-outcome-detail">{{ outcome.detail }}</p><div v-if="outcome.action === 'settings' || outcome.canCompleteMissing" class="task-outcome-actions"><button v-if="outcome.action === 'settings'" @click="emit('action', 'settings')">查看模型设置</button><button v-if="outcome.canCompleteMissing" @click="emit('action', 'repair')">补齐未完成项</button></div></template>
    <DeliveryFindings v-if="info.findings?.some(f => f.kind === 'problem' || f.nodeId)" :findings="info.findings.filter(f => f.kind === 'problem' || f.nodeId)" inspectable @inspect="emit('inspect', $event)" />
    <p v-if="info.reconnecting && !progress.terminal">正在连接本地服务，已保存的任务会继续；无需重复发送。</p>
    <p v-else-if="progress.stalled">已 {{ durationLabel(progress.idleMs) }} 没有新的执行进度。媒体生成可能需要较长时间，你可以继续浏览画布，或停止本轮。</p>
  </div>
</template>
<style scoped>
.task-outcome-dot { width:7px; height:7px; align-self:center; flex:0 0 auto; border-radius:50%; background:var(--theme-status-yellow); }
.task-outcome-dot[data-tone="green"] { background:var(--theme-status-green); }
.task-outcome-dot[data-tone="red"] { background:var(--theme-status-red); }
.task-outcome-detail { margin:8px 0; line-height:1.7; }
.task-outcome-actions { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 12px; }
.task-outcome-actions button { border:1px solid var(--theme-border); border-radius:8px; padding:6px 9px; color:var(--theme-text); background:var(--theme-surface); font:inherit; cursor:pointer; }
.task-progress {
  margin: 6px 0;
  padding: 2px 0;
  font-size: var(--ui-font-caption);
  line-height: 1.5;
  color: var(--theme-text-muted, #979797);
}
.task-progress-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 6px;
}
.task-progress-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.task-progress-separator { opacity: .6; }
.task-progress small { font-size: var(--ui-font-caption); }
.task-progress p { font-size: var(--ui-font-caption); line-height: 1.7; margin: 6px 0 0; }
.stalled p { color: var(--theme-warning, #8d8d8d); }
.failed .task-progress-label { color: var(--theme-danger, #727272); }
</style>
