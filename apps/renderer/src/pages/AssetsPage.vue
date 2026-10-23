<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ArrowUpRight, AudioLines, Box, Download, FileCode2, ImageOff, LoaderCircle, Star, Trash2, X } from 'lucide-vue-next';
import { RouterLink } from 'vue-router';
import LibraryPageLayout from '../components/shared/LibraryPageLayout.vue';
import EmptyState from '../components/shared/EmptyState.vue';
import BrandLoading from '../components/BrandLoading.vue';
import InfiniteScrollStatus from '../components/shared/InfiniteScrollStatus.vue';
import MasonryGrid from '../components/shared/MasonryGrid.vue';
import { assetLibraryServices, type LibraryAsset } from '../features/pageServices';
import CadPanel from '../components/CadPanel.vue';
import LibraryAssetThumbnail from '../components/assets/LibraryAssetThumbnail.vue';
import { assetModelFormat, assetPreviewKind, libraryAssetKey, libraryAssetUrl, loadAssetHtml, videoDuration } from '../features/assetPreview';
import { htmlPreviewDocument, HTML_PREVIEW_SANDBOX } from '../htmlPreview';
import { exportNode, nodeSaveLabel } from '../nodeExport';
const { loadState, globalAssets, apiBaseUrl, assetDisplayName, requestDeleteAsset, openProject } = assetLibraryServices.use();
const ModelViewer = defineAsyncComponent(() => import('../components/ModelViewer.vue'));
const referenceNotice = ref('');
const collectedReferenceKeys = ref(new Set<string>()), collectingReferenceKeys = ref(new Set<string>());
const referenceKey = (asset: LibraryAsset) => `${asset.projectId || ''}/${asset.id}`;
async function collectReference(asset: LibraryAsset) {
  const key = referenceKey(asset);
  if (collectingReferenceKeys.value.has(key)) return;
  collectingReferenceKeys.value = new Set(collectingReferenceKeys.value).add(key);
  referenceNotice.value = '';
  try {
    const response = await fetch(`${apiBaseUrl}/api/references/from-asset`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({projectId:asset.projectId,assetId:asset.id})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '收藏失败');
    collectedReferenceKeys.value = new Set(collectedReferenceKeys.value).add(key);
    referenceNotice.value = '已收藏到参考库';
  } catch (error) { referenceNotice.value = error instanceof Error ? error.message : '收藏失败'; }
  finally {
    const pending = new Set(collectingReferenceKeys.value); pending.delete(key); collectingReferenceKeys.value = pending;
  }
}
const assetSearch = ref('');
const assetTypeFilter = ref('all');
const assetBatchSize = 24;
const visibleAssetCount = ref(assetBatchSize);
const htmlAssets = ref<LibraryAsset[]>([]), htmlLoading = ref(false), htmlError = ref('');
let htmlCatalogController: AbortController | undefined;
async function loadHtmlLibrary() {
  htmlCatalogController?.abort();
  const controller = new AbortController(); htmlCatalogController = controller;
  htmlLoading.value = true; htmlError.value = '';
  try {
    const response = await fetch(`${apiBaseUrl}/api/library/html`, { signal: controller.signal });
    if (!response.ok) throw new Error('HTML catalogue unavailable');
    const records = await response.json();
    if (!Array.isArray(records)) throw new Error('Invalid HTML catalogue');
    if (!controller.signal.aborted) htmlAssets.value = records;
  } catch { if (!controller.signal.aborted) htmlError.value = 'HTML 产物暂时读取失败'; }
  finally { if (htmlCatalogController === controller) htmlLoading.value = false; }
}
onMounted(loadHtmlLibrary);
watch(globalAssets, loadHtmlLibrary);
const libraryAssets = computed(() => [...globalAssets.value, ...htmlAssets.value].sort((a, b) => (b.updatedAt || b.createdAt || '').localeCompare(a.updatedAt || a.createdAt || '')));
const filteredGlobalAssets = computed(() => {
  const query = assetSearch.value.trim().toLowerCase();
  return libraryAssets.value.filter((asset) => {
    const kind = assetPreviewKind(asset) || asset.kind;
    const matchesType = assetTypeFilter.value === 'all' || kind === assetTypeFilter.value || (assetTypeFilter.value === 'document' && kind !== 'html' && Boolean(asset.mime?.startsWith('text/') || asset.mime?.startsWith('application/')));
    const matchesQuery = !query || `${asset.pathRelative} ${asset.projectName || ''} ${asset.kind}`.toLowerCase().includes(query);
    return matchesType && matchesQuery;
  });
});
const visibleAssets = computed(() => filteredGlobalAssets.value.slice(0, visibleAssetCount.value));
const hasMoreAssets = computed(() => visibleAssets.value.length < filteredGlobalAssets.value.length);
type AssetTimelineGroup = { key: string; label: string; assets: LibraryAsset[] };
function assetTimelineDate(asset: LibraryAsset) {
  const value = asset.updatedAt || asset.createdAt || '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
function assetTimelineKey(asset: LibraryAsset) {
  const date = assetTimelineDate(asset);
  if (!date) return 'unknown';
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}
function assetTimelineLabel(asset: LibraryAsset) {
  const date = assetTimelineDate(asset);
  return date ? new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }).format(date) : '未记录时间';
}
const assetTimelineGroups = computed<AssetTimelineGroup[]>(() => {
  const groups = new Map<string, AssetTimelineGroup>();
  for (const asset of visibleAssets.value) {
    const key = assetTimelineKey(asset);
    const group = groups.get(key) || { key, label: assetTimelineLabel(asset), assets: [] };
    group.assets.push(asset);
    groups.set(key, group);
  }
  return [...groups.values()];
});
watch([assetSearch, assetTypeFilter], () => { visibleAssetCount.value = assetBatchSize; });
function loadMoreAssets() { visibleAssetCount.value = Math.min(visibleAssetCount.value + assetBatchSize, filteredGlobalAssets.value.length); }
const cadAsset = ref<LibraryAsset | null>(null);
const previewAsset = ref<LibraryAsset | null>(null);
const previewDialog = ref<HTMLDialogElement | null>(null);
const previewLoading = ref(false);
const previewFailed = ref(false);
const previewDimensions = ref('');
const previewAudio = ref<HTMLAudioElement | null>(null);
const previewVideo = ref<HTMLVideoElement | null>(null), previewHtml = ref('');
const previewKind = computed(() => previewAsset.value ? assetPreviewKind(previewAsset.value) : null);
const previewLabel = computed(() => previewKind.value === 'audio' ? '音频' : previewKind.value === 'video' ? '视频' : previewKind.value === 'html' ? 'HTML' : previewKind.value === '3d' ? '3D 模型' : previewKind.value === 'cad' ? 'CAD 模型' : '图像');
const previewModelFormat = computed(() => previewAsset.value ? assetModelFormat(previewAsset.value) : 'glb');
const previewFrame = ref<HTMLIFrameElement | null>(null);
const htmlDocument = computed(() => htmlPreviewDocument(previewHtml.value, {}, true));
const saveMenu = ref<{ asset: LibraryAsset; x: number; y: number } | null>(null);
const saveMenuElement = ref<HTMLElement | null>(null);
function openSaveMenu(event: MouseEvent, asset: LibraryAsset) {
  event.preventDefault(); event.stopPropagation();
  saveMenu.value = { asset, x: event.clientX, y: event.clientY };
}
watch(saveMenu, async menu => {
  await nextTick();
  if (!menu || saveMenu.value !== menu || !saveMenuElement.value) return;
  const rect = saveMenuElement.value.getBoundingClientRect();
  menu.x = Math.max(10, Math.min(menu.x, window.innerWidth - rect.width - 10));
  menu.y = Math.max(10, Math.min(menu.y, window.innerHeight - rect.height - 10));
});
function dismissSaveMenu(event: Event) {
  if (event.type === 'keydown' && (event as KeyboardEvent).key !== 'Escape') return;
  if (!(event.target instanceof Node) || !saveMenuElement.value?.contains(event.target)) saveMenu.value = null;
}
function previewContextMenu(event: MessageEvent) {
  const frame = previewFrame.value;
  if (!frame || !previewAsset.value || event.source !== frame.contentWindow) return;
  if (event.data?.type === 'aics:html-dismiss-menu') { saveMenu.value = null; return; }
  if (event.data?.type !== 'aics:html-context-menu') return;
  const { x, y } = event.data;
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > frame.clientWidth || y > frame.clientHeight) return;
  const rect = frame.getBoundingClientRect();
  saveMenu.value = { asset: previewAsset.value, x: rect.x + x * rect.width / frame.clientWidth, y: rect.y + y * rect.height / frame.clientHeight };
}
onMounted(() => { window.addEventListener('pointerdown', dismissSaveMenu, true); window.addEventListener('keydown', dismissSaveMenu, true); window.addEventListener('message', previewContextMenu); });
onBeforeUnmount(() => { window.removeEventListener('pointerdown', dismissSaveMenu, true); window.removeEventListener('keydown', dismissSaveMenu, true); window.removeEventListener('message', previewContextMenu); });
const downloading = ref(false);
const downloadError = ref('');
let downloadController: AbortController | undefined;
let previewController: AbortController | undefined;
const assetUrl = (asset: LibraryAsset) => libraryAssetUrl(apiBaseUrl, asset);
async function openPreview(asset: LibraryAsset) {
  if (assetPreviewKind(asset) === 'cad') { cadAsset.value = asset; return; }
  saveMenu.value = null;
  previewController?.abort(); downloadController?.abort(); previewVideo.value?.pause(); previewAudio.value?.pause(); downloading.value = false;
  const controller = new AbortController(); previewController = controller;
  previewAsset.value = asset;
  previewLoading.value = true;
  previewFailed.value = false;
  previewDimensions.value = '';
  previewHtml.value = '';
  downloadError.value = '';
  await nextTick();
  if (controller.signal.aborted) return;
  if (!previewDialog.value?.open) previewDialog.value?.showModal();
  if (assetPreviewKind(asset) === 'html') {
    try { const html = await loadAssetHtml(apiBaseUrl, asset, controller.signal); if (!controller.signal.aborted) previewHtml.value = html; }
    catch { if (!controller.signal.aborted) { previewFailed.value = true; previewLoading.value = false; } }
  }
}
function closePreview() {
  saveMenu.value = null;
  previewController?.abort(); previewController = undefined;
  previewVideo.value?.pause(); previewAudio.value?.pause(); previewHtml.value = '';
  downloadController?.abort();
  downloadController = undefined;
  downloading.value = false;
  previewDialog.value?.close();
  previewAsset.value = null;
}
function videoLoaded(event: Event) {
  const video = event.target as HTMLVideoElement;
  previewDimensions.value = [video.videoWidth && `${video.videoWidth} × ${video.videoHeight}`, videoDuration(video.duration)].filter(Boolean).join(' · ');
  previewLoading.value = false;
}
function imageLoaded(event: Event) {
  const image = event.target as HTMLImageElement;
  previewLoading.value = false;
  previewDimensions.value = `${image.naturalWidth} × ${image.naturalHeight}`;
}
async function downloadOriginal(asset = previewAsset.value) {
  if (!asset || downloading.value) return;
  saveMenu.value = null;
  const controller = new AbortController();
  downloadController = controller;
  downloading.value = true;
  downloadError.value = '';
  try {
    let blob: Blob;
    if (asset.htmlNodeId) {
      blob = new Blob([(previewAsset.value?.id === asset.id && previewHtml.value) || await loadAssetHtml(apiBaseUrl, asset, controller.signal)], { type: 'text/html;charset=utf-8' });
    } else {
      const response = await fetch(assetUrl(asset), { signal: controller.signal });
      if (!response.ok) throw new Error('Download failed');
      blob = await response.blob();
    }
    if (controller.signal.aborted) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = assetDisplayName(asset).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_');
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  } catch {
    if (!controller.signal.aborted) downloadError.value = '下载失败，请检查文件后重试。';
  } finally {
    if (downloadController === controller) { downloading.value = false; downloadController = undefined; }
  }
}
async function exportPdf(asset: LibraryAsset) {
  if (downloading.value) return;
  saveMenu.value = null;
  const controller = new AbortController(); downloadController = controller;
  downloading.value = true; downloadError.value = '';
  try {
    const html = (previewAsset.value?.id === asset.id && previewHtml.value) || await loadAssetHtml(apiBaseUrl, asset, controller.signal);
    if (!controller.signal.aborted) await exportNode({ kind: 'html', html, title: assetDisplayName(asset).replace(/\.html?$/i, '') }, 'pdf');
  } catch (error) { if (!controller.signal.aborted) downloadError.value = error instanceof Error ? error.message : 'PDF 导出失败，请重试。'; }
  finally { if (downloadController === controller) { downloading.value = false; downloadController = undefined; } }
}
onBeforeUnmount(() => { previewVideo.value?.pause(); previewAudio.value?.pause(); previewController?.abort(); downloadController?.abort(); htmlCatalogController?.abort(); });
</script>

