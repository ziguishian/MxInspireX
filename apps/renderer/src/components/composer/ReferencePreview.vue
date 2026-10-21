<script setup lang="ts">
import type { InlineReference } from '../../features/composer/references';
import { FileText } from 'lucide-vue-next';
defineProps<{ item: InlineReference; x: number; y: number }>();
</script>
<template><Teleport to="body"><aside class="composer-reference-preview" role="tooltip" :style="{ left: `${x}px`, top: `${y}px` }"><img v-if="item.preview" :src="item.preview" :alt="item.label" /><div v-else-if="item.textContent" class="reference-text-preview"><FileText :size="17" /><p>{{ item.textContent.slice(0, 360) }}</p></div><div v-else class="reference-document-preview">{{ item.kind }}</div><strong>{{ item.label }}</strong><small>{{ item.kind }}</small></aside></Teleport></template>
<style scoped>
.composer-reference-preview { position:fixed; z-index:1000; width:216px; padding:6px; border:1px solid var(--theme-border); border-radius:14px; background:var(--theme-surface-raised); color:var(--theme-text); box-shadow:0 12px 40px #0003; pointer-events:none; }
img { width:202px; height:180px; display:block; object-fit:contain; border-radius:9px; background:var(--theme-surface-subtle); }
.reference-text-preview { height:100px; overflow:hidden; padding:8px; border-radius:9px; background:var(--theme-surface-subtle); color:var(--theme-text-muted); }
.reference-text-preview p { display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:4; overflow:hidden; margin:5px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:11px; line-height:1.5; }
strong, small { display:block; margin:7px 6px 4px; font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } small { color:var(--theme-text-subtle); } .reference-document-preview { display:grid; place-items:center; height:100px; font-size:20px; color:var(--theme-text-muted); }
</style>
