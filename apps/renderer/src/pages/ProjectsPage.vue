<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Plus, Search } from 'lucide-vue-next';
import ProjectCard from '../components/projects/ProjectCard.vue';
import MasonryGrid from '../components/shared/MasonryGrid.vue';
import { projectCompleted, projectActivity } from '../features/projectStatus';
import LibraryPageLayout from '../components/shared/LibraryPageLayout.vue';
import EmptyState from '../components/shared/EmptyState.vue';
import InfiniteScrollStatus from '../components/shared/InfiniteScrollStatus.vue';
import { projectLibraryServices } from '../features/pageServices';

const { projects, isLoading, errorMessage, apiBaseUrl, projectCanvasPreviews, loadPreview, selectProject, createBlankCanvas, renameProject, requestDeleteProject } = projectLibraryServices.use();
const search = ref('');
const filter = ref<'all' | 'recent' | 'completed'>('all');
const projectBatchSize = 18;
const visibleProjectCount = ref(projectBatchSize);
const filteredProjects = computed(() => {
  const query = search.value.trim().toLowerCase();
  let list = projects.value;
  if (filter.value === 'recent') list = [...list].sort((a, b) => projectActivity(b).localeCompare(projectActivity(a)));
  if (filter.value === 'completed') list = list.filter(project => projectCompleted(project));
  return list.filter(project => !query || `${project.name} ${project.summary || project.brief}`.toLowerCase().includes(query));
});
const visibleProjects = computed(() => filteredProjects.value.slice(0, visibleProjectCount.value));
const hasMoreProjects = computed(() => visibleProjects.value.length < filteredProjects.value.length);
watch([search, filter], () => { visibleProjectCount.value = projectBatchSize; });
function loadMoreProjects() { visibleProjectCount.value = Math.min(visibleProjectCount.value + projectBatchSize, filteredProjects.value.length); }
</script>

<template>
  <LibraryPageLayout v-model:search="search" class="projects-page" eyebrow="PROJECTS / LOCAL WORKSPACE" title="我的项目" description="保留每个项目的对话与画布，随时继续设计。" search-label="搜索项目">
    <template #meta>共 {{ filteredProjects.length }} 个项目</template>
    <template #filters>
      <select v-model="filter" aria-label="筛选项目"><option value="all">全部项目</option><option value="recent">最近更新</option><option value="completed">已完成</option></select>
    </template>
    <EmptyState v-if="isLoading">正在读取项目…</EmptyState>
    <EmptyState v-else-if="errorMessage && !projects.length">{{ errorMessage }}</EmptyState>
    <template v-else>
      <MasonryGrid class="projects-grid">
        <article class="project-create-entry">
          <button class="project-create-card" type="button" aria-label="新建空白画布" @click="createBlankCanvas"><Plus :size="26" :stroke-width="1.5" /><strong>开始创作</strong></button>
        </article>
        <ProjectCard v-for="project in visibleProjects" :key="project.id" :project="project" :board="projectCanvasPreviews[project.id]" :api-base-url="apiBaseUrl" :rename="renameProject" :load-preview="loadPreview" @open="selectProject" @delete="requestDeleteProject" />
      </MasonryGrid>
      <EmptyState v-if="projects.length && !filteredProjects.length" class="projects-empty-search" :icon="Search" title="没有找到匹配的项目">请调整搜索或筛选条件。</EmptyState>
    </template>
    <InfiniteScrollStatus v-if="!isLoading && filteredProjects.length" :has-more="hasMoreProjects" :loaded="visibleProjects.length" :total="filteredProjects.length" item-label="个项目" @load-more="loadMoreProjects" />
  </LibraryPageLayout>
</template>

<style scoped>
.project-create-entry { position: relative; z-index: 0; display: grid; align-content: start; inline-size: 100%; min-width: 0; max-width: 100%; overflow: visible; }
.project-create-card { position: relative; z-index: 0; display: grid; inline-size: 100%; min-inline-size: 0; max-inline-size: 100%; margin: 0; padding: 0; aspect-ratio: var(--library-preview-ratio, 16 / 9); place-content: center; justify-items: center; gap: 10px; border: 1px solid var(--theme-border-strong); border-radius: var(--ui-radius-card); background: var(--theme-surface-subtle); color: var(--theme-text); box-shadow: var(--ui-media-shadow); transition: border-color .16s ease, background .16s ease, transform .16s ease; }
.project-create-card svg { color: var(--theme-text-muted); }
.project-create-card strong { font-size: var(--ui-font-card); font-weight: 600; }
.project-create-entry:has(.project-create-card:is(:hover, :focus-visible)) { z-index: 2; }
.project-create-card:hover { z-index: 1; border-color: var(--theme-accent-strong); background: var(--theme-surface-hover); transform: translate3d(0, -2px, 0); }
.project-create-card:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 4px; }
.projects-empty-search { margin-top: 24px; }
@media (prefers-reduced-motion: reduce) { .project-create-card { transition: none; } }
</style>
