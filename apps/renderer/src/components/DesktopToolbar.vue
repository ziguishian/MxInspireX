<script setup lang="ts">
import HomeUsageSummary from './home/HomeUsageSummary.vue';
</script>
<template><div class="window-chrome desktop-toolbar"><span class="desktop-brand">MxInspireX</span><HomeUsageSummary /></div></template>
<style scoped>
.desktop-toolbar { display:grid; grid-template-columns:240px 1fr 240px; padding:0 8px; box-sizing:border-box; }
.desktop-brand { padding-left:10px; color:var(--theme-text); font-size:13px; font-weight:600; letter-spacing:.01em; }
.home-usage { grid-column:2; justify-self:center; font-size:11px; }
@media(max-width:900px){.desktop-toolbar{grid-template-columns:210px 1fr 150px}.home-usage :deep(dt){display:none}}
</style>
