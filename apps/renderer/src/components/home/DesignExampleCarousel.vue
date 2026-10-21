<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ArrowUpRight, ChevronLeft, ChevronRight } from 'lucide-vue-next';
import type { DesignExample } from '../../features/home/designExamples';
import { useMotionPolicy } from '../../features/motion/useMotion';

const props = defineProps<{ example: DesignExample; order: number; disabled?: boolean }>();
const emit = defineEmits<{ choose: [prompt: string] }>();
const card = ref<HTMLElement | null>(null);
const active = ref(0);
const hovered = ref(false), focused = ref(false), visible = ref(false);
const { enabled: motionEnabled } = useMotionPolicy();
const paused = ref(false);
const current = computed(() => props.example.slides[active.value]!);
let timer: ReturnType<typeof setInterval> | undefined;
let observer: IntersectionObserver | undefined;
let tiltFrame = 0;
// Vue Bits TiltedCard mapping, limited to 2 degrees and mouse hover for this workspace.
function tilt(event: PointerEvent) {
  if (!card.value || !motionEnabled.value || props.disabled || event.pointerType !== 'mouse') return;
  const element = card.value, rect = element.getBoundingClientRect();
  const x = Math.max(-1, Math.min(1, (event.clientX - rect.left) / rect.width * 2 - 1));
  const y = Math.max(-1, Math.min(1, (event.clientY - rect.top) / rect.height * 2 - 1));
  cancelAnimationFrame(tiltFrame);
  tiltFrame = requestAnimationFrame(() => { element.style.setProperty('--card-rotate-x', `${-y * 2}deg`); element.style.setProperty('--card-rotate-y', `${x * 2}deg`); });
}
function resetTilt() { cancelAnimationFrame(tiltFrame); card.value?.style.removeProperty('--card-rotate-x'); card.value?.style.removeProperty('--card-rotate-y'); }
watch(motionEnabled, value => { if (!value) resetTilt(); });
function move(index: number) { active.value = (index + props.example.slides.length) % props.example.slides.length; paused.value = true; }
function onFocusOut(event: FocusEvent) { focused.value = !!card.value?.contains(event.relatedTarget as Node | null); }
onMounted(() => {
  observer = new IntersectionObserver(([entry]) => { visible.value = entry?.isIntersecting ?? false; }, { threshold: .15 });
  if (card.value) observer.observe(card.value);
  timer = setInterval(() => {
    if (visible.value && !hovered.value && !focused.value && !paused.value && motionEnabled.value) active.value = (active.value + 1) % props.example.slides.length;
  }, 4800 + props.order * 700);
});
onUnmounted(() => { clearInterval(timer); observer?.disconnect(); resetTilt(); });
</script>

