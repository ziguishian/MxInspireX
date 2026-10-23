<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { modelDisplayName } from '../modelEconomy';
import ModelBrandIcon from './ModelBrandIcon.vue';
import AnchoredPopover from './composer/AnchoredPopover.vue';
import { ArrowUp, ChevronDown, Expand, Shrink, Lightbulb, Plus, SlidersHorizontal, X, WandSparkles, Palette, Video, LoaderCircle, Link2, FileText, Image, Music2 } from 'lucide-vue-next';
import { referenceImageIds, referenceProblem, type CanvasReference } from '../features/canvasReferences';
import { requestedMediaRatio } from '../nodeSizing';

const props = defineProps<{ kind: string; modelOptions?: string[]; videoModelOptions?: string[]; audioModelOptions?: string[]; textModelOptions?: string[]; generating?: boolean; params?: Record<string, any>; apiBaseUrl: string; projectId: string; nodeId?: string; referencePreviewUrl?: string; initialPrompt?: string; connectedReferences?: CanvasReference[] }>();
const emit = defineEmits<{ submit: [payload: { prompt: string; params: Record<string, any> }]; 'aspect-change': [aspect: string] }>();
const modelButton = ref<HTMLElement | null>(null);
const modelMenu = ref<HTMLElement | null>(null);
const showModelMenu = ref(false);
function dismissModelMenu(event: PointerEvent) {
  if (event.target instanceof Node && !modelButton.value?.contains(event.target) && !modelMenu.value?.contains(event.target)) showModelMenu.value = false;
}
onMounted(() => document.addEventListener('pointerdown', dismissModelMenu));
onUnmounted(() => document.removeEventListener('pointerdown', dismissModelMenu));
const prompt = ref(props.initialPrompt || '');
const model = ref(props.params?.model || '');
const style = ref(props.params?.style || '');
const imageAspects = ['1:1', '16:9', '9:16', '4:3', '3:4', '4:5', '5:4', '3:2', '2:3', '21:9'];
function savedAspect() {
  const ratio = requestedMediaRatio(props.params);
  return imageAspects.find(value => { const [w, h] = value.split(':').map(Number); return ratio && Math.abs(w / h - ratio) < .000001; })
    || props.params?.aspectRatio || props.params?.aspect_ratio || props.params?.aspect || '16:9';
}
const aspect = ref(savedAspect());
const resolution = ref(props.params?.resolution || (props.kind === 'video' ? '720p' : 'auto'));
const quality = ref(props.params?.quality || 'auto');
const background = ref(props.params?.background || 'auto');
const outputFormat = ref(props.params?.output_format || 'png');
const extendedQuality = computed(() => /gpt-image-2\.5(?:-|$)/i.test(model.value));
const duration = ref(Number.parseInt(props.params?.duration || '5'));
const camera = ref(props.params?.camera || '');
const voice = ref(props.params?.voice || '');
const referenceInput = ref<HTMLInputElement | null>(null);
const referenceAssetId = ref(props.params?.source_asset_id || '');
const preview = ref(props.referencePreviewUrl || (referenceAssetId.value ? `${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/assets/${encodeURIComponent(referenceAssetId.value)}/content` : ''));
const speed = ref(Number(props.params?.speed || 1));
const uploading = ref(false);
const error = ref('');
const assistance = ref<'templates' | 'helper' | null>(null);
const expanded = ref(false);
const settings = ref<'style' | 'camera' | 'settings' | null>(null);
const dragging = ref(false);
const imageKind = computed(() => ['image', 'upload'].includes(props.kind));
const aspectOptions = computed(() => [...new Set([...(imageKind.value ? imageAspects : imageAspects.slice(0, 5)), aspect.value])]);
const linkedReferences = computed(() => props.connectedReferences || []);
const imageIds = computed(() => referenceImageIds(linkedReferences.value, referenceAssetId.value));
const referenceIssue = computed(() => referenceProblem(props.kind, linkedReferences.value, imageIds.value));
const frameLabel = (assetId?: string) => props.kind === 'video' && assetId && imageIds.value.includes(assetId) ? (imageIds.value.indexOf(assetId) === 0 ? '首帧' : '尾帧') : '';
const failedPreviews = ref<Record<string, string>>({});
const nodeDraftKey = props.nodeId ? `langjuart.nodeDraft.${props.projectId}.${props.nodeId}` : '';
const draftFields = { prompt, model, style, aspect, resolution, quality, background, outputFormat, duration, camera, voice, speed, referenceAssetId };
try {
  const saved = nodeDraftKey ? JSON.parse(localStorage.getItem(nodeDraftKey) || 'null') : null;
  if (saved && typeof saved === 'object') for (const [key, field] of Object.entries(draftFields)) if (typeof saved[key] === typeof field.value) field.value = saved[key];
  // Older builds persisted their implicit high default as if the user had
  // selected it. Empty nodes without an explicit saved node parameter migrate
  // to the new automatic creative tier.
  if (!props.params?.quality && saved?.quality === 'high') quality.value = 'auto';
  if (referenceAssetId.value) preview.value = `${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/assets/${encodeURIComponent(referenceAssetId.value)}/content`;
} catch { /* Ignore malformed or unavailable local draft storage. */ }
watch(Object.values(draftFields), () => {
  if (!nodeDraftKey) return;
  try { localStorage.setItem(nodeDraftKey, JSON.stringify(Object.fromEntries(Object.entries(draftFields).map(([key, field]) => [key, field.value])))); }
  catch { error.value = '节点草稿暂未保存，请保留当前页面'; }
}, { flush: 'sync' });
// Follow normalized output parameters while preserving a different unsent choice.
watch(savedAspect, (value, previous) => { if (aspect.value === previous) aspect.value = value; });

