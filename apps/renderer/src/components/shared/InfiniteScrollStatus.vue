<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = withDefaults(defineProps<{ hasMore: boolean; loading?: boolean; loaded: number; total: number; itemLabel?: string }>(), {
  loading: false,
  itemLabel: '项',
});
const emit = defineEmits<{ 'load-more': [] }>();
const target = ref<HTMLElement | null>(null);
const loadingLabel = computed(() => props.itemLabel.replace(/^(个|张|项)/, '') || '内容');
let observer: IntersectionObserver | undefined;
let requested = false;
let checkFrame = 0;
let observerFrame = 0;

function requestMore() {
  if (requested || props.loading || !props.hasMore) return;
  requested = true;
  emit('load-more');
}

function checkPosition() {
  const element = target.value;
  if (!element) return;
  const rect = element.getBoundingClientRect();
  if (rect.top <= window.innerHeight + 360 && rect.bottom >= -360) requestMore();
}

function schedulePositionCheck() {
  cancelAnimationFrame(checkFrame);
  checkFrame = requestAnimationFrame(() => {
    checkFrame = requestAnimationFrame(checkPosition);
  });
}

watch(() => [props.loading, props.loaded, props.hasMore], async () => {
  if (!props.loading) requested = false;
  await nextTick();
  schedulePositionCheck();
});

onMounted(() => {
  observerFrame = requestAnimationFrame(() => {
    observerFrame = requestAnimationFrame(() => {
      observer = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) requestMore();
      }, { rootMargin: '360px 0px' });
      if (target.value) observer.observe(target.value);
      checkPosition();
    });
  });
});
onBeforeUnmount(() => { cancelAnimationFrame(checkFrame); cancelAnimationFrame(observerFrame); observer?.disconnect(); });
</script>

<template>
  <div ref="target" class="infinite-scroll-status" role="status" :aria-busy="loading">
    <LoaderCircle v-if="loading" :size="16" class="spin-icon" />
    <span v-if="loading">正在加载更多{{ loadingLabel }}…</span>
    <span v-else-if="hasMore">继续向下滚动加载更多{{ loadingLabel }}</span>
    <span v-else>已加载全部 {{ total }} {{ itemLabel }}</span>
  </div>
</template>

<style scoped>
.infinite-scroll-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 52px;
  color: var(--theme-text-muted);
  font-size: 12px;
}
</style>
