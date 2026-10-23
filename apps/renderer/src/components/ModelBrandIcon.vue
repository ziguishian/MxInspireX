<script setup lang="ts">
import { computed } from 'vue';
import { modelBrand } from '../features/modelBrand';
import { modelPrices } from '../modelEconomy';
import sprite from '../assets/model-brands.svg?raw';
// Inline only this bundled symbol: external <use> is blocked for data/file URLs.
const symbols = Object.fromEntries([...sprite.matchAll(/<symbol id="([^"]+)"[^>]*>([\s\S]*?)<\/symbol>/g)].map(match => [match[1], match[2]]));
const props = defineProps<{ model: string }>();
const brand = computed(() => {
  const entry = modelPrices.value.find(item => item.id === props.model);
  return modelBrand(props.model, `${entry?.vendor || ''} ${entry?.ownedBy || ''}`);
});
</script>
<template><svg class="model-brand-icon" viewBox="0 0 24 24" role="img" :aria-label="brand.label" v-html="symbols[brand.id]" /></template>
<style scoped>.model-brand-icon { width: 20px; height: 20px; flex: 0 0 20px; color: currentColor; }</style>
