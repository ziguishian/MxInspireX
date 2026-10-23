<script setup lang="ts">
import { Box } from 'lucide-vue-next';
const capabilities = [
  { name: '图片转矢量', engine: 'VTracer · 本地描摹', description: '将图片转换为真实 SVG 路径，保留原图，可预览和下载矢量文件。', entry: '画布 → 图片节点右键 → 转矢量' },
  { name: '参数化 CAD', engine: '本地脚本构建', description: '通过参数化脚本构建模型，可调整参数并导出 STEP、STL 等文件。需本机 CAD 运行环境；生成脚本使用已配置的文本模型。', entry: '画布 → CAD 节点' },
  { name: 'HTML 与交付导出', engine: '预览与导出', description: '预览 HTML 设计并导出作品；桌面端支持 HTML / PDF 导出。生成内容使用已配置的模型。', entry: '画布 → HTML 节点 → 预览或导出' },
];
</script>

<template>
  <div class="local-capabilities">
    <div class="provider-config-heading"><span>设计工具与脚本能力</span><small>在画布中使用，运行依赖由下方能力组件管理</small></div>
    <article v-for="item in capabilities" :key="item.name" class="runtime-component-card">
      <div class="runtime-component-icon"><Box :size="18" /></div>
      <div><strong>{{ item.name }}</strong><p>{{ item.description }}</p><small>{{ item.engine }}</small><p class="capability-entry">{{ item.entry }}</p></div>
    </article>
  </div>
</template>

<style scoped>
.local-capabilities { display:grid; gap:14px; }
.capability-entry { color:var(--theme-text-muted); font-size:var(--ui-font-caption); }
</style>
