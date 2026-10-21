<script setup lang="ts">
import { RouterLink } from 'vue-router';
import PageHeader from '../components/shared/PageHeader.vue';
</script>
<template><div class="library-page"><PageHeader eyebrow="404 / PAGE NOT FOUND" title="这个页面不存在" description="链接可能已经失效，你可以回到首页或项目列表。" /><RouterLink class="primary-button" to="/">返回首页</RouterLink> <RouterLink class="ghost-button" to="/projects">我的项目</RouterLink></div></template>
