<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue';
import { ReplyTypewriter } from '../features/replyTypewriter';
import { typedMarkdown, revealMarkdown } from '../features/typedMarkdown';

const props = defineProps<{ content: string; compact?: boolean; inline?: boolean; animate?: boolean }>();
const emit = defineEmits<{ reveal: [] }>();
const tree = computed(() => typedMarkdown(props.content, props.inline));
const buffer = new ReplyTypewriter();
const position = ref(0);
const typing = computed(() => position.value < tree.value.characters.length);
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let frame = 0, lastFrame = 0, disposed = false;
function stop() { cancelAnimationFrame(frame); frame = 0; lastFrame = 0; }
function publish() {
  if (position.value === buffer.position) return;
  position.value = buffer.position;
  void nextTick(() => { if (!disposed) emit('reveal'); });
}
function tick(now: number) {
  frame = 0;
  buffer.advance(lastFrame ? now - lastFrame : 16);
  lastFrame = now;
  publish();
  if (buffer.pending) frame = requestAnimationFrame(tick);
  else lastFrame = 0;
}
function sync() {
  const immediate = !props.animate || reducedMotion.matches || document.hidden;
  buffer.update(tree.value.characters, immediate);
  publish();
  if (buffer.pending && !frame) frame = requestAnimationFrame(tick);
  else if (!buffer.pending) stop();
}
watch([tree, () => props.animate], sync, { immediate: true });
document.addEventListener('visibilitychange', sync);
reducedMotion.addEventListener('change', sync);
onUnmounted(() => {
  disposed = true; stop();
  document.removeEventListener('visibilitychange', sync);
  reducedMotion.removeEventListener('change', sync);
});
const MarkdownBody = () => revealMarkdown(tree.value.parts, position.value);
</script>

<template>
  <component :is="inline ? 'span' : 'div'" class="agent-markdown" :class="{ compact, inline }" :aria-busy="typing || undefined"><MarkdownBody /></component>
</template>

<style scoped>
.agent-markdown { min-width: 0; max-width: 100%; margin-top: 5px; font-size: 14px; line-height: 1.8; white-space: normal; overflow-wrap: anywhere; }
.agent-markdown.compact, .agent-markdown.inline { margin: 0; font-size: var(--agent-markdown-font-size, inherit); line-height: var(--agent-markdown-line-height, inherit); }
.agent-markdown :deep(p) { margin: .65em 0; font-size: inherit; line-height: inherit; white-space: normal; }
.agent-markdown :deep(h1), .agent-markdown :deep(h2), .agent-markdown :deep(h3), .agent-markdown :deep(h4), .agent-markdown :deep(h5), .agent-markdown :deep(h6) { margin: 1em 0 .45em; font-weight: 650; line-height: 1.45; }
.agent-markdown :deep(h1) { font-size: 1.4em; }
.agent-markdown :deep(h2) { font-size: 1.25em; }
.agent-markdown :deep(h3) { font-size: 1.1em; }
.agent-markdown :deep(h4), .agent-markdown :deep(h5), .agent-markdown :deep(h6) { font-size: 1em; }
.agent-markdown :deep(ul), .agent-markdown :deep(ol) { margin: .65em 0; padding-left: 1.6em; }
.agent-markdown :deep(ul) { list-style: disc; }
.agent-markdown :deep(ol) { list-style: decimal; }
.agent-markdown :deep(li) { display: list-item; margin: .2em 0; padding: 0; }
.agent-markdown :deep(li > ul), .agent-markdown :deep(li > ol), .agent-markdown :deep(li > p) { margin: .25em 0; }
.agent-markdown :deep(blockquote) { margin: .75em 0; padding: .15em 0 .15em .9em; border-left: 3px solid var(--theme-border-strong); color: var(--theme-text-muted); }
.agent-markdown :deep(hr) { margin: 1em 0; border: 0; border-top: 1px solid var(--theme-border); }
.agent-markdown :deep(a) { color: var(--theme-accent-strong); text-decoration: underline; text-underline-offset: 3px; }
.agent-markdown :deep(code) { border-radius: 4px; background: var(--theme-surface-subtle); padding: .15em .35em; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .9em; }
.agent-markdown :deep(pre) { max-width: 100%; margin: .8em 0; overflow-x: auto; border: 1px solid var(--theme-border); border-radius: 9px; background: var(--theme-surface-subtle); padding: 12px; white-space: pre; overflow-wrap: normal; line-height: 1.6; tab-size: 2; }
.agent-markdown :deep(pre code) { display: block; border: 0; background: transparent; padding: 0; white-space: inherit; overflow-wrap: normal; }
.agent-markdown :deep(.agent-markdown-table) { max-width: 100%; margin: .8em 0; overflow-x: auto; border: 1px solid var(--theme-border); border-radius: 9px; }
.agent-markdown :deep(table) { width: 100%; margin: 0; border-collapse: collapse; font-size: .9em; line-height: 1.6; }
.agent-markdown :deep(th), .agent-markdown :deep(td) { min-width: 6em; border-bottom: 1px solid var(--theme-border); padding: 8px 10px; text-align: left; vertical-align: top; }
.agent-markdown :deep(th) { background: var(--theme-surface-subtle); font-weight: 600; }
.agent-markdown :deep(tr:last-child td) { border-bottom: 0; }
.agent-markdown :deep(a:focus-visible), .agent-markdown :deep(.agent-markdown-table:focus-visible) { outline: 2px solid var(--theme-accent-strong); outline-offset: 2px; }
.agent-markdown :deep(> :first-child) { margin-top: 0; }
.agent-markdown :deep(> :last-child) { margin-bottom: 0; }
</style>
