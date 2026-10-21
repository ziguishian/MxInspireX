<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { FileText, X } from 'lucide-vue-next';
import ReferencePreview from './ReferencePreview.vue';
import { referenceSegments } from '../../features/composer/references';
import type { MessageReference } from '../../features/composer/messageReferences';
const props = defineProps<{ content: string; references?: MessageReference[] }>();
const failed = ref(new Set<string>());
const parts = computed(() => {
  const parts = referenceSegments(props.content, props.references || []).map(part => ({ ...part, reference: part.reference as MessageReference | undefined }));
  const used = new Set(parts.map(part => part.reference?.key));
  for (const item of props.references || []) if (item.attached && !used.has(item.key)) parts.push({ text: ' ', reference: undefined }, { text: '', reference: item });
  return parts;
});
const hover = ref<{ item: MessageReference; x: number; y: number } | null>(null);
const selected = ref<MessageReference | null>(null);
const dialog = ref<HTMLDialogElement | null>(null);
function preview(item: MessageReference, event: Event) {
  if (selected.value) return;
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
  const height = item.preview ? 256 : 176;
  hover.value = { item: failed.value.has(item.key) ? { ...item, preview: undefined } : item,
    x: Math.max(8, Math.min(bounds.left, innerWidth - 232)), y: bounds.top > height + 8 ? bounds.top - height : Math.max(8, Math.min(bounds.bottom + 8, innerHeight - height - 8)) };
}
function open(item: MessageReference) { hover.value = null; selected.value = item; }
function close() { selected.value = null; hover.value = null; dialog.value?.close(); }
watch(selected, async item => { await nextTick(); if (item && selected.value === item && !dialog.value?.open) dialog.value?.showModal(); });
</script>
<template>
  <div class="user-message-content">
    <template v-for="(part, index) in parts" :key="index">
      <span v-if="part.reference?.key.startsWith('skill:')" class="message-skill-chip" :title="part.reference.textContent"># {{ part.reference.label }}</span>
      <button v-else-if="part.reference" type="button" class="message-reference-chip" :data-reference-key="part.reference.key" :aria-label="`查看引用：${part.reference.label}`"
        @pointerenter="preview(part.reference, $event)" @pointerleave="hover = null" @focus="preview(part.reference, $event)" @blur="hover = null" @click.stop="open(part.reference)">
        <img v-if="part.reference.preview && !failed.has(part.reference.key)" :src="part.reference.preview" alt="" loading="lazy" decoding="async" @error="failed.add(part.reference.key)" />
        <span v-else class="message-reference-file"><FileText :size="18" /><small>{{ part.reference.kind }}</small></span>
        <span class="message-reference-badge">{{ part.reference.badge }}</span>
      </button><span v-else class="user-message-text">{{ part.text }}</span>
    </template>
  </div>
  <ReferencePreview v-if="hover" v-bind="hover" />
  <Teleport to="body"><dialog ref="dialog" class="message-reference-dialog" aria-label="引用文件预览" @click.self="close" @cancel="close" @close="selected = null">
    <template v-if="selected"><header><strong>{{ selected.label }}</strong><button type="button" aria-label="关闭引用预览" @click="close"><X :size="18" /></button></header>
      <img v-if="selected.preview && !failed.has(selected.key)" class="message-reference-full" :src="selected.preview" :alt="selected.label" @error="failed.add(selected.key)" />
      <pre v-else-if="selected.textContent" class="message-reference-text">{{ selected.textContent }}</pre>
      <div v-else class="message-reference-placeholder"><FileText :size="40" /><span>{{ selected.kind }}</span></div>
      <footer><span>{{ failed.has(selected.key) ? '预览暂不可用' : selected.kind }}</span><a v-if="selected.url" :href="selected.url" target="_blank" rel="noopener noreferrer">打开原文件 ↗</a></footer>
    </template>
  </dialog></Teleport>
</template>
<style scoped>
.user-message-content{font-size:14px;line-height:1.8;overflow-wrap:anywhere}.user-message-text{white-space:pre-wrap}
.message-skill-chip{display:inline;padding:3px 7px;margin:0 2px;border:1px solid var(--theme-border);border-radius:7px;background:var(--theme-surface-subtle);color:var(--theme-accent-strong);font-size:13px;box-decoration-break:clone}
.message-reference-chip{display:inline-flex;position:relative;vertical-align:middle;width:46px;height:46px;margin:2px 4px 3px 0;padding:2px;border:1px solid var(--theme-border);border-radius:10px;background:var(--theme-surface-subtle);color:var(--theme-text-muted);cursor:var(--cursor-pointer);overflow:hidden}
.message-reference-chip img{width:100%;height:100%;object-fit:cover;border-radius:7px}.message-reference-chip:hover,.message-reference-chip:focus-visible{border-color:var(--theme-accent-strong);outline:2px solid color-mix(in srgb,var(--theme-accent-strong) 24%,transparent);outline-offset:2px}
.message-reference-badge{position:absolute;right:1px;bottom:1px;border-radius:4px;padding:0 3px;font-size:8px;line-height:14px;background:var(--theme-accent-strong);color:var(--theme-surface-raised)}
.message-reference-file{display:flex;width:100%;flex-direction:column;align-items:center;justify-content:center;gap:1px}.message-reference-file small{font-size:8px;line-height:11px;max-width:100%;overflow:hidden}
.message-reference-dialog{width:min(760px,calc(100vw - 40px));max-height:calc(100dvh - 48px);padding:18px;border:1px solid var(--theme-border);border-radius:20px;background:var(--theme-surface-raised);color:var(--theme-text);box-shadow:0 24px 80px #0006}.message-reference-dialog::backdrop{background:#0008;backdrop-filter:blur(4px)}
header,footer{display:flex;align-items:center;justify-content:space-between;gap:16px}header strong{font-size:14px;overflow-wrap:anywhere}header button{display:grid;place-items:center;flex-shrink:0;width:30px;height:30px;border:0;border-radius:50%;background:var(--theme-surface-subtle);color:inherit}footer{margin-top:14px;font-size:12px;color:var(--theme-text-muted)}footer a{color:var(--theme-accent-strong)}
.message-reference-full{display:block;margin:16px auto 0;max-width:100%;max-height:65dvh;object-fit:contain;border-radius:12px}.message-reference-placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;min-height:200px;color:var(--theme-text-muted)}
.message-reference-text{max-height:65dvh;overflow:auto;margin:16px 0 0;padding:14px;border-radius:10px;background:var(--theme-surface-subtle);font:inherit;font-size:13px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}
</style>
