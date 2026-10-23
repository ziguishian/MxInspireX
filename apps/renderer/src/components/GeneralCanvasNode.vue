<script setup lang="ts">
import FolderInputNode from './FolderInputNode.vue';
import { generationFailureText } from '../features/generationErrors';
import { nodeDeliveryFindings } from '../features/deliveryFindings';
import DeliveryFindings from './DeliveryFindings.vue';
import { computed, defineAsyncComponent, onUnmounted, ref, watch } from 'vue';
import { htmlPreviewDocument, HTML_PREVIEW_SCALE, HTML_PREVIEW_SANDBOX } from '../htmlPreview';
import { canExportNode, nodeMediaUrl, type NodeExportFormat } from '../nodeExport';
import { canvasNodeKind, nodePreviewSize, type NodePreviewSize } from '../nodeSizing';
import CanvasMarkdown from './CanvasMarkdown.vue';
import CanvasDrawingPad from './CanvasDrawingPad.vue';
import DesignNodeEditor from './DesignNodeEditor.vue';
import { Handle, Position, useVueFlow } from '@vue-flow/core';
import { CircleAlert, Box, FileText, Images, Music2, Video, Image, SquarePlay, AudioLines, Type, Upload, Pencil, Download, Minus, Plus, Check, X, SlidersHorizontal, Expand } from 'lucide-vue-next';
const CadPanel = defineAsyncComponent(() => import('./CadPanel.vue'));
const CanvasImagePreview = defineAsyncComponent(() => import('./CanvasImagePreview.vue'));
const imagePreviewOpen = ref(false);
const imagePreviewButton = ref<HTMLButtonElement | null>(null);
function openImagePreview() {
  imagePreviewButton.value?.focus({ preventScroll: true });
  imagePreviewOpen.value = true;
}
const cadPanelOpen = ref(false);
const ModelViewer = defineAsyncComponent(() => import('./ModelViewer.vue'));
const props = withDefaults(defineProps<{ data: Record<string, any>; nodeId?: string; canvasZoom?: number; selected?: boolean; exporting?: boolean; uploading?: boolean; busy?: boolean; deleteDrawing?: () => Promise<boolean> }>(), {
  selected: undefined, exporting: undefined, uploading: undefined, busy: undefined,
});
const { viewport } = useVueFlow('design-canvas');
const selected = computed(() => props.selected ?? props.data.selected);
const busy = computed(() => props.busy ?? props.data.busy);
const uploading = computed(() => props.uploading ?? props.data.uploading);
const emit = defineEmits<{ 'folder-upload': [files: File[]]; 'cad-updated': []; 'drawing-saved': [result: { projectId: string; node: Record<string, any> }]; 'drawing-dirty': [value: boolean]; reference: []; upload: [file: File]; update: [patch: Record<string, any>]; export: [format: NodeExportFormat]; cancel: [taskId: string]; 'context-menu': [position: { x: number; y: number }]; 'dismiss-menu': []; 'resize-start': []; resize: [size: NodePreviewSize]; 'resize-end': []; 'media-ratio': [media: { url: string; ratio: number }] }>();
const uploadInput = ref<HTMLInputElement | null>(null);
const editing = ref(false);
const textDraft = ref('');
const resizing = ref(false);
const asset = computed(() => props.data.asset || {});
const imageOutput = computed(() => asset.value.metadata?.imageOutput || {});
const findings = computed(() => nodeDeliveryFindings(props.data, props.nodeId));
const mediaUrl = computed(() => nodeMediaUrl(props.data));
const format = computed(() => props.data.kind === 'cad' ? 'glb' : String(asset.value.pathRelative || '').split('.').pop()?.toLowerCase() || '');
const kind = computed(() => canvasNodeKind(props.data));
const isDrawing = computed(() => props.data.editor === 'drawing');
const isDesignEditor = computed(() => ['palette', 'storyboard'].includes(props.data.editor));
const failed = ref(false);
const mediaPending = ref(false);
const naturalRatio = ref<number | null>(null);
const title = computed(() => props.data.title || props.data.label || '设计资产');
const content = computed(() => kind.value === 'html' ? props.data.html || '' : props.data.text || props.data.summary || '');
const htmlFrame = ref<HTMLIFrameElement | null>(null);
const htmlPreview = computed(() => htmlPreviewDocument(content.value, props.data.htmlAssets, true));
const exportDisabled = computed(() => (props.exporting ?? props.data.exporting) || !canExportNode(props.data));
function htmlContextMenu(event: MessageEvent) {
  const frame = htmlFrame.value;
  if (!frame || event.source !== frame.contentWindow) return;
  if (event.data?.type === 'aics:html-dismiss-menu') { emit('dismiss-menu'); return; }
  if (event.data?.type !== 'aics:html-context-menu') return;
  const { x, y } = event.data;
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > frame.clientWidth || y > frame.clientHeight) return;
  const rect = frame.getBoundingClientRect();
  emit('context-menu', { x: rect.left + x * rect.width / frame.clientWidth, y: rect.top + y * rect.height / frame.clientHeight });
}
window.addEventListener('message', htmlContextMenu);
onUnmounted(() => window.removeEventListener('message', htmlContextMenu));
const previewSize = computed(() => nodePreviewSize(props.data, naturalRatio.value));
const contentSizedText = computed(() => kind.value === 'text' && Boolean(content.value) && !editing.value && !loading.value);
const surfaceStyle = computed(() => contentSizedText.value ? undefined : { height: `${previewSize.value.height}px` });
const transparencyBorderStyle = computed(() => {
  const zoom = Math.max(.05, props.canvasZoom || viewport.value.zoom || 1);
  // Compensate for the canvas transform, with a slightly stronger outline when zoomed out.
  const screenWidth = Math.max(1.25, Math.min(3, 2 / Math.sqrt(zoom)));
  return { '--transparent-border-width': `${screenWidth / zoom}px` };
});
const loadingScale = computed(() => Math.max(.6, Math.min(4, Math.max(1, 1 / (props.canvasZoom || viewport.value.zoom || 1)), previewSize.value.width / 220, previewSize.value.height / 180)));
const loadingColumns = computed(() => Math.max(6, Math.min(52, Math.ceil(previewSize.value.width / 28))));
const recommendedSize = computed(() => nodePreviewSize({ ...props.data, previewSizingVersion: 2, previewSize: undefined }, naturalRatio.value));
const pageStyle = computed(() => ({ width: `${previewSize.value.width / HTML_PREVIEW_SCALE}px`, height: `${previewSize.value.height / HTML_PREVIEW_SCALE}px`, transform: `scale(${HTML_PREVIEW_SCALE})` }));
const resizeTitle = computed(() => {
  const scale = kind.value === 'html' ? HTML_PREVIEW_SCALE : 1;
  return `拖动调整${kindLabel.value}尺寸 · ${Math.round(previewSize.value.width / scale)} × ${Math.round(previewSize.value.height / scale)}；方向键微调，Shift 加速`;
});
let nodeResize: { pointerId: number; x: number; y: number; size: NodePreviewSize; zoom: number; handle: HTMLElement } | undefined;
const aspectLockedMedia = computed(() => ['image', 'video'].includes(kind.value));
function resizePreview(widthDelta: number, heightDelta: number) {
  const size = previewSize.value;
  // A corner drag still feels natural for media, while the image/video ratio
  // remains locked. Use the axis with the larger proportional adjustment.
  const width = aspectLockedMedia.value
    ? Math.abs(widthDelta / size.width) >= Math.abs(heightDelta / size.height)
      ? size.width + widthDelta
      : (size.height + heightDelta) * (naturalRatio.value || size.width / size.height)
    : size.width + widthDelta;
  const height = aspectLockedMedia.value ? width / (naturalRatio.value || size.width / size.height) : size.height + heightDelta;
  return nodePreviewSize({ ...props.data, previewSize: { width, height } }, naturalRatio.value);
}
function startNodeResize(event: PointerEvent) {
  if (event.button !== 0 || busy.value) return;
  event.preventDefault();
  const handle = event.currentTarget as HTMLElement;
  // Zoom affects the pointer-to-canvas conversion only at resize start; it
  // must not be a render dependency for image/video/HTML/Markdown content.
  nodeResize = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, size: previewSize.value, zoom: props.canvasZoom || viewport.value.zoom || 1, handle };
  handle.setPointerCapture(event.pointerId);
  resizing.value = true;
  emit('resize-start');
}
function moveNodeResize(event: PointerEvent) {
  if (!nodeResize || event.pointerId !== nodeResize.pointerId) return;
  emit('resize', resizePreview((event.clientX - nodeResize.x) / nodeResize.zoom, (event.clientY - nodeResize.y) / nodeResize.zoom));
}
function finishNodeResize() {
  if (!nodeResize) return;
  const previous = nodeResize; nodeResize = undefined;
  resizing.value = false;
  if (previous.handle.hasPointerCapture(previous.pointerId)) previous.handle.releasePointerCapture(previous.pointerId);
  emit('resize-end');
}
function resizeNodeWithKeyboard(event: KeyboardEvent) {
  if (busy.value || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault();
  event.stopPropagation();
  const step = event.shiftKey ? 80 : 20;
  emit('resize-start');
  const ratio = naturalRatio.value || previewSize.value.width / previewSize.value.height;
  const widthDelta = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : event.key === 'ArrowUp' ? -step * ratio : event.key === 'ArrowDown' ? step * ratio : 0;
  const heightDelta = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : event.key === 'ArrowLeft' ? -step / ratio : event.key === 'ArrowRight' ? step / ratio : 0;
  emit('resize', resizePreview(widthDelta, heightDelta));
  emit('resize-end');
}
function enlargeImageNode() {
  emit('resize-start');
  emit('resize', recommendedSize.value);
  emit('resize-end');
}
window.addEventListener('blur', finishNodeResize);
onUnmounted(() => { finishNodeResize(); window.removeEventListener('blur', finishNodeResize); });
const submitted = computed(() => !mediaUrl.value && props.data.status === '任务已提交'
  && !['failed', 'cancelled', 'succeeded', 'completed'].includes(props.data.job?.status));
const generating = computed(() => Boolean(props.data.generating || submitted.value));
const errorMessage = computed(() => {
  if (generating.value) return '';
  if (props.data.error) return props.data.status === '生成结果待确认' ? '生成结果待确认' : '生成失败';
  if (failed.value) return '素材暂时无法加载';
  return '';
});
const loading = computed(() => !errorMessage.value && (generating.value || mediaPending.value || uploading.value));
const empty = computed(() => !mediaUrl.value && !content.value && !loading.value && !errorMessage.value);
const textSize = computed(() => Number(props.data.textStyle?.fontSize) || 15);
const uploadAccept = computed(() => (({ image: 'image/*', video: 'video/*', audio: 'audio/*', text: '.txt,.md,.markdown,.csv,.json', html: '.html,.htm' } as Record<string, string>)[kind.value] || 'image/*'));
const kindLabel = computed(() => (({ image: '图像', video: '视频', audio: '音频', text: '文本', html: '网页', '3d': '3D', cad: 'CAD', upload: '素材', document: '文档' } as Record<string, string>)[kind.value] || '素材'));
watch(loading, value => { if (value) editing.value = false; });
const loadingLabel = computed(() => {
  if (uploading.value) return '正在上传…';
  if (kind.value === 'html' && generating.value) return '正在生成网页…';
  if (submitted.value && !props.data.generating) return '任务已提交，等待结果…';
  return generating.value ? '正在生成…' : '正在加载…';
});
watch([mediaUrl, kind], () => {
  failed.value = false;
  naturalRatio.value = null;
  mediaPending.value = Boolean(!isDrawing.value && mediaUrl.value && ['image', 'video', 'audio'].includes(kind.value));
}, { immediate: true });
function mediaReady(event: Event) {
  const element = event.target;
  if (element instanceof HTMLImageElement && element.naturalHeight) naturalRatio.value = element.naturalWidth / element.naturalHeight;
  if (element instanceof HTMLVideoElement && element.videoHeight) naturalRatio.value = element.videoWidth / element.videoHeight;
  if (naturalRatio.value) emit('media-ratio', { url: mediaUrl.value, ratio: naturalRatio.value });
  mediaPending.value = false;
}
function mediaFailed() { failed.value = true; mediaPending.value = false; }
function chooseUpload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) emit('upload', file);
  input.value = '';
}
function editText() { textDraft.value = content.value; editing.value = true; }
function saveText() { emit('update', { [kind.value === 'html' ? 'html' : 'text']: textDraft.value, summary: '', draft: false }); editing.value = false; }
function resizeText(delta: number) { emit('update', { textStyle: { ...props.data.textStyle, fontSize: Math.max(12, Math.min(28, textSize.value + delta)) } }); }
</script>
<template>
  <article class="design-asset-node is-preview" :style="transparencyBorderStyle" :class="{ 'is-empty': empty, 'is-transparent-image': kind === 'image' && imageOutput.hasTransparency === true, 'is-vector': asset.mime === 'image/svg+xml' || format === 'svg' || !!data.vectorSource, 'has-image': kind === 'image' && !!mediaUrl && !failed && !isDrawing }" :data-kind="kind" :data-selected="selected ? 'true' : 'false'" :aria-busy="loading">
    <header>
      <Pencil v-if="isDrawing" :size="15" /><Images v-else-if="kind === 'image'" :size="15" /><Video v-else-if="kind === 'video'" :size="15" /><Music2 v-else-if="kind === 'audio'" :size="15" /><Box v-else-if="['3d', 'cad'].includes(kind)" :size="15" /><FileText v-else :size="15" /><strong :title="title">{{ title }}</strong><small v-if="data.adopted" class="adopted-version-badge">已采用</small>
      <button v-if="kind === 'cad' && data.assetId" class="design-cad-action nodrag nowheel nopan" type="button" title="打开模型参数与导出" @pointerdown.stop @click.stop="cadPanelOpen = true"><SlidersHorizontal :size="13" />参数与导出</button>
      <button v-if="!isDrawing && kind === 'image' && mediaUrl && !failed && previewSize.width < recommendedSize.width" class="design-image-expand nodrag nowheel nopan" type="button" :disabled="busy" title="将节点调整为推荐尺寸，可撤销" @pointerdown.stop @click.stop="enlargeImageNode">放大节点</button>
      <button v-if="!isDrawing && kind === 'image' && mediaUrl && !failed" ref="imagePreviewButton" class="design-image-expand nodrag nowheel nopan" type="button" aria-label="查看大图" title="查看大图 · 也可双击图片" @pointerdown.stop @click.stop="openImagePreview"><Expand :size="13" />查看大图</button>
    </header>
    <div v-if="kind === 'html' && selected && !loading" class="design-text-tools nodrag nowheel" role="group" aria-label="网页工具" @click.stop>
      <button type="button" title="编辑 HTML" @click="editText"><Pencil :size="14" />源码</button>
      <button type="button" title="导出 HTML" :disabled="exportDisabled" @click="emit('export', 'html')"><Download :size="14" />导出 HTML</button>
      <button type="button" title="导出 PDF" :disabled="exportDisabled" @click="emit('export', 'pdf')"><Download :size="14" />导出 PDF</button>
    </div>
    <div v-if="kind === 'text' && !isDesignEditor && selected && !loading" class="design-text-tools nodrag nowheel" aria-label="文本工具" @click.stop>
      <button type="button" aria-label="编辑文本" title="编辑文本" @click="editText"><Pencil :size="14" /></button>
      <button type="button" aria-label="缩小文字" :disabled="textSize <= 12" @click="resizeText(-1)"><Minus :size="14" /></button>
      <span>{{ textSize }}</span><button type="button" aria-label="放大文字" :disabled="textSize >= 28" @click="resizeText(1)"><Plus :size="14" /></button>
      <button type="button" :aria-label="data.downloadable ? '下载文件' : '导出文本'" :title="data.downloadable ? '下载文件' : '导出文本'" :disabled="exportDisabled" @click="emit('export', 'original')"><Download :size="14" /></button>
    </div>
    <CadPanel v-if="cadPanelOpen" :api-base-url="data.apiBaseUrl" :project-id="data.projectId || asset.projectId" :asset-id="data.assetId" :node-id="nodeId" :busy="busy" @close="cadPanelOpen = false" @updated="emit('cad-updated')" />
    <div class="design-node-frame">
      <Handle id="input" type="target" :position="Position.Left" />
      <div class="design-node-surface" :class="{ 'is-loading': loading, 'has-error': errorMessage, 'is-placeholder': empty, 'is-text': kind === 'text', 'nodrag nowheel nopan': kind === 'html' }" :style="surfaceStyle">
        <DesignNodeEditor v-if="isDesignEditor" :data="data" :busy="busy" @update="emit('update', $event)" />
        <FolderInputNode v-if="data.workflowFolder" :entries="data.folderEntries || []" :busy="busy" @upload="emit('folder-upload', $event)" />
        <CanvasDrawingPad v-else-if="isDrawing && data.drawing" :drawing="data.drawing" :api-base-url="data.apiBaseUrl" :project-id="data.projectId" :node-id="nodeId!" :disabled="busy" :delete-node="deleteDrawing" @saved="emit('drawing-saved', $event)" @dirty="emit('drawing-dirty', $event)" @reference="emit('reference')" />
        <div v-else-if="editing" class="design-text-editor nodrag nowheel" @click.stop>
          <textarea v-model="textDraft" aria-label="编辑节点文本" :style="{ fontSize: `${textSize}px` }" @keydown.meta.enter.prevent="saveText" @keydown.ctrl.enter.prevent="saveText" />
          <div><button type="button" @click="editing = false"><X :size="13" />取消</button><button type="button" @click="saveText"><Check :size="13" />保存</button></div>
        </div>
        <div v-else-if="empty" class="design-node-placeholder">
          <Image v-if="kind === 'image'" :size="36" :stroke-width="1.6" /><SquarePlay v-else-if="kind === 'video'" :size="36" :stroke-width="1.6" /><AudioLines v-else-if="kind === 'audio'" :size="38" :stroke-width="1.7" /><Type v-else :size="38" :stroke-width="1.5" />
          <button v-if="kind !== 'cad'" class="design-node-upload nodrag nowheel" type="button" :aria-label="`上传${kindLabel}`" :disabled="busy" @click="uploadInput?.click()"><Upload :size="13" />上传{{ kindLabel }}</button>
          <small v-if="kind === 'cad'">选中后描述模型并提供尺寸，可添加参考图片</small>
          <small v-if="kind === 'text'">选中后输入生成，或使用上方工具编辑</small>
        </div>
        <iframe v-if="kind === 'html' && content && !editing" ref="htmlFrame" class="design-html-preview nodrag nowheel nopan" :style="pageStyle" :title="title" :srcdoc="htmlPreview" :sandbox="HTML_PREVIEW_SANDBOX" referrerpolicy="no-referrer" />
        <template v-if="!isDrawing && mediaUrl && !failed && kind !== 'html'">
          <img v-if="kind === 'image'" :key="mediaUrl" :src="mediaUrl" :alt="title" title="双击查看大图" draggable="false" @load="mediaReady" @error="mediaFailed" @dblclick.stop="openImagePreview" />
          <video v-else-if="kind === 'video'" :key="mediaUrl" class="nodrag nowheel" :src="mediaUrl" controls playsinline preload="metadata" @loadedmetadata="mediaReady" @error="mediaFailed" />
          <audio v-else-if="kind === 'audio'" :key="mediaUrl" class="nodrag nowheel" :src="mediaUrl" controls preload="metadata" @loadedmetadata="mediaReady" @error="mediaFailed" />
          <div v-else-if="['3d', 'cad'].includes(kind)" class="design-model-preview nodrag nowheel"><ModelViewer :key="mediaUrl" :asset-url="mediaUrl" :asset-format="format" :label="title" /></div>
          <a v-else :href="mediaUrl" target="_blank" rel="noopener" @click.stop>打开文档</a>
        </template>
        <CanvasMarkdown v-if="kind === 'text' && !isDesignEditor && !editing && content" class="design-asset-caption nodrag nowheel nopan" :content="content" :font-size="textSize" />
        <div v-if="loading" class="design-media-loading" :style="{ '--loading-scale': loadingScale }" role="status" aria-live="polite">
          <span class="design-loading-grid" aria-hidden="true"><i v-for="column in loadingColumns" :key="column" :style="{ '--wave-delay': `${column * -.14}s` }" /></span>
          <span class="design-media-loading-copy"><span class="design-media-dots" aria-hidden="true"><i /><i /></span><span>{{ loadingLabel }}</span></span>
          <button v-if="data.taskId" class="design-node-stop nodrag nowheel nopan" type="button" aria-label="停止这个节点的生成" @click.stop="emit('cancel', data.taskId)"><X :size="12" />停止</button>
        </div>
        <div v-else-if="errorMessage" class="design-media-error" role="status">
          <CircleAlert :size="20" /><span>{{ errorMessage }}</span><small v-if="data.error">{{ generationFailureText({ message: data.error, code: data.status === '生成结果待确认' ? 'image_result_unconfirmed' : '' }) }}</small>
        </div>
      </div>
      <Handle id="output" type="source" :position="Position.Right" />
      <button v-if="!contentSizedText" class="design-node-resize nodrag nowheel nopan" :class="{ 'design-html-resize': kind === 'html', 'is-resizing': resizing }" type="button" :aria-label="`调整${kindLabel}尺寸`" :title="resizeTitle" :disabled="busy" @pointerdown.stop="startNodeResize" @pointermove.stop="moveNodeResize" @pointerup.stop="finishNodeResize" @pointercancel.stop="finishNodeResize" @lostpointercapture="finishNodeResize" @keydown="resizeNodeWithKeyboard" @click.stop>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M3 9 9 3" /></svg>
      </button>
    </div>
    <p v-if="kind === 'image' && !loading && imageOutput.warning" class="image-output-status has-warning" role="status"><CircleAlert :size="13" />{{ imageOutput.warning }}</p>
    <p v-else-if="kind === 'image' && !loading && imageOutput.hasTransparency === true" class="image-output-status"><Check :size="13" />透明背景 · 已验证</p>
    <DeliveryFindings v-if="!loading && findings.length" class="nodrag nowheel nopan" :findings="findings" compact @pointerdown.stop @click.stop />
    <input ref="uploadInput" type="file" class="visually-hidden" :accept="uploadAccept" tabindex="-1" @change="chooseUpload" @click.stop />
    <CanvasImagePreview v-if="imagePreviewOpen && kind === 'image' && mediaUrl" :src="mediaUrl" :title="title" :downloading="exporting ?? data.exporting" :download-disabled="exportDisabled" @close="imagePreviewOpen = false" @download="emit('export', 'original')" />
  </article>