// The panel stays mounted while hidden. An upload to the preview card must
// update its reference too, without replacing unsent prompt/parameter drafts.
watch(() => [props.params?.source_asset_id, props.referencePreviewUrl] as const, ([assetId, url], previous) => {
  if (assetId === previous?.[0] && url === previous?.[1]) return;
  referenceAssetId.value = assetId || '';
  preview.value = url || (assetId ? `${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/assets/${encodeURIComponent(assetId)}/content` : '');
});

const visual = computed(() => props.kind === 'image' || props.kind === 'video' || props.kind === 'upload' || props.kind === 'cad');
const referenceAccept = computed(() => visual.value ? 'image/*' : '.txt,.md,.markdown');
const referenceLabel = computed(() => visual.value ? '上传参考图' : '导入参考文字');
const placeholder = computed(() => props.kind === 'cad' ? '描述产品结构、尺寸（mm）和孔位，可添加参考图片…' : props.kind === 'audio' ? '输入要朗读的文字，选择音色与语速…' : ['text', 'html'].includes(props.kind) ? (props.kind === 'html' ? '描述网页的布局、内容、风格与交互…' : '描述你想生成或修改的内容…') : '拖入或粘贴参考图，描述你想创作的画面…');
const settingsLabel = computed(() => props.kind === 'audio' ? `${voice.value || '默认音色'} · ${speed.value}×` : [aspect.value, props.kind === 'video' && `${duration.value}s`, resolution.value].filter(Boolean).join(' · '));
function toggleSettings(value: 'style' | 'camera' | 'settings') { settings.value = settings.value === value ? null : value; }
const label = computed(() => ({ image: '图像', video: '视频', audio: '音频', text: '文本', html: '网页', cad: 'CAD 模型', upload: '图像' }[props.kind] || '内容'));
const options = computed(() => props.kind === 'video' ? (props.videoModelOptions || []) : ['text', 'html', 'cad'].includes(props.kind) ? (props.textModelOptions || []) : props.kind === 'audio' ? (props.audioModelOptions || []) : (props.modelOptions || []));
const templates = computed(() => props.kind === 'cad' ? ['制作 80×50×8 mm 的底座，四角各有一个直径 5 mm 的通孔。', '参考图片设计外壳，宽 80 mm，壁厚 2 mm，保留可修改参数。'] : props.kind === 'html' ? ['生成品牌产品展示网页，包含首屏、特色、产品卡片和交互按钮。', '制作交互式数据看板，支持筛选与图表展示。'] : props.kind === 'video' ? ['产品展示短片：主体、使用场景、镜头运动和收尾特写。', '从参考图延展场景，保持主体一致，镜头缓慢推进。'] : ['text', 'html'].includes(props.kind) ? ['撰写一份设计说明，包含目标、受众、设计亮点与应用场景。', '根据参考资料整理三个方案方向，并比较优缺点。'] : props.kind === 'audio' ? ['用自然清晰的语气朗读以下内容：', '欢迎来到我们的产品展示。接下来，为你介绍设计的亮点。'] : ['产品棚拍：主体居中，柔和光线，纯净背景，突出材质细节。', '创作一套年轻化插画，主题明确，配色协调，适用于品牌传播。']);
function applyTemplate(value: string) { prompt.value = value; assistance.value = null; }
function addDetail(value: string) { prompt.value = `${prompt.value.trim()}\n${value}：`.trimStart(); }
async function uploadReference(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) await readReference(file);
  (event.target as HTMLInputElement).value = '';
}
async function readReference(file: File) {
  if (uploading.value || props.generating) return;
  uploading.value = true; error.value = '';
  try {
    if (!visual.value) {
      prompt.value = [prompt.value.trim(), await file.text()].filter(Boolean).join('\n\n');
      return;
    }
    if (!file.type.startsWith('image/')) throw new Error('请添加图像文件作为参考');
    const form = new FormData(); form.append('file', file); form.append('kind', 'image');
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/assets/upload`, { method: 'POST', body: form });
    if (!response.ok) throw new Error(await response.text());
    const asset = await response.json(); referenceAssetId.value = asset.id;
    preview.value = `${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/assets/${encodeURIComponent(asset.id)}/content`;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '参考图上传失败'; }
  finally { uploading.value = false; }
}
function dropReference(event: DragEvent) { dragging.value = false; const file = event.dataTransfer?.files[0]; if (file) void readReference(file); }
function pasteReference(event: ClipboardEvent) { const file = event.clipboardData?.files[0]; if (file && visual.value) { event.preventDefault(); void readReference(file); } }
function submit() {
  if (!prompt.value.trim() || props.generating || uploading.value || referenceIssue.value) return;
  error.value = '';
  if (props.kind === 'video' && (!Number.isInteger(duration.value) || duration.value < 1 || duration.value > 60)) { error.value = '请输入 1–60 的整数秒视频时长'; return; }
  if (props.kind === 'audio' && (!Number.isFinite(speed.value) || speed.value < .25 || speed.value > 4)) { error.value = '请将语速设置为 0.25–4 倍'; return; }
  const params: Record<string, any> = { model: model.value };
  if (referenceAssetId.value) params.source_asset_id = referenceAssetId.value;
  if (visual.value && props.kind !== 'cad') Object.assign(params, { style: style.value, aspectRatio: aspect.value,
    ...(resolution.value !== 'auto' ? { resolution: resolution.value } : {}) });
  if (imageKind.value) Object.assign(params, {
    ...(quality.value !== 'auto' ? { quality: !extendedQuality.value && ['xhigh', 'max'].includes(quality.value) ? 'high' : quality.value } : {}),
    background: background.value,
    output_format: background.value === 'transparent' && outputFormat.value === 'jpeg' ? 'png' : outputFormat.value,
  });
  if (props.kind === 'video') Object.assign(params, { duration: duration.value, camera: camera.value });
  if (props.kind === 'audio') Object.assign(params, { voice: voice.value.trim(), speed: speed.value });
  emit('submit', { prompt: prompt.value.trim(), params });
}
</script>
<template>
  <section class="canvas-prompt-panel nodrag nowheel" :class="{ 'is-expanded': expanded, 'is-dragging': dragging }" :aria-label="`${label}节点输入框`" @click.stop @dblclick.stop @contextmenu.stop @dragover.prevent="dragging = true" @dragleave.self="dragging = false" @drop.prevent.stop="dropReference">
    <header><span>{{ kind === 'text' ? '内容创作' : '提示词' }}</span><div><button type="button" :aria-expanded="assistance === 'templates'" @click="assistance = assistance === 'templates' ? null : 'templates'"><Lightbulb :size="13" />模板</button><button type="button" :aria-expanded="assistance === 'helper'" @click="assistance = assistance === 'helper' ? null : 'helper'"><WandSparkles :size="13" />提示词助手</button><button type="button" class="prompt-expand" :aria-label="expanded ? '收起输入区' : '展开输入区'" @click="expanded = !expanded"><Shrink v-if="expanded" :size="13" /><Expand v-else :size="13" /></button></div></header>
    <div v-if="assistance === 'templates'" class="prompt-assistance"><button v-for="item in templates" :key="item" @click="applyTemplate(item)">{{ item }}</button></div>
    <div v-if="assistance === 'helper'" class="prompt-assistance"><span>补充这些细节，让结果更贴近你的目标</span><div><button v-for="item in (kind === 'text' ? ['目标', '受众', '语气', '篇幅'] : kind === 'audio' ? ['开场白', '正文', '结束语'] : ['主体', '场景', '风格', '光线'])" :key="item" @click="addDetail(item)">{{ item }} +</button></div></div>
    <div class="canvas-prompt-tools" aria-label="节点参考素材">
      <button type="button" class="prompt-plus" :aria-label="referenceLabel" :disabled="uploading || generating" @click="referenceInput?.click()"><Plus :size="18" /></button>
      <span v-if="preview" class="prompt-reference-image" :title="frameLabel(referenceAssetId) || '添加的参考图'"><img :src="preview" :alt="frameLabel(referenceAssetId) || '节点参考图'" /><button type="button" aria-label="移除参考图" @click="preview = ''; referenceAssetId = ''"><X :size="10" /></button></span>
      <div v-for="reference in linkedReferences" :key="reference.nodeId" class="prompt-linked-reference" :class="{ 'is-pending': reference.status !== 'ready' }" :data-reference-node="reference.nodeId" :title="`${reference.title} · 连线参考${reference.text ? '\n' + reference.text.slice(0, 240) : ''}`">
        <img v-if="reference.assetId && ['image', 'upload'].includes(reference.kind) && failedPreviews[reference.nodeId] !== reference.previewUrl" :src="reference.previewUrl" :alt="reference.title" @error="failedPreviews[reference.nodeId] = reference.previewUrl || ''" />
        <div v-else class="linked-reference-placeholder"><LoaderCircle v-if="reference.status === 'generating'" :size="18" class="spin-icon" /><Video v-else-if="reference.kind === 'video'" :size="18" /><Music2 v-else-if="reference.kind === 'audio'" :size="18" /><Image v-else-if="['image', 'upload'].includes(reference.kind)" :size="18" /><FileText v-else :size="18" /><span v-if="reference.text">{{ reference.text }}</span></div>
        <span class="linked-reference-caption"><Link2 :size="10" /><span>{{ frameLabel(reference.assetId) ? `${frameLabel(reference.assetId)} · ` : '' }}{{ reference.title }}</span></span>
      </div>
      <small v-if="uploading">正在读取…</small>
    </div>
    <p v-if="linkedReferences.length || kind === 'video' && imageIds.length" class="prompt-reference-status" :class="{ 'has-issue': referenceIssue }" aria-live="polite">{{ referenceIssue || (kind === 'video' && imageIds.length ? (imageIds.length === 2 ? '按参考顺序：第一张首帧，第二张尾帧' : '当前参考图作为首帧') : `已连接 ${linkedReferences.length} 个素材，将作为生成参考`) }}</p>
    <p class="prompt-delivery-summary" aria-live="polite">{{ generating ? '正在生成' : '本次生成' }}：1 项{{ label }}<span v-if="imageIds.length"> · {{ imageIds.length }} 张参考图</span><span v-if="linkedReferences.some(item => item.text.trim())"> · 含上游文字</span></p>
    <input ref="referenceInput" type="file" class="visually-hidden" :accept="referenceAccept" tabindex="-1" @change="uploadReference" />
    <textarea v-model="prompt" :aria-label="`${label}节点提示词`" :placeholder="placeholder" @paste="pasteReference" @keydown.meta.enter.prevent="submit" @keydown.ctrl.enter.prevent="submit" />
    <div v-if="settings" class="prompt-options" :aria-label="settings === 'style' ? '风格设置' : settings === 'camera' ? '镜头设置' : '生成参数'">
      <div class="prompt-options-heading"><span>{{ settings === 'style' ? '画面风格' : settings === 'camera' ? '镜头运动' : '生成参数' }}</span><button type="button" aria-label="关闭参数" @click="settings = null"><X :size="13" /></button></div>
      <div class="prompt-advanced-grid">
        <label v-if="settings === 'style'">风格<input v-model="style" placeholder="写实、插画、电影感…" /></label>
        <label v-else-if="settings === 'camera'">镜头<select v-model="camera"><option value="">跟随描述</option><option>静态</option><option>推近</option><option>拉远</option><option>横移</option><option>环绕</option></select></label>
        <template v-else>
          <template v-if="visual && kind !== 'cad'"><label>画幅<select v-model="aspect" :disabled="generating" @change="emit('aspect-change', aspect)"><option v-for="value in aspectOptions" :key="value">{{ value }}</option></select></label><label>分辨率<select v-model="resolution"><template v-if="imageKind"><option value="auto">自动（创意 1K）</option><option>1K</option><option>2K</option><option>4K</option></template><template v-else><option>720p</option><option>1080p</option><option>4K</option></template></select></label></template>
          <template v-if="imageKind">
            <label>质量<select v-model="quality"><option value="auto">自动</option><option value="low">快速</option><option value="medium">标准</option><option value="high">高质量</option><template v-if="extendedQuality"><option value="xhigh">超高质量</option><option value="max">最高质量</option></template></select></label>
            <label>背景<select v-model="background" aria-label="图像背景" @change="background === 'transparent' && outputFormat === 'jpeg' && (outputFormat = 'png')"><option value="auto">自动识别</option><option value="transparent">透明背景</option><option value="opaque">不透明背景</option></select></label>
            <label>输出格式<select v-model="outputFormat" aria-label="图像输出格式"><option value="png">PNG</option><option value="webp">WebP</option><option v-if="background !== 'transparent'" value="jpeg">JPEG</option></select></label>
            <small v-if="background === 'transparent'" class="prompt-background-hint">需要支持透明输出的 GPT Image 模型；生成后校验透明通道。</small>
          </template>
          <label v-if="kind === 'video'">时长（秒）<input v-model.number="duration" type="number" min="1" max="60" /></label>
          <template v-if="kind === 'audio'"><label>音色<input v-model="voice" placeholder="留空使用服务默认音色" /></label><label>语速<input v-model.number="speed" type="number" min="0.25" max="4" step="0.25" /></label></template>
        </template>
      </div>
    </div>
    <p v-if="error" role="alert" class="prompt-error">{{ error }}</p>
    <footer>
      <button ref="modelButton" type="button" class="prompt-model-trigger" :aria-label="`${label}模型`" aria-haspopup="dialog" :aria-expanded="showModelMenu" @click.stop="showModelMenu = !showModelMenu"><ModelBrandIcon :model="model || ''" /><span>{{ model ? modelDisplayName(model) : '自动选择模型' }}</span><ChevronDown :size="11" /></button>
      <AnchoredPopover v-if="showModelMenu" :anchor="modelButton" :label="`选择${label}模型`" @close="showModelMenu = false">
        <div ref="modelMenu" class="canvas-model-options nodrag nowheel"><button v-for="item in ['', ...options]" :key="item" type="button" :aria-pressed="model === item" @click.stop="model = item; showModelMenu = false; modelButton?.focus()"><ModelBrandIcon :model="item" /><span>{{ item ? modelDisplayName(item) : '自动选择模型' }}</span></button></div>
      </AnchoredPopover>
      <button v-if="visual && kind !== 'cad'" class="prompt-footer-tool" type="button" :aria-expanded="settings === 'style'" @click="toggleSettings('style')"><Palette :size="13" />风格</button>
      <button v-if="kind === 'video'" class="prompt-footer-tool" type="button" :aria-expanded="settings === 'camera'" @click="toggleSettings('camera')"><Video :size="13" />镜头</button>
      <button v-if="['image', 'upload', 'video', 'audio'].includes(kind)" class="prompt-footer-tool prompt-settings-toggle" type="button" aria-label="生成参数" :aria-expanded="settings === 'settings'" @click="toggleSettings('settings')"><SlidersHorizontal :size="13" /><span>{{ settingsLabel }}</span></button>
      <button class="prompt-submit" type="button" :disabled="!prompt.trim() || generating || uploading || !!referenceIssue" :aria-label="`生成${label}`" :title="referenceIssue || `生成${label} · ⌘ / Ctrl + Enter`" @click="submit"><LoaderCircle v-if="generating" :size="16" class="spin-icon" /><ArrowUp v-else :size="16" /></button>
    </footer>
  </section>
</template>
<style scoped>
.prompt-model-trigger { display: flex; align-items: center; gap: 6px; max-width: 240px; min-width: 0; padding: 6px; border: 0; border-radius: 8px; background: transparent; color: var(--theme-text); font-size: 13px; }
.prompt-model-trigger > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.canvas-model-options { max-height: 320px; overflow: auto; scrollbar-width: thin; }
.canvas-model-options button { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; padding: 8px; border: 0; border-radius: 8px; background: transparent; color: var(--theme-text); text-align: left; font-size: 13px; overflow-wrap: anywhere; }
.canvas-model-options button[aria-pressed="true"], .canvas-model-options button:hover { background: var(--theme-surface-hover); }
.prompt-background-hint { grid-column: 1 / -1; color: var(--text-muted, #a9a9a9); font-size: 11px; line-height: 1.5; }
.canvas-prompt-tools { flex-wrap: wrap; align-items: center; gap: 8px; max-height: 168px; overflow-y: auto; padding: 6px 4px; }
.prompt-linked-reference { position: relative; width: 76px; height: 60px; flex: 0 0 76px; overflow: hidden; border: 1px solid var(--theme-border); border-radius: 9px; background: var(--theme-surface); }
.prompt-linked-reference > img { width: 100%; height: 100%; object-fit: cover; }
.linked-reference-placeholder { display: flex; height: 100%; align-items: center; justify-content: center; padding: 5px 6px 18px; gap: 4px; color: var(--theme-text-muted); }
.linked-reference-placeholder > svg { flex-shrink: 0; }
.linked-reference-placeholder > span { overflow: hidden; font-size: 8px; line-height: 1.4; max-height: 32px; }
.linked-reference-caption { position: absolute; inset: auto 0 0; display: flex; align-items: center; gap: 4px; padding: 3px 5px; background: rgba(19, 19, 19, .86); color: #e0e0e0; font-size: 9px; }
.linked-reference-caption > svg { flex-shrink: 0; color: var(--theme-accent); }
.linked-reference-caption > span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.prompt-linked-reference.is-pending { border-style: dashed; }
.prompt-reference-status { margin: 0 0 7px; font-size: 10px; line-height: 1.5; color: var(--theme-text-muted); }
.prompt-reference-status.has-issue { color: #bbbbbb; }
.prompt-delivery-summary { margin: 0 0 7px; color: var(--theme-text-muted); font-size: var(--ui-font-caption); line-height: 1.5; }
</style>
