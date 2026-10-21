<script setup lang="ts">
import { computed } from 'vue';
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@vue-flow/core';
import { X } from 'lucide-vue-next';

defineOptions({ inheritAttrs: false });
const props = defineProps<EdgeProps & { disabled?: boolean }>();
const emit = defineEmits<{ delete: [id: string] }>();
const curve = computed(() => getBezierPath({
  sourceX: props.sourceX, sourceY: props.sourceY, sourcePosition: props.sourcePosition,
  targetX: props.targetX, targetY: props.targetY, targetPosition: props.targetPosition,
  curvature: props.curvature ?? .25,
}));
</script>

<template>
  <BaseEdge :id="id" :path="curve[0]" :style="style" :marker-start="markerStart" :marker-end="markerEnd" :interaction-width="Math.max(interactionWidth ?? 20, 20)" />
  <EdgeLabelRenderer>
    <button v-if="selected" type="button" class="canvas-edge-delete nodrag nopan" :data-edge-id="id"
      :style="{ transform: `translate(-50%, -50%) translate(${curve[1]}px, ${curve[2]}px)` }"
      :disabled="disabled" aria-label="删除连线" title="删除连线（也可按 Backspace）"
      @pointerdown.stop @mousedown.stop @dblclick.stop @click.stop="emit('delete', id)">
      <X :size="16" :stroke-width="2.5" aria-hidden="true" />
    </button>
  </EdgeLabelRenderer>
</template>

<style scoped>
.canvas-edge-delete {
  position: absolute; top: 0; left: 0; display: grid; place-items: center;
  width: 28px; height: 28px; padding: 0; border: 1px solid #6c6c6c; border-radius: 50%;
  background: #1d1d1d; color: #999999; box-shadow: 0 2px 10px #0006;
  pointer-events: all; transition: background .15s, color .15s, box-shadow .15s;
}
.canvas-edge-delete:hover { background: #575757; color: #fff; box-shadow: 0 0 0 4px #8484841c; }
.canvas-edge-delete:focus-visible { outline: 2px solid #b0b0b0; outline-offset: 3px; }
.canvas-edge-delete:disabled { opacity: .5; cursor: wait; }
@media (prefers-reduced-motion: reduce) { .canvas-edge-delete { transition: none; } }
</style>
