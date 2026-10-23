<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { Box, Image, MoreHorizontal, Pencil, Trash2 } from 'lucide-vue-next';
import type { Project } from '@contracts/project';
import type { CanvasDocument, LibraryAsset } from '../../features/pageServices';
import { assetPreviewKind } from '../../features/assetPreview';
import { firstGeneratedProjectAsset } from '../../features/projectPreview';
import LibraryAssetThumbnail from '../assets/LibraryAssetThumbnail.vue';

const props = defineProps<{ project: Project; board?: CanvasDocument; apiBaseUrl: string; loadPreview: (project: Project) => Promise<void>; rename: (project: Project, name: string) => Promise<void> }>();
const emit = defineEmits<{ open: [id: string]; delete: [project: Project] }>();
const card = ref<HTMLElement | null>(null);
const menuTrigger = ref<HTMLButtonElement | null>(null);
const nameInput = ref<HTMLInputElement | null>(null);
const menuOpen = ref(false);
const editing = ref(false);
const name = ref('');
const saving = ref(false);
const error = ref('');
let previewObserver: IntersectionObserver | undefined;
const visible = ref(false);

onMounted(() => {
  previewObserver = new IntersectionObserver(entries => { visible.value = Boolean(entries[0]?.isIntersecting); }, { rootMargin: '120px' });
  if (card.value) previewObserver.observe(card.value);
});
watch(() => [visible.value, props.project.previewRevision], () => { if (visible.value) void props.loadPreview(props.project); });
onUnmounted(() => previewObserver?.disconnect());

const previewAsset = computed<LibraryAsset | null>(() => {
  return firstGeneratedProjectAsset(props.board, props.project.id);
});
const previewKind = computed(() => previewAsset.value ? assetPreviewKind(previewAsset.value) : null);
const description = computed(() => props.project.brief?.trim() || props.project.summary?.trim() || '尚未添加项目描述');
const fallbackIcon = computed(() => previewAsset.value?.kind === '3d' || previewAsset.value?.kind === 'cad' ? Box : Image);

async function startRename() {
  menuOpen.value = false; name.value = props.project.name; error.value = ''; editing.value = true;
  await nextTick(); nameInput.value?.focus(); nameInput.value?.select();
}
async function saveName() {
  if (!editing.value || saving.value) return;
  const next = name.value.trim();
  if (!next || next === props.project.name) { editing.value = false; return; }
  saving.value = true;
  try { await props.rename(props.project, next); editing.value = false; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '重命名失败，请重试'; }
  finally { saving.value = false; }
}
function outside(event: PointerEvent) { if (!card.value?.contains(event.target as Node)) menuOpen.value = false; }
function closeMenu() { menuOpen.value = false; menuTrigger.value?.focus(); }
onMounted(() => document.addEventListener('pointerdown', outside));
onUnmounted(() => document.removeEventListener('pointerdown', outside));
</script>

<template>
  <article ref="card" class="project-card" :class="{ 'is-editing': editing, 'is-menu-open': menuOpen }" role="button" tabindex="0" :aria-label="`打开项目 ${project.name}`" @click="emit('open', project.id)" @keydown.enter.self.prevent="emit('open', project.id)" @keydown.space.self.prevent="emit('open', project.id)">
    <div class="project-card-preview" :class="{ 'has-asset': previewKind, 'has-natural-image': previewKind === 'image' }">
      <LibraryAssetThumbnail v-if="previewAsset && previewKind" :asset="previewAsset" :api-base-url="apiBaseUrl" fit="contain" :natural="previewKind === 'image'" />
      <div v-else class="project-card-placeholder"><component :is="fallbackIcon" :size="38" :stroke-width="1.45" /><span>{{ visible && board?.nodes?.length ? '正在准备预览' : '尚未生成资产' }}</span></div>
      <div class="project-card-info">
        <strong v-if="!editing">{{ project.name }}</strong>
        <input v-else ref="nameInput" v-model="name" class="project-rename-input" aria-label="项目名称" :disabled="saving" @click.stop @keydown.enter.prevent="saveName" @keydown.esc.prevent="editing = false" @blur="saveName" />
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <p v-else class="project-card-description">{{ description }}</p>
      </div>
    </div>
    <div class="project-card-actions" @click.stop @keydown.esc.stop="closeMenu">
      <button ref="menuTrigger" type="button" class="project-menu-trigger" :class="{ 'is-open': menuOpen }" aria-label="项目操作" aria-haspopup="menu" :aria-controls="`project-menu-${project.id}`" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen"><MoreHorizontal :size="18" /></button>
      <Transition name="project-actions">
        <div v-if="menuOpen" :id="`project-menu-${project.id}`" class="project-menu" role="menu" aria-label="项目操作">
          <button type="button" role="menuitem" @click="startRename"><Pencil :size="15" :stroke-width="1.7" /><span>重命名</span></button>
          <div class="project-menu-divider" role="separator" />
          <button type="button" role="menuitem" class="project-menu-delete" @click="menuOpen = false; emit('delete', project)"><Trash2 :size="15" :stroke-width="1.7" /><span>删除</span></button>
        </div>
      </Transition>
    </div>
  </article>
</template>

