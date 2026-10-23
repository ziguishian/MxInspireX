<script setup lang="ts">
import { ref } from 'vue';
import { FolderOpen, Upload } from 'lucide-vue-next';
defineProps<{ entries: Array<{title:string}>; busy?:boolean }>();
const emit=defineEmits<{upload:[files:File[]]}>();
const input=ref<HTMLInputElement|null>(null);
function select(event:Event){const element=event.target as HTMLInputElement;const files=Array.from(element.files||[]).sort((a,b)=>a.webkitRelativePath.localeCompare(b.webkitRelativePath));element.value='';if(files.length)emit('upload',files);}
</script>
<template><div class="folder-input nodrag nowheel nopan" @click.stop @pointerdown.stop>
  <FolderOpen :size="32" /><strong>文件夹 · 批量输入</strong><span>{{ entries.length ? `${entries.length} 个文件，逐项运行下游工作流` : '上传文件夹后，连接到需要处理的节点' }}</span>
  <button type="button" :disabled="busy" @click="input?.click()"><Upload :size="15" />{{ entries.length?'更换文件夹':'上传文件夹' }}</button>
  <input ref="input" type="file" webkitdirectory multiple hidden @change="select" />
  <ul v-if="entries.length"><li v-for="(entry,index) in entries" :key="index" :title="entry.title">{{ entry.title }}</li></ul>
</div></template>
<style scoped>.folder-input{width:100%;height:100%;box-sizing:border-box;padding:24px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--theme-text)}.folder-input span{font-size:12px;color:var(--theme-text-muted)}button{display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid var(--theme-border);border-radius:10px;background:var(--theme-input);color:inherit;cursor:pointer}ul{width:100%;max-height:180px;overflow:auto;padding:0;list-style:none;font-size:13px}li{padding:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}</style>
