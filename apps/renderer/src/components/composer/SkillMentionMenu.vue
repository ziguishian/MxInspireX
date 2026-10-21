<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Wrench, LoaderCircle } from 'lucide-vue-next';
import type { SkillList, SkillSummary } from '@contracts/skills';
import { createSkillsApi } from '../../features/skills';

const props = defineProps<{ query: string; apiBaseUrl: string }>();
const emit = defineEmits<{ select: [skill: SkillSummary]; close: [] }>();
const request = createSkillsApi(props.apiBaseUrl);
const items = ref<SkillSummary[]>([]), loading = ref(false), error = ref(''), active = ref(0);
const nextOffset = ref<number | null>(null), menu = ref<HTMLElement | null>(null);
const placement = ref<'above' | 'below'>('above'), maxHeight = ref(260);
const activeId = computed(() => items.value.length ? `skill-option-${active.value}` : undefined);
let observer: ResizeObserver | undefined;
function position() {
  const anchor = menu.value?.parentElement?.getBoundingClientRect();
  if (!anchor) return;
  const above = anchor.top - 56, below = innerHeight - anchor.bottom - 20;
  placement.value = above >= 160 || above >= below ? 'above' : 'below';
  maxHeight.value = Math.max(80, Math.min(340, placement.value === 'above' ? above : below));
}
onMounted(() => {
  position(); observer = new ResizeObserver(position);
  if (menu.value?.parentElement) observer.observe(menu.value.parentElement);
  window.addEventListener('resize', position); window.addEventListener('scroll', position, true);
});
let controller: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined, revision = 0;
const available = (skill: SkillSummary) => !skill.missingTools.length;
async function load(more = false) {
  controller?.abort(); controller = new AbortController();
  const current = ++revision;
  loading.value = true; error.value = '';
  try {
    const params = new URLSearchParams({ query: props.query, limit: '50', offset: String(more ? nextOffset.value || 0 : 0), include_disabled: 'false' });
    const page = await request<SkillList>(`?${params}`, { signal: controller.signal });
    if (current !== revision) return;
    const found = page.skills.filter(s => s.enabled && !s.deleted);
    items.value = more ? [...items.value, ...found.filter(s => !items.value.some(old => old.id === s.id))] : found;
    nextOffset.value = page.nextOffset;
    if (!more) active.value = Math.max(0, items.value.findIndex(available));
  } catch (cause) {
    if (current === revision && !controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '技能加载失败';
  } finally { if (current === revision) loading.value = false; }
}
watch(() => props.query, () => {
  clearTimeout(timer); controller?.abort(); ++revision;
  items.value = []; nextOffset.value = null; error.value = ''; loading.value = true;
  timer = setTimeout(() => void load(), 120);
}, { immediate: true });
onBeforeUnmount(() => { clearTimeout(timer); controller?.abort(); ++revision; observer?.disconnect(); window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true); });
function select(skill: SkillSummary) { if (available(skill)) emit('select', skill); }
function keydown(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(event.key)) return;
  event.preventDefault(); event.stopPropagation();
  if (event.key === 'Escape') { emit('close'); return; }
  const selectable = items.value.flatMap((s, i) => available(s) ? [i] : []);
  if (!selectable.length) return;
  if (event.key === 'Enter' || event.key === 'Tab') { if (items.value[active.value]) select(items.value[active.value]); return; }
  const index = selectable.indexOf(active.value), delta = event.key === 'ArrowDown' ? 1 : -1;
  active.value = selectable[(index + delta + selectable.length) % selectable.length];
  void nextTick(() => menu.value?.querySelector('.active')?.scrollIntoView({ block: 'nearest' }));
}
defineExpose({ keydown, activeId });
</script>

<template>
  <div ref="menu" class="asset-mention-menu skill-mention-menu" :style="{ maxHeight: `${maxHeight}px`, ...(placement === 'below' ? { top: 'calc(100% + 8px)', bottom: 'auto' } : {}) }" @mousedown.prevent>
    <div class="skill-mention-heading"><span><Wrench :size="14" />选择技能</span><small>↑↓ 选择 · Enter 确认 · Esc 关闭</small></div>
    <div id="skill-mention-options" role="listbox" aria-label="选择技能" :aria-busy="loading" :aria-activedescendant="items.length ? `skill-option-${active}` : undefined">
      <button v-for="(skill, index) in items" :id="`skill-option-${index}`" :key="skill.id" type="button" role="option" :aria-selected="index === active" :aria-disabled="!available(skill)" :disabled="!available(skill)" tabindex="-1"
        :class="['asset-mention-option', { active: index === active }]" @click="select(skill)">
        <span class="asset-mention-option-icon"><Wrench :size="19" /></span>
        <span class="skill-mention-copy"><strong>{{ skill.title }} <i>v{{ skill.version }}</i></strong><small>{{ skill.description }}</small><small v-if="skill.missingTools.length" class="skill-mention-error">缺少工具：{{ skill.missingTools.join('、') }}</small></span>
      </button>
    </div>
    <div v-if="loading" class="asset-mention-empty" role="status"><LoaderCircle :size="14" class="spin-icon" /> 正在查找技能…</div>
    <div v-else-if="error" class="asset-mention-empty" role="alert">{{ error }} <button type="button" @click="load()">重试</button></div>
    <div v-else-if="!items.length" class="asset-mention-empty">{{ query ? '没有匹配的技能，试试名称或适用场景' : '暂无已启用的技能，请到技能库安装或启用' }}</div>
    <button v-if="nextOffset !== null && !loading && !error" type="button" class="skill-mention-more" @click="load(true)">显示更多技能</button>
  </div>
</template>

<style scoped>
.skill-mention-menu{max-height:min(340px,45vh)}
.skill-mention-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:7px 9px 10px;color:var(--theme-text-muted);font-size:12px}
.skill-mention-heading span{display:flex;align-items:center;gap:6px}.skill-mention-heading small{font-size:10px}
.skill-mention-copy{min-width:0}.skill-mention-copy strong{display:flex;align-items:center;gap:8px}.skill-mention-copy i{font-size:10px;font-weight:400;font-style:normal;color:var(--theme-text-muted)}
.skill-mention-copy small{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;white-space:normal;line-height:1.5}
.asset-mention-option{width:100%}.asset-mention-option:disabled{opacity:.5;cursor:default}.skill-mention-error{color:var(--theme-text-muted)}
.asset-mention-empty button,.skill-mention-more{border:0;border-radius:6px;padding:6px 10px;color:var(--theme-text);background:var(--theme-surface-subtle);cursor:pointer}.skill-mention-more{margin:4px 8px}.asset-mention-empty{line-height:1.7}
@media(max-width:480px){.skill-mention-heading small{display:none}}
</style>
