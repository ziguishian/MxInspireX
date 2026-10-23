<script setup lang="ts">
import { computed } from 'vue';
import { mascotSpriteStyle, useMascotSettings } from '../features/home/mascot';
import { xiaojuStateLabels, type XiaojuState } from '../features/xiaojuState';
withDefaults(defineProps<{ state?: XiaojuState }>(), { state: 'idle' });
const mascot = useMascotSettings();
const agentName = computed(() => mascot?.activeName.value || '点阵机器人');
const spriteStyle = computed(() => mascot
  ? mascotSpriteStyle(mascot.apiBaseUrl, mascot.active.value, mascot.activePreset.value)
  : mascotSpriteStyle('', null));
</script>
<template><span class="agent-avatar-sprite" :style="spriteStyle" :data-state="state" role="img" :aria-label="`${agentName} · ${xiaojuStateLabels[state]}`" :title="xiaojuStateLabels[state]" /></template>
