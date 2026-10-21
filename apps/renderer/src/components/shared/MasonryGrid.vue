<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useMotion } from '../../features/motion/useMotion';

const root = ref<HTMLElement | null>(null);
let itemObserver: ResizeObserver | undefined;
let gridObserver: ResizeObserver | undefined;
let mutationObserver: MutationObserver | undefined;
let frame = 0;
const observed = new Set<HTMLElement>();
const positions = new Map<HTMLElement, { x:number; y:number }>();
const motion = useMotion();

function layoutItem(item: HTMLElement) {
  const grid = root.value;
  if (!grid) return;
  const styles = getComputedStyle(grid);
  const row = Number.parseFloat(styles.gridAutoRows) || 1;
  const gap = Number.parseFloat(styles.rowGap) || 0;
  if (item.style.alignSelf !== 'start') item.style.alignSelf = 'start';
  const rowEnd = `span ${Math.max(1, Math.ceil((item.offsetHeight + gap) / (row + gap)))}`;
  if (item.style.gridRowEnd !== rowEnd) item.style.gridRowEnd = rowEnd;
}

function scheduleLayout() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => {
    const grid = root.value;
    if (!grid) return;
    const children = Array.from(grid.children).filter((item): item is HTMLElement => item instanceof HTMLElement);
    for (const item of observed) {
      if (!children.includes(item)) { itemObserver?.unobserve(item); observed.delete(item); positions.delete(item); }
    }
    for (const item of children) {
      if (!observed.has(item)) { observed.add(item); itemObserver?.observe(item); }
      layoutItem(item);
    }
    // Vue Bits Masonry's reposition/reveal treatment, retaining our CSS grid and pagination.
    // Layout offsets exclude animation transforms and viewport scrolling.
    children.forEach((item, index) => {
      const before = positions.get(item), after = { x:item.offsetLeft, y:item.offsetTop };
      positions.set(item, after);
      const bounds = item.getBoundingClientRect();
      if (bounds.bottom < 0 || bounds.top > window.innerHeight) return;
      if (!before) {
        motion.play(item, [{ opacity:.3, translate:'0 10px' }, { opacity:1, translate:'0 0' }], { delay:Math.min(index, 5) * 18 });
      } else {
        const x = before.x - after.x, y = before.y - after.y;
        if (Math.abs(x) > 1 || Math.abs(y) > 1) motion.play(item, [{ translate:`${x}px ${y}px` }, { translate:'0 0' }]);
      }
    });
  });
}

onMounted(async () => {
  itemObserver = new ResizeObserver(scheduleLayout);
  gridObserver = new ResizeObserver(scheduleLayout);
  mutationObserver = new MutationObserver(scheduleLayout);
  if (root.value) {
    gridObserver.observe(root.value);
    mutationObserver.observe(root.value, { childList: true });
  }
  await nextTick();
  scheduleLayout();
});

onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
  itemObserver?.disconnect();
  gridObserver?.disconnect();
  mutationObserver?.disconnect();
  observed.clear();
  positions.clear();
});
</script>

<template><div ref="root" class="masonry-grid"><slot /></div></template>

<style scoped>
.masonry-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-auto-flow: dense;
  grid-auto-rows: 1px;
  column-gap: 20px;
  row-gap: 16px;
  align-items: start;
}
@media (max-width: 1080px) { .masonry-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 720px) { .masonry-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; row-gap: 12px; } }
@media (max-width: 480px) { .masonry-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
