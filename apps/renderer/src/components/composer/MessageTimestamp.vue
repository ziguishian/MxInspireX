<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{ value?: string | null }>();
const date = computed(() => { const value = props.value ? new Date(props.value) : null; return value && Number.isFinite(value.getTime()) ? value : null; });
</script>
<template><time v-if="date" :datetime="date.toISOString()" :title="date.toLocaleString()">{{ date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) }}</time></template>
<style scoped>time { align-self:center; padding:0 5px; color:var(--theme-text-muted); font-size:var(--ui-font-caption); white-space:nowrap; }</style>
