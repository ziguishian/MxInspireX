<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
import { Mic, Square, LoaderCircle } from 'lucide-vue-next';
const props = defineProps<{ apiBaseUrl: string }>();
const emit = defineEmits<{ text: [value: string] }>();
const phase = ref<'idle' | 'starting' | 'recording' | 'transcribing'>('idle');
const error = ref('');
let stream: MediaStream | undefined;
let recorder: MediaRecorder | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const controller = new AbortController();
function release() { clearTimeout(timer); stream?.getTracks().forEach(track => track.stop()); stream = undefined; }
async function api(init?: RequestInit) {
  const response = await fetch(`${props.apiBaseUrl}/api/voice-input`, { ...init, signal: controller.signal });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '语音输入服务暂不可用');
  return result;
}
async function toggle() {
  if (phase.value === 'recording') { if (recorder?.state === 'recording') recorder.stop(); return; }
  if (phase.value !== 'idle') return;
  phase.value = 'starting'; error.value = '';
  try {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('当前环境不支持录音，请使用桌面端或支持录音的浏览器。');
    await api();
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (disposed) { release(); return; }
    const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
    if (!mimeType) throw new Error('当前环境没有可用的录音格式');
    recorder = new MediaRecorder(stream, { mimeType });
    const chunks: Blob[] = [];
    let bytes = 0;
    recorder.ondataavailable = event => { if (event.data.size) { chunks.push(event.data); bytes += event.data.size; if (bytes > 9 * 1024 * 1024 && recorder?.state === 'recording') recorder.stop(); } };
    recorder.onerror = () => { error.value = '录音中断，请检查麦克风。'; release(); phase.value = 'idle'; };
    recorder.onstop = async () => {
      release();
      if (disposed || error.value) return;
      phase.value = 'transcribing';
      try {
        const body = new FormData(); body.append('file', new Blob(chunks, { type: mimeType }), 'dictation');
        const result = await api({ method: 'POST', body });
        if (!disposed) emit('text', result.text);
      } catch (cause) { if (!disposed) error.value = cause instanceof Error ? cause.message : '语音识别失败，未自动重试。'; }
      finally { phase.value = 'idle'; }
    };
    recorder.start(1000); phase.value = 'recording';
    timer = setTimeout(() => { if (recorder?.state === 'recording') recorder.stop(); }, 120000);
  } catch (cause) {
    release(); phase.value = 'idle';
    if (!disposed) error.value = cause instanceof DOMException && cause.name === 'NotAllowedError' ? '麦克风权限被拒绝，请在系统或浏览器设置中允许麦克风。' : cause instanceof DOMException && cause.name === 'NotFoundError' ? '未找到麦克风，请连接后再试。' : cause instanceof Error ? cause.message : '无法开始录音';
  }
}
onBeforeUnmount(() => { disposed = true; controller.abort(); if (recorder?.state === 'recording') recorder.stop(); release(); });
</script>
<template>
  <span class="voice-input">
    <button type="button" class="composer-tool voice-input-button" :class="{ recording: phase === 'recording' }" :disabled="phase === 'starting' || phase === 'transcribing'" :aria-pressed="phase === 'recording'" :aria-label="phase === 'recording' ? '结束录音并转写' : '语音输入'" :title="phase === 'recording' ? '点击结束录音（最长 2 分钟）' : '语音输入：录音将由当前服务商转写，可能产生费用'" @click="toggle"><Square v-if="phase === 'recording'" :size="17" /><LoaderCircle v-else-if="phase !== 'idle'" :size="19" class="spin-icon" /><Mic v-else :size="19" /></button>
    <span v-if="phase !== 'idle' || error" class="voice-input-status" :role="error ? 'alert' : 'status'">{{ error || (phase === 'recording' ? '正在录音 · 再次点击结束' : phase === 'transcribing' ? '正在转写…' : '正在准备麦克风…') }}</span>
  </span>
</template>
<style scoped>
.voice-input { position:relative; display:inline-flex; }
.voice-input-button { justify-content:center; width:36px; height:36px; border-radius:50%; }
.voice-input-button.recording { color:var(--theme-status-red); background:var(--theme-surface); }
.voice-input-status { position:absolute; bottom:calc(100% + 12px); right:0; width:max-content; max-width:min(280px, 65vw); padding:9px 12px; border:1px solid var(--theme-border); border-radius:10px; background:var(--theme-surface-floating); color:var(--theme-text); font-size:12px; z-index:80; }
</style>
