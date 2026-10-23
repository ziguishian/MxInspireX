<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Upload } from 'lucide-vue-next';
import DesignExampleCarousel from '../components/home/DesignExampleCarousel.vue';
import { designExamples } from '../features/home/designExamples';
import { timedLumoMessage, timedLumoStorageKey, type LumoReaction } from '../features/home/lumoTimeMessages';
import { homeServices } from '../features/pageServices';
import { mascotSpriteStyle, useMascotSettings } from '../features/home/mascot';
import BlurText from '../components/motion/BlurText.vue';
import { claimEntrance, motionTiming, useMotion } from '../features/motion/useMotion';
const page = ref<HTMLElement | null>(null);
const entrance = useMotion();
onMounted(() => {
  if (!claimEntrance('home-content')) return;
  page.value?.querySelectorAll('.intake-heading p, .home-composer-stage, .home-upload-hint').forEach(element => {
    entrance.play(element, [{ opacity:.55, translate:'0 6px' }, { opacity:1, translate:'0 0' }], { duration:motionTiming.entrance });
  });
});
const mascot = useMascotSettings();
const customMascotStyle = computed(() => mascot ? mascotSpriteStyle(mascot.apiBaseUrl, mascot.active.value, mascot.activePreset.value) : mascotSpriteStyle('', null));
const hasMascotColor = computed(() => Boolean(customMascotStyle.value['--xiaoju-image']));
const { errorMessage, isSubmitting, addFiles, composerReady, useExample, startDemo, openFeaturedProject, showcaseSlugs } = homeServices.use();
const visibleExamples = computed(() => designExamples.filter(example => !example.requiresImport || (example.projectSlug && showcaseSlugs?.value.includes(example.projectSlug))));
type ComposerLumoReaction = LumoReaction | 'thinking' | 'sleepy';
const isDraggingFiles = ref(false);
const lumoMessage = ref('');
const lumoReaction = ref<ComposerLumoReaction | ''>('');
let dragDepth = 0;
let lumoMessageTimer: number | undefined;
let lumoReactionTimer: number | undefined;
let lumoTimedStartTimer: number | undefined;
let lumoClockTimer: number | undefined;
let lastLumoLine = -1;

const lumoLines = [
  '别看我趴着，我脑内已经开工了。',
  '你负责大胆，我负责把它变得好看。',
  '检测到一枚野生灵感，要现在捕捉吗？',
  '空白画布最怕的，其实是你的第一句话。',
  '再点一下？我会假装这是用户研究。',
  '今天也要把“差不多”改成“就这个”！',
  '我刚眨了下眼，灵感加载到 1% 了。',
  '悄悄说：好点子通常都先有一点离谱。',
];
const lumoReactions = ['wink', 'happy', 'thinking', 'calm', 'sleepy'] as const;

function hasFiles(event: DragEvent) {
  return Boolean(event.dataTransfer && (Array.from(event.dataTransfer.types).includes('Files')
    || Array.from(event.dataTransfer.items).some(item => item.kind === 'file')));
}

function resetDrag() { dragDepth = 0; isDraggingFiles.value = false; }

function handleDragEnter(event: DragEvent) {
  if (!hasFiles(event)) return;
  event.preventDefault();
  dragDepth += 1;
  isDraggingFiles.value = true;
}

function handleDragOver(event: DragEvent) {
  if (!hasFiles(event)) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = isSubmitting.value ? 'none' : 'copy';
  isDraggingFiles.value = true;
}

function handleDragLeave(event: DragEvent) {
  if (!isDraggingFiles.value) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth || (event.relatedTarget === null && (event.clientX <= 0 || event.clientY <= 0 || event.clientX >= window.innerWidth || event.clientY >= window.innerHeight))) resetDrag();
}

function handleDrop(event: DragEvent) {
  const fileDrop = hasFiles(event);
  resetDrag();
  if (!fileDrop || !event.dataTransfer) return;
  // Capture file drops before the browser opens a file or inserts it into the editor.
  event.preventDefault();
  event.stopPropagation();
  const items = Array.from(event.dataTransfer.items).filter(item => item.kind === 'file');
  const files = items.length ? items.filter(item => !item.webkitGetAsEntry?.()?.isDirectory)
    .map(item => item.getAsFile()).filter((file): file is File => Boolean(file)) : Array.from(event.dataTransfer.files);
  addFiles(files);
}

