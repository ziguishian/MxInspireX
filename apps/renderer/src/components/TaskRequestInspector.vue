<script setup lang="ts">
import { formatCny, formatTokens } from '../modelEconomy';
import { onMounted, ref } from 'vue';
import { durationLabel } from '../features/taskProgress';
const props = defineProps<{ apiBaseUrl: string; projectId: string; taskId: string }>();
const emit = defineEmits<{ close: []; locate: [nodeId?: string]; recovered: [] }>();
const tab = ref<'request' | 'outputs' | 'billing' | 'performance'>('request');
const data = ref<any>();
const error = ref('');
const loading = ref(false);
const recovering = ref(false);
const recoveryMessage = ref('');
async function recover(id: string) {
  recovering.value = true; recoveryMessage.value = ''; error.value = '';
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${props.projectId}/tasks/${props.taskId}/image-results/${id}/recover`, {method:'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '原结果暂时无法取回，请稍后查询。');
    recoveryMessage.value = result.message;
    if (result.state === 'saved') emit('recovered');
    await load();
  } catch (e) { error.value = e instanceof Error ? e.message : '查询失败'; }
  finally { recovering.value = false; }
}
const dialog = ref<HTMLDialogElement>();
const timingLabels: Record<string, string> = {
  contextPreparationMs:'上下文准备', textModelMs:'文本模型', imagePreflightMs:'图像参数预检',
  referenceUploadMs:'参考图上传', providerSubmitMs:'提交图像请求', providerWaitMs:'服务商等待',
  observedQueueMs:'其中：排队（观测）', observedProcessingMs:'其中：处理（观测）',
  resultDownloadMs:'结果下载', assetSaveMs:'资产与画布保存',
};
async function load() {
  loading.value = true; error.value = '';
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${props.projectId}/tasks/${props.taskId}/inspection`);
    if (!response.ok) throw new Error('暂时无法读取请求记录，请稍后刷新。');
    data.value = await response.json();
  } catch (e) { error.value = e instanceof Error ? e.message : '读取失败'; }
  finally { loading.value = false; }
}
function dismissOutside(event: MouseEvent) {
  const bounds = dialog.value?.getBoundingClientRect();
  if (bounds && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) emit('close');
}
onMounted(() => { dialog.value?.showModal(); void load(); });
</script>
<template>
    <dialog ref="dialog" class="modal request-inspector" aria-label="请求、产物与计费" @cancel.prevent="emit('close')" @click.self="dismissOutside">
      <header><h2>请求、产物与计费</h2><button type="button" aria-label="关闭" @click="emit('close')">×</button></header>
      <nav aria-label="核对记录"><button :aria-pressed="tab === 'request'" @click="tab = 'request'">查看原请求</button><button :aria-pressed="tab === 'outputs'" @click="tab = 'outputs'">已保存产物</button><button :aria-pressed="tab === 'billing'" @click="tab = 'billing'">计费状态</button><button :aria-pressed="tab === 'performance'" @click="tab = 'performance'">耗时与调用</button></nav>
      <p v-if="error" role="alert">{{ error }}</p><p v-if="loading">正在读取本地记录…</p>
      <section v-if="data?.recoverableImages?.some((item: any) => !item.saved)" aria-label="取回原媒体">
        <p>查询已提交的图片或语音任务并取回原结果，不重新生成。</p>
        <article v-for="item in data.recoverableImages.filter((item: any) => !item.saved)" :key="item.id">
          <small>{{ item.model }} · {{ item.providerTaskId }}</small>
          <button :disabled="recovering || ['running','queued','cancelled'].includes(data.task.status)" @click="recover(item.id)">{{ recovering ? '正在取回…' : '取回原结果' }}</button>
        </article>
      </section>
      <p v-if="recoveryMessage" role="status">{{ recoveryMessage }}</p>
      <template v-if="data">
        <section v-if="tab === 'request'"><small>请求 {{ taskId }} · {{ data.task.createdAt }}</small><p class="original-request">{{ data.task.userMessage }}</p><p>执行状态：{{ ({ succeeded: '已完成', failed: '遇到问题', cancelled: '已停止', running: '运行中', queued: '排队中' } as Record<string, string>)[data.task.status] || data.task.status }}</p><button @click="emit('locate')">定位原对话</button></section>
        <section v-else-if="tab === 'outputs'"><p v-if="!data.nodes.length">当前没有与本次请求关联的已保存画布产物。结果尚未确认时，不代表服务商没有完成生成。</p><article v-for="node in data.nodes" :key="node.id"><img v-if="node.data?.assetId && node.data?.kind === 'image'" :src="`${apiBaseUrl}/api/projects/${projectId}/assets/${node.data.assetId}/content`" :alt="node.data.title || '已保存图片'" /><strong>{{ node.data?.title || node.id }}</strong><button @click="emit('locate', node.id)">在画布中查看</button></article></section>
        <section v-else-if="tab === 'billing'"><p>{{ data.billingNote }}</p><p v-if="!data.billing.length">本地暂无计费记录，收费状态尚不能确认。</p><ul><li v-for="entry in data.billing" :key="entry.id">{{ entry.model }} · {{ entry.kind }} · {{ entry.tokenUnreported && !entry.totalTokens ? 'Token 未返回' : `${formatTokens(entry.totalTokens)} Token${entry.tokenUnreported ? '（部分）' : ''}` }} · {{ entry.costCny != null ? `${formatCny(entry.costCny)}（已确认扣费）` : entry.estimatedCostCny != null ? `待对账 · 参考估算 ${formatCny(entry.estimatedCostCny)}（非扣款）` : '待对账' }}</li></ul><details><summary>工具记录（{{ data.receipts.length }}）</summary><ul><li v-for="(receipt, index) in data.receipts" :key="index">{{ receipt.tool }} · {{ receipt.status === 'running' ? '已提交，结果尚未确认' : receipt.status === 'rejected' ? '调用被拒绝，请核对费用' : '已有回执' }} · {{ receipt.updatedAt }}</li></ul></details></section>
        <section v-else aria-label="任务性能记录"><template v-if="data.performance"><dl class="performance-metrics"><div><dt>首个产物</dt><dd>{{ data.performance.firstArtifactMs == null ? '—' : durationLabel(data.performance.firstArtifactMs) }}</dd></div><div><dt>文本请求</dt><dd>{{ data.performance.sdkRequests ?? '—' }} 次</dd></div><div><dt>图片提交</dt><dd>{{ data.performance.imageRequests ?? '—' }} 次</dd></div><div><dt>累计输入 Token</dt><dd>{{ data.performance.inputTokens?.toLocaleString() ?? '—' }}</dd></div><div><dt>累计输出 Token</dt><dd>{{ data.performance.outputTokens?.toLocaleString() ?? '—' }}</dd></div></dl><small>{{ data.performance.note }}{{ data.performance.coverage !== 'full' ? ' 此任务的统计不完整。' : '' }}</small></template><p v-else>此历史任务未记录性能数据。</p></section>
      </template>
      <section v-if="tab === 'performance' && data?.performance?.timingMs" aria-label="分阶段耗时">
        <dl class="phase-timings"><div v-for="(label, key) in timingLabels" :key="key"><dt>{{ label }}</dt><dd>{{ data.performance.timingMs[key] == null ? '—' : `${(data.performance.timingMs[key] / 1000).toFixed(2)} 秒` }}</dd></div></dl>
        <p v-if="data.performance.referenceUploadCacheHits != null">参考上传复用 {{ data.performance.referenceUploadCacheHits }} 次</p>
        <small>{{ data.performance.timingNote }}</small>
      </section>
      <footer><small>核对后可在对话中说明下一步；队列仍等交付通过。刷新只读取本地记录。</small><button :disabled="loading" @click="load">刷新记录</button></footer>
    </dialog>
