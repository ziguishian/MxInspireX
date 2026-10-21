<script setup lang="ts">
import { computed } from 'vue';
const props = withDefaults(defineProps<{ total: number; pageSize: number; itemLabel?: string; alwaysVisible?: boolean }>(), { itemLabel: '项目', alwaysVisible: false });
const page = defineModel<number>({ required: true });
type PageItem = { type: 'page' | 'ellipsis'; value?: number; key: string };
const pageCount = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
const items = computed<PageItem[]>(() => {
  const total = pageCount.value;
  const current = Math.min(page.value, total);
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => {
      const page = index + 1;
      return { type: 'page', value: page, key: `page-${page}` };
    });
  }
  const pageSet = new Set<number>([1, total, current]);
  if (current > 2) pageSet.add(current - 1);
  if (current < total - 1) pageSet.add(current + 1);
  const pages = [...pageSet].sort((a, b) => a - b);
  const items: PageItem[] = [];
  pages.forEach((page, index) => {
    const previous = pages[index - 1];
    if (previous && page - previous > 1) items.push({ type: 'ellipsis', key: `ellipsis-${previous}-${page}` });
    items.push({ type: 'page', value: page, key: `page-${page}` });
  });
  return items;
});
</script>
<template>
  <nav v-if="alwaysVisible || pageCount > 1" class="project-pagination" :aria-label="`${itemLabel}分页`">
    <span class="project-pagination-meta">共 {{ total }} 个{{ itemLabel }} · 第 {{ page }} / {{ pageCount }} 页</span>
    <button type="button" :disabled="page <= 1" aria-label="上一页" @click="page -= 1">上一页</button>
    <div class="project-pagination-pages"><template v-for="item in items" :key="item.key"><span v-if="item.type === 'ellipsis'" class="project-pagination-ellipsis" aria-hidden="true">…</span><button v-else type="button" :class="{ active: page === item.value }" :aria-current="page === item.value ? 'page' : undefined" :aria-label="`第 ${item.value} 页`" @click="page = item.value || 1">{{ item.value }}</button></template></div>
    <button type="button" :disabled="page >= pageCount" aria-label="下一页" @click="page += 1">下一页</button>
  </nav>
</template>
