<script setup lang="ts">
import { computed } from 'vue';
import { AudioLines, Box, FileText, Image, SquarePlay, FileCode2 } from 'lucide-vue-next';
import { canvasNodeKind, nodePreviewSize } from '../nodeSizing';
import { HTML_PREVIEW_SCALE } from '../htmlPreview';
import { assetPreviewKind } from '../features/assetPreview';
import type { LibraryAsset } from '../features/pageServices';
import LibraryAssetThumbnail from './assets/LibraryAssetThumbnail.vue';
const props = defineProps<{ board?: { nodes?: any[]; edges?: any[]; revision?: string }; apiBaseUrl: string; projectId: string }>();
const nodes = computed(() => props.board?.nodes || []);
const sizes = computed(() => new Map(nodes.value.map(node => [node.id, nodePreviewSize(node.data)])));
const size = (node: any) => sizes.value.get(node.id)!;
const bounds = computed(() => {
  if (!nodes.value.length) return '0 0 600 340';
  const xs = nodes.value.map(n => Number(n.position?.x || 0));
  const ys = nodes.value.map(n => Number(n.position?.y || 0));
  const right = Math.max(...nodes.value.map((node, index) => xs[index] + size(node).width));
  const bottom = Math.max(...nodes.value.map((node, index) => ys[index] + size(node).height + 40));
  return `${Math.min(...xs) - 50} ${Math.min(...ys) - 50} ${right - Math.min(...xs) + 100} ${bottom - Math.min(...ys) + 100}`;
});
function connection(edge: any) {
  const start = nodes.value.find(n => n.id === edge.source), end = nodes.value.find(n => n.id === edge.target);
  if (!start || !end) return '';
  const x = start.position.x + size(start).width, y = start.position.y + (size(start).height + 40) / 2;
  const endY = end.position.y + (size(end).height + 40) / 2;
  return `M${x},${y} C${x + 50},${y} ${end.position.x - 50},${endY} ${end.position.x},${endY}`;
}
const previewAssets = computed(() => new Map(nodes.value.map(node => {
  const data = node.data || {}, asset = data.asset || {};
  const assetId = data.assetId || asset.id;
  // Older preview responses have only kind + assetId. Canvas HTML is loaded
  // separately so project cards never need the entire board's embedded images.
  const htmlNodeId = data.htmlNodeId || (data.htmlNodeId === undefined && data.kind === 'html' && !assetId ? node.id : undefined);
  const preview: LibraryAsset = { id: assetId || node.id, projectId: asset.projectId || props.projectId,
    kind: canvasNodeKind(data), pathRelative: asset.pathRelative || '', mime: asset.mime, byteSize: 0,
    htmlNodeId, revision: props.board?.revision };
  return [node.id, (assetId || htmlNodeId) && assetPreviewKind(preview) ? preview : null];
})));
const labels: Record<string, string> = { image: '图片', video: '视频', html: '网页', audio: '音频', '3d': '3D 模型', text: '文本', upload: '素材', document: '文档' };
const icons: Record<string, any> = { image: Image, video: SquarePlay, html: FileCode2, audio: AudioLines, '3d': Box };
function placeholder(node: any) {
  const data = node.data || {}, label = labels[canvasNodeKind(data)] || '素材';
  return data.error ? '生成失败' : data.generating ? '正在生成…' : (data.assetId || data.asset?.id) ? label : `暂无${label}`;
}
function pageSize(node: any) {
  // Match the canvas iframe's desktop viewport even when the SVG is tiny.
  const frame = size(node);
  return { width: frame.width / HTML_PREVIEW_SCALE, height: frame.height / HTML_PREVIEW_SCALE };
}
</script>
<template>
  <svg class="project-board-preview" :viewBox="bounds" role="img" aria-label="项目画布预览" preserveAspectRatio="xMidYMid meet">
    <path v-for="edge in board?.edges || []" :key="edge.id" :d="connection(edge)" fill="none" stroke="currentColor" stroke-width="3" opacity=".5" />
    <g v-for="node in nodes" :key="node.id" :data-node-id="node.id" :transform="`translate(${node.position?.x || 0},${node.position?.y || 0})`">
      <rect :width="size(node).width" :height="size(node).height + 40" rx="16" class="project-board-node" />
      <text x="16" y="24" font-size="13" fill="currentColor">{{ (node.data?.title || '设计节点').slice(0, Math.floor((size(node).width - 32) / 13)) }}</text>
      <foreignObject x="0" y="35" :width="size(node).width" :height="size(node).height">
        <div xmlns="http://www.w3.org/1999/xhtml" class="project-board-content">
          <LibraryAssetThumbnail v-if="previewAssets.get(node.id)" :asset="previewAssets.get(node.id)!" :api-base-url="apiBaseUrl" :page-size="pageSize(node)" fit="contain" paused />
          <p v-else-if="node.data?.text || node.data?.summary" class="project-board-text">{{ (node.data.text || node.data.summary).slice(0, 140) }}</p>
          <div v-else class="project-board-placeholder"><component :is="icons[canvasNodeKind(node.data)] || FileText" :size="36" /><span>{{ placeholder(node) }}</span></div>
        </div>
      </foreignObject>
    </g>
    <text v-if="!nodes.length" x="300" y="180" text-anchor="middle" fill="currentColor" font-size="20" opacity=".5">画布尚未添加节点</text>
  </svg>
</template>
<style scoped>
.project-board-content { position: relative; width: 100%; height: 100%; overflow: hidden; border-radius: 0 0 12px 12px; pointer-events: none; }
.project-board-text { padding: 12px 16px; white-space: pre-wrap; }
.project-board-placeholder { display: flex; height: 100%; flex-direction: column; align-items: center; justify-content: center; gap: 12px; font-size: 16px; }
</style>
