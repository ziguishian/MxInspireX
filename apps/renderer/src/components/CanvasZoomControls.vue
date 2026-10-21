<script setup lang="ts">
import { useVueFlow } from '@vue-flow/core';
import { Minus, Plus } from 'lucide-vue-next';
import { MAX_CANVAS_ZOOM } from '../features/canvasWorkspace';

// Keep the live zoom label out of the board/chat render effect. Reading the
// viewport in GeneralCanvas made every pan tick update every node slot.
const { viewport, zoomIn, zoomOut } = useVueFlow('design-canvas');
const emit = defineEmits<{ fit: [] }>();
</script>

<template>
  <button type="button" aria-label="缩小画布" @click="zoomOut({ duration: 180 })"><Minus :size="17" /></button>
  <button type="button" aria-label="适应画布" @click="emit('fit')">{{ Math.round(viewport.zoom * 100) }}%</button>
  <button type="button" aria-label="放大画布" :disabled="viewport.zoom >= MAX_CANVAS_ZOOM" :title="`最大可放大至 ${MAX_CANVAS_ZOOM * 100}%`" @click="zoomIn({ duration: 180 })"><Plus :size="17" /></button>
</template>
