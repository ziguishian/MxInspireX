<script setup lang="ts">
import { ref } from 'vue';
import { canvasBackground, saveCanvasBackground, type CanvasBackground } from '../features/canvasBackground';
import { prepareCanvasBackgroundImage } from '../features/canvasBackgroundImage';
const error = ref('');
const processing = ref(false);
const saved = ref(false);
const fileInput = ref<HTMLInputElement>();
function chooseImage() {
  error.value = '';
  const input = fileInput.value;
  if (!input) return;
  // Open synchronously from the button gesture; do not rely on label activation
  // of a one-pixel transparent control inside the desktop window.
  try {
    if (typeof input.showPicker === 'function') input.showPicker();
    else input.click();
  } catch {
    error.value = '无法打开文件选择窗口，请再次点击上传。';
  }
}
function save(patch: Partial<CanvasBackground>) { try { saveCanvasBackground({...canvasBackground,...patch});error.value='';saved.value=true; } catch {saved.value=false;error.value='保存失败，本地存储空间不足。原背景已保留，请清理应用存储空间后重试。';} }
async function upload(event: Event) {
  const input=event.target as HTMLInputElement, file=input.files?.[0]; input.value=''; if(!file)return;
  if (processing.value) return;
  processing.value=true;error.value='';saved.value=false;
  try { save({image:await prepareCanvasBackgroundImage(file)}); }
  catch (cause) { error.value=cause instanceof Error ? cause.message : '图片读取失败，请重试。'; }
  finally { processing.value=false; }
}
</script>
<template>
  <section class="canvas-background-settings appearance-palette-card">
    <div class="appearance-mode-card background-pattern-row">
      <strong>画布背景</strong>
      <div class="appearance-mode-options" role="group" aria-label="画布背景样式">
        <button v-for="item in [['grid','方格'],['dots','点状'],['none','空白']]" :key="item[0]" type="button" :aria-pressed="canvasBackground.pattern===item[0]" @click="save({pattern:item[0] as CanvasBackground['pattern']})">
          <span class="appearance-mini background-preview" :style="{ backgroundImage: canvasBackground.image ? `url(${canvasBackground.image})` : undefined }" aria-hidden="true"><span class="background-pattern" :class="item[0]" /></span>
          <span>{{ item[1] }}</span>
        </button>
      </div>
    </div>
    <div class="background-image-row">
      <div class="background-image-actions">
        <strong>背景图片</strong>
        <button type="button" class="background-upload" :disabled="processing" @click="chooseImage" @keydown.enter.prevent="chooseImage" @keydown.space.prevent="chooseImage">{{ processing ? '正在处理图片…' : canvasBackground.image ? '更换背景图片' : '上传背景图片' }}</button>
        <input ref="fileInput" class="background-file-input" type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择画布背景图片" tabindex="-1" @change="upload" />
        <button v-if="canvasBackground.image" type="button" class="background-remove" :disabled="processing" @click="save({image:''})">移除图片</button>
        <p v-if="error" class="background-feedback" role="alert">{{ error }}</p>
        <p v-else-if="processing || saved" class="background-feedback" role="status">{{ processing ? '正在处理并保存背景图片…' : '已保存，进入项目画布即可查看。' }}</p>
      </div>
      <div class="background-image-thumbnail">
        <span class="appearance-mini background-preview">
          <img v-if="canvasBackground.image" :src="canvasBackground.image" alt="当前画布背景图片预览" />
          <span v-else class="background-image-empty">未设置</span>
        </span>
        <small>图片预览</small>
      </div>
    </div>
    <small>支持 20 MB 以内的 PNG、JPEG、WebP，会自动缩放压缩并在本机保存。仅用于画布背景，不作为生成参考。</small>
  </section>
</template>
<style scoped>
.canvas-background-settings { display:grid; gap:16px; margin-top:28px; }
.background-pattern-row { padding:0; border:0; border-radius:0; background:transparent; }
.background-preview { background-color:var(--theme-bg); background-size:cover; background-position:center; }
.background-pattern { position:absolute; inset:0; }
.background-pattern.grid { background-image:linear-gradient(var(--workspace-grid-color) 1px,transparent 1px),linear-gradient(90deg,var(--workspace-grid-color) 1px,transparent 1px); background-size:14px 14px; }
.background-pattern.dots { background-image:radial-gradient(circle,var(--workspace-grid-color) 1px,transparent 1px); background-size:10px 10px; }
.background-image-row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding-top:16px; border-top:1px solid var(--theme-border); }
.background-image-actions { display:flex; align-items:center; flex-wrap:wrap; gap:12px; }
.background-feedback { flex-basis:100%; margin:0; font-size:var(--ui-font-caption); }
.background-feedback[role="alert"] { color:var(--theme-status-red); }
.background-upload,.background-remove { padding:8px 14px; border:1px solid var(--theme-border); border-radius:10px; background:var(--theme-bg); color:var(--theme-text); cursor:pointer; font-size:var(--ui-font-control); }
.background-upload:focus-visible { outline:2px solid var(--theme-accent); outline-offset:2px; }
.background-upload,.background-remove { -webkit-app-region:no-drag; }
.background-file-input { display:none; }
.background-image-thumbnail { box-sizing:border-box; flex:0 0 96px; width:96px; padding:7px; text-align:center; }
.background-image-thumbnail img { width:100%; height:100%; object-fit:cover; }
.background-image-thumbnail small { display:block; margin-top:6px; font-size:var(--ui-font-caption); }
.background-image-empty { display:grid; height:100%; place-items:center; font-size:var(--ui-font-caption); color:var(--theme-text-muted); }
small { color:var(--theme-text-muted); }
</style>
