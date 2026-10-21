<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { ArrowUp, Check, ChevronLeft, ChevronRight, CornerDownLeft, MessageCircleQuestion } from 'lucide-vue-next';
import AgentMarkdown from './AgentMarkdown.vue';
import { clarificationAnswered, clarificationReply, structuredAnswers, type ClarificationSubmission, restoreClarificationDraft, type Clarification } from '../features/clarification';

const props = defineProps<{ clarification: Clarification; projectId: string; taskId: string; busy: boolean }>();
const emit = defineEmits<{ submit: [submission: Omit<ClarificationSubmission, 'taskId'>] }>();
const storageKey = `langjuart.clarification.${props.projectId}.${props.taskId}`;
let saved: string | null = null;
try { saved = localStorage.getItem(storageKey); } catch { /* Drafts remain usable in memory. */ }
const initial = restoreClarificationDraft(props.clarification, saved);
const step = ref(initial.step);
const answers = ref(initial.answers);
const current = computed(() => props.clarification.questions[step.value]);
const answer = computed(() => answers.value[step.value]);
const last = computed(() => step.value === props.clarification.questions.length - 1);
const canContinue = computed(() => clarificationAnswered(answer.value) || answer.value.skipped);
const submissionPending = ref(false);
const disabled = computed(() => props.busy || submissionPending.value);
const body = ref<HTMLElement | null>(null);
const heading = ref<HTMLElement | null>(null);
const customInput = ref<HTMLTextAreaElement | null>(null);
const notice = ref('');
const customVisible = computed(() => answer.value.useCustom || !current.value.options.length);

watch([step, answers], () => {
  try { localStorage.setItem(storageKey, JSON.stringify({ signature: JSON.stringify(props.clarification.questions), step: step.value, answers: answers.value })); }
  catch { /* Storage failure must not prevent answering. */ }
}, { deep: true, flush: 'sync' });
watch(() => props.busy, busy => { if (!busy) submissionPending.value = false; });

function selectOption(option: string) {
  const value = answer.value;
  value.skipped = false;
  if (current.value.multi) value.selected = value.selected.includes(option) ? value.selected.filter(item => item !== option) : [...value.selected, option];
  else { value.selected = [option]; value.useCustom = false; }
}
async function selectCustom() {
  answer.value.useCustom = current.value.multi ? !answer.value.useCustom : true;
  answer.value.skipped = false;
  if (!current.value.multi) answer.value.selected = [];
  await nextTick();
  if (answer.value.useCustom) customInput.value?.focus();
}
function writeCustom(event: Event) {
  answer.value.custom = (event.target as HTMLTextAreaElement).value;
  answer.value.useCustom = true;
  answer.value.skipped = false;
}
async function navigate(index: number) {
  if (disabled.value || index < 0 || index >= answers.value.length) return;
  step.value = index;
  notice.value = '';
  await nextTick();
  body.value?.scrollTo({ top: 0 });
  heading.value?.focus({ preventScroll: true });
}
async function advance(skip = false) {
  if (disabled.value || (!skip && !canContinue.value)) return;
  if (skip) { answer.value.selected = []; answer.value.custom = ''; answer.value.useCustom = false; answer.value.skipped = true; }
  if (!last.value) { await navigate(step.value + 1); return; }
  const missing = answers.value.findIndex(value => !value.skipped && !clarificationAnswered(value));
  if (missing >= 0) { await navigate(missing); notice.value = '请回答这一题，或选择跳过。'; return; }
  submissionPending.value = true;
  emit('submit', { answers: clarificationReply(props.clarification, answers.value), entries: structuredAnswers(props.clarification, answers.value) });
  await nextTick();
  // If validation stops submission before a task starts, keep the form editable.
  if (!props.busy) submissionPending.value = false;
}
</script>