<style scoped>
.project-card.project-card { position: relative; min-width: 0; align-self: start; overflow: visible; border: 0; border-radius: var(--ui-radius-card); background: transparent; box-shadow: none; cursor: pointer; }
.project-card.project-card:hover { border-color: transparent; background: transparent; transform: none; }
.project-card:is(:hover, :focus-within, .is-editing, .is-menu-open) { z-index: 3; }
.project-card:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 4px; border-radius: 14px; }
.project-card-preview { position: relative; aspect-ratio: var(--library-preview-ratio, 16 / 9); overflow: hidden; border: 1px solid var(--theme-border); border-radius: var(--ui-radius-card); background: var(--theme-surface-subtle); box-shadow: var(--ui-media-shadow); transition: border-color .16s ease, transform .16s ease; }
.project-card-preview.has-natural-image { aspect-ratio: auto; }
.project-card:hover .project-card-preview, .project-card:focus-within .project-card-preview { border-color: var(--theme-border-strong); transform: translate3d(0, -2px, 0); }
.project-card-placeholder { display: grid; width: 100%; height: 100%; place-content: center; justify-items: center; gap: 9px; color: var(--theme-text-subtle); background: color-mix(in srgb, var(--theme-surface-subtle) 82%, var(--theme-bg)); font-size: 11px; }
.project-card-actions { position: absolute; top: 10px; right: 10px; z-index: 3; opacity: 0; transform: translate3d(0, -4px, 0); transition: opacity .14s ease, transform .14s ease; }
.project-card:is(:hover, :focus-within, .is-menu-open) .project-card-actions { opacity: 1; transform: translate3d(0, 0, 0); }
.project-menu-trigger { display: grid; place-items: center; width: var(--ui-control-compact); height: var(--ui-control-compact); padding: 0; border: 1px solid #ffffff40; border-radius: var(--ui-radius-control); background: #151515b8; color: #f5f5f5; box-shadow: 0 3px 12px #0004; }
.project-menu-trigger:is(:hover, .is-open) { border-color: #ffffff6b; background: #151515e8; color: #fff; }
.project-menu { position: absolute; top: calc(100% + 6px); right: 0; display: grid; width: 152px; gap: 2px; padding: 5px; border: 1px solid var(--theme-border-strong); border-radius: 12px; background: var(--theme-surface-raised); box-shadow: 0 8px 24px #0003; transform-origin: top right; }
.project-menu button { display: flex; align-items: center; gap: 10px; min-height: 35px; padding: 8px 10px; border: 0; border-radius: 7px; color: var(--theme-text); background: transparent; font: inherit; font-size: var(--ui-font-control); line-height: 18px; text-align: left; }
.project-menu button svg { flex-shrink: 0; color: var(--theme-text-muted); }
.project-menu button:is(:hover, :focus-visible) { background: var(--theme-surface-hover); }
.project-menu .project-menu-delete:is(:hover, :focus-visible) { color: var(--theme-danger); background: var(--theme-danger-soft); }
.project-menu button:is(:hover, :focus-visible) svg { color: currentColor; }
.project-menu-divider { height: 1px; margin: 3px 7px; background: var(--theme-border); }
.project-card-info { position: absolute; inset: auto 0 0; z-index: 1; display: grid; gap: 4px; padding: 14px 12px 10px; color: #f2f1ed; isolation: isolate; opacity: 0; visibility: hidden; transform: translate3d(0, 12px, 0); pointer-events: none; transition: opacity .22s ease, transform .22s cubic-bezier(.2,.7,.2,1), visibility .22s; }
.project-card-info::before { content: ''; position: absolute; inset: 0; z-index: -1; background: var(--ui-media-overlay); -webkit-backdrop-filter: var(--ui-media-blur); backdrop-filter: var(--ui-media-blur); -webkit-mask-image: var(--ui-media-mask); mask-image: var(--ui-media-mask); }
.project-card:is(:hover, :focus-within, .is-editing) .project-card-info { opacity: 1; visibility: visible; transform: translate3d(0, 0, 0); }
.project-card.is-menu-open .project-card-info { opacity: 0; visibility: hidden; }
.project-card-info strong { display: -webkit-box; min-width: 0; min-height: 20px; padding-right: 36px; overflow: hidden; color: inherit; font-size: var(--ui-font-card); font-weight: 620; line-height: 1.4; text-shadow: 0 1px 4px #18181880; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 1; }
.project-card-info .project-card-description { display: -webkit-box; margin: 0; overflow: hidden; color: #e7e5e1; font-size: var(--ui-font-caption); line-height: 1.5; text-shadow: 0 1px 4px #18181880; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.project-card-info .project-rename-input { width: calc(100% - 36px); height: 28px; min-width: 0; border: 1px solid var(--theme-border-strong); border-radius: 7px; padding: 3px 6px; background: var(--theme-surface-raised); color: var(--theme-text); font: inherit; font-size: 13px; pointer-events: auto; }
.project-card-info .error-message { margin: 0; color: #ffb4b4; font-size: 11px; line-height: 1.6; }
.project-actions-enter-active, .project-actions-leave-active { transition: opacity .14s ease, transform .14s ease; }
.project-actions-enter-from, .project-actions-leave-to { opacity: 0; transform: translateY(-4px) scale(.98); }
@media (hover: none) { .project-card-info { opacity: 1; visibility: visible; transform: none; } .project-card-actions { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .project-card-preview, .project-card-info, .project-card-actions, .project-actions-enter-active, .project-actions-leave-active { transition: none; } }
</style>