<template>
  <article ref="card" class="design-example" :class="{ 'motion-enabled': motionEnabled }" role="region" aria-roledescription="轮播图" :aria-label="`${example.category}示例`" @pointerenter="hovered = true" @pointermove="tilt" @pointerleave="hovered = false; resetTilt()" @focusin="focused = true" @focusout="onFocusOut" @keydown.left.prevent="move(active - 1)" @keydown.right.prevent="move(active + 1)">
    <div class="example-preview">
      <button type="button" :disabled="disabled" class="example-artwork" :aria-label="example.projectSlug ? `打开${example.title}项目：${current.title}` : example.demoId ? `开始${example.category}整套方案：${current.title}` : `使用${example.category}示例：${current.title}`" @click="emit('choose', current.prompt)">
        <span v-for="(slide, index) in example.slides" :key="slide.title" class="example-sprite" :class="{ active: active === index }" :style="{ backgroundImage: `url(${example.cover})` }" role="img" :aria-label="slide.alt" :aria-hidden="active !== index" />
        <span class="example-card-body">
          <strong>{{ example.title }}</strong>
          <span class="example-category">{{ example.category }} · 已保存成果</span>
          <span class="example-action">打开项目 <ArrowUpRight :size="14" /></span>
        </span>
      </button>
      <button v-if="example.slides.length > 1" type="button" class="example-arrow previous" :aria-label="`${example.category}上一张`" @click="move(active - 1)"><ChevronLeft :size="16" /></button>
      <button v-if="example.slides.length > 1" type="button" class="example-arrow next" :aria-label="`${example.category}下一张`" @click="move(active + 1)"><ChevronRight :size="16" /></button>
      <div v-if="example.slides.length > 1" class="example-dots" :aria-label="`${example.category}轮播分页`">
        <button v-for="(slide, index) in example.slides" :key="slide.title" type="button" :aria-label="`${example.category}第 ${index + 1} 张：${slide.title}`" :aria-pressed="active === index" @click="move(index)"><span /></button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.design-example { position:relative; min-width:0; contain:paint; border:1px solid color-mix(in srgb, var(--theme-border) 72%, transparent); border-radius:16px; overflow:hidden; background:var(--theme-bg); box-shadow:0 10px 30px #0000001f; transition:transform var(--ui-motion-standard) var(--ui-motion-ease), border-color var(--ui-motion-quick), box-shadow var(--ui-motion-standard); }
.design-example:hover, .design-example:focus-within { border-color:color-mix(in srgb, var(--theme-accent-strong) 46%, var(--theme-border)); box-shadow:0 15px 36px #00000032; }
.design-example.motion-enabled:focus-within { transform:translateY(-2px); }
@media(hover:hover) and (pointer:fine) { .design-example.motion-enabled:hover { transform:perspective(900px) translateY(-2px) rotateX(var(--card-rotate-x,0deg)) rotateY(var(--card-rotate-y,0deg)); } }
.design-example:not(.motion-enabled), .design-example:not(.motion-enabled) * { transition:none; }
.example-preview { position:relative; aspect-ratio:16/9; overflow:hidden; background:var(--theme-surface-subtle); }
.example-artwork { position:absolute; inset:0; display:block; width:100%; height:100%; padding:0; border:0; cursor:pointer; background:transparent; color:#fff; text-align:left; }
.example-sprite { position:absolute; inset:0; display:block; background-position:center; background-repeat:no-repeat; background-size:cover; opacity:0; transition:opacity .65s ease; pointer-events:none; }
.example-sprite.active { opacity:1; }
.example-card-body { position:absolute; right:0; bottom:0; left:0; display:grid; gap:5px; min-height:112px; padding:43px 14px 13px; opacity:0; transform:translate3d(0, 8px, 0); backface-visibility:hidden; pointer-events:none; isolation:isolate; transition:opacity var(--ui-motion-standard) var(--ui-motion-ease), transform var(--ui-motion-standard) var(--ui-motion-ease); }
.example-card-body::before { content:''; position:absolute; inset:0; z-index:-1; background:linear-gradient(to top, #0e0e0eb3 0%, #1717176b 48%, #1f1f1f24 76%, #1f1f1f00 100%); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); box-shadow:inset 0 -1px #ffffff12; -webkit-mask-image:linear-gradient(to top, #000 0%, #000 62%, transparent 100%); mask-image:linear-gradient(to top, #000 0%, #000 62%, transparent 100%); }
.example-card-body strong { overflow:hidden; color:#f9f9f9; font-size:14px; font-weight:620; line-height:1.45; text-overflow:ellipsis; text-shadow:0 1px 6px #0009; white-space:nowrap; }
.example-category { overflow:hidden; color:#dbdbdb; font-size:var(--ui-font-caption); line-height:1.45; text-overflow:ellipsis; text-shadow:0 1px 5px #0009; white-space:nowrap; }
.example-action { display:flex; align-items:center; gap:4px; color:#f1f1f1; font-size:var(--ui-font-caption); line-height:1.4; text-shadow:0 1px 5px #0009; }
.example-action svg { flex:0 0 auto; }
.design-example:is(:hover, :focus-within) .example-card-body { opacity:1; transform:translate3d(0, 0, 0); will-change:opacity, transform; }
.example-arrow { position:absolute; top:50%; transform:translateY(-50%); display:grid; place-items:center; width:27px; height:30px; padding:0; border:1px solid #ffffff40; border-radius:8px; background:#1d1d1d85; color:#fff; opacity:0; transition:opacity .2s; cursor:pointer; }
.previous { left:8px; } .next { right:8px; }
.design-example:hover .example-arrow, .design-example:focus-within .example-arrow { opacity:1; }
.example-dots { position:absolute; bottom:8px; left:50%; transform:translateX(-50%); display:flex; padding:0 5px; border-radius:20px; background:#1d1d1d75; backdrop-filter:blur(6px); }
.example-dots button { display:grid; place-items:center; width:20px; height:24px; padding:0; border:0; background:transparent; cursor:pointer; }
.example-dots span { display:block; width:5px; height:5px; border-radius:6px; background:#ffffff70; transition:width .2s, background .2s; }
.example-dots button[aria-pressed="true"] span { width:12px; background:#fff; }
button:focus-visible { outline:2px solid var(--theme-accent-strong); outline-offset:-3px; }
@media(hover:none) { .example-arrow { opacity:1; } .example-card-body { opacity:1; transform:none; } }
@media(prefers-reduced-motion:reduce) { .design-example, .example-sprite, .example-card-body, .example-dots span { transition:none; } .design-example:hover, .design-example:focus-within { transform:none; } }
</style>