<template>
  <section class="clarification-card" aria-label="补充设计需求" :aria-busy="disabled" @keydown.stop>
    <header class="clarification-header">
      <span><MessageCircleQuestion :size="15" />提问</span>
      <nav aria-label="问题导航">
        <button type="button" aria-label="上一题" :disabled="disabled || step === 0" @click="navigate(step - 1)"><ChevronLeft :size="15" /></button>
        <span aria-live="polite" aria-atomic="true">{{ step + 1 }} / {{ clarification.questions.length }}</span>
        <button type="button" aria-label="下一题" :disabled="disabled || last || !canContinue" @click="advance()"><ChevronRight :size="15" /></button>
      </nav>
    </header>
    <div ref="body" class="clarification-body" :key="step">
      <h3 ref="heading" class="clarification-title" tabindex="-1"><AgentMarkdown :content="current.question" compact /></h3>
      <p class="clarification-hint">{{ current.options.length ? current.multi ? '可多选，也可以补充自己的想法' : '选择一项，或填写自己的想法' : '按你的想法填写即可' }}</p>
      <div class="clarification-options" role="group" :aria-label="current.question">
        <label v-for="(option, index) in current.options" :key="option" class="clarification-option" :class="{ selected: answer.selected.includes(option) }">
          <input :type="current.multi ? 'checkbox' : 'radio'" :name="`clarification-${taskId}-${step}`" :checked="answer.selected.includes(option)" :disabled="disabled" @change="selectOption(option)" />
          <span class="clarification-letter" aria-hidden="true">{{ String.fromCharCode(65 + index) }}</span>
          <AgentMarkdown :content="option" inline /><Check v-if="answer.selected.includes(option)" class="clarification-check" :size="14" aria-hidden="true" />
        </label>
        <label v-if="current.options.length" class="clarification-option clarification-custom-option" :class="{ selected: answer.useCustom }">
          <input :type="current.multi ? 'checkbox' : 'radio'" :name="`clarification-${taskId}-${step}`" :checked="answer.useCustom" :disabled="disabled" @change="selectCustom" />
          <span class="clarification-letter" aria-hidden="true">{{ String.fromCharCode(65 + current.options.length) }}</span>
          <span>自己填写</span><Check v-if="answer.useCustom" class="clarification-check" :size="14" aria-hidden="true" />
        </label>
      </div>
      <textarea v-if="customVisible" ref="customInput" class="clarification-custom-input" :value="answer.custom" :disabled="disabled" :aria-label="`${current.question} 自定义回答`" placeholder="输入你的想法、具体要求或其他方向…" rows="3" maxlength="4000" @input="writeCustom" @keydown.meta.enter.prevent="advance()" @keydown.ctrl.enter.prevent="advance()" />
      <p v-if="notice" class="clarification-notice" role="status">{{ notice }}</p>
    </div>
    <footer class="clarification-footer">
      <button v-if="step > 0" type="button" class="clarification-back" :disabled="disabled" @click="navigate(step - 1)">上一步</button>
      <span v-else class="clarification-footer-note">按需补充即可</span>
      <div>
        <button type="button" class="clarification-skip" :disabled="disabled" @click="advance(true)">{{ last ? '跳过并提交' : '跳过' }}</button>
        <button type="button" class="clarification-next" :disabled="disabled || !canContinue" @click="advance()">{{ disabled ? '提交中…' : last ? '提交' : '下一个' }}<ArrowUp v-if="last" :size="14" /><CornerDownLeft v-else :size="14" /></button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.clarification-card { display:flex; flex-direction:column; width:100%; min-width:0; min-height:0; border:1px solid var(--theme-border); border-radius:22px; background:var(--theme-surface-raised); color:var(--theme-text); box-shadow:0 8px 24px #0000000a; overflow:hidden; }
.clarification-header { display:flex; align-items:center; justify-content:space-between; flex-shrink:0; gap:12px; padding:15px 16px 8px; color:var(--theme-text-muted); font-size:12px; }
.clarification-header > span, nav { display:flex; align-items:center; gap:8px; }
nav { gap:3px; }
nav > span { min-width:44px; text-align:center; font-variant-numeric:tabular-nums; }
button { display:inline-flex; align-items:center; justify-content:center; gap:6px; border:1px solid var(--theme-border); border-radius:10px; padding:8px 12px; background:transparent; color:var(--theme-text); font:inherit; font-size:12px; cursor:pointer; }
nav button { padding:4px; border:0; color:var(--theme-text-muted); }
button:disabled { opacity:.4; cursor:default; }
button:focus-visible, textarea:focus-visible { outline:2px solid var(--theme-accent-strong); outline-offset:2px; }
.clarification-body { min-height:0; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; padding:8px 16px 12px; }
.clarification-title { margin:0; outline:none; }
.clarification-title .agent-markdown { --agent-markdown-font-size:13px; --agent-markdown-line-height:1.65; font-weight:600; }
.clarification-hint { margin:7px 0 12px; color:var(--theme-text-subtle); font-size:11px; line-height:1.5; }
.clarification-options { display:flex; flex-direction:column; gap:5px; }
.clarification-option { position:relative; display:flex; align-items:flex-start; gap:9px; min-height:37px; padding:8px; border:1px solid transparent; border-radius:10px; cursor:pointer; font-size:12px; line-height:1.6; overflow-wrap:anywhere; }
.clarification-option:hover { background:var(--theme-surface-subtle); }
.clarification-option.selected { background:var(--theme-accent-soft); border-color:var(--theme-border-strong); }
.clarification-option:has(input:focus-visible) { outline:2px solid var(--theme-accent-strong); outline-offset:1px; }
.clarification-option:has(input:disabled) { cursor:default; opacity:.6; }
.clarification-option input { position:absolute; opacity:0; width:1px; height:1px; }
.clarification-option .agent-markdown { flex:1; min-width:0; --agent-markdown-font-size:12px; --agent-markdown-line-height:1.6; }
.clarification-letter { display:grid; place-items:center; flex:0 0 20px; height:20px; border-radius:5px; background:var(--theme-surface-subtle); color:var(--theme-text-muted); font-size:11px; }
.selected .clarification-letter { background:var(--theme-accent-strong); color:var(--theme-on-accent, #151515); }
.clarification-check { flex-shrink:0; margin:3px 0 0 auto; color:var(--theme-accent-strong); }
.clarification-custom-option { color:var(--theme-text-muted); }
.clarification-custom-input { display:block; resize:vertical; width:100%; min-height:78px; max-height:180px; box-sizing:border-box; margin:8px 0 2px; padding:10px 12px; border:1px solid var(--theme-border-strong); border-radius:11px; background:var(--theme-surface); color:var(--theme-text); font:inherit; font-size:12px; line-height:1.65; }
.clarification-custom-input::placeholder { color:var(--theme-text-subtle); }
.clarification-notice { font-size:11px; color:var(--theme-text-muted); }
.clarification-footer { display:flex; align-items:center; justify-content:space-between; flex-shrink:0; gap:8px; padding:12px 16px 14px; }
.clarification-footer > div { display:flex; gap:7px; }
.clarification-back { border:0; padding-left:0; color:var(--theme-text-muted); }
.clarification-footer-note { color:var(--theme-text-subtle); font-size:10px; }
.clarification-next { border-color:var(--theme-text); background:var(--theme-text); color:var(--theme-surface-raised); }
@media (max-height:650px) { .clarification-header { padding-top:10px; } .clarification-footer { padding-top:8px; padding-bottom:10px; } }
</style>
