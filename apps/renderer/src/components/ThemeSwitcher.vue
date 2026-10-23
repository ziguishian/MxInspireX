<script setup lang="ts">
import { computed } from 'vue';
import { Monitor, Moon, Sun } from 'lucide-vue-next';
const mode = defineModel<'system' | 'light' | 'dark'>({ required: true });
const choices = [{ value: 'system', label: '跟随系统', icon: Monitor }, { value: 'light', label: '浅色模式', icon: Sun }, { value: 'dark', label: '深色模式', icon: Moon }] as const;
const active = computed(() => choices.find(item => item.value === mode.value)!);
const next = computed(() => choices[(choices.findIndex(item => item.value === mode.value) + 1) % choices.length]);
</script>
<template>
  <div class="mx-theme-switch">
    <button type="button" :aria-label="`界面主题：${active.label}，点击切换为${next.label}`" :title="`当前${active.label} · 切换为${next.label}`" @click="mode = next.value"><component :is="active.icon" :size="18" :stroke-width="1.5" /></button>
  </div>
</template>
<style scoped>
.mx-theme-switch { border:0; padding:0; background:transparent; }
.mx-theme-switch > button { width:36px; height:36px; border:1px solid var(--theme-border); border-radius:50%; background:var(--theme-surface); }
</style>
