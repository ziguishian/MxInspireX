<script setup lang="ts">
defineProps<{ eyebrow: string; title: string; description?: string }>();
</script>
<template>
  <header class="page-heading">
    <div><p class="eyebrow">{{ eyebrow }}</p><h2>{{ title }}</h2><p v-if="description || $slots.default" class="muted"><slot>{{ description }}</slot></p></div>
    <div v-if="$slots.actions" class="page-heading-actions"><slot name="actions" /></div>
  </header>
</template>
<style scoped>
.page-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:24px; }
.page-heading > div:first-child { min-width:0; }
h2 { margin:6px 0 10px; font-size:var(--ui-font-page); font-weight:600; line-height:var(--ui-line-heading); } p { line-height:1.65; } .page-heading-actions { flex-shrink:0; }
@media(max-width:680px) { .page-heading { flex-direction:column; gap:12px; } .page-heading-actions { width:100%; } }
.page-heading .muted { margin: 0; font-size: var(--ui-font-body); line-height: var(--ui-line-body); }
</style>