</template>
<style scoped>
.request-inspector { width: min(720px, 92vw); max-height: 85vh; overflow: auto; padding: 24px; }
.request-inspector::backdrop { background:var(--theme-overlay); backdrop-filter:blur(8px); }
header, nav, footer, article { display: flex; align-items: center; gap: 12px; }
header { justify-content: space-between; } h2 { font-size: 18px; }
nav { margin: 12px 0 20px; flex-wrap:wrap; } button { cursor: pointer; padding: 7px 10px; border: 1px solid var(--theme-border); border-radius: 8px; background: var(--theme-surface-raised); color: inherit; }
.performance-metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.performance-metrics div { padding:14px; background:var(--theme-surface); border-radius:12px; }
.performance-metrics dt { color:var(--theme-text-muted); font-size:var(--ui-font-caption); }
.performance-metrics dd { margin:6px 0 0; font-size:var(--ui-font-section); }
.phase-timings { margin-top:20px; font-size:var(--ui-font-body); }
.phase-timings div { display:flex; justify-content:space-between; gap:16px; padding:8px 0; border-bottom:1px solid var(--theme-border); }
.phase-timings dt { color:var(--theme-text-muted); } .phase-timings dd { margin:0; white-space:nowrap; font-variant-numeric:tabular-nums; }
button[aria-pressed="true"] { border-color: var(--theme-accent, #939393); }
.original-request { white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: var(--theme-surface-raised); border-radius: 8px; }
article { padding: 10px 0; } article strong { flex: 1; } article img { width: 100px; height: 80px; object-fit: contain; }
footer { margin-top: 20px; justify-content: space-between; } small { color: var(--theme-text-muted); } li { margin: 8px 0; }
</style>
