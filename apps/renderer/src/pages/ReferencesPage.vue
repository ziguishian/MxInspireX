<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { ArrowUpRight, ImagePlus, Link, Plus, X, Trash2, RefreshCw, Check } from 'lucide-vue-next';
import { RouterLink } from 'vue-router';
import LibraryPageLayout from '../components/shared/LibraryPageLayout.vue';
import EmptyState from '../components/shared/EmptyState.vue';
import BrandLoading from '../components/BrandLoading.vue';
import InfiniteScrollStatus from '../components/shared/InfiniteScrollStatus.vue';
import MasonryGrid from '../components/shared/MasonryGrid.vue';
import { assetLibraryServices } from '../features/pageServices';
import { referenceRequest, referenceUrl, type DesignLesson, type VisualReference } from '../features/references';
const { apiBaseUrl } = assetLibraryServices.use();
const items = ref<VisualReference[]>([]), total = ref(0), query = ref(''), industry = ref(''), designType = ref('');
const categories = ref<{ id: string; dimension: string; name: string }[]>([]);
const busy = ref(false), loading = ref(true), loadingMore = ref(false), refreshing = ref(false), error = ref(''), notice = ref(''), link = ref(''), showLink = ref(false);
const fileInput = ref<HTMLInputElement>(), detail = ref<VisualReference>(), tags = ref(''), deleteTarget = ref<VisualReference>();
const categoryName = ref(''), categoryDimension = ref('industry'), showCategory = ref(false);
const lessons = ref<DesignLesson[]>([]);
const industries = computed(() => categories.value.filter(c => c.dimension === 'industry'));
const types = computed(() => categories.value.filter(c => c.dimension === 'designType'));
const referenceBatchSize = 24;
const hasMore = computed(() => items.value.length < total.value);
let timer: ReturnType<typeof setInterval>, debounce: ReturnType<typeof setTimeout>, loadVersion = 0;
const api = <T,>(path: string, init?: RequestInit) => referenceRequest<T>(apiBaseUrl, path, init);
const json = (method: string, body: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
async function load(reset = true) {
  if (!reset && (loading.value || loadingMore.value || refreshing.value || !hasMore.value)) return;
  const version = reset ? ++loadVersion : loadVersion;
  const offset = reset ? 0 : items.value.length;
  if (reset) { loading.value = true; loadingMore.value = false; }
  else loadingMore.value = true;
  try {
    const result = await api<{ items: VisualReference[]; total: number }>(`?${new URLSearchParams({ q: query.value, industry: industry.value, design_type: designType.value, offset: String(offset), limit: String(referenceBatchSize) })}`);
    if (version === loadVersion) {
      items.value = reset ? result.items : [...items.value, ...result.items.filter(item => !items.value.some(existing => existing.id === item.id))];
      total.value = result.total; error.value = '';
    }
  } catch (cause) { if (version === loadVersion) error.value = String(cause instanceof Error ? cause.message : cause); }
  finally {
    if (version === loadVersion) {
      if (reset) loading.value = false;
      else loadingMore.value = false;
    }
  }
}
async function loadLessons() {
  try { lessons.value = (await api<{ items: DesignLesson[] }>('/lessons?limit=24')).items; } catch { /* Reference images remain usable if lessons are unavailable. */ }
}
async function deleteLesson(lesson: DesignLesson) {
  await operate(async () => {
    await api(`/lessons/${lesson.id}`, { method: 'DELETE' });
    lessons.value = lessons.value.filter(item => item.id !== lesson.id);
    notice.value = '已删除工作区设计经验';
  });
}
async function refreshLoaded() {
  if (loading.value || loadingMore.value || refreshing.value || !items.value.length) return;
  const version = loadVersion;
  refreshing.value = true;
  try {
    const refreshed: VisualReference[] = [];
    let refreshedTotal = total.value;
    for (let offset = 0; offset < items.value.length; offset += 100) {
      const limit = Math.min(100, items.value.length - offset);
      const result = await api<{ items: VisualReference[]; total: number }>(`?${new URLSearchParams({ q: query.value, industry: industry.value, design_type: designType.value, offset: String(offset), limit: String(limit) })}`);
      if (version !== loadVersion) return;
      refreshed.push(...result.items); refreshedTotal = result.total;
    }
    if (version === loadVersion) { items.value = refreshed; total.value = refreshedTotal; error.value = ''; }
  } catch (cause) { if (version === loadVersion) error.value = String(cause instanceof Error ? cause.message : cause); }
  finally { refreshing.value = false; }
}
async function operate(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ''; notice.value = '';
  try { await action(); await load(true); } catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败'; }
  finally { busy.value = false; }
}
async function upload(files: File[]) {
  if (!files.length) return;
  await operate(async () => {
    const data = new FormData(); files.forEach(file => data.append('files', file));
    const result = await api<{ items: VisualReference[]; errors: { message: string }[] }>('/upload', { method: 'POST', body: data });
    notice.value = `已保存 ${result.items.length} 张参考图` + (result.errors.length ? `；${result.errors.map(e => e.message).join('；')}` : '，正在整理视觉标签');
  });
}
function paste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || []);
  if (files.length) { event.preventDefault(); void upload(files); }
}
let detailTrigger: HTMLElement | null = null;
watch(() => Boolean(detail.value), async visible => { if (visible) { detailTrigger = document.activeElement as HTMLElement; await nextTick(); document.querySelector<HTMLButtonElement>('.reference-close')?.focus(); } else detailTrigger?.focus(); });
let deleteTrigger: HTMLElement | null = null;
watch(() => Boolean(deleteTarget.value), async visible => { if (visible) { deleteTrigger = document.activeElement as HTMLElement; await nextTick(); document.querySelector<HTMLButtonElement>('.reference-delete-cancel')?.focus(); } else deleteTrigger?.focus(); });
function open(item: VisualReference) { detail.value = JSON.parse(JSON.stringify(item)); tags.value = (item.tags || []).join('，'); }
function requestDelete(item: VisualReference) { deleteTarget.value = item; }
async function confirmDelete() {
  const target = deleteTarget.value;
  if (!target) return;
  await operate(async () => {
    await api(`/${target.id}`, { method: 'DELETE' });
    if (detail.value?.id === target.id) detail.value = undefined;
    deleteTarget.value = undefined;
    notice.value = '已删除参考图';
  });
}
function toggle(key: 'industries' | 'designTypes', value: string) {
  if (!detail.value) return;
  const selected = detail.value[key] || [];
  detail.value[key] = selected.includes(value) ? selected.filter(v => v !== value) : [...selected, value];
}
async function saveDetail() {
  if (!detail.value) return;
  const item = detail.value;
  await operate(async () => {
    await api(`/${item.id}`, json('PATCH', { title: item.title, industries: item.industries || [], designTypes: item.designTypes || [], tags: tags.value.split(/[,，]/).map(t => t.trim()).filter(Boolean), description: item.description || '', notes: item.notes || '', author: item.author || '', rightsStatus: item.rightsStatus || 'unknown' }));
    detail.value = undefined; notice.value = '已保存参考信息';
  });
}
watch([query, industry, designType], () => {
  loadVersion++; items.value = []; total.value = 0; loading.value = true;
  clearTimeout(debounce); debounce = setTimeout(() => void load(true), 250);
});
onMounted(async () => {
  await load(true);
  try { categories.value = await api('/categories'); } catch { error.value = '分类读取失败，请重试'; }
  await loadLessons();
  timer = setInterval(() => { if (!detail.value && items.value.some(i => ['pending', 'running'].includes(i.analysisStatus))) void refreshLoaded(); }, 4000);
});
onBeforeUnmount(() => { clearInterval(timer); clearTimeout(debounce); loadVersion++; });
</script>

