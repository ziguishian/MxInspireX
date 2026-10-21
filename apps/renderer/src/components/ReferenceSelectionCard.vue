<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { Check, Expand, ImagePlus, RefreshCw, ArrowUpRight, X } from 'lucide-vue-next';
import { referenceUrl, referenceRequest, selectedReferenceEntries, referenceTextChoices, referenceAspects, type ReferenceSelection, type ReferenceSubmission, type VisualReference } from '../features/references';
const props = defineProps<{ selection: ReferenceSelection; apiBaseUrl: string; projectId: string; disabled: boolean }>();
const emit = defineEmits<{ submit: [ReferenceSubmission] }>();
const card = ref(props.selection), selected = ref<string[]>([]), aspects = ref<Record<string, string[]>>({}), notes = ref(''), zoom = ref<VisualReference>(), busy = ref(false), error = ref('');
let zoomTrigger: HTMLElement | null = null;
watch(() => Boolean(zoom.value), async visible => { if (visible) { zoomTrigger = document.activeElement as HTMLElement; await nextTick(); document.querySelector<HTMLButtonElement>('.choice-lightbox>button')?.focus(); } else zoomTrigger?.focus(); });
const picker = ref<HTMLInputElement>();
const chosenEntries = computed(() => selected.value.length ? selectedReferenceEntries(card.value, selected.value, aspects.value) : referenceTextChoices(card.value, notes.value));
const key = () => `langjuart.references.${props.projectId}.${props.selection.id}`;
watch(() => props.selection, value => {
  card.value = value;
  try { const data = value.selected ? {selected:value.selected.map(item=>item.id),aspects:Object.fromEntries(value.selected.map(item=>[item.id,item.aspects])),notes:value.notes || ''} : JSON.parse(localStorage.getItem(key()) || '{}'); selected.value = (data.selected || []).filter((id: string) => value.items.some(i => i.id === id)); aspects.value = data.aspects || {}; notes.value = data.notes || ''; } catch { selected.value = []; }
}, { immediate: true });
watch([selected, aspects, notes], () => { try { localStorage.setItem(key(), JSON.stringify({ selected: selected.value, aspects: aspects.value, notes: notes.value })); } catch { /* Selection remains usable without localStorage. */ } }, { deep: true });
function select(id: string) { selected.value = selected.value.includes(id) ? selected.value.filter(i => i !== id) : [...selected.value, id]; }
function aspect(id: string, value: string) { const values = aspects.value[id] || []; aspects.value[id] = values.includes(value) ? values.filter(v => v !== value) : [...values, value]; }
function submit(action: ReferenceSubmission['action']) {
  if (busy.value || props.disabled) return;
  emit('submit', { id: card.value.id, action, selected: chosenEntries.value, notes: notes.value });
}
async function upload(files: File[]) {
  if (!files.length || busy.value || props.disabled) return;
  busy.value = true; error.value = '';
  try {
    const data = new FormData(); files.forEach(file => data.append('files', file));
    const result = await referenceRequest<{ card: ReferenceSelection; uploadedIds: string[] }>(props.apiBaseUrl, `/selections/${card.value.id}/upload?project_id=${encodeURIComponent(props.projectId)}`, { method: 'POST', body: data });
    card.value = result.card; selected.value = result.uploadedIds;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '上传失败'; }
  finally { busy.value = false; }
}
</script>

