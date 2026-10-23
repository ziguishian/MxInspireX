<script setup lang="ts">
import { ref } from 'vue';
import { canvasBackground, saveCanvasBackground, type CanvasBackground } from '../features/canvasBackground';
const error = ref('');
function save(patch: Partial<CanvasBackground>) { try { saveCanvasBackground({...canvasBackground,...patch});error.value=''; } catch {error.value='保存失败，本地存储空间不足，请换用较小的图片。';} }
async function upload(event: Event) {
  const input=event.target as HTMLInputElement, file=input.files?.[0]; input.value=''; if(!file)return;
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024){error.value='请选择 2 MB 以内的 PNG、JPEG 或 WebP 图片。';return;}
  try { const image=await createImageBitmap(file);image.close();const reader=new FileReader();reader.onerror=()=>{error.value='图片读取失败';};reader.onload=()=>save({image:String(reader.result)});reader.readAsDataURL(file); }
  catch {error.value='图片无法解码，请更换文件。';}
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
        <label class="background-upload">{{ canvasBackground.image ? '更换背景图片' : '上传背景图片' }}<input type="file" accept="image/png,image/jpeg,image/webp" @change="upload" /></label>
        <button v-if="canvasBackground.image" type="button" class="background-remove" @click="save({image:''})">移除图片</button>
      </div>
      <div class="background-image-thumbnail">
        <span class="appearance-mini background-preview">
          <img v-if="canvasBackground.image" :src="canvasBackground.image" alt="当前画布背景图片预览" />
          <span v-else class="background-image-empty">未设置</span>
        </span>
        <small>图片预览</small>
      </div>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <small>自动保存 · 仅用于画布背景，不作为生成参考。</small>
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
.background-upload,.background-remove { padding:8px 14px; border:1px solid var(--theme-border); border-radius:10px; background:var(--theme-bg); color:var(--theme-text); cursor:pointer; font-size:var(--ui-font-control); }
.background-upload:focus-within { outline:2px solid var(--theme-accent); outline-offset:2px; }
.background-upload { position:relative; }
.background-upload input { position:absolute; width:1px; height:1px; opacity:0; }
.background-image-thumbnail { box-sizing:border-box; flex:0 0 96px; width:96px; padding:7px; text-align:center; }
.background-image-thumbnail img { width:100%; height:100%; object-fit:cover; }
.background-image-thumbnail small { display:block; margin-top:6px; font-size:var(--ui-font-caption); }
.background-image-empty { display:grid; height:100%; place-items:center; font-size:var(--ui-font-caption); color:var(--theme-text-muted); }
small { color:var(--theme-text-muted); }
</style>