<template>
  <LibraryPageLayout v-model:search="query" class="reference-page" eyebrow="REFERENCES / VISUAL LIBRARY" title="参考库" description="收藏视觉灵感，让每次设计从喜欢的方向开始。" search-label="搜索参考" search-placeholder="搜索行业、配色、材质或风格…" @paste="paste" @dragover.prevent @drop.prevent="upload(Array.from($event.dataTransfer?.files || []))">
    <template #actions>
      <button class="primary-button" :disabled="busy" @click="fileInput?.click()"><ImagePlus :size="16" />{{ busy ? '正在处理…' : '上传参考图' }}</button>
      <button class="ghost-button" :aria-expanded="showLink" @click="showLink = !showLink"><Link :size="16" />导入作品链接</button>
      <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden @change="upload(Array.from(($event.target as HTMLInputElement).files || [])); ($event.target as HTMLInputElement).value = ''" />
    </template>
    <template #meta><span>共 {{ total }} 张参考图</span><RouterLink to="/references/legacy">历史资料 <ArrowUpRight :size="13" /></RouterLink></template>
    <template #filters>
      <select v-model="industry" aria-label="按行业筛选"><option value="">所有行业</option><option v-for="c in industries" :key="c.id">{{ c.name }}</option></select>
      <select v-model="designType" aria-label="按设计类型筛选"><option value="">所有设计类型</option><option v-for="c in types" :key="c.id">{{ c.name }}</option></select>
      <button class="ghost-button" :aria-expanded="showCategory" @click="showCategory = !showCategory"><Plus :size="16" />分类</button>
    </template>
    <form v-if="showLink" class="reference-inline" @submit.prevent="operate(async () => { const result = await api<{items:VisualReference[];errors:{message:string}[]}>('/import-url', json('POST', {url:link})); notice = `已导入 ${result.items.length} 张图片` + (result.errors.length ? '；部分图片无法读取' : ''); link = ''; })"><input v-model="link" type="url" required placeholder="粘贴 Pinterest、Behance 或公开作品页面链接" aria-label="作品链接" /><button :disabled="busy" class="primary-button">导入</button></form>
    <form v-if="showCategory" class="reference-inline" @submit.prevent="operate(async () => { categories = await api('/categories', json('POST', {dimension:categoryDimension,name:categoryName})); categoryName = ''; showCategory = false; })"><select v-model="categoryDimension" aria-label="分类维度"><option value="industry">行业</option><option value="designType">设计类型</option></select><input v-model="categoryName" required maxlength="50" placeholder="新分类名称" aria-label="新分类名称" /><button class="primary-button" :disabled="busy">添加</button></form>
    <p v-if="error" class="reference-error" role="alert">{{ error }} <button @click="load(true)">重试</button></p><p v-if="notice" class="reference-notice" role="status">{{ notice }}</p>
    <section v-if="lessons.length" class="reference-lessons" aria-label="工作区设计经验">
      <div><h2>工作区设计经验</h2><p>只沉淀用户已确认的策略与避坑提示；不会保存项目素材、客户信息或原始提示词。</p></div>
      <ul><li v-for="lesson in lessons" :key="lesson.id"><span><strong>{{ lesson.strategy }}</strong><small v-if="lesson.avoid.length">避坑：{{ lesson.avoid.join('；') }}</small><em>{{ lesson.tags.join(' · ') || lesson.mediaKind }}</em></span><button type="button" :disabled="busy" @click="deleteLesson(lesson)">删除</button></li></ul>
    </section>
    <BrandLoading v-if="loading" label="正在读取本地参考…" />
    <EmptyState v-else-if="!items.length" :icon="ImagePlus" :title="query || industry || designType ? '没有找到匹配参考' : '从一张喜欢的图片开始'">上传设计案例、包装或灵感图片，整理为可随时取用的视觉参考。<template #action><button class="ghost-button" @click="fileInput?.click()">添加参考图</button></template></EmptyState>
    <MasonryGrid v-else class="reference-grid">
      <article v-for="item in items" :key="item.id" class="reference-tile">
        <button type="button" class="reference-tile-open" :aria-label="`查看参考 ${item.title}`" @click="open(item)">
          <div class="reference-image"><img :src="referenceUrl(apiBaseUrl,item.thumbnailUrl)" :alt="item.title" loading="lazy" /></div>
          <div class="reference-tile-body"><h3>{{ item.title }}</h3><p>{{ [...(item.industries || []), ...(item.designTypes || [])].join(' · ') || '待分类' }}</p><div class="reference-tags"><span v-for="tag in (item.tags || []).slice(0,3)" :key="tag">{{ tag }}</span><small v-if="['pending','running'].includes(item.analysisStatus)">整理标签中</small><small v-else-if="['failed','interrupted'].includes(item.analysisStatus)">可手动分类</small></div></div>
        </button>
        <button type="button" class="reference-tile-delete" :aria-label="`删除参考 ${item.title}`" :title="`删除 ${item.title}`" :disabled="busy" @click.stop="requestDelete(item)"><Trash2 :size="16" /></button>
      </article>
    </MasonryGrid>
    <InfiniteScrollStatus v-if="items.length" :has-more="hasMore" :loading="loadingMore" :loaded="items.length" :total="total" item-label="张参考图" @load-more="load(false)" />
    <Teleport to="body"><div v-if="detail" class="reference-overlay" @click.self="detail = undefined" @keydown.esc="detail = undefined"><section class="reference-detail" role="dialog" aria-modal="true" aria-label="参考详情"><button class="reference-close" aria-label="关闭参考详情" @click="detail = undefined"><X :size="20" /></button><div class="reference-detail-image"><img :src="referenceUrl(apiBaseUrl,detail.contentUrl)" :alt="detail.title" /></div><form class="reference-detail-form" @submit.prevent="saveDetail"><input v-model="detail.title" class="reference-title-input" required maxlength="300" aria-label="参考标题" /><small>{{ detail.width }} × {{ detail.height }}</small><label>行业</label><div class="reference-chips"><button v-for="c in industries" :key="c.id" type="button" :class="{selected:detail.industries?.includes(c.name)}" @click="toggle('industries',c.name)">{{ c.name }}</button></div><label>设计类型</label><div class="reference-chips"><button v-for="c in types" :key="c.id" type="button" :class="{selected:detail.designTypes?.includes(c.name)}" @click="toggle('designTypes',c.name)">{{ c.name }}</button></div><label>风格标签<input v-model="tags" placeholder="用逗号分隔，如留白、暖色、自然材质" /></label><label>视觉描述<textarea v-model="detail.description" rows="3" maxlength="4000" /></label><label>我的备注<textarea v-model="detail.notes" rows="2" maxlength="4000" /></label><label>作者<input v-model="detail.author" maxlength="300" /></label><label>授权信息<input v-model="detail.rightsStatus" maxlength="300" /></label><a v-if="detail.sourceUrl?.startsWith('https://') || detail.sourceUrl?.startsWith('http://')" :href="detail.sourceUrl" target="_blank" rel="noopener noreferrer">查看原作 <ArrowUpRight :size="12" /></a><p v-if="detail.analysisError">{{ detail.analysisError }}</p><div class="reference-detail-actions"><button type="submit" class="primary-button" :disabled="busy"><Check :size="14" />保存</button><button type="button" class="ghost-button" :disabled="busy" @click="operate(async () => { await api(`/${detail!.id}/analyze`, {method:'POST'}); notice='已安排重新分析'; })"><RefreshCw :size="14" />重新分析</button></div></form></section></div></Teleport>
    <Teleport to="body"><div v-if="deleteTarget" class="reference-delete-overlay" @click.self="!busy && (deleteTarget = undefined)" @keydown.esc="!busy && (deleteTarget = undefined)"><section class="reference-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="reference-delete-title" aria-describedby="reference-delete-description"><span class="reference-delete-icon"><Trash2 :size="20" /></span><h2 id="reference-delete-title">删除这张参考图？</h2><p id="reference-delete-description">“{{ deleteTarget.title }}”将从共享参考库移除。项目已采用的副本会保留。</p><div><button type="button" class="ghost-button reference-delete-cancel" :disabled="busy" @click="deleteTarget = undefined">取消</button><button type="button" class="reference-delete-confirm" :disabled="busy" @click="confirmDelete">{{ busy ? '删除中…' : '确认删除' }}</button></div></section></div></Teleport>
  </LibraryPageLayout>
