<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue';
import { useVueFlow } from '@vue-flow/core';
import { nodePreviewSize } from '../nodeSizing';

type Point = { x: number; y: number };
type Rect = Point & { width: number; height: number };
const emit = defineEmits<{ navigate: [center: Point]; close: [] }>();
const { getNodes, getEdges, viewport, dimensions } = useVueFlow('design-canvas');
const svg = ref<SVGSVGElement | null>(null);
const drag = ref<{ pointerId: number; projection: Rect; offset: Point } | null>(null);
const frames = computed(() => getNodes.value.filter(node => !node.hidden).map(node => {
  const fallback = nodePreviewSize(node.data);
  return { id: node.id, x: node.computedPosition.x, y: node.computedPosition.y,
    width: node.dimensions.width || fallback.width, height: node.dimensions.height || fallback.height + 26,
    selected: node.selected, title: node.data?.title || node.data?.label || '未命名节点' };
}));
const visibleArea = computed<Rect>(() => ({ x: -viewport.value.x / viewport.value.zoom, y: -viewport.value.y / viewport.value.zoom,
  width: dimensions.value.width / viewport.value.zoom, height: dimensions.value.height / viewport.value.zoom }));
// The viewport marker stays live, while the map's scale settles after a
// gesture. Changing the SVG viewBox every frame rescales every miniature node.
const settledArea = shallowRef<Rect>({ ...visibleArea.value });
let settleTimer: ReturnType<typeof setTimeout> | undefined;
watch(visibleArea, () => {
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => { settledArea.value = { ...visibleArea.value }; }, 120);
});
const projection = computed<Rect>(() => {
  // Freeze the coordinate system during navigation so moving the viewport
  // cannot resize the map underneath the pointer and accelerate the gesture.
  if (drag.value) return drag.value.projection;
  const rects = [...frames.value, settledArea.value];
  const x = Math.min(...rects.map(rect => rect.x)), y = Math.min(...rects.map(rect => rect.y));
  const width = Math.max(1, ...rects.map(rect => rect.x + rect.width - x));
  const height = Math.max(1, ...rects.map(rect => rect.y + rect.height - y));
  const padding = Math.max(width, height) * .06 + 24;
  return { x: x - padding, y: y - padding, width: width + 2 * padding, height: height + 2 * padding };
});
const viewBox = computed(() => { const p = projection.value; return `${p.x} ${p.y} ${p.width} ${p.height}`; });
const connections = computed(() => {
  const byId = new Map(frames.value.map(frame => [frame.id, frame]));
  return getEdges.value.filter(edge => !edge.hidden).flatMap(edge => {
    const a = byId.get(edge.source), b = byId.get(edge.target);
    return a && b ? [{ id: edge.id, x1: a.x + a.width, y1: a.y + a.height / 2, x2: b.x, y2: b.y + b.height / 2 }] : [];
  });
});
function pointAt(event: PointerEvent): Point | null {
  const matrix = svg.value?.getScreenCTM();
  if (!matrix || !svg.value) return null;
  const point = svg.value.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
  const result = point.matrixTransform(matrix.inverse());
  return { x: result.x, y: result.y };
}
function startNavigation(event: PointerEvent) {
  if (event.button !== 0 || !svg.value) return;
  const point = pointAt(event); if (!point) return;
  event.preventDefault(); svg.value.focus({ preventScroll: true });
  const insideViewport = event.target instanceof Element && Boolean(event.target.closest('.canvas-overview-viewport'));
  const area = visibleArea.value;
  drag.value = { pointerId: event.pointerId, projection: { ...projection.value },
    offset: insideViewport ? { x: point.x - area.x - area.width / 2, y: point.y - area.y - area.height / 2 } : { x: 0, y: 0 } };
  svg.value.setPointerCapture(event.pointerId);
  if (!insideViewport) emit('navigate', point);
}
function moveNavigation(event: PointerEvent) {
  if (!drag.value || event.pointerId !== drag.value.pointerId) return;
  const point = pointAt(event); if (!point) return;
  emit('navigate', { x: point.x - drag.value.offset.x, y: point.y - drag.value.offset.y });
}
function stopNavigation() {
  const gesture = drag.value; drag.value = null;
  if (gesture && svg.value?.hasPointerCapture(gesture.pointerId)) svg.value.releasePointerCapture(gesture.pointerId);
}
function navigateWithKeyboard(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); stopNavigation(); emit('close'); return; }
  if (event.metaKey || event.ctrlKey || event.altKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault(); event.stopPropagation();
  const area = visibleArea.value, step = (event.shiftKey ? 240 : 80) / viewport.value.zoom;
  emit('navigate', { x: area.x + area.width / 2 + (event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0),
    y: area.y + area.height / 2 + (event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0) });
}
onMounted(() => window.addEventListener('blur', stopNavigation));
onUnmounted(() => { stopNavigation(); clearTimeout(settleTimer); window.removeEventListener('blur', stopNavigation); });
</script>

<template>
  <aside id="canvas-overview" class="canvas-overview nodrag nopan nowheel" aria-label="画布观察视图" @pointerdown.stop @mousedown.stop @click.stop @dblclick.stop.prevent @contextmenu.stop.prevent @wheel.stop.prevent>
    <header><span>画布观察</span><small>{{ frames.length }} 个节点</small></header>
    <div class="canvas-overview-map">
      <svg ref="svg" :viewBox="viewBox" preserveAspectRatio="xMidYMid meet" tabindex="0" role="group" aria-label="画布导航，点击或拖动定位，方向键移动视野" @pointerdown="startNavigation" @pointermove="moveNavigation" @pointerup="stopNavigation" @pointercancel="stopNavigation" @lostpointercapture="stopNavigation" @keydown="navigateWithKeyboard">
        <line v-for="edge in connections" :key="edge.id" v-bind="edge" class="canvas-overview-edge" vector-effect="non-scaling-stroke" />
        <rect v-for="node in frames" :key="node.id" :data-node-id="node.id" :x="node.x" :y="node.y" :width="node.width" :height="node.height" :rx="Math.min(node.width, node.height) * .06" class="canvas-overview-node" :class="{ selected: node.selected }" vector-effect="non-scaling-stroke"><title>{{ node.title }}</title></rect>
        <rect v-bind="visibleArea" class="canvas-overview-viewport" vector-effect="non-scaling-stroke" />
      </svg>
      <span v-if="!frames.length" class="canvas-overview-empty">尚无节点</span>
    </div>
    <small class="canvas-overview-hint">点击或拖动定位</small>
  </aside>
</template>
