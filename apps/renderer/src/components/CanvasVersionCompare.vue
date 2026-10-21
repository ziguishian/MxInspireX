<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import CanvasMarkdown from './CanvasMarkdown.vue';
import { nodeMediaUrl } from '../nodeExport';
import { canvasNodeKind } from '../nodeSizing';
import { htmlPreviewDocument, HTML_PREVIEW_SANDBOX } from '../htmlPreview';
const props = defineProps<{ nodes: Array<{ id: string; data: Record<string, any> }>; initialIds: string[]; busy: boolean; lockedIds: string[] }>();
const emit = defineEmits<{ close: []; adopt: [id: string, comparedIds: string[]]; continue: [id: string] }>();
const ids = ref(props.initialIds.slice(0, 4));
const compared = computed(() => ids.value.flatMap(id => props.nodes.filter(node => node.id === id)));
const dialog = ref<HTMLElement>();
onMounted(() => dialog.value?.focus());
</script>
<template>
  <Teleport to="body"><div class="modal-backdrop" @click.self="emit('close')" @keydown.esc.stop="emit('close')"><section ref="dialog" class="version-compare" role="dialog" aria-modal="true" aria-label="作品版本对比" tabindex="-1">
    <header><div><h2>作品版本对比</h2><small>选择 2–4 个作品并排查看；采用标记只在本次对比中切换，保留所有原作。</small></div><button aria-label="关闭对比" @click="emit('close')">×</button></header>
    <div class="version-picker" aria-label="选择对比作品"><label v-for="node in nodes" :key="node.id"><input v-model="ids" type="checkbox" :value="node.id" :disabled="ids.length >= 4 && !ids.includes(node.id)" />{{ node.data.title || node.id }}{{ node.data.adopted ? ' · 已采用' : '' }}</label></div>
    <p v-if="compared.length < 2">再选择一个作品即可并排对比。</p>
    <div class="version-grid" :style="{ gridTemplateColumns: `repeat(${Math.max(1, compared.length)}, minmax(250px, 1fr))` }"><article v-for="node in compared" :key="node.id" :data-node-id="node.id">
      <h3>{{ node.data.title || node.id }} <small v-if="node.data.adopted">已采用</small></h3>
      <div class="version-preview"><img v-if="canvasNodeKind(node.data) === 'image'" :src="nodeMediaUrl(node.data)" :alt="node.data.title" /><CanvasMarkdown v-else-if="canvasNodeKind(node.data) === 'text'" :content="node.data.text || node.data.summary || ''" /><iframe v-else-if="canvasNodeKind(node.data) === 'html'" :srcdoc="htmlPreviewDocument(node.data.html || '', node.data.htmlAssets, true)" :sandbox="HTML_PREVIEW_SANDBOX" :title="node.data.title" referrerpolicy="no-referrer" /><video v-else-if="canvasNodeKind(node.data) === 'video'" :src="nodeMediaUrl(node.data)" controls preload="metadata" /><audio v-else-if="canvasNodeKind(node.data) === 'audio'" :src="nodeMediaUrl(node.data)" controls preload="metadata" /><p v-else>请在画布中查看此类文件。</p></div>
      <footer><button :disabled="busy || lockedIds.some(id => ids.includes(id)) || !!node.data.adopted" @click="emit('adopt', node.id, ids)">{{ node.data.adopted ? '已采用此版' : '采用此版' }}</button><button :disabled="busy || lockedIds.includes(node.id)" @click="emit('continue', node.id)">从此版继续修改</button></footer>
    </article></div>
  </section></div></Teleport>
</template>
<style scoped>
.version-compare { width: min(1400px, 95vw); max-height: 90vh; overflow: auto; padding: 22px; border-radius: 16px; background: var(--theme-surface-raised); color: var(--theme-text); border: 1px solid var(--theme-border); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; } h2 { margin: 0 0 8px; font-size: 18px; } small { color: var(--theme-text-muted); } button { padding: 7px 10px; border-radius: 7px; border: 1px solid var(--theme-border); color: inherit; background: var(--theme-surface-raised); cursor: pointer; } button:disabled { opacity: .5; cursor: default; }
.version-picker { display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0; max-height: 100px; overflow: auto; font-size: 12px; } label { display: flex; align-items: center; gap: 4px; }
.version-grid { display: grid; gap: 16px; overflow-x: auto; } article { border: 1px solid var(--theme-border); padding: 12px; border-radius: 10px; } h3 { font-size: 13px; margin: 0 0 12px; } .version-preview { height: 45vh; overflow: auto; } img, video { width: 100%; height: 100%; object-fit: contain; } iframe { width: 100%; height: 100%; border: 0; background: white; } footer { margin-top: 12px; flex-wrap: wrap; }
</style>
