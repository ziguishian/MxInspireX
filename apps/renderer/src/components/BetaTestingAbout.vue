<script setup lang="ts">
import { ref } from 'vue';
import { Download, FlaskConical, LoaderCircle } from 'lucide-vue-next';
const props = defineProps<{ apiBaseUrl: string }>();
const exporting = ref(false), message = ref(''), failed = ref(false);
async function exportLogs() {
  if (exporting.value) return;
  exporting.value = true; message.value = ''; failed.value = false;
  try {
    if (window.studio?.exportTestingLogs) {
      const path = await window.studio.exportTestingLogs();
      if (path) message.value = `日志已导出：${path}`;
    } else {
      const response = await fetch(`${props.apiBaseUrl}/api/testing/export`);
      if (!response.ok || !response.headers.get('content-type')?.includes('application/zip')) throw new Error('日志导出失败，请确认本地服务已连接');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = `MxinspireX-beta-logs-${new Date().toISOString().slice(0, 10)}.zip`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
      message.value = '日志压缩包已下载';
    }
  } catch (cause) { failed.value = true; message.value = cause instanceof Error ? cause.message : '日志导出失败，请重试'; }
  finally { exporting.value = false; }
}
</script>

<template>
  <div class="beta-testing-about" @click.stop>
    <strong><FlaskConical :size="15" />测试版 · Beta</strong>
    <p>功能与体验持续完善中，欢迎通过评分与反馈帮助我们改进。</p>
    <p>使用记录与评分保存在本机。导出日志包含近 30 天的对话文本、任务运行过程和评分，用于问题排查；会过滤常见密钥，不包含原始素材文件。</p>
    <button type="button" class="beta-export-logs" :disabled="exporting" @click="exportLogs"><LoaderCircle v-if="exporting" :size="15" class="spin-icon" /><Download v-else :size="15" />{{ exporting ? '正在导出日志…' : '一键导出日志' }}</button>
    <p v-if="message" class="beta-export-result" :class="{ failed }" role="status">{{ message }}</p>
  </div>
</template>

<style scoped>
.beta-testing-about { width: 100%; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--theme-border); }
.beta-testing-about strong { display: flex; align-items: center; gap: 7px; color: var(--theme-accent-strong); font-size: 12px; font-weight: 500; }
.beta-testing-about p { margin: 8px 0 0; color: var(--theme-text-muted); font-size: 11px; line-height: 1.75; }
.beta-export-logs { display: inline-flex; align-items: center; gap: 7px; margin-top: 12px; padding: 8px 12px; border: 1px solid var(--theme-border); border-radius: 8px; background: transparent; color: var(--theme-text); font-size: 12px; cursor: pointer; }
.beta-export-logs:hover { border-color: var(--theme-accent-strong); }
.beta-export-logs:disabled { opacity: .6; cursor: wait; }
.beta-testing-about .beta-export-result { overflow-wrap: anywhere; color: var(--theme-accent-strong); }
.beta-testing-about .beta-export-result.failed { color: var(--theme-danger); }
</style>