<template>
  <LibraryPageLayout v-model:search="assetSearch" class="library-page" eyebrow="ASSETS / LOCAL LIBRARY" title="资产库" description="集中预览和管理项目产物，回到对话中可用 @ 引用。" search-label="搜索资产名称或项目">
    <template #actions><RouterLink class="ghost-button" to="/projects"><ArrowUpRight :size="16" />查看项目</RouterLink></template>
    <template #meta>共 {{ filteredGlobalAssets.length }} 个资产</template>
    <template #filters><select v-model="assetTypeFilter" aria-label="资产类型"><option value="all">全部类型</option><option value="image">图像</option><option value="video">视频</option><option value="audio">音频</option><option value="html">HTML 网页</option><option value="3d">3D 模型</option><option value="document">文档</option><option value="cad">CAD</option></select></template>
    <p v-if="referenceNotice" class="library-notice" role="status">{{ referenceNotice }}</p>
          <p v-if="htmlError" class="library-preview-error" role="status">{{ htmlError }}<button type="button" @click="loadHtmlLibrary">重试</button></p>
          <p v-if="downloadError && !previewAsset" class="library-preview-error" role="alert">{{ downloadError }}</p>
          <BrandLoading v-if="(loadState.loading.value || htmlLoading) && !filteredGlobalAssets.length" label="正在读取资料…" />
          <EmptyState v-else-if="loadState.error.value">{{ loadState.error.value }}<template #action><button class="ghost-button" :disabled="loadState.loading.value" @click="loadState.retry">重新加载</button></template></EmptyState>
          <EmptyState v-else-if="!filteredGlobalAssets.length" :icon="ImageOff" title="这里将收集你的设计资产">先在首页上传图片或资料，或运行一个任务生成资产；也可以调整当前筛选。</EmptyState>
          <div v-if="filteredGlobalAssets.length" class="asset-timeline" aria-label="资产时间轴">
            <section v-for="group in assetTimelineGroups" :key="group.key" class="asset-timeline-group">
              <header class="asset-timeline-heading"><span aria-hidden="true" /><time :datetime="group.key">{{ group.label }}</time><small>{{ group.assets.length }} 个资产</small></header>
              <MasonryGrid class="global-library-grid">
                <article v-for="asset in group.assets" :key="libraryAssetKey(asset)" class="global-library-card" @contextmenu="openSaveMenu($event, asset)">
                  <button v-if="assetPreviewKind(asset)" type="button" class="global-library-thumb asset-preview-trigger" :class="{ 'is-natural-image': assetPreviewKind(asset) === 'image' }" :aria-label="`放大预览 ${assetDisplayName(asset)}`" @click="openPreview(asset)">
                    <LibraryAssetThumbnail :asset="asset" :api-base-url="apiBaseUrl" :paused="!!previewAsset" :natural="assetPreviewKind(asset) === 'image'" fit="contain" />
                  </button>
                  <div v-else class="global-library-thumb"><span>{{ asset.kind.toUpperCase() }}</span></div>
                  <button v-if="['image/jpeg','image/png','image/webp'].includes(asset.mime || '')" type="button" class="library-collect-button" :class="{ 'is-collected': collectedReferenceKeys.has(referenceKey(asset)) }" :disabled="collectingReferenceKeys.has(referenceKey(asset))" :aria-label="collectedReferenceKeys.has(referenceKey(asset)) ? `已收藏 ${assetDisplayName(asset)}` : `收藏 ${assetDisplayName(asset)} 到参考库`" :aria-pressed="collectedReferenceKeys.has(referenceKey(asset))" :title="collectedReferenceKeys.has(referenceKey(asset)) ? '已收藏到参考库' : '收藏到参考库'" @click.stop="collectReference(asset)"><Star :size="17" :fill="collectedReferenceKeys.has(referenceKey(asset)) ? 'currentColor' : 'none'" /></button>
                  <div class="global-library-card-info">
                    <div class="global-library-card-heading"><strong :title="assetDisplayName(asset)">{{ assetDisplayName(asset) }}</strong><button v-if="asset.htmlNodeId && openProject" type="button" class="library-delete-button" :aria-label="`打开所属项目 ${asset.projectName || ''}`" title="在项目中编辑" @click.stop="openProject(asset.projectId!)"><ArrowUpRight :size="14" /></button><button v-else-if="!asset.htmlNodeId" type="button" class="library-delete-button" :aria-label="`删除资产 ${assetDisplayName(asset)}`" title="删除资产" @click.stop="requestDeleteAsset(asset)"><Trash2 :size="14" /></button></div>
                    <small>{{ asset.projectName || '本地项目' }}<span aria-hidden="true"> · </span>{{ Math.max(1, Math.round(asset.byteSize / 1024)) }} KB</small>
                  </div>
                </article>
              </MasonryGrid>
            </section>
          </div>
          <InfiniteScrollStatus v-if="filteredGlobalAssets.length" :has-more="hasMoreAssets" :loaded="visibleAssets.length" :total="filteredGlobalAssets.length" item-label="个资产" @load-more="loadMoreAssets" />
  </LibraryPageLayout>
  <CadPanel v-if="cadAsset" :api-base-url="apiBaseUrl" :project-id="cadAsset.projectId!" :asset-id="cadAsset.id" @close="cadAsset = null" />
  <Teleport to="body">
    <dialog ref="previewDialog" class="asset-preview-dialog" aria-labelledby="asset-preview-title" @cancel.prevent="closePreview" @close="!previewDialog?.open && closePreview()" @click.self="closePreview" @keydown.stop>
      <template v-if="previewAsset">
        <header class="asset-preview-header">
          <div><small>{{ previewLabel }}预览</small><h2 id="asset-preview-title" :title="assetDisplayName(previewAsset)">{{ assetDisplayName(previewAsset) }}</h2></div>
          <button type="button" class="asset-preview-close" aria-label="关闭预览" autofocus @click="closePreview"><X :size="19" /></button>
        </header>
        <div class="asset-preview-stage" :aria-busy="previewLoading" @contextmenu="openSaveMenu($event, previewAsset)">
          <template v-if="!previewFailed">
            <img v-if="previewKind === 'image'" :key="libraryAssetKey(previewAsset)" :src="assetUrl(previewAsset)" :alt="assetDisplayName(previewAsset)" @load="imageLoaded" @error="previewLoading = false; previewFailed = true" />
            <video v-else-if="previewKind === 'video'" ref="previewVideo" :key="libraryAssetKey(previewAsset)" :src="assetUrl(previewAsset)" controls playsinline preload="auto" :aria-label="assetDisplayName(previewAsset)" @loadedmetadata="videoLoaded" @loadeddata="previewLoading = false" @error="previewLoading = false; previewFailed = true" />
            <div v-else-if="previewKind === 'audio'" class="asset-audio-preview"><AudioLines :size="64" :stroke-width="1.2" aria-hidden="true" /><audio ref="previewAudio" :key="libraryAssetKey(previewAsset)" :src="assetUrl(previewAsset)" controls preload="metadata" :aria-label="assetDisplayName(previewAsset)" @loadedmetadata="previewLoading = false; previewDimensions = videoDuration(($event.target as HTMLAudioElement).duration)" @error="previewLoading = false; previewFailed = true" /></div>
            <iframe ref="previewFrame" v-else-if="previewKind === 'html' && previewHtml" :key="libraryAssetKey(previewAsset)" :srcdoc="htmlDocument" :sandbox="HTML_PREVIEW_SANDBOX" :title="assetDisplayName(previewAsset)" @load="previewLoading = false" />
            <ModelViewer v-else-if="previewKind === '3d'" :key="libraryAssetKey(previewAsset)" :asset-url="assetUrl(previewAsset)" :asset-format="previewModelFormat" :label="assetDisplayName(previewAsset)" @loaded="previewLoading = false" @error="previewLoading = false; previewFailed = true" />
          </template>
          <div v-if="previewLoading" class="asset-preview-status" role="status"><LoaderCircle :size="24" class="spin-icon" /><span>正在加载{{ previewLabel }}…</span></div>
          <div v-else-if="previewFailed" class="asset-preview-status" role="status"><FileCode2 v-if="previewKind === 'html'" :size="28" /><Box v-else-if="previewKind === '3d'" :size="28" /><ImageOff v-else :size="28" /><span>{{ previewLabel }}暂时无法预览</span><button type="button" class="ghost-button" @click="openPreview(previewAsset)">重新加载</button></div>
        </div>
        <footer class="asset-preview-footer">
          <div class="asset-preview-meta"><span>{{ previewAsset.projectName || '本地项目' }}</span><small>{{ previewDimensions }}{{ previewDimensions ? ' · ' : '' }}{{ Math.max(1, Math.round(previewAsset.byteSize / 1024)) }} KB</small><small v-if="downloadError" class="asset-download-error" role="alert">{{ downloadError }}</small></div>
          <button type="button" class="asset-download-button" :disabled="downloading" @click="downloadOriginal()"><LoaderCircle v-if="downloading" :size="16" class="spin-icon" /><Download v-else :size="16" />{{ downloading ? '正在下载…' : previewKind === 'audio' ? '下载音频' : previewKind === 'video' ? '下载视频' : previewKind === 'html' ? '导出 HTML' : previewKind === '3d' ? '下载 3D 模型' : '下载原图' }}</button>
          <button v-if="previewKind === 'html'" type="button" class="asset-download-button asset-pdf-button" :disabled="downloading || !previewHtml" @click="exportPdf(previewAsset)"><Download :size="16" />导出 PDF</button>
        </footer>
      </template>
    </dialog>
  </Teleport>
  <Teleport v-if="saveMenu" :to="previewAsset && previewDialog ? previewDialog : 'body'">
    <div ref="saveMenuElement" class="canvas-context-menu asset-save-menu" :style="{ left: `${saveMenu.x}px`, top: `${saveMenu.y}px` }" @click.stop @contextmenu.prevent.stop>
      <template v-if="assetPreviewKind(saveMenu.asset) === 'html'">
        <button type="button" :disabled="downloading" @click="downloadOriginal(saveMenu.asset)"><Download :size="15" />导出 HTML</button>
        <button type="button" :disabled="downloading" @click="exportPdf(saveMenu.asset)"><Download :size="15" />导出 PDF</button>
      </template>
      <button v-else type="button" :disabled="downloading || !saveMenu.asset.projectId" @click="downloadOriginal(saveMenu.asset)"><Download :size="15" />{{ nodeSaveLabel({ kind: saveMenu.asset.kind, asset: saveMenu.asset }) }}</button>
      <button type="button" @click="saveMenu = null"><X :size="15" />关闭菜单</button>
    </div>
  </Teleport>
