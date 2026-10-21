<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { Check, ImageOff, RotateCcw, X } from 'lucide-vue-next';
import { stylePresets } from '../../features/composer/stylePresets';

const open = defineModel<boolean>('open', { required: true });
const props = defineProps<{ selected: string }>();
const emit = defineEmits<{ select: [style: string] }>();
// Resolve against the document, never the bundled stylesheet's assets directory.
const spriteUrl = new URL(`${import.meta.env.BASE_URL}assets/style-presets-v1.png`, document.baseURI).href;
const dialog = ref<HTMLDialogElement | null>(null);
const previewStates = ref<Record<string, 'loaded' | 'error'>>({});
const attempt = ref(0);
const previewUrl = computed(() => attempt.value ? `${spriteUrl}?retry=${attempt.value}` : spriteUrl);
const hasPreviewError = computed(() => Object.values(previewStates.value).includes('error'));
const selectedLabel = computed(() => stylePresets.find(preset => preset.key === props.selected)?.label);

watch(open, async value => {
  await nextTick();
  if (value && !dialog.value?.open) dialog.value?.showModal();
  else if (!value) dialog.value?.close();
}, { immediate: true });

function select(style: string) {
  emit('select', style);
  open.value = false;
}

function retryPreviews() {
  previewStates.value = {};
  attempt.value += 1;
}

