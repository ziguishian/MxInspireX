<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { AudioLines, FileCode2, ImageOff, LoaderCircle, Play } from 'lucide-vue-next';
import type { LibraryAsset } from '../../features/pageServices';
import { assetModelFormat, assetPreviewKind, libraryAssetKey, libraryAssetUrl, loadAssetHtml, videoDuration } from '../../features/assetPreview';
import { htmlPreviewDocument, HTML_PREVIEW_SANDBOX, type HtmlPreviewSize } from '../../htmlPreview';

const props = defineProps<{ asset: LibraryAsset; apiBaseUrl: string; paused?: boolean; pageSize?: HtmlPreviewSize; fit?: 'cover' | 'contain'; natural?: boolean }>();
const ModelViewer = defineAsyncComponent(() => import('../ModelViewer.vue'));
const host = ref<HTMLElement | null>(null), video = ref<HTMLVideoElement | null>(null);
const visible = ref(false), loading = ref(true), failed = ref(false), html = ref(''), width = ref(300), duration = ref('');
const imageAttempt = ref(0);
const kind = computed(() => assetPreviewKind(props.asset));
const modelFormat = computed(() => assetModelFormat(props.asset));
const cadThumbnail = ref('');
const url = computed(() => kind.value === 'cad' ? cadThumbnail.value : libraryAssetUrl(props.apiBaseUrl, props.asset));
const imageUrl = computed(() => {
  if (!url.value || imageAttempt.value === 0) return url.value;
  return `${url.value}${url.value.includes('?') ? '&' : '?'}preview_attempt=${imageAttempt.value}`;
});
const document = computed(() => htmlPreviewDocument(html.value));
const frameStyle = computed(() => {
  const page = props.pageSize || { width: 1280, height: 720 };
  return { width: `${page.width}px`, height: `${page.height}px`, transform: `scale(${width.value / page.width})` };
});
let intersection: IntersectionObserver | undefined, resize: ResizeObserver | undefined, request: AbortController | undefined;
let imageRetryTimer: ReturnType<typeof setTimeout> | undefined;
let imageWatchdog: ReturnType<typeof setTimeout> | undefined;
let imageLoadToken = 0;
let hovered = false;
watch(() => props.paused, paused => { if (paused) video.value?.pause(); });

function clearImageTimers() {
  clearTimeout(imageRetryTimer);
  clearTimeout(imageWatchdog);
  imageRetryTimer = undefined;
  imageWatchdog = undefined;
}

function armImageWatchdog() {
  clearTimeout(imageWatchdog);
  imageWatchdog = undefined;
  if (!visible.value || !loading.value || failed.value || !imageUrl.value || !['image', 'cad'].includes(kind.value || '')) return;
  imageWatchdog = setTimeout(() => retryImage(), 15_000);
}

function retryImage() {
  imageLoadToken += 1;
  clearImageTimers();
  if (imageAttempt.value >= 2) { failed.value = true; loading.value = false; return; }
  loading.value = true;
  failed.value = false;
  imageRetryTimer = setTimeout(() => {
    imageAttempt.value += 1;
    void nextTick(armImageWatchdog);
  }, imageAttempt.value ? 900 : 350);
}

