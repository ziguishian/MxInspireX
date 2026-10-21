<script setup lang="ts">
import type { Component } from 'vue';
defineProps<{ title?: string; icon?: Component }>();
</script>
<template>
  <div class="product-empty" :class="{ 'is-illustrated': title || icon }" role="status">
    <component :is="icon" v-if="icon" :size="32" :stroke-width="1.5" class="product-empty-icon" aria-hidden="true" />
    <h3 v-if="title">{{ title }}</h3>
    <p><slot /></p>
    <div v-if="$slots.action" class="product-empty-action"><slot name="action" /></div>
  </div>
</template>
<style scoped>
.product-empty { display: grid; align-content: center; justify-items: center; gap: 12px; min-width: 0; min-height: 96px; padding: 32px 24px; border: 1px dashed var(--theme-border); border-radius: var(--ui-radius-card); color: var(--theme-text-muted); text-align: center; font-size: var(--ui-font-body); line-height: var(--ui-line-body); }
.product-empty.is-illustrated { min-height: 280px; }
.product-empty-icon { margin-bottom: 4px; color: var(--theme-text-muted); }
.product-empty h3 { margin: 0; color: var(--theme-text); font-size: var(--ui-font-section); font-weight: 600; line-height: var(--ui-line-heading); }
.product-empty p { max-width: 44rem; margin: 0; overflow-wrap: anywhere; }
.product-empty-action { margin-top: 4px; }
@media (max-width: 600px) { .product-empty { padding: 24px 18px; } .product-empty.is-illustrated { min-height: 240px; } }
</style>
