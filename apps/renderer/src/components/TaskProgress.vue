<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { durationLabel, taskProgress, deliveryProgress, type ExecutionInfo } from '../features/taskProgress';
import { taskOutcome } from '../features/taskOutcome';
import type { TaskIssue } from '../features/taskErrors';
import DeliveryFindings from './DeliveryFindings.vue';
import AnimatedList from './motion/AnimatedList.vue';
const props = defineProps<{ info: ExecutionInfo; status: string; clarification?: boolean; referenceSelection?: boolean }>();
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
const currentAction = computed(() => [...(props.info.trace || [])].reverse().find(item => item.phase === 'progress' && item.message && !/模型|tokens|参数|上下文|轮次|缓存|调用/.test(item.message))?.message || '');
const delivery = computed(() => deliveryProgress(props.info));
const outcome = computed(() => taskOutcome(props.info, props.status));
const roles = { input:'用户资料',logo:'原 Logo',key_visual:'主视觉',specialist:'专项素材',style:'风格参考',artifact:'生成产物' };
const states = { confirmed:'已确认',assumed:'暂定判断',proposed:'建议',observed:'实际记录' };
const imageUrl = (id: string) => `${props.info.assetBaseUrl}/${encodeURIComponent(id)}/content`;
const missingImages = ref(new Set<string>());
const executionLabel = computed(() => props.status === 'succeeded' ? waitingForInput.value ? '等待你的确认' : '执行完成' : props.status === 'failed' ? '执行失败' : props.status === 'cancelled' ? '执行已停止' : '执行中');
const deliveryLabel = computed(() => ({passed:'交付通过',pending:'交付处理中',needs_review:'交付需处理',failed:'交付未完成'} as Record<string,string>)[props.info.deliveryStatus || '']);
</script>
<template>
  <div class="task-progress" :class="{ stalled: progress.stalled, failed: status === 'failed' }">
    <div class="task-progress-title"><i v-if="progress.terminal && !waitingForInput" class="task-outcome-dot" :data-tone="outcome.tone" aria-hidden="true" /><span class="task-progress-label">{{ progress.terminal && !waitingForInput ? outcome.title : progress.label }}</span><span class="task-progress-separator" aria-hidden="true">·</span><span class="task-progress-time">用时 {{ durationLabel(progress.totalMs) }}</span></div>
    <template v-if="progress.terminal && !waitingForInput"><p class="task-outcome-detail">{{ outcome.detail }}</p><div class="task-outcome-actions"><button v-if="outcome.action === 'settings'" @click="emit('action', 'settings')">查看模型设置</button><button v-if="outcome.canCompleteMissing" @click="emit('action', 'repair')">补齐未完成项</button><button @click="emit('action', 'inspect')">{{ outcome.action === 'inspect' ? '查看请求与计费' : '查看产物与用量' }}</button></div></template>
    <p v-if="!progress.terminal && currentAction" class="task-current-action">{{ currentAction }}</p>
    <details class="task-execution-details" :open="!progress.terminal"><summary>执行详情</summary>
    <DeliveryFindings v-if="info.findings?.some(f => f.kind !== 'problem' && !f.nodeId)" :findings="info.findings.filter(f => f.kind !== 'problem' && !f.nodeId)" />
    <AnimatedList v-if="progress.terminal" class="task-result-states" aria-label="任务与交付状态">
      <span :key="`execution:${status}`" :data-state="status">{{ executionLabel }}</span>
      <span v-if="deliveryLabel && !waitingForInput" :key="`delivery:${info.deliveryStatus}`" :data-state="info.deliveryStatus">{{ deliveryLabel }}</span>
    </AnimatedList>
    <ul v-if="info.updates?.length" class="task-supplements" aria-label="运行中补充"><li v-for="update in info.updates" :key="update.id"><span>{{ update.text }}</span><small>{{ update.appliedAt ? '已纳入后续判断' : progress.terminal ? '任务已结束，这条补充未应用' : '已保存，等待下一次判断' }}</small></li></ul>
    <div v-if="progress.modelProgress.calls || progress.modelProgress.recoveryCount || progress.modelProgress.context" class="task-model-progress" aria-label="模型调用与上下文状态">
      <span v-if="progress.modelProgress.calls">模型调用 {{ progress.modelProgress.calls }} 次 · Agent 轮次 {{ progress.modelProgress.agentRounds }}<template v-if="progress.modelProgress.compactionCalls"> · 压缩调用 {{ progress.modelProgress.compactionCalls }}</template></span>
      <span v-if="progress.modelProgress.recoveryCount">失败恢复 {{ progress.modelProgress.recoveryStageTotal }}/{{ progress.modelProgress.recoveryStageLimit }}<template v-if="progress.modelProgress.correctionLimit"> · 参数修正 {{ progress.modelProgress.correctionAttempt }}/{{ progress.modelProgress.correctionLimit }}</template></span>
      <span v-if="progress.modelProgress.cache" class="task-cache-status">{{ progress.modelProgress.cache.label }} · {{ progress.modelProgress.cache.writeLabel }}</span>
      <span v-if="progress.modelProgress.localContext">上下文已精简（估算） {{ Number(progress.modelProgress.localContext.beforeTokens || 0).toLocaleString() }} → {{ Number(progress.modelProgress.localContext.afterTokens || 0).toLocaleString() }} tokens<small v-if="progress.modelProgress.localContext.reason"> · {{ progress.modelProgress.localContext.reason }}</small></span>
      <span v-if="progress.modelProgress.nativeContext">原生压缩{{ progress.modelProgress.nativeContext.status === 'started' ? '进行中' : progress.modelProgress.nativeContext.status === 'not_needed' ? '尚未触发' : progress.modelProgress.nativeContext.status === 'skipped' ? '未启用' : progress.modelProgress.nativeContext.succeeded === false ? '未完成' : '已完成' }}<template v-if="progress.modelProgress.nativeContext.beforeTokens && progress.modelProgress.nativeContext.afterTokens">（估算） {{ Number(progress.modelProgress.nativeContext.beforeTokens).toLocaleString() }} → {{ Number(progress.modelProgress.nativeContext.afterTokens).toLocaleString() }} tokens</template><template v-if="progress.modelProgress.nativeContext.reason"> · {{ progress.modelProgress.nativeContext.reason }}</template></span>
      <span v-if="progress.modelProgress.safetyWarning" class="task-model-warning">{{ progress.modelProgress.safetyWarning }}</span>
    </div>
    <p v-if="info.batch?.status === 'needs_plan'" class="task-batch-planning">{{ info.batch.intent === 'revise' ? '正在整理本轮修改项' : '正在整理下一批清单' }}</p>
    <details v-if="delivery.total" class="task-deliverables" :open="!progress.terminal">
      <summary>{{ info.batch ? '本批进度' : '交付进度' }} {{ delivery.ready }}/{{ delivery.total }} 项已生成<template v-if="info.batch"> · {{ info.batch.intent === 'revise' ? '修改' : '第 ' + info.batch.number + ' 批' }}</template></summary>
      <AnimatedList as="ul" aria-label="交付清单"><li v-for="item in delivery.rows" :key="item.id" :data-status="item.status"><span>{{ item.title }}<em v-if="item.issue || item.blockingFields?.length">{{ item.issue || '等待：' + item.blockingFields?.join('、') }}</em></span><small>{{ delivery.label(item) }}</small></li></AnimatedList>
    </details>
    <details v-if="info.batch && (info.batch.number > 1 || delivery.cumulativeTotal > delivery.total)" class="task-deliverables task-cumulative">
      <summary>累计进度 {{ delivery.cumulativeReady }}/{{ delivery.cumulativeTotal }} 项已生成</summary>
      <ul aria-label="累计交付清单"><li v-for="item in delivery.cumulativeRows" :key="item.id" :data-status="item.status"><span>{{ item.title }}</span><small>{{ delivery.label(item) }}</small></li></ul>
    </details>
    <details v-if="info.brief" class="task-brief">
      <summary>本轮设计需求 · 已整理</summary>
      <small>根据你的要求整理；明确约束以原文为准。</small>
      <p class="task-brief-summary">{{ info.brief.summary }}</p>
      <template v-if="info.brief.assumptions.length"><strong>暂定假设</strong><ul><li v-for="(item, index) in info.brief.assumptions" :key="index">{{ item }}</li></ul></template>
      <template v-if="info.brief.openQuestions.length"><strong>待确认事项</strong><ul><li v-for="(item, index) in info.brief.openQuestions" :key="index">{{ item }}</li></ul></template>
    </details>
    <details v-if="info.brief?.visualDirection" class="task-visual-direction">
      <summary>本轮视觉设计判断</summary>
      <small>这是生成前可核对的设计依据，不替代你的原始要求。</small>
      <dl>
        <dt>受众与主题</dt><dd>{{ info.brief.visualDirection.audience }} · {{ info.brief.visualDirection.theme }}</dd>
        <dt>核心创意</dt><dd>{{ info.brief.visualDirection.coreConcept }}</dd>
        <dt>视觉层级</dt><dd>{{ info.brief.visualDirection.visualHierarchy.join('；') }}</dd>
        <dt>造型语言</dt><dd>{{ info.brief.visualDirection.formLanguage.join('；') }}</dd>
        <dt>材质与工艺</dt><dd>{{ info.brief.visualDirection.materialProcess.join('；') }}</dd>
        <dt>色彩、构图与光线</dt><dd>{{ [...info.brief.visualDirection.colorRelationships, ...info.brief.visualDirection.compositionLighting].join('；') }}</dd>
        <dt v-if="info.brief.visualDirection.avoid.length">明确避免</dt><dd v-if="info.brief.visualDirection.avoid.length">{{ info.brief.visualDirection.avoid.join('；') }}</dd>
      </dl>
      <ul v-if="info.brief.visualDirection.evidence.length" class="task-visual-evidence"><li v-for="(item, index) in info.brief.visualDirection.evidence" :key="index">{{ item.use }}<small> · {{ item.source === 'user' ? '用户要求' : item.source === 'reference' ? '参考资料' : item.source === 'research' ? '研究证据' : item.source === 'lesson' ? '已确认经验' : '暂定假设' }}<template v-if="item.reference">：{{ item.reference }}</template></small></li></ul>
    </details>
    <details v-if="info.memory?.analyzed" class="task-memory">
      <summary>本轮使用的对话信息 · {{ info.memory.selected.length }} 条</summary>
      <small>仅当前聊天 · 记忆版本 {{ info.memory.memoryRevision }} · 可在对话中更正</small>
      <p v-if="!info.memory.selected.length">本轮没有选用历史信息。</p>
      <ul><li v-for="item in info.memory.selected" :key="item.id">
        <a v-if="item.assetId && info.assetBaseUrl && !missingImages.has(item.assetId)" :href="imageUrl(item.assetId)" target="_blank" rel="noopener"><img :src="imageUrl(item.assetId)" :alt="item.content" loading="lazy" @error="missingImages.add(item.assetId)" /></a>
        <small v-else-if="item.assetId">参考图暂时无法读取</small>
        <span>{{ item.content }}</span>
        <small>{{ item.role ? roles[item.role] + ' · ' : '' }}{{ states[item.status] }} · v{{ item.version }} · {{ item.scope === 'task' ? '当前任务' : item.scope === 'topic' ? item.topic : '当前聊天' }}</small>
        <blockquote v-if="item.source.quote">{{ item.source.quote }}</blockquote>
      </li></ul>
      <div v-for="item in info.memory.progress?.filter(p => p.imageQuality)" :key="item.nodeId" class="task-image-quality">
        <span>{{ item.title || '生成图像' }} · {{ item.imageQuality?.model }}</span>
        <small v-if="item.imageRoute?.fallbackUsed">首选不可用，已使用 {{ item.imageRoute.finalModel }}</small>
        <small>模型档位 {{ item.imageQuality?.tier }} · {{ item.imageQuality?.status === 'applied' ? `质量 ${item.imageQuality.quality}` : '接口未声明可调质量' }}<template v-if="item.imageQuality?.inputFidelity"> · 参考保真 {{ item.imageQuality.inputFidelity }}</template><template v-if="item.dimensions?.width"> · {{ item.dimensions.width }} × {{ item.dimensions.height }}</template></small>
        <small v-if="item.referenceSnapshot?.references.length">实际参考：{{ item.referenceSnapshot.references.map(r => r.purpose).join('、') }}</small>
      </div>
    </details>
    <details v-if="info.decisions?.length" class="task-decisions"><summary>本轮沿用的需求</summary><dl><template v-for="(item, index) in info.decisions" :key="index"><dt>{{ item.label }}</dt><dd>{{ item.value || '尚未确定' }}<small> · {{ item.status === 'confirmed' ? '已确认' : item.status === 'assumed' ? '临时假设' : item.status === 'skipped' ? '已跳过' : '待确认' }}</small></dd></template></dl></details>
    </details>
    <DeliveryFindings v-if="info.findings?.some(f => f.kind === 'problem' || f.nodeId)" :findings="info.findings.filter(f => f.kind === 'problem' || f.nodeId)" inspectable @inspect="emit('inspect', $event)" />
    <div v-if="!progress.terminal" class="task-progress-stages" aria-label="执行阶段"><span v-for="(label, key) in progress.stages" :key="key" :class="{ current: key === progress.stage }">{{ label }}</span></div>
    <div v-if="info.skills?.length" class="task-progress-skills"><span v-for="skill in info.skills" :key="skill.skillId">{{ skill.title }} v{{ skill.version }} · {{ skill.active ? '已加载' : '已卸载' }}</span></div>
    <small v-if="!progress.terminal">当前阶段 {{ durationLabel(progress.stageMs || 0) }} · 最后更新 {{ new Date(progress.lastActivity).toLocaleTimeString('zh-CN', { hour12: false }) }}</small>
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
.task-execution-details > summary { padding:6px 0; }
.task-supplements { padding-left: 16px; } .task-supplements small { display: block; color: var(--theme-text-muted); }
.task-execution-details summary { cursor: pointer; color: var(--theme-text-muted); }
.task-brief { margin: 6px 0; overflow-wrap: anywhere; }
.task-brief summary { cursor: pointer; }
.task-brief-summary { white-space: pre-wrap; }
.task-brief ul { padding-left: 18px; }
.task-visual-direction { margin: 6px 0; overflow-wrap: anywhere; }
.task-visual-direction summary { cursor: pointer; }
.task-visual-direction dl { margin: 6px 0; }
.task-visual-direction dt { margin-top: 5px; color: var(--theme-text-muted); }
.task-visual-direction dd { margin: 0; color: var(--theme-text); }
.task-visual-evidence { margin: 6px 0 0; padding-left: 18px; }
.task-visual-evidence small { color: var(--theme-text-muted); }
.task-memory { margin: 6px 0; overflow-wrap: anywhere; }
.task-memory summary { cursor: pointer; }
.task-memory ul { padding: 0; list-style: none; }
.task-memory li { padding: 6px 0; border-bottom: 1px solid var(--theme-border); }
.task-memory li > span, .task-memory small, .task-image-quality > span { display: block; }
.task-memory img { max-width: 90px; height: 64px; object-fit: contain; border-radius: 4px; }
.task-memory blockquote { margin: 4px 0; padding-left: 8px; border-left: 2px solid var(--theme-border); }
.task-image-quality { margin-top: 8px; }
.task-deliverables, .task-decisions { margin: 6px 0; max-width: 100%; }
.task-deliverables summary, .task-decisions summary { cursor: pointer; }
.task-deliverables ul { padding: 0; margin: 6px 0; list-style: none; }
.task-deliverables li { display: flex; align-items: baseline; gap: 10px; margin: 5px 0; }
.task-deliverables li > span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.task-deliverables em { display: block; font-size: var(--ui-font-caption); font-style: normal; }
.task-deliverables li > small { flex: 0 0 auto; }
.task-deliverables [data-status="needs_review"], .task-deliverables [data-status="blocked"] { color: var(--theme-text); }
.task-decisions dl { margin: 6px 0; overflow-wrap: anywhere; }
.task-decisions dt { margin-top: 6px; }
.task-decisions dd { margin: 0; color: var(--theme-text); }
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
.task-result-states { display:flex; flex-wrap:wrap; gap:5px; margin:5px 0; }
.task-result-states span { padding:2px 7px; border:1px solid var(--theme-border); border-radius:999px; font-size: var(--ui-font-caption); }
.task-result-states [data-state="passed"], .task-result-states [data-state="succeeded"] { color:var(--theme-success, #898989); }
.task-result-states [data-state="needs_review"], .task-result-states [data-state="timed_out"], .task-result-states [data-state="unavailable"] { color:var(--theme-warning, #8d8d8d); }
.task-result-states [data-state="failed"] { color:var(--theme-danger, #727272); }
.task-model-progress { display:flex; flex-wrap:wrap; gap:4px 10px; margin:5px 0; font-size: var(--ui-font-caption); }
.task-model-progress span { min-width:0; max-width:100%; overflow-wrap:anywhere; padding:2px 7px; border:1px solid var(--theme-border); border-radius:999px; }
.task-model-progress .task-model-warning { color:var(--theme-warning, #8d8d8d); }
.task-progress-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.task-progress-separator { opacity: .6; }
.task-progress-stages {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin: 4px 0 2px;
  font-size: var(--ui-font-caption);
}
.task-progress-stages .current {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.task-progress small { font-size: var(--ui-font-caption); }
.task-progress p { font-size: var(--ui-font-caption); line-height: 1.7; margin: 6px 0 0; }
.stalled p { color: var(--theme-warning, #8d8d8d); }
.failed .task-progress-label { color: var(--theme-danger, #727272); }
.task-progress-skills { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; font-size: var(--ui-font-caption); }
</style>
