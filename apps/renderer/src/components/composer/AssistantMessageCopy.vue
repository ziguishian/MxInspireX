<script setup lang="ts">
import { onUnmounted, ref } from 'vue';
import { Check, Copy, Volume2, Square } from 'lucide-vue-next';
import MessageTimestamp from './MessageTimestamp.vue';
import { recordBetaUsage } from '../../features/betaTesting';

const props = defineProps<{ content: string; taskId?: string; timestamp?: string | null; readAloud?: boolean }>();
const speaking = ref(false);
const speechError = ref('');
let utterance: SpeechSynthesisUtterance | undefined;
function toggleSpeech() {
  speechError.value = '';
  if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === 'undefined') { speechError.value = '当前环境不支持朗读'; return; }
  if (speaking.value) { window.speechSynthesis.cancel(); speaking.value = false; return; }
  window.speechSynthesis.cancel();
  utterance = new SpeechSynthesisUtterance(props.content.replace(/```[\s\S]*?```/g, '').replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/^[#>]+\s*/gm, '').replace(/[*`_]/g, ''));
  utterance.lang = /[\u4e00-\u9fff]/.test(props.content) ? 'zh-CN' : 'en-US';
  utterance.onend = () => { speaking.value = false; };
  utterance.onerror = event => { speaking.value = false; if (!['canceled', 'interrupted'].includes(event.error)) speechError.value = '朗读不可用，请检查系统语音包'; };
  speaking.value = true;
  window.speechSynthesis.speak(utterance);
}
const copied = ref(false);
const failed = ref(false);
let resetTimer: ReturnType<typeof setTimeout> | undefined;

async function copyReply() {
  failed.value = false;
  try {
    await navigator.clipboard.writeText(props.content);
    recordBetaUsage('message_copy', { taskId: props.taskId });
    copied.value = true;
    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => { copied.value = false; }, 2000);
  } catch {
    copied.value = false;
    failed.value = true;
  }
}

onUnmounted(() => { clearTimeout(resetTimer); if (speaking.value) window.speechSynthesis?.cancel(); });
</script>

<template>
  <div class="assistant-message-actions" role="group" aria-label="回复操作">
    <button type="button" :aria-label="copied ? '已复制' : failed ? '复制失败，请重试' : '复制回复'" :title="copied ? '已复制' : failed ? '复制失败，请重试' : '复制回复'" @click.stop="copyReply">
      <Check v-if="copied" :size="14" aria-hidden="true" />
      <Copy v-else :size="14" :stroke-width="1.7" aria-hidden="true" />
    </button>
    <button v-if="readAloud" type="button" :aria-label="speaking ? '停止朗读' : '朗读回复'" :title="speaking ? '停止朗读' : '朗读回复'" :aria-pressed="speaking" @click.stop="toggleSpeech"><Square v-if="speaking" :size="14" /><Volume2 v-else :size="16" /></button>
    <MessageTimestamp :value="timestamp" />
    <span v-if="speechError" class="speech-error" role="status">{{ speechError }}</span>
    <span v-if="copied" class="sr-only" role="status">回复已复制</span>
    <span v-if="failed" class="sr-only" role="status">复制失败，请重试</span>
  </div>
</template>

<style scoped>
.assistant-message-actions{display:flex;align-items:center;gap:3px;min-height:27px;margin-top:6px;flex-wrap:wrap;opacity:0;pointer-events:none}
.speech-error{font-size:12px;color:var(--theme-text-muted)}
:global(.design-message.assistant:hover) .assistant-message-actions,:global(.design-message.assistant:focus-within) .assistant-message-actions{opacity:1;pointer-events:auto}
.assistant-message-actions button{display:grid;place-items:center;width:27px;height:27px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--theme-text-muted);cursor:var(--cursor-pointer)}
.assistant-message-actions button:hover{background:var(--theme-surface-hover);color:var(--theme-text)}
.assistant-message-actions button:focus-visible{outline:1px solid var(--theme-accent-strong);outline-offset:1px}
@media(hover:none){.assistant-message-actions{opacity:1;pointer-events:auto}}
@media(prefers-reduced-motion:reduce){.assistant-message-actions{transition:none}}
</style>
