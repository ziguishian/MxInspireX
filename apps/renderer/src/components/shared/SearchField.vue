<script setup lang="ts">
import { Search } from 'lucide-vue-next';
defineProps<{ label: string; placeholder?: string }>();
const model = defineModel<string>({ required: true });
</script>
<template><label class="project-search"><Search :size="14" /><input v-model="model" type="search" :placeholder="placeholder || label" :aria-label="label" /></label></template>
