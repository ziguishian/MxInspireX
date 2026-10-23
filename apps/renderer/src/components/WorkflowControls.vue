<script setup lang="ts">
import { ref } from 'vue';
import { Play, Square, ChevronUp, ChevronDown } from 'lucide-vue-next';
const props=defineProps<{apiBaseUrl:string;projectId:string;running:boolean;progress:string}>();
const emit=defineEmits<{run:[count:number];stop:[]}>();
const count=ref(1), showSave=ref(false), name=ref(''), saving=ref(false), error=ref(''), notice=ref('');
function normalizeCount(){count.value=Math.min(20,Math.max(1,Math.floor(Number(count.value)||1)));}
defineExpose({openSave:()=>{showSave.value=true;error.value='';}});
async function save() {
  if(saving.value || !name.value.trim())return; saving.value=true; error.value='';
  try {const r=await fetch(`${props.apiBaseUrl}/api/workflows`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value.trim(),projectId:props.projectId})});const data=await r.json(); if(!r.ok)throw Error(data.detail||'保存失败');showSave.value=false;notice.value='已保存到工作流';}
  catch(e){error.value=(e as Error).message;}finally{saving.value=false;}
}
</script>
<template>
  <div class="workflow-controls" @pointerdown.stop>
    <label class="workflow-count">运行次数<div class="workflow-stepper"><input v-model="count" type="number" min="1" max="20" step="1" aria-label="运行次数" :disabled="running" @change="normalizeCount" /><div><button type="button" aria-label="增加运行次数" :disabled="running || count>=20" @click="normalizeCount();count=Math.min(20,Number(count)+1)"><ChevronUp :size="12" /></button><button type="button" aria-label="减少运行次数" :disabled="running || count<=1" @click="normalizeCount();count=Math.max(1,Number(count)-1)"><ChevronDown :size="12" /></button></div></div></label>
    <button v-if="running" type="button" aria-label="停止后续" title="当前步骤结束后停止" @click="emit('stop')"><Square :size="16" /></button><button v-else type="button" class="workflow-run" aria-label="运行工作流" title="运行整个工作流" @click="normalizeCount();emit('run',Number(count))"><Play :size="18" fill="currentColor" /></button>
    <small v-if="progress || notice" role="status">{{ progress || notice }}</small>
  </div>
  <Teleport to="body"><div v-if="showSave" class="workflow-save-overlay" @click.self="!saving && (showSave=false)"><form class="workflow-save-dialog" role="dialog" aria-modal="true" aria-labelledby="workflow-save-title" @submit.prevent="save" @keydown.esc="!saving && (showSave=false)"><h3 id="workflow-save-title">保存工作流</h3><label>名称<input v-model="name" required maxlength="80" autofocus :disabled="saving" /></label><p>保存节点、连线和素材，运行结果不写入模板。</p><p v-if="error" role="alert">{{ error }}</p><div><button type="button" :disabled="saving" @click="showSave=false">取消</button><button type="submit" :disabled="saving || !name.trim()">{{ saving?'保存中…':'保存' }}</button></div></form></div></Teleport>
</template>
<style scoped>
.workflow-count{display:flex;align-items:center;gap:8px}.workflow-stepper{display:flex;height:32px;border:1px solid var(--theme-border);border-radius:8px;overflow:hidden;background:var(--theme-input)}.workflow-stepper input{width:42px;padding:0 4px;text-align:center;appearance:textfield;border:0;background:transparent;color:inherit;font:inherit}.workflow-stepper input::-webkit-inner-spin-button{appearance:none}.workflow-stepper>div{display:flex;flex-direction:column;border-left:1px solid var(--theme-border)}.workflow-stepper button{display:grid;place-items:center;min-height:0;height:16px;width:22px;padding:0;border:0;border-radius:0}.workflow-controls .workflow-run{color:var(--theme-status-green);display:grid;place-items:center;width:34px;padding:0}
.workflow-controls{position:absolute;right:84px;top:18px;z-index:25;display:flex;align-items:center;gap:6px;padding:6px;background:var(--theme-surface-floating);border:1px solid var(--theme-border);border-radius:12px;color:var(--theme-text);font-size:12px;flex-wrap:wrap;max-width:calc(100% - 130px)}
button{border:1px solid var(--theme-border);background:var(--theme-surface);color:var(--theme-text);border-radius:8px;min-height:32px;padding:5px 9px;cursor:pointer}button:disabled{opacity:.5;cursor:default}.workflow-controls small{flex-basis:100%;max-width:350px;color:var(--theme-text-muted)}
.workflow-save-overlay{position:fixed;inset:0;z-index:700;display:grid;place-items:center;background:#0007}.workflow-save-dialog{width:min(400px,90vw);padding:24px;border-radius:20px;background:var(--theme-surface-floating);color:var(--theme-text)}.workflow-save-dialog label{display:grid;gap:8px}.workflow-save-dialog input{padding:10px;border:1px solid var(--theme-border);border-radius:8px;background:var(--theme-input);color:inherit}.workflow-save-dialog p{font-size:12px;color:var(--theme-text-muted)}.workflow-save-dialog>div{display:flex;justify-content:flex-end;gap:8px}
</style>