function handleDragKeydown(event: KeyboardEvent) { if (event.key === 'Escape') resetDrag(); }

function openExample(example: typeof designExamples[number], prompt: string) {
  if (example.projectSlug && openFeaturedProject) { openFeaturedProject(example.projectSlug); return; }
  if (example.demoId && startDemo) { startDemo(example.demoId); return; }
  useExample(prompt);
}

function showLumoLine(text: string, reaction: ComposerLumoReaction, duration = 3600) {
  lumoMessage.value = text;
  lumoReaction.value = reaction;
  if (lumoMessageTimer) window.clearTimeout(lumoMessageTimer);
  if (lumoReactionTimer) window.clearTimeout(lumoReactionTimer);
  lumoReactionTimer = window.setTimeout(() => { lumoReaction.value = ''; }, 1100);
  lumoMessageTimer = window.setTimeout(() => { lumoMessage.value = ''; }, duration);
}

function talkToLumo() {
  let nextLine = Math.floor(Math.random() * lumoLines.length);
  if (nextLine === lastLumoLine) nextLine = (nextLine + 1) % lumoLines.length;
  lastLumoLine = nextLine;
  showLumoLine(lumoLines[nextLine] ?? lumoLines[0]!, lumoReactions[nextLine % lumoReactions.length]!);
}

function maybeTellTimedLumoLine() {
  if (document.visibilityState === 'hidden' || lumoMessage.value) return;
  const now = new Date();
  const message = timedLumoMessage(now);
  if (!message) return;
  const key = timedLumoStorageKey(message, now);
  try {
    if (localStorage.getItem(key) === 'true') return;
    localStorage.setItem(key, 'true');
  } catch { /* A private browser can reject storage; the reminder may repeat after reload. */ }
  showLumoLine(message.text, message.reaction, 6200);
}

onMounted(() => {
  composerReady();
  window.addEventListener('dragenter', handleDragEnter, true);
  window.addEventListener('dragover', handleDragOver, true);
  window.addEventListener('dragleave', handleDragLeave, true);
  window.addEventListener('drop', handleDrop, true);
  window.addEventListener('dragend', resetDrag);
  window.addEventListener('blur', resetDrag);
  window.addEventListener('keydown', handleDragKeydown);
  document.addEventListener('visibilitychange', maybeTellTimedLumoLine);
  lumoTimedStartTimer = window.setTimeout(maybeTellTimedLumoLine, 1200);
  lumoClockTimer = window.setInterval(maybeTellTimedLumoLine, 30_000);
});
onUnmounted(() => {
  window.removeEventListener('dragenter', handleDragEnter, true);
  window.removeEventListener('dragover', handleDragOver, true);
  window.removeEventListener('dragleave', handleDragLeave, true);
  window.removeEventListener('drop', handleDrop, true);
  window.removeEventListener('dragend', resetDrag);
  window.removeEventListener('blur', resetDrag);
  window.removeEventListener('keydown', handleDragKeydown);
  document.removeEventListener('visibilitychange', maybeTellTimedLumoLine);
  if (lumoMessageTimer) window.clearTimeout(lumoMessageTimer);
  if (lumoReactionTimer) window.clearTimeout(lumoReactionTimer);
  if (lumoTimedStartTimer) window.clearTimeout(lumoTimedStartTimer);
  if (lumoClockTimer) window.clearInterval(lumoClockTimer);
  resetDrag();
});
</script>

<template>

