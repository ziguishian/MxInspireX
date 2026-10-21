<script setup lang="ts">
// Adapted from Vue Bits CountUp: time-based, bounded duration, exact accessible value.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useMotionPolicy } from '../../features/motion/useMotion';
const props = withDefaults(defineProps<{ to: number; format?: (value: number) => string; duration?: number }>(), { duration: 420 });
const target = computed(() => Math.max(0, Number.isFinite(props.to) ? props.to : 0));
const formatValue = (value: number) => props.format ? props.format(value) : Math.round(value).toLocaleString('zh-CN');
const exactLabel = computed(() => formatValue(target.value));
const root = ref<HTMLElement | null>(null);
const shown = ref(target.value);
const { enabled } = useMotionPolicy();
let frame = 0, played = false, inView = false;
let observer: IntersectionObserver | undefined;
function finish() { cancelAnimationFrame(frame); frame = 0; shown.value = target.value; }
function start() {
  finish();
  if (!inView || played || !target.value || !enabled.value) return;
  played = true;
  const started = performance.now(), end = target.value;
  shown.value = 0;
  const tick = (now: number) => {
    const t = Math.max(0, Math.min(1, (now - started) / Math.max(1, props.duration)));
    shown.value = end * (1 - (1 - t) ** 3);
    if (t < 1) frame = requestAnimationFrame(tick);
    else finish();
  };
  frame = requestAnimationFrame(tick);
}
watch(target, start);
watch(enabled, value => { if (!value) finish(); });
onMounted(() => {
  observer = new IntersectionObserver(([entry]) => { inView = Boolean(entry?.isIntersecting); if (inView) start(); else finish(); });
  if (root.value) observer.observe(root.value);
});
onUnmounted(() => { finish(); observer?.disconnect(); });
</script>
<template><span ref="root" class="mx-count"><span class="mx-count-width" aria-hidden="true">{{ exactLabel }}</span><span class="mx-count-value" aria-hidden="true">{{ formatValue(shown) }}</span><span class="mx-count-accessible">{{ exactLabel }}</span></span></template>
<style scoped>
.mx-count { display:inline-grid; position:relative; font-variant-numeric:tabular-nums; }
.mx-count-width, .mx-count-value { grid-area:1 / 1; text-align:end; }
.mx-count-width { visibility:hidden; }
.mx-count-accessible { position:absolute; width:1px; height:1px; padding:0; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
</style>
