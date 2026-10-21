<script setup lang="ts">
import { Pause, Play, RotateCcw, SkipForward, LoaderCircle, Check } from 'lucide-vue-next';
defineProps<{ name:string; progress:string; playing:boolean; preparing:boolean; done:boolean; completed:number; total:number; error:string }>();
defineEmits<{ pause:[]; play:[]; replay:[]; finish:[] }>();
</script>
<template>
<section class="demo-playback" aria-label="项目制作进度">
  <div class="demo-label"><span>制作进度</span><small>方案内容将按阶段保存到画布</small></div>
  <strong>{{ name }}</strong>
  <p role="status" aria-live="polite"><Check v-if="done" :size="14"/><LoaderCircle v-else-if="playing || preparing" :size="14" class="spin-icon"/>{{ progress }}</p>
  <progress :value="completed" :max="total" :aria-label="`已展示 ${completed} / ${total} 项产物`"/>
  <p v-if="error" class="demo-error" role="alert">{{ error }}</p>
  <div class="demo-buttons">
    <button v-if="playing" @click="$emit('pause')"><Pause :size="14"/>暂停制作</button>
    <button v-else-if="!done" :disabled="preparing" @click="$emit('play')"><Play :size="14"/>{{ error ? '重试制作' : '继续制作' }}</button>
    <button v-else @click="$emit('replay')"><RotateCcw :size="14"/>重新制作</button>
    <button v-if="!done" :disabled="preparing" @click="$emit('finish')"><SkipForward :size="14"/>查看完整方案</button>
  </div>
  <small class="demo-help">{{ done ? '产物已保存，可放大、预览和导出。' : '各项产物会按阶段逐步展示；离开项目自动暂停。' }}</small>
</section>
</template>
<style scoped>
.demo-playback{margin:8px 0 0;padding:18px;border:1px solid var(--theme-border);border-radius:18px;background:var(--theme-surface);color:var(--theme-text)}.demo-label{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px}.demo-label span{font-size:11px;background:var(--theme-surface-subtle);padding:4px 8px;border-radius:6px;color:var(--theme-accent-strong)}small{font-size:10px;color:var(--theme-text-muted)}strong{font-size:14px}.demo-playback p{display:flex;align-items:center;gap:7px;font-size:12px;margin:10px 0;color:var(--theme-text-muted)}progress{width:100%;height:4px;accent-color:var(--theme-accent-strong)}.demo-buttons{display:flex;gap:8px;margin:14px 0 9px}.demo-buttons button{display:flex;align-items:center;justify-content:center;gap:6px;flex:1;padding:9px 7px;background:var(--theme-surface-subtle);color:var(--theme-text);border:1px solid var(--theme-border);border-radius:9px;cursor:pointer;font-size:11px}.demo-buttons button:first-child{background:var(--theme-accent-strong);color:var(--theme-surface)}button:disabled{opacity:.5;cursor:wait}button:focus-visible{outline:2px solid var(--theme-accent-strong);outline-offset:2px}.demo-playback .demo-error{color:#595959;line-height:1.5}.demo-help{display:block;line-height:1.5}
</style>