<template>
  <section class="reference-choice" aria-label="选择视觉参考" :aria-busy="busy">
    <header><span>视觉方向</span><small>{{ disabled ? '本轮参考记录' : '可多选 · 选择后继续设计' }}</small></header>
    <p>{{ card.intro }}</p>
    <div v-if="card.items.length" class="reference-choice-grid"><article v-for="(item,index) in card.items" :key="item.id" :class="{selected:selected.includes(item.id)}"><div class="choice-image"><button type="button" class="choice-select" :disabled="disabled || busy" :aria-pressed="selected.includes(item.id)" :aria-label="`选择第${index+1}张：${item.title}`" @click="select(item.id)"><img :src="referenceUrl(apiBaseUrl,item.thumbnailUrl)" :alt="item.title" loading="lazy" /><span class="choice-number">{{ index+1 }}<Check v-if="selected.includes(item.id)" :size="12" /></span></button><button class="choice-expand" type="button" :aria-label="`放大第${index+1}张`" @click="zoom=item"><Expand :size="13" /></button></div><div class="choice-caption"><strong>{{ item.direction || item.title }}</strong><small class="choice-evidence">{{ item.evidenceType === 'material_process' ? '材质 / 工艺证据' : item.evidenceType === 'product_photography' ? '产品 / 摄影证据' : '设计案例证据' }}</small><small>{{ item.reason || item.description || '选择可借鉴的具体设计语言' }}</small><a v-if="item.sourceUrl?.startsWith('http://') || item.sourceUrl?.startsWith('https://')" :href="item.sourceUrl" target="_blank" rel="noopener noreferrer">来源 <ArrowUpRight :size="10" /></a><div v-if="selected.includes(item.id)" class="choice-aspects"><button v-for="value in referenceAspects" :key="value" :disabled="disabled || busy" :class="{active:aspects[item.id]?.includes(value)}" @click="aspect(item.id,value)">{{ value }}</button></div></div></article></div>
    <div v-else class="choice-empty">暂无匹配的图片。上传自己的参考、换个方向查找，或跳过参考继续。</div>
    <details v-if="card.errors?.length"><summary>部分来源暂不可用</summary><p v-for="(issue,index) in card.errors" :key="index">{{ issue.message }}</p></details>
    <template v-if="!disabled"><textarea v-model="notes" maxlength="4000" rows="2" placeholder="例如：第2张的配色，第5张的排版；也可以说明想调整的方向…" aria-label="参考偏好补充" @paste="($event.clipboardData?.files.length && (upload(Array.from($event.clipboardData.files)), $event.preventDefault()))" /><div class="choice-actions"><button :disabled="busy" @click="submit('refresh')"><RefreshCw :size="13" />换一批</button><button :disabled="busy" @click="picker?.click()"><ImagePlus :size="13" />上传自己的参考</button><button :disabled="busy" @click="submit('skip')">跳过参考</button><button class="choice-confirm" :disabled="busy || !chosenEntries.length" @click="submit('confirm')">按所选方向设计</button></div><input ref="picker" type="file" multiple accept="image/jpeg,image/png,image/webp" hidden @change="upload(Array.from(($event.target as HTMLInputElement).files || [])); ($event.target as HTMLInputElement).value=''" /></template>
    <p v-if="error" role="alert">{{ error }}</p>
    <Teleport to="body"><div v-if="zoom" class="choice-lightbox" @click.self="zoom=undefined" @keydown.esc="zoom=undefined"><button aria-label="关闭预览" @click="zoom=undefined"><X :size="22" /></button><img :src="referenceUrl(apiBaseUrl,zoom.contentUrl)" :alt="zoom.title" /></div></Teleport>
  </section>
</template>

<style scoped>
.reference-choice{margin:14px 0;padding:16px;border:1px solid var(--theme-border);border-radius:16px;background:var(--theme-surface-raised);color:var(--theme-text);font-size:12px}.reference-choice header{display:flex;justify-content:space-between;align-items:center;gap:8px}.reference-choice header span{font-weight:650}.reference-choice small{color:var(--theme-text-muted);font-size:10px}.reference-choice>p{line-height:1.7;color:var(--theme-text-muted)}.reference-choice-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.reference-choice article{border:1px solid var(--theme-border);border-radius:11px;overflow:hidden}.reference-choice article.selected{border-color:var(--theme-accent-strong);box-shadow:0 0 0 1px var(--theme-accent-strong)}.choice-image{height:145px;position:relative;background:var(--theme-surface-subtle)}.choice-select{display:block;border:0;background:transparent;width:100%;height:100%;padding:8px;cursor:pointer}.choice-select img{width:100%;height:100%;object-fit:contain}.choice-number{position:absolute;top:6px;left:6px;display:flex;align-items:center;gap:4px;background:var(--theme-surface-raised);border-radius:5px;padding:3px 6px;color:var(--theme-text);font-size:10px}.choice-expand{position:absolute;bottom:6px;right:6px;border:0;border-radius:5px;padding:4px;background:var(--theme-surface-raised);color:var(--theme-text);cursor:pointer}.choice-caption{padding:8px;display:flex;flex-direction:column;gap:5px}.choice-caption strong{font-size:11px;line-height:1.5;max-height:3em;overflow:hidden}.choice-caption small{line-height:1.6}.choice-caption a{color:var(--theme-text-muted);font-size:10px;text-decoration:none}.choice-aspects{display:flex;flex-wrap:wrap;gap:4px}.choice-aspects button{font-size:10px;padding:3px 6px}.choice-aspects .active{background:var(--theme-accent-soft)}.reference-choice textarea{width:100%;box-sizing:border-box;resize:vertical;margin-top:12px;padding:9px;border:1px solid var(--theme-border);border-radius:9px;background:var(--theme-surface);color:inherit;font:inherit;line-height:1.7}.choice-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.choice-actions button,.choice-aspects button{display:flex;gap:4px;align-items:center;border:1px solid var(--theme-border);border-radius:7px;background:transparent;color:inherit;cursor:pointer}.choice-actions button{padding:7px 9px;font-size:10px}.choice-actions .choice-confirm{background:var(--theme-text);color:var(--theme-surface);margin-left:auto}.reference-choice button:disabled{opacity:.5;cursor:default}.reference-choice button:focus-visible,.reference-choice textarea:focus-visible{outline:2px solid var(--theme-accent-strong);outline-offset:2px}.choice-empty{padding:24px 8px;line-height:1.8;text-align:center;color:var(--theme-text-muted)}.reference-choice details{margin-top:10px;color:var(--theme-text-muted);font-size:10px}.choice-lightbox{position:fixed;inset:0;background:#000b;z-index:1600;display:grid;place-items:center;padding:30px}.choice-lightbox img{max-width:95vw;max-height:90vh;object-fit:contain}.choice-lightbox>button{position:absolute;top:16px;right:16px;background:#fff;border:0;border-radius:50%;padding:8px;cursor:pointer}
</style>