watch(() => libraryAssetKey(props.asset), () => {
  request?.abort();
  clearImageTimers();
  html.value = '';
  cadThumbnail.value = '';
  imageLoadToken += 1;
  imageAttempt.value = 0;
  loading.value = true;
  failed.value = false;
  duration.value = '';
});
watch([visible, imageUrl], armImageWatchdog, { flush: 'post' });
watch([visible, () => libraryAssetKey(props.asset)], async ([inView]) => {
  if (!inView) { video.value?.pause(); request?.abort(); return; }
  if (kind.value === 'cad') {
    const controller = new AbortController(); request?.abort(); request = controller;
    try {
      const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.asset.projectId!)}/cad/models/${encodeURIComponent(props.asset.id)}`, { signal: controller.signal });
      if (!response.ok) throw new Error('模型不存在');
      const model = await response.json();
      if (!controller.signal.aborted) cadThumbnail.value = `${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.asset.projectId!)}/assets/${encodeURIComponent(model.files.thumbnail)}/content`;
    } catch { if (!controller.signal.aborted) fail(); }
    return;
  }
  if (kind.value !== 'html' || html.value) return;
  const controller = new AbortController(); request?.abort(); request = controller;
  loading.value = true; failed.value = false;
  try { const content = await loadAssetHtml(props.apiBaseUrl, props.asset, controller.signal); if (!controller.signal.aborted) html.value = content; }
  catch { if (!controller.signal.aborted) { failed.value = true; loading.value = false; } }
});
function metadataLoaded() {
  if (!video.value) return;
  duration.value = videoDuration(video.value.duration);
  // Seek into the actual clip so metadata-only loading does not leave a blank tile.
  if (Number.isFinite(video.value.duration) && video.value.duration > 0) video.value.currentTime = Math.min(.1, video.value.duration / 2);
}
function mediaLoaded() {
  clearImageTimers();
  loading.value = false;
  failed.value = false;
  if (hovered && !props.paused) void video.value?.play().catch(() => undefined);
}
async function imageDecoded(event: Event) {
  const image = event.currentTarget as HTMLImageElement;
  const token = ++imageLoadToken;
  try { await image.decode(); }
  catch {
    if (!image.complete || image.naturalWidth === 0) {
      if (token === imageLoadToken) retryImage();
      return;
    }
  }
  if (token !== imageLoadToken || !image.isConnected || image.naturalWidth === 0) return;
  mediaLoaded();
}
function hover(value: boolean) {
  hovered = value;
  if (value && visible.value && !props.paused) void video.value?.play().catch(() => undefined);
  else video.value?.pause();
}
function fail() { failed.value = true; loading.value = false; }
onMounted(() => {
  if (!host.value) return;
  intersection = new IntersectionObserver(entries => { visible.value = Boolean(entries[0]?.isIntersecting); }, { rootMargin: '640px 0px' });
  intersection.observe(host.value);
  resize = new ResizeObserver(entries => {
    const rect = entries[0]?.contentRect;
    width.value = rect?.width || 300;
  });
  resize.observe(host.value);
});
onBeforeUnmount(() => { imageLoadToken += 1; request?.abort(); clearImageTimers(); intersection?.disconnect(); resize?.disconnect(); video.value?.pause(); });
</script>
<template>
  <div ref="host" class="library-media-thumbnail" :class="{ 'is-natural': natural, 'is-loading': loading, 'is-failed': failed }" :data-kind="kind" :aria-busy="loading" @pointerenter="hover(true)" @pointerleave="hover(false)">
    <template v-if="!failed">
      <img v-if="(kind === 'image' || kind === 'cad') && imageUrl" :key="`${libraryAssetKey(asset)}/${imageAttempt}`" :src="imageUrl" :style="{ objectFit: fit || 'cover' }" alt="" loading="eager" decoding="async" @load="imageDecoded" @error="retryImage" />
      <div v-else-if="kind === 'audio'" class="library-audio-cover"><AudioLines :size="44" :stroke-width="1.3" /><span>点击播放音频</span></div>
      <video v-else-if="kind === 'video' && visible" :key="libraryAssetKey(asset)" ref="video" :src="url" :style="{ objectFit: fit || 'cover' }" muted loop playsinline preload="metadata" tabindex="-1" aria-hidden="true" @loadedmetadata="metadataLoaded" @loadeddata="mediaLoaded" @error="fail" />
      <iframe v-else-if="kind === 'html' && visible && html" :srcdoc="document" :sandbox="HTML_PREVIEW_SANDBOX" :style="frameStyle" title="HTML 页面缩略图" tabindex="-1" aria-hidden="true" @load="mediaLoaded" />
      <ModelViewer v-else-if="kind === '3d' && visible && url" :asset-url="url" :asset-format="modelFormat" :label="asset.pathRelative || '3D 模型缩略图'" @loaded="mediaLoaded" @error="fail" />
    </template>
    <div v-if="failed" class="library-thumbnail-status"><ImageOff v-if="kind !== 'html'" :size="22" /><FileCode2 v-else :size="22" /><span>暂时无法预览</span></div>
    <div v-else-if="loading && kind !== 'audio'" class="library-thumbnail-status library-thumbnail-loading" aria-hidden="true"><span class="library-thumbnail-loading-label"><LoaderCircle :size="19" class="spin-icon" /><span>正在加载预览</span></span></div>
    <template v-if="!failed && kind === 'video'"><span class="library-video-play" aria-hidden="true"><Play :size="19" fill="currentColor" /></span><span v-if="duration" class="library-video-duration" aria-hidden="true">{{ duration }}</span></template>
    <span v-if="kind === 'html' && !failed" class="library-html-badge" aria-hidden="true"><FileCode2 :size="12" />HTML</span>
  </div>
</template>
<style scoped>
.library-audio-cover { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; width:100%; height:100%; background:var(--theme-surface); color:var(--theme-text-muted); font-size:12px; }
.library-media-thumbnail { position: absolute; inset: 0; overflow: hidden; isolation: isolate; border-radius: inherit; background: var(--theme-bg); }
.library-media-thumbnail > img, .library-media-thumbnail > video { position: relative; z-index: 0; display: block; width: 100%; height: 100%; object-fit: cover; pointer-events: none; opacity: 1; transition: opacity .22s ease; }
.library-media-thumbnail > iframe { opacity: 1; transition: opacity .22s ease; }
.library-media-thumbnail.is-loading > :is(img, video, iframe) { opacity: 0; }
.library-media-thumbnail.is-natural { position: relative; inset: auto; width: 100%; }
.library-media-thumbnail.is-natural:is(.is-loading, .is-failed) { min-height: 160px; }
.library-media-thumbnail.is-natural > img { height: auto; }
.library-media-thumbnail > iframe { position: absolute; top: 0; left: 0; max-width: none; border: 0; transform-origin: top left; pointer-events: none; background: white; }
.library-media-thumbnail :deep(.cad-model-viewer) { position: absolute; inset: 0; min-height: 0; pointer-events: none; }
.library-media-thumbnail :deep(.cad-viewer-controls) { display: none; }
.library-thumbnail-status { position: absolute; inset: 0; z-index: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--theme-text-muted); font-size: 11px; pointer-events: none; }
.library-thumbnail-loading { overflow: hidden; background: linear-gradient(145deg,color-mix(in srgb,var(--theme-surface) 86%,var(--theme-bg)),color-mix(in srgb,var(--theme-surface-hover) 58%,var(--theme-bg))); }
.library-thumbnail-loading::before { content: ''; position: absolute; inset: 0; width: 48%; background: linear-gradient(90deg,transparent,color-mix(in srgb,var(--theme-text) 7%,transparent),transparent); transform: translate3d(-140%,0,0) skewX(-12deg); will-change: transform; animation: library-thumbnail-shimmer 1.45s ease-in-out infinite; }
.library-thumbnail-loading-label { position: relative; z-index: 2; display: inline-flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid #ffffff26; border-radius: 999px; background: #151515d9; color: #e2e2e2; font-weight: 520; line-height: 1; box-shadow: 0 5px 18px #00000038; }
.library-thumbnail-loading-label .spin-icon { color: var(--theme-accent-strong); }
@keyframes library-thumbnail-shimmer { to { transform: translate3d(310%,0,0) skewX(-12deg); } }
.library-video-play { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); display: grid; place-items: center; width: 40px; height: 40px; padding-left: 2px; border: 1px solid #ffffff4d; border-radius: 50%; background: #101010a6; color: #fff; box-shadow: 0 2px 12px #0002; pointer-events: none; }
.library-media-thumbnail:hover .library-video-play { background: #10101070; }
.library-video-duration, .library-html-badge { position: absolute; display: flex; align-items: center; gap: 4px; padding: 3px 6px; border-radius: 5px; background: #151515c9; color: #efefef; font-size: 10px; line-height: 14px; pointer-events: none; }
.library-video-duration { right: 8px; bottom: 8px; font-variant-numeric: tabular-nums; }
.library-html-badge { top: 8px; left: 8px; }
@media (prefers-reduced-motion: reduce) { .library-media-thumbnail > :is(img, video, iframe) { transition: none; }.library-thumbnail-loading::before { animation: none; transform: translate3d(120%,0,0) skewX(-12deg); } }
</style>