<div ref="page" class="intake-page home-intake">
  <div class="intake-hero">
    <div class="intake-heading"><div><p class="eyebrow">你的 AI 设计 Agent</p><BlurText as="h2" text="从一句需求，到一套设计。" once-key="home-heading" /><p>MxinspireX 理解需求与参考资料，生成设计方案，并在画布中持续迭代。</p></div></div>
    <div class="home-composer-stage">
      <div id="intake-composer-host" />
      <button class="home-composer-lumo" :class="{ 'is-custom': hasMascotColor }" type="button" aria-label="和MxinspireX打个招呼" @click="talkToLumo">
        <span class="home-composer-lumo-sprite" :style="customMascotStyle" :class="isSubmitting ? 'is-thinking' : lumoReaction ? `is-${lumoReaction}` : undefined" aria-hidden="true" />
        <Transition name="lumo-speech">
          <span v-if="lumoMessage" :key="lumoMessage" class="home-composer-lumo-speech" role="status" aria-live="polite" aria-atomic="true">{{ lumoMessage }}</span>
        </Transition>
      </button>
    </div>
    <p class="home-upload-hint">可将图片、文档或 CSV 表格拖到此页，添加为附件</p>
    <p v-if="errorMessage" class="error-message intake-error-message" role="alert">{{ errorMessage }}</p>
  </div>
  <section class="home-examples" aria-label="精选项目">
    <div class="home-examples-grid"><DesignExampleCarousel v-for="(example, index) in visibleExamples" :key="example.id" :example="example" :order="index" :disabled="isSubmitting" @choose="prompt => openExample(example, prompt)" /></div>
  </section>
</div>
<Teleport to="body"><footer class="home-footer"><p class="intake-safety-note">AI 生成内容，请仔细甄别</p></footer></Teleport>
<Teleport to="body">
  <div v-if="isDraggingFiles" class="home-file-drop-overlay" role="status" aria-live="polite">
    <div class="home-file-drop-card">
      <Upload :size="32" :stroke-width="1.6" aria-hidden="true" />
      <strong>{{ isSubmitting ? '正在上传资料，请稍候' : '松开鼠标，添加为附件' }}</strong>
      <span>支持一次拖入多个图片、文档或 CSV 表格</span>
      <small>添加后可预览、移除，点击发送时上传</small>
    </div>
  </div>
</Teleport>
</template>

