<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Download, Maximize2, Minus, Plus, X } from 'lucide-vue-next';

const props = defineProps<{ src: string; title: string; downloading?: boolean; downloadDisabled?: boolean }>();
const emit = defineEmits<{ close: []; download: [] }>();
const dialog = ref<HTMLDialogElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const imageSize = ref({ width: 0, height: 0 });
const stageSize = ref({ width: 1, height: 1 });
const zoom = ref(1);
const offset = ref({ x: 0, y: 0 });
const fitting = ref(true);
const failed = ref(false);
const dragging = ref(false);
const loaded = computed(() => imageSize.value.width > 0 && !failed.value);
const fitZoom = computed(() => Math.min(1, Math.max(1, stageSize.value.width - 48) / (imageSize.value.width || 1), Math.max(1, stageSize.value.height - 48) / (imageSize.value.height || 1)));
const minZoom = computed(() => Math.min(.1, fitZoom.value));
const imageStyle = computed(() => ({ width: `${imageSize.value.width}px`, height: `${imageSize.value.height}px`,
  transform: `translate(-50%, -50%) translate(${offset.value.x}px, ${offset.value.y}px) scale(${zoom.value})`, visibility: loaded.value ? 'visible' as const : 'hidden' as const }));
let observer: ResizeObserver | undefined;
let previousFocus: HTMLElement | null = null;
let pan: { id: number; x: number; y: number; offset: { x: number; y: number } } | undefined;

