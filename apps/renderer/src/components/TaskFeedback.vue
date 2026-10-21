<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { Check, LoaderCircle, Star, X } from 'lucide-vue-next';
import { betaActor, feedbackCooldownKey, shouldPromptFeedback, type TaskFeedback } from '../features/betaTesting';

const props = defineProps<{ apiBaseUrl: string; projectId: string; taskId: string; record?: TaskFeedback; active: boolean; ready: boolean; loaded: boolean; running: boolean }>();
const emit = defineEmits<{ saved: [record: TaskFeedback] }>();
const anchor = ref<HTMLElement | null>(null);
const promptVisible = ref(false), saving = ref(false), hovered = ref(0), error = ref(''), inView = ref(false);
const shown = computed(() => Boolean(props.record?.rating) || props.active && promptVisible.value);
const labels = ['很不满意', '不太满意', '一般', '满意', '很满意'];
let observer: IntersectionObserver | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;

async function save(action: 'shown' | 'dismissed' | 'rated', rating?: number) {
  const response = await fetch(`${props.apiBaseUrl}/api/testing/projects/${encodeURIComponent(props.projectId)}/tasks/${encodeURIComponent(props.taskId)}/feedback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, rating, actor: betaActor() }),
  });
  if (!response.ok) throw new Error('反馈尚未保存，请重试');
  const record = await response.json() as TaskFeedback;
  if (!disposed) emit('saved', record);
}
function lastPrompt() { try { return Number(localStorage.getItem(feedbackCooldownKey)) || 0; } catch { return 0; } }
async function reveal() {
  promptVisible.value = true;
  try { localStorage.setItem(feedbackCooldownKey, String(Date.now())); } catch { /* Local storage may be unavailable. */ }
  try { await save('shown'); } catch { /* Rating can still be submitted when the service recovers. */ }
}
function schedulePrompt() {
  clearTimeout(timer);
  if (!props.loaded || !props.active || !props.ready || !inView.value || shown.value || document.visibilityState !== 'visible') return;
  if (!shouldPromptFeedback(props.record, lastPrompt(), Date.now())) return;
  timer = setTimeout(() => {
    if (shouldPromptFeedback(props.record, lastPrompt(), Date.now()) && document.visibilityState === 'visible') void reveal();
  }, 6000);
}
async function rate(rating: number) {
  if (saving.value) return;
  saving.value = true; error.value = '';
  try { await save('rated', rating); }
  catch { error.value = '评分未保存，点击星标重试'; }
  finally { saving.value = false; }
}
async function dismiss() {
  if (saving.value) return;
  saving.value = true; error.value = '';
  try { await save('dismissed'); promptVisible.value = false; }
  catch { error.value = '暂时无法保存，请重试'; }
  finally { saving.value = false; }
}
watch([() => props.active, () => props.ready, () => props.loaded, () => props.record, inView], schedulePrompt);
onMounted(async () => {
  await nextTick();
  if (disposed) return;
  observer = new IntersectionObserver(entries => { inView.value = entries[0]?.isIntersecting || false; }, { threshold: 0.1 });
  const target = anchor.value?.closest('.design-message') || anchor.value;
  if (target) observer.observe(target);
  document.addEventListener('visibilitychange', schedulePrompt);
});
onUnmounted(() => { disposed = true; observer?.disconnect(); clearTimeout(timer); document.removeEventListener('visibilitychange', schedulePrompt); });
</script>

<template>
  <div ref="anchor" class="task-feedback-anchor">
    <div v-if="loaded && shown" class="task-feedback" aria-label="生成结果满意度">
      <div class="task-feedback-heading"><span>{{ record?.rating ? '感谢反馈' : running ? '先看看已生成的内容，满意吗？' : '这次生成的结果满意吗？' }}</span><button v-if="!record?.rating" type="button" aria-label="暂不评价" title="暂不评价" :disabled="saving" @click="dismiss"><X :size="12" /></button></div>
      <div class="task-feedback-controls"><div class="task-feedback-stars" role="group" aria-label="1 至 5 星评分" @mouseleave="hovered = 0"><button v-for="score in 5" :key="score" type="button" :aria-label="`${score} 星，${labels[score - 1]}`" :aria-pressed="record?.rating === score" :title="labels[score - 1]" :disabled="saving" @mouseenter="hovered = score" @focus="hovered = score" @blur="hovered = 0" @click="rate(score)"><Star :size="19" :fill="score <= (hovered || record?.rating || 0) ? 'currentColor' : 'none'" :stroke-width="1.5" /></button></div><small><LoaderCircle v-if="saving" :size="12" class="spin-icon" /><Check v-else-if="record?.rating" :size="12" />{{ saving ? '保存中' : hovered ? labels[hovered - 1] : record?.rating ? `${record.rating}/5 · 可修改` : '点亮星标即可 · 可跳过' }}</small></div>
      <p v-if="error" role="status">{{ error }}</p>
    </div>
    <button v-else-if="loaded && active && ready && !record?.dismissedAt" type="button" class="task-feedback-invite" @click="reveal"><Star :size="13" />评价结果</button>
  </div>
</template>

<style scoped>
.task-feedback { margin-top: 12px; color: var(--theme-text-muted); font-size: var(--ui-font-caption); }
.task-feedback-heading, .task-feedback-controls { display: flex; align-items: center; gap: 8px; }
.task-feedback-heading { justify-content: space-between; }
.task-feedback-heading button, .task-feedback-stars button, .task-feedback-invite { display: inline-flex; align-items: center; justify-content: center; border: 0; background: transparent; color: inherit; cursor: pointer; }
.task-feedback-heading button { padding: 4px; }
.task-feedback-controls { margin-top: 6px; flex-wrap: wrap; }
.task-feedback-stars { display: flex; gap: 2px; color: var(--theme-accent-strong); }
.task-feedback-stars button { padding: 4px; }
.task-feedback button:focus-visible, .task-feedback-invite:focus-visible { outline: 1px solid var(--theme-accent-strong); outline-offset: 2px; border-radius: 4px; }
.task-feedback-controls small { display: inline-flex; align-items: center; gap: 4px; color: var(--theme-text-subtle); font-size: var(--ui-font-caption); }
.task-feedback p { margin: 5px 0 0; color: var(--theme-danger); }
.task-feedback-invite { gap: 5px; padding: 10px 0 0; color: var(--theme-text-subtle); font-size: var(--ui-font-caption); }
.task-feedback-invite:hover { color: var(--theme-accent-strong); }
</style>