</template>

<style scoped>
.reference-inline{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0}
input,select,textarea{box-sizing:border-box;border:1px solid var(--theme-border);border-radius:10px;padding:10px 12px;background:var(--theme-surface);color:var(--theme-text);font:inherit;font-size:var(--ui-font-control)}input:focus-visible,select:focus-visible,textarea:focus-visible,button:focus-visible{outline:2px solid var(--theme-accent-strong);outline-offset:3px}.reference-inline input{flex:1;min-width:160px}
.reference-tile { position: relative; contain: paint; padding: 0; text-align: left; background: var(--theme-bg); border: 1px solid color-mix(in srgb, var(--theme-border) 72%, transparent); border-radius: var(--ui-radius-card); overflow: hidden; color: #fff; box-shadow: var(--ui-media-shadow); transition: transform .16s, border-color .16s, box-shadow .16s; }
.reference-tile:is(:hover, :focus-within) { transform: translateY(-3px); border-color: color-mix(in srgb, var(--theme-accent-strong) 46%, var(--theme-border)); box-shadow: 0 15px 36px #00000032; }
.reference-tile-open { display: block; width: 100%; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.reference-tile-open:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: -3px; }
.reference-tile-delete { position: absolute; z-index: 3; top: 10px; right: 10px; display: grid; place-items: center; width: var(--ui-control-compact); height: var(--ui-control-compact); padding: 0; border: 1px solid #ffffff2e; border-radius: var(--ui-radius-control); background: #151515d9; color: #f3f3f3; box-shadow: 0 6px 18px #0007; opacity: 0; transform: translate3d(0, -5px, 0); pointer-events: none; backdrop-filter: blur(12px); transition: opacity .16s, transform .16s, border-color .16s, background .16s, color .16s; }
.reference-tile-delete:hover, .reference-tile-delete:focus-visible { border-color: #8b8b8b; background: #262626df; color: #afafaf; }
.reference-tile:is(:hover, :focus-within) .reference-tile-delete { opacity: 1; transform: translate3d(0, 0, 0); pointer-events: auto; }
.reference-image { position: relative; width: 100%; height: auto; aspect-ratio: auto; overflow: visible; background: var(--theme-surface-subtle); }
.reference-image img { display: block; width: 100%; height: auto; max-height: none; object-fit: contain; object-position: center; filter: none; }
.reference-tile-body { position: absolute; right: 0; bottom: 0; left: 0; display: grid; gap: 5px; min-height: 0; padding: 18px 12px 12px; opacity: 0; transform: translate3d(0, 12px, 0); backface-visibility: hidden; pointer-events: none; isolation: isolate; transition: opacity .22s ease, transform .22s cubic-bezier(.2,.7,.2,1); }
.reference-tile-body::before { content: ''; position: absolute; inset: 0; z-index: -1; background: var(--ui-media-overlay); -webkit-mask-image: var(--ui-media-mask); mask-image: var(--ui-media-mask); -webkit-backdrop-filter:var(--ui-media-blur); backdrop-filter:var(--ui-media-blur); }
.reference-tile h3 { margin: 0; overflow: hidden; color: #f9f9f9; font-size: var(--ui-font-card); font-weight: 620; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 6px #0009; }
.reference-tile p { margin: 0 0 3px; overflow: hidden; color: #dbdbdb; font-size: var(--ui-font-caption); line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 5px #0009; }
.reference-tags { display: flex; gap: 5px; flex-wrap: wrap; min-height: 20px; }
.reference-tags span { padding: 3px 7px; border: 1px solid #ffffff21; border-radius: 999px; background: #ffffff24; color: #f1f1f1; font-size: var(--ui-font-micro); line-height: 16px; }
.reference-tags small { align-self: center; color: #e0e0e0; font-size: var(--ui-font-caption); text-shadow: 0 1px 5px #0009; }
.reference-tile:is(:hover, :focus-within) .reference-tile-body { opacity: 1; transform: translate3d(0, 0, 0); pointer-events: auto; will-change: opacity, transform; }
@media (hover: none) { .reference-tile-delete { opacity: 1; transform: none; pointer-events: auto; width:var(--ui-control-compact); height:var(--ui-control-compact); border-radius:var(--ui-radius-control); } }
@media (prefers-reduced-motion: reduce) { .reference-tile, .reference-tile-body, .reference-tile-delete { transition: none; } }button:disabled{opacity:.45;cursor:default}.reference-error{color:#616161;font-size:var(--ui-font-control)}.reference-notice{font-size:var(--ui-font-control);color:var(--theme-text-muted)}
.reference-lessons{display:grid;gap:10px;margin:18px 0;padding:14px;border:1px solid var(--theme-border);border-radius:14px;background:var(--theme-surface-subtle)}.reference-lessons h2{margin:0;font-size:var(--ui-font-body);color:var(--theme-text)}.reference-lessons p{margin:4px 0 0;color:var(--theme-text-muted);font-size:var(--ui-font-caption)}.reference-lessons ul{display:grid;gap:7px;margin:0;padding:0;list-style:none}.reference-lessons li{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding-top:8px;border-top:1px solid var(--theme-border)}.reference-lessons span{display:grid;gap:3px}.reference-lessons strong{font-size:var(--ui-font-caption);font-weight:550}.reference-lessons small,.reference-lessons em{color:var(--theme-text-muted);font-size:var(--ui-font-caption);font-style:normal}.reference-lessons button{border:1px solid var(--theme-border);border-radius:7px;padding:4px 8px;background:transparent;color:var(--theme-text-muted);font:inherit;font-size:var(--ui-font-caption);cursor:pointer}
.reference-overlay{position:fixed;inset:0;z-index:1500;background:#0009;display:flex;align-items:center;justify-content:center;padding:24px}.reference-detail{position:relative;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,1fr);max-width:1120px;width:100%;max-height:90vh;background:var(--theme-surface-raised);color:var(--theme-text);border-radius:20px;overflow:hidden}.reference-close{position:absolute;right:10px;top:10px;z-index:1;border:0;border-radius:50%;padding:7px;background:var(--theme-surface);color:inherit;cursor:pointer}.reference-detail-image{padding:24px;display:grid;place-items:center;background:var(--theme-surface-subtle);min-height:0}.reference-detail-image img{max-width:100%;max-height:80vh;object-fit:contain}.reference-detail-form{padding:35px 26px;overflow:auto;display:flex;flex-direction:column;gap:12px;font-size:var(--ui-font-caption)}.reference-title-input{font-size:var(--ui-font-section);font-weight:600}.reference-detail-form label{display:flex;flex-direction:column;gap:6px}.reference-chips{display:flex;flex-wrap:wrap;gap:6px}.reference-chips button{border:1px solid var(--theme-border);border-radius:20px;padding:6px 9px;background:transparent;color:inherit;font-size:var(--ui-font-caption);cursor:pointer}.reference-chips .selected{background:var(--theme-accent-soft);border-color:var(--theme-accent-strong)}.reference-detail-actions{display:flex;gap:6px;flex-wrap:wrap}.reference-detail-actions button{display:flex;gap:5px;align-items:center;font-size:var(--ui-font-caption)}.reference-detail-form a{color:inherit}
.reference-delete-overlay { position: fixed; inset: 0; z-index: 1600; display: grid; place-items: center; padding: 24px; background: #0009; backdrop-filter: blur(8px); }
.reference-delete-dialog { width: min(420px, 100%); padding: 24px; border: 1px solid color-mix(in srgb, #8b8b8b 54%, var(--theme-border)); border-radius: 18px; background: var(--theme-surface-raised); color: var(--theme-text); box-shadow: 0 24px 70px #0009; }
.reference-delete-icon { display: grid; place-items: center; width: 42px; height: 42px; border: 1px solid color-mix(in srgb, #8b8b8b 58%, var(--theme-border)); border-radius: 12px; background: color-mix(in srgb, #404040 24%, var(--theme-surface-subtle)); color: #afafaf; }
.reference-delete-dialog h2 { margin: 17px 0 8px; font-size: 20px; }
.reference-delete-dialog p { margin: 0; color: var(--theme-text-muted); font-size: var(--ui-font-caption); line-height: 1.75; overflow-wrap: anywhere; }
.reference-delete-dialog > div { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
.reference-delete-dialog button { min-height: 38px; padding: 0 14px; border-radius: 10px; }
.reference-delete-confirm { border: 1px solid #6b6b6b; background: #404040; color: #f6f6f6; }
.reference-delete-confirm:hover:not(:disabled) { border-color: #8e8e8e; background: #4d4d4d; }
@media(max-width:720px){.reference-detail{display:block;overflow:auto}.reference-detail-image img{max-height:34vh}.reference-detail-form{overflow:visible}}
</style>
