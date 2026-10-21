<script setup lang="ts">
import AgentMarkdown from './AgentMarkdown.vue';

withDefaults(defineProps<{ content: string; fontSize?: number }>(), { fontSize: 15 });
</script>

<template>
  <div class="canvas-markdown" :style="{ fontSize: `${fontSize}px` }" tabindex="0" role="region" aria-label="节点文本内容">
    <AgentMarkdown :content="content" compact />
  </div>
</template>

<style scoped>
.canvas-markdown {
  box-sizing: border-box;
  min-width: 0;
  height: 100%;
  margin: 0;
  padding: 1.4em 1.5em;
  overflow: auto;
  overscroll-behavior: contain;
  white-space: normal;
  overflow-wrap: anywhere;
  color: var(--theme-text);
  line-height: 1.8;
  user-select: text;
  cursor: text;
  --agent-markdown-font-size: inherit;
  --agent-markdown-line-height: 1.8;
}
.canvas-markdown:focus-visible { outline: 2px solid var(--theme-border-strong); outline-offset: -3px; border-radius: 14px; }
.canvas-markdown :deep(.agent-markdown h1) { font-size: 1.55em; line-height: 1.4; letter-spacing: -.02em; }
.canvas-markdown :deep(.agent-markdown h2) { margin-top: 1.6em; padding-bottom: .45em; border-bottom: 1px solid var(--theme-border); font-size: 1.2em; }
.canvas-markdown :deep(.agent-markdown h3) { margin-top: 1.4em; font-size: 1.08em; }
.canvas-markdown :deep(.agent-markdown p) { margin-block: .85em; }
.canvas-markdown :deep(.agent-markdown strong) { font-weight: 650; }
.canvas-markdown :deep(.agent-markdown li) { margin-block: .35em; }
.canvas-markdown :deep(.agent-markdown li > p) { margin-block: .3em; }
.canvas-markdown :deep(.agent-markdown li::marker) { color: var(--theme-text-muted); }
.canvas-markdown :deep(.agent-markdown blockquote) { margin-inline: 0; padding: .6em 1em; border-color: var(--theme-accent-strong); border-radius: 0 8px 8px 0; background: var(--theme-surface-subtle); color: var(--theme-text-subtle); }
.canvas-markdown :deep(.agent-markdown tbody tr:nth-child(even)) { background: color-mix(in srgb, var(--theme-text) 3%, transparent); }
.canvas-markdown :deep(.agent-markdown pre), .canvas-markdown :deep(.agent-markdown-table) { overscroll-behavior-x: contain; }
.canvas-markdown :deep(.agent-markdown > :first-child) { margin-top: 0; }
.canvas-markdown :deep(.agent-markdown > :last-child) { margin-bottom: 0; }
/* Canvas text nodes grow with their rendered Markdown rather than leaving a
   fixed empty panel below short text. Version comparison keeps its own scroll
   container because it does not add this class. */
.design-asset-caption.canvas-markdown { height: auto; overflow: visible; }
</style>
