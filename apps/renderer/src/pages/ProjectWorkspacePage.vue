<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { House } from 'lucide-vue-next';
import GeneralCanvas from '../components/GeneralCanvas.vue';
import EmptyState from '../components/shared/EmptyState.vue';
import { projectWorkspaceServices } from '../features/pageServices';
const { isLoading, errorMessage, options, designCanvasVisible, events } = projectWorkspaceServices.use();
const route = useRoute();
// Never show the previous project's canvas while this URL is still hydrating.
const projectOptions = computed(() => options.value?.projectId === route.params.projectId ? options.value : null);
</script>

<template>
<div class="design-agent-page">
  <GeneralCanvas v-if="projectOptions" :key="projectOptions.projectId" v-model:canvas-visible="designCanvasVisible" v-bind="projectOptions" v-on="events" />
  <template v-else>
    <button type="button" class="canvas-home-button canvas-loading-home" aria-label="返回首页" title="返回首页" @click="events['return-home']"><House :size="18" :stroke-width="1.7" /></button>
    <EmptyState>{{ isLoading ? '正在读取项目…' : errorMessage || '等待本地服务连接，恢复后会继续读取项目。' }}</EmptyState>
  </template>
</div>
</template>
