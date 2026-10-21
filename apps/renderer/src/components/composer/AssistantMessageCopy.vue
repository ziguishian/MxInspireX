<script setup lang="ts">
import { onUnmounted, ref } from 'vue';
import { Check, Copy } from 'lucide-vue-next';
import { recordBetaUsage } from '../../features/betaTesting';

const props = defineProps<{ content: string; taskId?: string }>();
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

onUnmounted(() => clearTimeout(resetTimer));
</script>

<template>
  <div class="assistant-message-actions" role="group" aria-label="回复操作">
    <button type="button" :aria-label="copied ? '已复制' : failed ? '复制失败，请重试' : '复制回复'" :title="copied ? '已复制' : failed ? '复制失败，请重试' : '复制回复'" @click.stop="copyReply">
      <Check v-if="copied" :size="14" aria-hidden="true" />
      <Copy v-else :size="14" :stroke-width="1.7" aria-hidden="true" />
    </button>
    <span v-if="copied" class="sr-only" role="status">回复已复制</span>
    <span v-if="failed" class="sr-only" role="status">复制失败，请重试</span>
  </div>
</template>

<style scoped>
.assistant-message-actions{display:flex;justify-content:flex-end;min-height:27px;margin-top:2px;opacity:0;pointer-events:none;transition:opacity .12s ease}
:global(.design-message.assistant:hover) .assistant-message-actions,:global(.design-message.assistant:focus-within) .assistant-message-actions{opacity:1;pointer-events:auto}
.assistant-message-actions button{display:grid;place-items:center;width:27px;height:27px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--theme-text-muted);cursor:var(--cursor-pointer)}
.assistant-message-actions button:hover{background:var(--theme-surface-hover);color:var(--theme-text)}
.assistant-message-actions button:focus-visible{outline:1px solid var(--theme-accent-strong);outline-offset:1px}
@media(hover:none){.assistant-message-actions{opacity:1;pointer-events:auto}}
@media(prefers-reduced-motion:reduce){.assistant-message-actions{transition:none}}
</style>