</template>

<style scoped>
.adopted-version-badge { color: #939393; font-size: 10px; white-space: nowrap; }
.design-node-stop{position:absolute;right:10px;bottom:10px;display:inline-flex;align-items:center;gap:3px;border:1px solid var(--theme-border);border-radius:8px;padding:5px 8px;background:var(--theme-surface-raised);color:var(--theme-text-muted);font-size:10px;cursor:pointer}.design-node-stop:hover{color:var(--theme-text);border-color:var(--theme-accent-strong)}
.image-output-status { display: flex; align-items: center; gap: 5px; margin: 0; padding: 8px 12px; color: var(--text-muted, #a9a9a9); font-size: 11px; line-height: 1.5; }
.image-output-status svg { flex-shrink: 0; }
.image-output-status.has-warning { color: #bbbbbb; }
.design-html-preview { display: block; border: 0; background: white; transform-origin: top left; }
.design-asset-node > header { cursor: inherit; }
.design-asset-node[data-kind="image"] > header strong { flex:1; min-width:0; }
.design-image-expand { display:inline-flex; align-items:center; flex-shrink:0; gap:4px; margin-left:auto; padding:3px 5px; border:0; border-radius:5px; background:transparent; color:var(--theme-text-muted); font:inherit; font-size:10px; cursor:pointer; }
.design-image-expand:hover, .design-image-expand:focus-visible { color:var(--theme-accent-strong); background:var(--theme-accent-soft); }
.design-asset-node[data-kind="cad"] > header strong { flex: 1; min-width: 0; }
.design-cad-action { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; gap: 5px; height: 26px; margin-left: 5px; padding: 0 9px; border: 1px solid var(--theme-border); border-radius: 7px; background: var(--theme-surface); color: var(--theme-text-muted); font: inherit; font-size: 11px; line-height: 1; white-space: nowrap; cursor: pointer; }
.design-cad-action:hover { border-color: var(--theme-border-strong); background: var(--theme-surface-hover); color: var(--theme-text); }
.design-cad-action:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 2px; }
.design-asset-node[data-kind="html"] .design-text-tools { width: max-content; }
.design-asset-node[data-kind="html"] .design-text-tools button { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; width: auto; height: 26px; padding: 0 9px; gap: 5px; border-radius: 999px; font: inherit; font-size: 11px; line-height: 1; white-space: nowrap; }
.design-asset-node[data-kind="html"] .design-text-tools button svg { flex: 0 0 auto; }
.design-node-frame { position: relative; }
.design-node-resize { position: absolute; bottom: 4px; right: 4px; z-index: 6; display: grid; place-items: center; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 3px; background: transparent; color: color-mix(in srgb, var(--theme-text-muted) 55%, transparent); box-shadow: none; cursor: nwse-resize; touch-action: none; opacity: 0; pointer-events: none; transition: opacity .15s ease; }
.design-asset-node:hover .design-node-resize:not(:disabled), .design-node-resize:focus-visible:not(:disabled), .design-node-resize.is-resizing { opacity: 1; pointer-events: auto; }
.design-node-resize:focus-visible { outline: 1px solid var(--theme-border-strong); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .design-node-resize { transition: none; } }
</style>
