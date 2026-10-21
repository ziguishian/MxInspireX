<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue';

const props = withDefaults(defineProps<{ anchor: HTMLElement | null; topInset?: number; label?: string }>(), { topInset: 12, label: '选择模型' });
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement | null>(null);
const content = ref<HTMLElement | null>(null);
const placement = ref<'top' | 'bottom'>('bottom');
let frame = 0;
let observer: ResizeObserver | undefined;

function reposition() {
  frame = 0;
  const target = props.anchor;
  const popup = panel.value;
  const body = content.value;
  if (!target?.isConnected || !popup || !body) return;

  const viewport = window.visualViewport;
  const leftEdge = (viewport?.offsetLeft ?? 0) + 12;
  const rightEdge = (viewport?.offsetLeft ?? 0) + (viewport?.width ?? window.innerWidth) - 12;
  const topEdge = Math.max((viewport?.offsetTop ?? 0) + 12, props.topInset);
  const bottomEdge = (viewport?.offsetTop ?? 0) + (viewport?.height ?? window.innerHeight) - 12;
  const anchor = target.getBoundingClientRect();
  if (anchor.bottom <= topEdge || anchor.top >= bottomEdge || anchor.right <= leftEdge || anchor.left >= rightEdge) {
    emit('close');
    return;
  }

  const width = Math.min(286, Math.max(0, rightEdge - leftEdge));
  popup.style.width = `${width}px`;
  // Measure unconstrained content, so a previously shortened menu can expand again.
  const style = getComputedStyle(popup);
  const height = body.getBoundingClientRect().height + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
    + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
  const above = Math.max(0, anchor.top - 8 - topEdge);
  const below = Math.max(0, bottomEdge - anchor.bottom - 8);
  placement.value = below >= height ? 'bottom' : above >= height ? 'top' : below >= above ? 'bottom' : 'top';
  const available = placement.value === 'bottom' ? below : above;
  const shownHeight = Math.min(height, available);
  const top = placement.value === 'bottom' ? anchor.bottom + 8 : anchor.top - 8 - shownHeight;
  popup.style.left = `${Math.max(leftEdge, Math.min(anchor.left, rightEdge - width))}px`;
  popup.style.top = `${Math.max(topEdge, top)}px`;
  popup.style.maxHeight = `${available}px`;
  const firstPosition = popup.style.visibility !== 'visible';
  popup.style.visibility = 'visible';
  if (firstPosition) popup.focus({ preventScroll: true });
}

function schedulePosition(event?: Event) {
  // Scrolling the menu's own list doesn't move its anchor.
  if (event?.type === 'scroll' && event.target instanceof Node && panel.value?.contains(event.target)) return;
  if (!frame) frame = requestAnimationFrame(reposition);
}

function observeAnchor() {
  observer?.disconnect();
  if (content.value) observer?.observe(content.value);
  // Composer growth and workspace layout changes can move the trigger without resizing it.
  for (let element = props.anchor; element; element = element.parentElement) observer?.observe(element);
  schedulePosition();
}

function closeFromKeyboard() {
  emit('close');
  props.anchor?.focus({ preventScroll: true });
}

watch(() => props.anchor, async () => { await nextTick(); observeAnchor(); });
watch(() => props.topInset, () => schedulePosition());
onMounted(() => {
  observer = new ResizeObserver(() => schedulePosition());
  observeAnchor();
  window.addEventListener('resize', schedulePosition);
  window.addEventListener('scroll', schedulePosition, true);
  window.visualViewport?.addEventListener('resize', schedulePosition);
  window.visualViewport?.addEventListener('scroll', schedulePosition);
});
onUnmounted(() => {
  cancelAnimationFrame(frame);
  observer?.disconnect();
  window.removeEventListener('resize', schedulePosition);
  window.removeEventListener('scroll', schedulePosition, true);
  window.visualViewport?.removeEventListener('resize', schedulePosition);
  window.visualViewport?.removeEventListener('scroll', schedulePosition);
});
</script>

<template>
  <Teleport to="body">
    <div ref="panel" class="composer-popover agent-popover anchored-popover" :data-placement="placement" role="dialog" :aria-label="label" tabindex="-1"
      @keydown.esc.stop.prevent="closeFromKeyboard">
      <div ref="content" class="anchored-popover-content"><slot /></div>
    </div>
  </Teleport>
</template>

<style scoped>
.anchored-popover { position:fixed; inset:auto; z-index:190; display:block; box-sizing:border-box; visibility:hidden; overflow-x:hidden; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; scrollbar-color:var(--theme-border-strong) transparent; -webkit-app-region:no-drag; }
.anchored-popover-content { display:grid; gap:4px; }
</style>