function handleClose() {
  // A queued close event must not dismiss a dialog that has already reopened.
  if (!dialog.value?.open) open.value = false;
}
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="style-picker-dialog" aria-labelledby="style-picker-title" aria-describedby="style-picker-description"
      @cancel.prevent="open = false" @close="handleClose" @click.self="open = false">
      <header>
        <div>
          <span class="style-picker-eyebrow">VISUAL DIRECTION</span>
          <h2 id="style-picker-title">选择你喜欢的视觉风格</h2>
          <p id="style-picker-description">同一组器物，六种视觉表达。点击参考图，为接下来的创作选择方向。</p>
        </div>
        <button type="button" class="style-picker-close" aria-label="关闭风格选择" @click="open = false"><X :size="20" /></button>
      </header>

      <div v-if="open" class="style-picker-grid" role="group" aria-label="视觉风格">
        <button v-for="preset in stylePresets" :key="preset.key" type="button" class="style-preview-card"
          :class="{ selected: selected === preset.key }" :aria-pressed="selected === preset.key" @click="select(preset.key)">
          <span class="style-preview-image" :class="{ 'is-loading': !previewStates[preset.key] }" :aria-busy="!previewStates[preset.key]">
            <img :key="attempt" :src="previewUrl" :alt="`${preset.label}风格参考图`" draggable="false" decoding="async"
              :class="{ 'is-loaded': previewStates[preset.key] === 'loaded' }"
              :style="{ left: `${-preset.column * 100}%`, top: `${-preset.row * 100}%` }"
              @load="previewStates[preset.key] = 'loaded'" @error="previewStates[preset.key] = 'error'" />
            <span v-if="previewStates[preset.key] === 'error'" class="style-preview-placeholder"><ImageOff :size="26" /><span>参考图加载失败</span></span>
            <span v-else-if="!previewStates[preset.key]" class="style-preview-placeholder">正在加载参考图…</span>
            <span v-if="selected === preset.key" class="style-selected" aria-label="已选择"><Check :size="15" :stroke-width="2.5" /></span>
          </span>
          <span class="style-preview-caption"><strong>{{ preset.label }}</strong><small>{{ preset.detail }}</small></span>
        </button>
      </div>

      <div v-if="hasPreviewError" class="style-preview-error" role="status">
        <span>部分参考图未能加载，请重试。</span>
        <button type="button" @click="retryPreviews"><RotateCcw :size="14" />重新加载</button>
      </div>
      <footer><span v-if="selectedLabel">当前：<strong>{{ selectedLabel }}</strong></span><span>参考图仅作风格引导，可随时更换。</span></footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.style-picker-dialog { box-sizing:border-box; width:min(800px, calc(100vw - 32px)); max-height:calc(100dvh - 40px); padding:24px; border:1px solid var(--theme-border); border-radius:var(--ui-radius-dialog); background:var(--theme-surface-raised); color:var(--theme-text); box-shadow:0 28px 100px #0004; overflow-y:auto; }
.style-picker-dialog::backdrop { background:#0d0d0d66; backdrop-filter:blur(7px); }
header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; margin-bottom:22px; }
.style-picker-eyebrow { font-size:var(--ui-font-caption); letter-spacing:.15em; color:var(--theme-text-subtle); }
h2 { font-size:var(--ui-font-section); margin:8px 0; line-height:var(--ui-line-heading); }
header p, footer { color:var(--theme-text-muted); font-size:var(--ui-font-caption); line-height:1.7; margin:0; }
.style-picker-close { display:grid; place-items:center; flex:0 0 32px; width:32px; height:32px; border:0; border-radius:50%; color:var(--theme-text-muted); background:transparent; cursor:pointer; }
.style-picker-close:hover { background:var(--theme-surface-hover); }
.style-picker-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }
.style-preview-card { display:flex; flex-direction:column; min-width:0; padding:5px; border:1px solid var(--theme-border); border-radius:17px; background:var(--theme-surface); color:var(--theme-text); text-align:left; cursor:pointer; transition:border-color .18s, transform .18s, background .18s; }
.style-preview-card:hover { transform:translateY(-2px); border-color:var(--theme-border-strong); background:var(--theme-surface-hover); }
.style-preview-card.selected { border-color:var(--theme-accent-strong); background:var(--theme-accent-soft); }
.style-preview-card:focus-visible { outline:2px solid var(--theme-accent-strong); outline-offset:3px; }
.style-preview-image { position:relative; isolation:isolate; display:block; width:100%; aspect-ratio:1; border-radius:12px; overflow:hidden; background:var(--theme-surface-hover); }
.style-preview-image img { position:absolute; display:block; width:300%; height:200%; max-width:none; max-height:none; object-fit:fill; opacity:0; transition:opacity .2s; pointer-events:none; user-select:none; }
.style-preview-image img.is-loaded { opacity:1; }
.style-preview-placeholder { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:12px; font-size:var(--ui-font-caption); color:var(--theme-text-subtle); }
.style-preview-image.is-loading::before { content:""; position:absolute; inset:0; background:linear-gradient(100deg,transparent 20%,var(--theme-accent-soft) 50%,transparent 80%); animation:style-preview-loading 1.6s ease-in-out infinite; }
.style-preview-caption { display:flex; flex-direction:column; gap:5px; padding:12px 8px 10px; }
.style-preview-caption strong { font-size:var(--ui-font-body); font-weight:600; }
.style-preview-caption small { font-size:var(--ui-font-caption); line-height:1.6; color:var(--theme-text-muted); }
.style-selected { position:absolute; right:10px; top:10px; display:grid; place-items:center; width:26px; height:26px; border:2px solid var(--theme-surface-raised); border-radius:50%; background:var(--theme-accent-strong); color:var(--theme-surface-raised); box-shadow:0 2px 8px #0002; }
.style-preview-error { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-top:18px; font-size:var(--ui-font-caption); color:var(--theme-text-muted); }
.style-preview-error button { display:flex; align-items:center; gap:6px; padding:7px 11px; border:1px solid var(--theme-border); border-radius:20px; color:var(--theme-text); background:var(--theme-surface-hover); cursor:pointer; }
footer { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-top:20px; padding-top:16px; border-top:1px solid var(--theme-border); }
footer strong { color:var(--theme-text); font-weight:500; }
@keyframes style-preview-loading { from { transform:translateX(-100%); } to { transform:translateX(100%); } }
@media(max-width:580px) { .style-picker-dialog { padding:18px; border-radius:var(--ui-radius-dialog); } .style-picker-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; } h2 { font-size:var(--ui-font-section); line-height:var(--ui-line-heading); } .style-preview-caption { padding:10px 5px 8px; } }
@media(prefers-reduced-motion:reduce) { .style-preview-card, .style-preview-image img { transition:none; } .style-preview-image.is-loading::before { animation:none; } }
</style>
