<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import ModelViewer from './ModelViewer.vue';
import { saveBlob } from '../nodeExport';
const props = defineProps<{ apiBaseUrl: string; projectId: string; assetId: string; nodeId?: string; busy?: boolean }>();
const emit = defineEmits<{ close: []; updated: [] }>();
const dialog = ref<HTMLDialogElement | null>(null), cad = ref<any>(null), values = ref<Record<string, any>>({});
const error = ref(''), state = ref(''), building = ref(false), buildId = ref(''), versions = ref<any[]>([]), versionId = ref('');
const controller = new AbortController();
const base = `${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}`;
const assetUrl = (id: string) => `${base}/assets/${encodeURIComponent(id)}/content`;
const preview = computed(() => cad.value?.files?.glb ? assetUrl(cad.value.files.glb) : '');
async function request(path: string, body?: unknown) {
  const response = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal });
  const result = await response.json(); if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'CAD 请求失败'); return result;
}
function setModel(model: any) { cad.value = model; values.value = { ...model.parameters }; }
onMounted(async () => {
  dialog.value?.showModal();
  try { setModel(await request(`/cad/models/${encodeURIComponent(props.assetId)}`)); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '模型读取失败'; }
});
onBeforeUnmount(() => { controller.abort(); dialog.value?.close(); });
async function rebuild() {
  error.value = ''; building.value = true; state.value = '正在提交本地重建…';
  try {
    const parameters = Object.fromEntries((cad.value.parameter_definitions || []).filter((d: any) => !d.expression).map((d: any) => [d.name, values.value[d.name]]));
    let build = await request('/cad/builds', { canvas_node_id: props.nodeId, base_revision: cad.value.revision, parameters, title: cad.value.title, request_id: crypto.randomUUID() });
    buildId.value = build.id;
    while (!['succeeded', 'failed', 'cancelled'].includes(build.status)) {
      state.value = '正在本地重建模型…';
      await new Promise(resolve => setTimeout(resolve, 600));
      if (controller.signal.aborted) return;
      build = await request(`/cad/builds/${build.id}`);
    }
    if (build.status !== 'succeeded') throw new Error(build.error || '重建未完成');
    setModel(build.result.node.data.cad); state.value = '已保存新版本'; versions.value = []; emit('updated');
  } catch (reason) { if (!controller.signal.aborted) error.value = reason instanceof Error ? reason.message : '重建失败'; }
  finally { building.value = false; buildId.value = ''; }
}
async function cancel() { try { if (buildId.value) await request(`/cad/builds/${buildId.value}/cancel`, {}); } catch (reason) { error.value = String(reason); } }
async function history() {
  try { const result = await request('/agent-tools/canvas_versions', { node_id: props.nodeId }); versions.value = result.versions || []; }
  catch (reason) { error.value = String(reason); }
}
async function restore() {
  try {
    const result = await request('/agent-tools/canvas_restore_node', { node_id: props.nodeId, version_id: versionId.value });
    if (result.node?.data?.cad) setModel(result.node.data.cad);
    else throw new Error('这个版本没有完整 CAD 模型，请选择其他版本');
    emit('updated'); state.value = '已恢复历史版本';
  } catch (reason) { error.value = String(reason); }
}
async function download(role: string, extension: string) {
  try {
    const response = await fetch(assetUrl(cad.value.files[role]), { signal: controller.signal });
    if (!response.ok) throw new Error('导出文件读取失败');
    saveBlob(await response.blob(), `${String(cad.value.title || '模型').replace(/[\\/:*?"<>|]/g, '_')}.${extension}`);
  } catch (reason) { error.value = String(reason); }
}
</script>
<template>
  <Teleport to="body">
    <dialog ref="dialog" class="cad-detail" aria-labelledby="cad-title" :aria-busy="building" @cancel.prevent="!building && emit('close')" @click.stop @pointerdown.stop @keydown.stop>
      <header><div><small>参数化 CAD · mm</small><h2 id="cad-title">{{ cad?.title || 'CAD 模型' }}</h2></div><button type="button" aria-label="关闭 CAD 详情" :disabled="building" @click="emit('close')">关闭</button></header>
      <div v-if="cad" class="cad-detail-body">
        <div class="cad-detail-preview"><ModelViewer :asset-url="preview" asset-format="glb" :label="cad.title" /></div>
        <section class="cad-parameters">
          <p v-if="cad.checks?.dimensionsMm">外形 {{ Object.values(cad.checks.dimensionsMm).map((v: any) => Number(v).toFixed(2)).join(' × ') }} mm</p>
          <p>{{ cad.checks?.solidCount }} 个实体 · {{ cad.checks?.stepRoundTrip ? '实体与 STEP 回读检查通过' : '等待检查' }}</p>
          <form @submit.prevent="rebuild">
            <label v-for="definition in cad.parameter_definitions" :key="definition.name" class="cad-parameter">
              <span>{{ definition.label }} <small>{{ definition.unit }}</small></span>
              <input v-if="definition.type === 'boolean'" v-model="values[definition.name]" type="checkbox" :disabled="!!definition.expression || building || busy || !nodeId" />
              <select v-else-if="definition.type === 'enum'" v-model="values[definition.name]" :disabled="!!definition.expression || building || busy || !nodeId"><option v-for="value in definition.options" :key="value">{{ value }}</option></select>
              <input v-else v-model.number="values[definition.name]" type="number" :step="definition.type === 'integer' ? 1 : 'any'" :min="definition.minimum" :max="definition.maximum" :readonly="!!definition.expression" :disabled="building || busy || !nodeId" required />
            </label>
            <button v-if="nodeId" type="submit" :disabled="building || busy">{{ building ? '正在重建…' : '应用参数' }}</button>
            <button v-if="building" type="button" @click="cancel">取消构建</button>
          </form>
          <ul v-if="cad.assumptions?.length"><li v-for="assumption in cad.assumptions" :key="assumption">{{ assumption }}</li></ul>
          <div v-if="nodeId" class="cad-history"><button type="button" :disabled="building || busy" @click="history">历史版本</button><template v-if="versions.length"><select v-model="versionId" aria-label="选择 CAD 历史版本"><option value="">选择版本</option><option v-for="version in versions" :key="version.id" :value="version.id">{{ new Date(version.createdAt).toLocaleString() }} · {{ version.title }}</option></select><button type="button" :disabled="!versionId || building || busy" @click="restore">恢复</button></template></div>
        </section>
      </div>
      <p v-else-if="!error" role="status">正在读取模型…</p>
      <p v-if="error" role="alert" class="cad-error">{{ error }}</p><p v-else-if="state" role="status">{{ state }}</p>
      <footer v-if="cad"><button v-for="(extension, role) in { step: 'step', stl: 'stl', glb: 'glb', source: 'py', parameters: 'json' }" :key="role" type="button" @click="download(role, extension)">导出 {{ extension.toUpperCase() }}</button></footer>
    </dialog>
  </Teleport>
</template>
<style scoped>
.cad-detail{width:min(1050px,94vw);max-height:92vh;padding:22px;border:1px solid var(--theme-border,#ddd);border-radius:16px;background:var(--theme-surface,#fff);color:var(--theme-text,#222);overflow:auto}.cad-detail::backdrop{background:#0008}.cad-detail header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.cad-detail h2{margin:4px 0;font-size:20px}.cad-detail button,.cad-detail input,.cad-detail select{font:inherit;border:1px solid var(--theme-border,#ccc);border-radius:6px;padding:7px;background:var(--theme-bg,#fafafa);color:inherit}.cad-detail button{cursor:pointer}.cad-detail button:disabled{opacity:.5;cursor:default}.cad-detail-body{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:20px}.cad-detail-preview{height:460px}.cad-parameters{max-height:460px;overflow:auto;font-size:13px}.cad-parameter{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:12px 0}.cad-parameter input:not([type=checkbox]),.cad-parameter select{width:125px}.cad-parameter small{opacity:.6}.cad-detail footer,.cad-history{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.cad-error{color:#5a5a5a}@media(max-width:760px){.cad-detail-body{grid-template-columns:1fr}.cad-detail-preview{height:300px}.cad-parameters{max-height:none}}
</style>