<style scoped>
.canvas-panel > .home-intake { width:min(100%, 1120px); max-width:1120px; padding:24px 0 58px; }
.home-intake .intake-heading h2 { font-size:clamp(23px, 2.3vw, 30px); line-height:1.3; }
.home-intake .intake-heading p:not(.eyebrow) { max-width:760px; font-size:13px; }
.home-intake .intake-heading { margin-bottom:22px; }
.home-composer-stage { position:relative; isolation:isolate; width:100%; }
.home-composer-stage #intake-composer-host { position:relative; z-index:1; }
.home-composer-lumo {
  --xiaoju-size:calc(clamp(144px, 16vw, 184px) * 2 / 3);
  position:absolute;
  /* The opaque composer sits in front of the torso, leaving the face above its edge. */
  z-index:0;
  top:0;
  right:clamp(10px, 3.2vw, 42px);
  width:var(--xiaoju-size);
  aspect-ratio:1;
  margin:0;
  padding:0;
  border:0;
  appearance:none;
  background:transparent;
  color:inherit;
  transform:translateY(-88%);
  filter:drop-shadow(0 6px 9px rgb(58 58 58 / .16));
  cursor:pointer;
  user-select:none;
  -webkit-tap-highlight-color:transparent;
}
.home-composer-lumo:focus-visible { outline:2px solid var(--theme-accent-strong); outline-offset:4px; border-radius:40%; }
.home-intake .home-composer-lumo.is-custom { filter:drop-shadow(0 3px 3px #18181820); }
.home-composer-lumo-sprite {
  display:block;
  width:100%;
  height:100%;
}
.home-composer-lumo-sprite.is-calm { animation:none; background-position:var(--xiaoju-frame-calm); }
.home-composer-lumo-sprite.is-happy { animation:none; background-position:var(--xiaoju-frame-happy); }
.home-composer-lumo-sprite.is-wink { animation:none; background-position:var(--xiaoju-frame-wink); }
.home-composer-lumo-sprite.is-thinking { animation:none; background-position:var(--xiaoju-frame-thinking); }
.home-composer-lumo-sprite.is-sleepy { animation:none; background-position:var(--xiaoju-frame-sleepy); }
.home-composer-lumo-speech {
  --lumo-speech-bg:color-mix(in srgb, var(--theme-surface-raised) 94%, var(--theme-accent-soft));
  --lumo-speech-border:color-mix(in srgb, var(--theme-accent-strong) 42%, var(--theme-border));
  position:absolute;
  z-index:3;
  bottom:calc(100% + 8px);
  right:0;
  width:max-content;
  max-width:min(220px, 44vw);
  padding:9px 12px;
  border:1px solid var(--lumo-speech-border);
  border-radius:13px;
  background:var(--lumo-speech-bg);
  box-shadow:0 10px 28px rgb(0 0 0 / .18);
  color:var(--theme-text);
  font-size:12px;
  font-weight:500;
  line-height:1.5;
  text-align:left;
  white-space:normal;
  pointer-events:none;
}
.home-composer-lumo-speech::before,
.home-composer-lumo-speech::after {
  content:'';
  position:absolute;
  right:calc(var(--xiaoju-size) / 2 - 8px);
  width:0;
  height:0;
  border-left:8px solid transparent;
  border-right:8px solid transparent;
}
.home-composer-lumo-speech::before {
  bottom:-9px;
  border-top:9px solid var(--lumo-speech-border);
}
.home-composer-lumo-speech::after {
  bottom:-7px;
  border-top:8px solid var(--lumo-speech-bg);
}
.lumo-speech-enter-active, .lumo-speech-leave-active { transition:opacity .18s ease, transform .18s cubic-bezier(.2,.8,.2,1); }
.lumo-speech-enter-from, .lumo-speech-leave-to { opacity:0; transform:translate(8px, 5px) scale(.96); }
.home-upload-hint { margin:10px 4px 0; color:var(--theme-text-subtle); font-size:11px; line-height:1.5; }
.home-file-drop-overlay { position:fixed; inset:12px; z-index:150; display:grid; place-items:center; padding:20px; border:2px dashed var(--theme-accent-strong); border-radius:24px; background:color-mix(in srgb, var(--theme-surface-raised) 88%, transparent); pointer-events:none; }
.home-file-drop-card { display:grid; justify-items:center; gap:12px; max-width:100%; padding:32px; border:1px solid var(--theme-border); border-radius:20px; background:var(--theme-surface-raised); box-shadow:0 12px 40px #0001; text-align:center; }
.home-file-drop-card svg { color:var(--theme-accent-strong); }
.home-file-drop-card strong { color:var(--theme-text); font-size:20px; font-weight:500; }
.home-file-drop-card span { color:var(--theme-text-muted); font-size:13px; line-height:1.6; }
.home-file-drop-card small { color:var(--theme-text-subtle); font-size:11px; line-height:1.5; }
.home-intake :deep(#intake-composer-host .intake-composer-editor) {
  min-height:112px;
  max-height:min(320px, 40dvh);
  overflow-y:auto;
  overscroll-behavior-y:contain;
  scrollbar-width:thin;
  scrollbar-color:var(--theme-border-strong) transparent;
}
.home-examples {
  /* Let the visual entry points breathe a little beyond the writing surface. */
  width:calc(100% + 96px);
  margin:30px -48px 0;
}
.home-examples-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }
.home-footer { position:fixed; inset:auto 0 0; z-index:24; padding:12px 76px max(14px, env(safe-area-inset-bottom)); background:transparent; pointer-events:none; }
.home-footer .intake-safety-note { position:static; margin:0; padding:0; }
@media(min-width:761px) and (max-width:1100px) { .canvas-panel > .home-intake { width:calc(100% - 32px); margin-left:32px; margin-right:0; } }
@media(max-width:760px) { .canvas-panel > .home-intake { width:calc(100% - 56px); margin-left:56px; margin-right:0; } }
@media(max-width:1100px) { .home-composer-lumo { right:2px; } }
@media(max-width:1200px) { .home-examples { width:100%; margin-right:0; margin-left:0; } }
@media(max-width:900px) { .canvas-panel > .home-intake { justify-content:flex-start; } .home-intake .intake-heading { margin-bottom:144px; } .home-examples-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; } }
@media(max-width:580px) { .canvas-panel > .home-intake { padding-top:16px; } .home-composer-lumo { --xiaoju-size:calc(136px * 2 / 3); right:2px; } .home-composer-lumo-speech { max-width:min(168px, calc(100vw - 110px)); padding:8px 10px; font-size:11px; } .home-examples { margin-top:24px; } .home-examples-grid { gap:10px; } .home-intake .intake-heading p:not(.eyebrow) { font-size:12px; } }
@media(prefers-reduced-motion:reduce) { .lumo-speech-enter-active, .lumo-speech-leave-active { transition:none; } }
</style>