</template>

<style scoped>
.asset-audio-preview { display:grid; justify-items:center; gap:28px; width:min(520px, 90%); color:var(--theme-accent-strong); }
.asset-audio-preview audio { width:100%; }
.asset-save-menu { z-index: 1000; }
.asset-preview-footer { flex-wrap: wrap; }
.asset-preview-meta { flex: 1 1 160px; }
.library-notice { font-size: var(--ui-font-control); color: var(--theme-text-muted); }
.asset-timeline { position: relative; display: grid; gap: 28px; padding-left: 28px; }
.asset-timeline::before { content: ''; position: absolute; top: 8px; bottom: 8px; left: 8px; width: 1px; background: var(--theme-border); }
.asset-timeline-group { position: relative; min-width: 0; }
.asset-timeline-heading { display: flex; align-items: center; gap: 9px; min-height: 26px; margin: 0 0 14px -28px; color: var(--theme-text); }
.asset-timeline-heading > span { position: relative; z-index: 1; width: 17px; height: 17px; border: 4px solid var(--theme-surface); border-radius: 50%; background: var(--theme-accent-strong); box-shadow: 0 0 0 1px var(--theme-border-strong); }
.asset-timeline-heading time { font-size: var(--ui-font-body); font-weight: 620; line-height: 1.4; }
.asset-timeline-heading small { color: var(--theme-text-muted); font-size: var(--ui-font-caption); }
.global-library-card { position: relative; display: flex; flex-direction: column; min-width: 0; overflow: hidden; contain: paint; padding: 0; border-color: color-mix(in srgb, var(--theme-border) 72%, transparent); border-radius: var(--ui-radius-card); background: var(--theme-bg); color: #fff; box-shadow: var(--ui-media-shadow); }
.global-library-card strong { color: #f6f8f4; }
.global-library-card small { color: #dadada; }
.global-library-thumb { position: relative; flex-shrink: 0; width: 100%; aspect-ratio: var(--library-preview-ratio, 16 / 9); min-height: 0; }
.global-library-thumb > img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.global-library-thumb.is-natural-image { display: block; aspect-ratio: auto; }
.asset-preview-trigger { position: relative; width: 100%; padding: 0; border: 0; }
.asset-preview-trigger:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 3px; }
.global-library-card-info { position: absolute; right: 0; bottom: 0; left: 0; z-index: 1; display: grid; gap: 5px; min-height: 0; padding: 18px 12px 12px; opacity: 0; transform: translate3d(0, 12px, 0); backface-visibility: hidden; pointer-events: none; isolation: isolate; transition: opacity .22s ease, transform .22s cubic-bezier(.2,.7,.2,1); }
.global-library-card-info::before { content: ''; position: absolute; inset: 0; z-index: -1; background: var(--ui-media-overlay); -webkit-mask-image: var(--ui-media-mask); mask-image: var(--ui-media-mask); -webkit-backdrop-filter: var(--ui-media-blur); backdrop-filter: var(--ui-media-blur); }
.global-library-card-info .global-library-card-heading { align-items: center; }
.global-library-card-info strong { min-width: 0; overflow: hidden; font-size: var(--ui-font-card); font-weight: 620; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 6px #0009; }
.global-library-card-info small { overflow: hidden; font-size: var(--ui-font-caption); line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 5px #0009; }
.global-library-card-info .library-delete-button { color: #f2f2f2; }
.global-library-card-info .library-delete-button:hover { border-color: #ffffff52; background: #ffffff1f; color: #fff; }
.global-library-card:is(:hover, :focus-within) .global-library-card-info { opacity: 1; transform: translate3d(0, 0, 0); pointer-events: auto; will-change: opacity, transform; }
.library-collect-button { position: absolute; top: 18px; right: 18px; z-index: 2; display: grid; place-items: center; width: 32px; height: 32px; padding: 0; opacity: 0; transform: translate3d(0, -4px, 0) scale(.96); backface-visibility: hidden; pointer-events: none; border: 1px solid #ffffff47; border-radius: var(--ui-radius-control); background: #151515b8; color: #f5f5f5; box-shadow: 0 3px 12px #0004; cursor: pointer; transition: opacity .14s ease, transform .14s ease, background .14s ease, color .14s ease; }
.global-library-card:is(:hover, :focus-within) .library-collect-button { opacity: 1; transform: translate3d(0, 0, 0) scale(1); pointer-events: auto; will-change: opacity, transform; }
.library-collect-button:hover { transform: scale(1.06); background: #222222dd; color: var(--theme-accent-strong); }
.library-collect-button.is-collected { border-color: color-mix(in srgb, var(--theme-accent-strong) 70%, transparent); background: var(--theme-accent-soft); color: var(--theme-accent-strong); }
.library-collect-button:disabled { cursor: wait; opacity: .65; }
.library-collect-button:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { .global-library-card-info, .library-collect-button { transition: none; } }
.asset-preview-dialog { width: min(1080px, calc(100vw - 40px)); max-width: none; max-height: calc(100dvh - 40px); padding: 0; border: 1px solid var(--theme-border); border-radius: var(--ui-radius-dialog); background: var(--theme-surface-raised); color: var(--theme-text); box-shadow: var(--theme-shadow); overflow: hidden; }
.asset-preview-dialog[open] { display: flex; flex-direction: column; }
.asset-preview-dialog::backdrop { background: var(--theme-overlay); backdrop-filter: blur(6px); }
.asset-preview-header, .asset-preview-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 20px; flex-shrink: 0; }
.asset-preview-header { border-bottom: 1px solid var(--theme-border); }
.asset-preview-header > div { min-width: 0; }.asset-preview-header small { font-size: var(--ui-font-caption); color: var(--theme-text-subtle); }
.asset-preview-header h2 { margin: 5px 0 0; font-size: var(--ui-font-body); font-weight: 550; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
.asset-preview-close { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; flex-shrink: 0; border: 0; border-radius: 50%; background: var(--theme-surface-subtle); color: var(--theme-text-muted); }.asset-preview-close:hover { background: var(--theme-surface-hover); color: var(--theme-text); }
.asset-preview-stage { position: relative; display: grid; place-items: center; height: min(66dvh, 720px); min-height: 0; overflow: hidden; background: var(--theme-bg); }
.asset-preview-stage > img { display: block; width: 100%; height: 100%; min-height: 0; min-width: 0; object-fit: contain; }
.asset-preview-stage > video { display: block; width: 100%; height: 100%; min-height: 0; object-fit: contain; }
.asset-preview-stage > iframe { display: block; width: 100%; height: 100%; min-height: 0; border: 0; background: white; }
.asset-preview-stage :deep(.cad-model-viewer) { width: 100%; height: 100%; min-height: 0; border-radius: 0; }
@media (max-width: 540px) { .asset-timeline { padding-left: 22px; }.asset-timeline-heading { margin-left: -22px; } }
.library-preview-error { display: flex; align-items: center; gap: 8px; color: var(--theme-text-muted); font-size: var(--ui-font-caption); }
.library-preview-error button { border: 0; background: transparent; color: var(--theme-accent-strong); }
.asset-preview-status { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: var(--theme-text-muted); font-size: var(--ui-font-control); }
.asset-preview-footer { border-top: 1px solid var(--theme-border); }.asset-preview-meta { display: grid; gap: 5px; min-width: 0; font-size: var(--ui-font-caption); color: var(--theme-text-muted); }.asset-preview-meta > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.asset-preview-meta small { font-size: var(--ui-font-caption); color: var(--theme-text-subtle); }.asset-preview-meta .asset-download-error { color: var(--theme-danger); }
.asset-download-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; flex-shrink: 0; padding: 10px 16px; border: 0; border-radius: var(--ui-radius-control); background: var(--theme-accent-strong); color: var(--theme-accent-foreground); font-size: var(--ui-font-control); min-height: var(--ui-control-height); }.asset-download-button:disabled { opacity: .65; cursor: wait; }
@media (max-width: 540px) { .asset-preview-dialog { width: calc(100vw - 24px); max-height: calc(100dvh - 24px); border-radius: var(--ui-radius-dialog); }.asset-preview-header, .asset-preview-footer { padding: 14px; gap: 10px; }.asset-download-button { padding: 10px 12px; font-size: var(--ui-font-control); border-radius: var(--ui-radius-control); min-height: var(--ui-control-height); } }
</style>
