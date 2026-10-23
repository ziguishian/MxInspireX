<script setup lang="ts">
import { ArrowUp } from 'lucide-vue-next';
import { onBeforeUnmount, onMounted, ref } from 'vue';
import PageHeader from './PageHeader.vue';
import SearchField from './SearchField.vue';

defineProps<{ eyebrow: string; title: string; description: string; searchLabel: string; searchPlaceholder?: string }>();
const search = defineModel<string>('search', { required: true });
const root = ref<HTMLElement | null>(null);
const showBackToTop = ref(false);
let scrollParent: HTMLElement | null = null;

function scrollPosition() {
  return Math.max(scrollParent?.scrollTop || 0, window.scrollY, document.scrollingElement?.scrollTop || 0);
}

function updateBackToTop() { showBackToTop.value = scrollPosition() >= 720; }

function backToTop() {
  const behavior: ScrollBehavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  scrollParent?.scrollTo({ top: 0, behavior });
  window.scrollTo({ top: 0, behavior });
}

onMounted(() => {
  scrollParent = root.value?.closest('.canvas-panel') || null;
  scrollParent?.addEventListener('scroll', updateBackToTop, { passive: true });
  window.addEventListener('scroll', updateBackToTop, { passive: true });
  updateBackToTop();
});
onBeforeUnmount(() => {
  scrollParent?.removeEventListener('scroll', updateBackToTop);
  window.removeEventListener('scroll', updateBackToTop);
});
</script>

<template>
  <section ref="root" class="collection-page">
    <PageHeader :eyebrow="eyebrow" :title="title" :description="description" />
    <div class="collection-actions">
      <div class="collection-action-buttons"><slot name="actions" /></div>
      <div class="collection-meta"><slot name="meta" /></div>
    </div>
    <div class="collection-toolbar">
      <SearchField v-model="search" :label="searchLabel" :placeholder="searchPlaceholder" />
      <div class="collection-filters"><slot name="filters" /></div>
    </div>
    <slot />
    <button v-show="showBackToTop" type="button" class="library-back-to-top" aria-label="回到顶部" title="回到顶部" @click="backToTop"><ArrowUp :size="19" /></button>
  </section>
</template>

<style scoped>
/* All three libraries share the reference library's width and gutters. */
.collection-page {
  width: 100%; max-width: 1600px; min-width: 0; margin: 0 auto;
  padding: 16px clamp(20px, 4vw, 64px) 34px; color: var(--theme-text);
  --library-preview-ratio: 16 / 9;
}
.collection-page :deep(.page-heading) { margin-bottom: 24px; }
.collection-actions, .collection-action-buttons, .collection-meta, .collection-toolbar, .collection-filters {
  display: flex; align-items: center; gap: 12px;
}
.collection-actions { min-height: 40px; flex-wrap: wrap; margin-bottom: 20px; }
.collection-action-buttons, .collection-meta { flex-wrap: wrap; }
.collection-meta { margin-left: auto; color: var(--theme-text-muted); font-size: var(--ui-font-caption); line-height: 20px; }
.collection-toolbar { flex-wrap: wrap; margin-bottom: 20px; scroll-margin-top: 64px; }
.collection-filters { margin-left: auto; flex-wrap: wrap; }
.collection-toolbar :deep(.project-search) {
  flex: 0 1 48%; min-width: 200px; height: var(--ui-control-height); gap: 8px;
  border: 1px solid var(--theme-border); border-radius: var(--ui-radius-control); padding: 0 12px;
  background: var(--theme-surface); color: var(--theme-text-muted);
}
.collection-toolbar :deep(.project-search input) {
  min-width: 0; width: 100%; height: 100%; padding: 0; border: 0; border-radius: 0;
  background: transparent; color: var(--theme-text); font-size: var(--ui-font-control); line-height: 20px;
}
.collection-toolbar :deep(.project-search svg) { width: 16px; height: 16px; flex-shrink: 0; }
.collection-toolbar :deep(.project-search:focus-within) { outline: 2px solid var(--theme-accent-strong); outline-offset: 3px; }
/* The search container provides the single visible keyboard-focus ring. */
.collection-toolbar :deep(.project-search input:focus-visible) { outline: none; }
.collection-filters :deep(select) {
  min-width: 120px; max-width: 100%; height: var(--ui-control-height); padding: 0 12px;
  border: 1px solid var(--theme-border); border-radius: var(--ui-radius-control);
  background: var(--theme-surface); color: var(--theme-text); font-size: var(--ui-font-control); line-height: 20px;
}
.collection-actions :deep(.primary-button), .collection-actions :deep(.ghost-button), .collection-filters :deep(.ghost-button) {
  display: inline-flex; justify-content: center; align-items: center; gap: 8px;
  height: var(--ui-control-height); padding: 0 14px; border-radius: var(--ui-radius-control); font-size: var(--ui-font-control);
  line-height: 20px; white-space: nowrap; text-decoration: none;
}
.collection-actions :deep(svg), .collection-filters :deep(svg) { flex-shrink: 0; }
.collection-meta :deep(a) { display: inline-flex; align-items: center; gap: 5px; color: inherit; text-decoration: none; }
.collection-meta :deep(a:hover) { color: var(--theme-accent-strong); }
.collection-actions :deep(:is(button, a):focus-visible), .collection-filters :deep(:is(button, select):focus-visible) {
  outline: 2px solid var(--theme-accent-strong); outline-offset: 3px;
}
.collection-page :deep(.library-grid) { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.library-back-to-top {
  position: fixed; right: var(--page-floating-action-right, 28px); bottom: 74px; z-index: 70;
  display: grid; place-items: center; width: var(--corner-button-size, 42px); height: var(--corner-button-size, 42px); padding: 0;
  border: 1px solid color-mix(in srgb, var(--theme-accent-strong) 38%, var(--theme-border));
  border-radius: 50%; background: color-mix(in srgb, var(--theme-surface) 90%, transparent);
  color: var(--theme-accent-strong); box-shadow: 0 10px 28px #0007;
  cursor: pointer; transform: translateZ(0); transition: transform .16s ease, border-color .16s ease, background .16s ease;
}
.library-back-to-top:hover { transform: translate3d(0, -2px, 0); border-color: var(--theme-accent-strong); background: var(--theme-surface); }
.library-back-to-top:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 3px; }
@media (max-width: 920px) {
  /* The shell already reserves the navigation rail; keep page gutters symmetric. */
  .collection-page { padding-left: 16px; padding-right: 16px; }
  .collection-meta { width: 100%; margin-left: 0; }
}
@media (max-width: 720px) {
  .collection-toolbar :deep(.project-search) { flex-basis: 100%; min-width: 0; height: var(--ui-control-height); border-radius: var(--ui-radius-control); }
  .collection-filters { margin-left: 0; width: 100%; }
  .collection-filters :deep(select) { flex: 1; min-width: 0; height: var(--ui-control-height); border-radius: var(--ui-radius-control); }
  .collection-meta { width: 100%; margin-left: 0; }
  .collection-page :deep(.library-grid) { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
}
@media (max-width: 480px) {
  .collection-page :deep(.page-heading .muted) { min-height: 40px; }
  .collection-filters :deep(select) { min-width: 120px; height: var(--ui-control-height); border-radius: var(--ui-radius-control); }
  .collection-page :deep(.library-grid) { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) { .library-back-to-top { transition: none; } }
</style>