function constrainOffset() {
  const x = Math.max(0, (imageSize.value.width * zoom.value - stageSize.value.width) / 2 + 24);
  const y = Math.max(0, (imageSize.value.height * zoom.value - stageSize.value.height) / 2 + 24);
  offset.value = { x: Math.max(-x, Math.min(x, offset.value.x)), y: Math.max(-y, Math.min(y, offset.value.y)) };
}
function fitImage() { fitting.value = true; zoom.value = fitZoom.value; offset.value = { x: 0, y: 0 }; }
function setZoom(value: number, anchor = { x: 0, y: 0 }) {
  if (!loaded.value) return;
  fitting.value = false;
  const next = Math.min(8, Math.max(minZoom.value, value));
  const factor = next / zoom.value;
  offset.value = { x: anchor.x - (anchor.x - offset.value.x) * factor, y: anchor.y - (anchor.y - offset.value.y) * factor };
  zoom.value = next;
  constrainOffset();
}
function imageLoaded(event: Event) {
  const image = event.target as HTMLImageElement;
  imageSize.value = { width: image.naturalWidth, height: image.naturalHeight };
  failed.value = false;
  fitImage();
}
function wheelZoom(event: WheelEvent) {
  const bounds = stage.value?.getBoundingClientRect();
  if (!bounds) return;
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1);
  setZoom(zoom.value * Math.exp(-Math.max(-600, Math.min(600, delta)) * .002), { x: event.clientX - bounds.left - bounds.width / 2, y: event.clientY - bounds.top - bounds.height / 2 });
}
function startPan(event: PointerEvent) {
  if (event.button !== 0 || !loaded.value) return;
  event.preventDefault();
  pan = { id: event.pointerId, x: event.clientX, y: event.clientY, offset: { ...offset.value } };
  stage.value?.setPointerCapture(event.pointerId);
  dragging.value = true;
}
function movePan(event: PointerEvent) {
  if (!pan || pan.id !== event.pointerId) return;
  offset.value = { x: pan.offset.x + event.clientX - pan.x, y: pan.offset.y + event.clientY - pan.y };
  constrainOffset();
}
function endPan() {
  const previous = pan; pan = undefined; dragging.value = false;
  if (previous && stage.value?.hasPointerCapture(previous.id)) stage.value.releasePointerCapture(previous.id);
}
function keydown(event: KeyboardEvent) {
  if (['+', '=', '-', '0', 'f', 'F'].includes(event.key)) {
    event.preventDefault();
    if (event.key === '0') setZoom(1);
    else if (event.key.toLowerCase() === 'f') fitImage();
    else setZoom(zoom.value * (event.key === '-' ? 1 / 1.25 : 1.25));
  }
}
watch(() => props.src, () => { failed.value = false; imageSize.value = { width: 0, height: 0 }; fitImage(); });
onMounted(() => {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  dialog.value?.showModal();
  observer = new ResizeObserver(() => {
    if (!stage.value) return;
    stageSize.value = { width: stage.value.clientWidth, height: stage.value.clientHeight };
    if (fitting.value) fitImage(); else constrainOffset();
  });
  if (stage.value) observer.observe(stage.value);
});
onBeforeUnmount(() => {
  endPan(); observer?.disconnect(); dialog.value?.close();
  if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
});
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="canvas-image-preview" aria-label="图像大图预览" @cancel.prevent="emit('close')" @keydown.stop="keydown" @click.stop @pointerdown.stop @dblclick.stop>
      <header>
        <div class="image-preview-heading"><strong :title="title">{{ title }}</strong><small v-if="loaded">{{ imageSize.width }} × {{ imageSize.height }} 像素</small></div>
        <div class="image-preview-tools" role="group" aria-label="图像预览工具">
          <button type="button" aria-label="缩小图像" :disabled="!loaded || zoom <= minZoom" @click="setZoom(zoom / 1.25)"><Minus :size="17" /></button>
          <output aria-live="polite" aria-label="图像缩放比例">{{ Math.round(zoom * 100) }}%</output>
          <button type="button" aria-label="放大图像" :disabled="!loaded || zoom >= 8" @click="setZoom(zoom * 1.25)"><Plus :size="17" /></button>
          <button type="button" :disabled="!loaded" @click="fitImage"><Maximize2 :size="15" />适应窗口</button>
          <button type="button" :disabled="!loaded" @click="setZoom(1)">原始尺寸</button>
          <button type="button" :disabled="downloadDisabled || downloading" @click="emit('download')"><Download :size="15" />{{ downloading ? '保存中…' : '保存原图' }}</button>
          <button type="button" class="image-preview-close" aria-label="关闭图像预览" autofocus @click="emit('close')"><X :size="20" /></button>
        </div>
      </header>
      <div ref="stage" class="image-preview-stage" :class="{ dragging }" @wheel.prevent="wheelZoom" @pointerdown="startPan" @pointermove="movePan" @pointerup="endPan" @pointercancel="endPan" @lostpointercapture="endPan" @dblclick.prevent="fitting ? setZoom(1) : fitImage()">
        <img :key="src" :src="src" :alt="title" :style="imageStyle" draggable="false" @load="imageLoaded" @error="failed = true" />
        <p v-if="failed" role="alert">图片暂时无法加载，请关闭预览后重试。</p>
        <p v-else-if="!loaded" role="status">正在加载原图…</p>
      </div>
      <footer>滚轮缩放 · 拖动查看细节 · 双击切换适应窗口 / 原始尺寸 · Esc 关闭</footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.canvas-image-preview { position:fixed; inset:0; width:100vw; height:100dvh; max-width:none; max-height:none; margin:0; padding:0; border:0; background:var(--theme-bg, #111512); color:var(--theme-text); overflow:hidden; }
.canvas-image-preview[open] { display:flex; flex-direction:column; }
.canvas-image-preview::backdrop { background:#000b; }
.canvas-image-preview > header { position:relative; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; padding:14px 20px; border-bottom:1px solid var(--theme-border); background:var(--theme-surface-raised); }
.image-preview-heading { display:grid; gap:4px; min-width:0; flex:1; }
.image-preview-heading strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; font-weight:500; }
.image-preview-heading small { color:var(--theme-text-muted); font-size:11px; }
.image-preview-tools { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.image-preview-tools button { display:inline-flex; align-items:center; justify-content:center; gap:5px; min-width:34px; min-height:34px; padding:6px 9px; border:1px solid var(--theme-border); border-radius:8px; background:var(--theme-surface); color:var(--theme-text); font:inherit; font-size:12px; }
.image-preview-tools button:hover:not(:disabled) { background:var(--theme-accent-soft); }
.image-preview-tools button:disabled { opacity:.4; }
.image-preview-tools button:focus-visible { outline:2px solid var(--theme-accent-strong); outline-offset:2px; }
.image-preview-tools output { min-width:45px; text-align:center; font-size:12px; font-variant-numeric:tabular-nums; }
.image-preview-stage { position:relative; flex:1; min-height:0; overflow:hidden; display:grid; place-items:center; touch-action:none; cursor:grab; background-color:var(--theme-surface-subtle); background-image:conic-gradient(#80808012 25%,transparent 0 50%,#80808012 0 75%,transparent 0); background-size:24px 24px; }
.image-preview-stage.dragging { cursor:grabbing; }
.image-preview-stage img { position:absolute; top:50%; left:50%; max-width:none; max-height:none; transform-origin:center; user-select:none; }
.image-preview-stage p { color:var(--theme-text-muted); font-size:13px; }
.canvas-image-preview > footer { padding:10px 16px; text-align:center; font-size:11px; line-height:1.5; color:var(--theme-text-muted); background:var(--theme-surface-raised); }
@media (max-width:700px) { .canvas-image-preview > header { padding:10px 12px; } .image-preview-heading { flex-basis:100%; padding-right:44px; } .image-preview-tools { gap:4px; } .image-preview-tools button { padding:6px; font-size:11px; } .image-preview-tools .image-preview-close { position:absolute; top:10px; right:12px; } }
</style>
