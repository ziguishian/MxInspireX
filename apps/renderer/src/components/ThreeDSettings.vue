<script setup lang="ts">
import { ref } from 'vue';
const props = defineProps<{ apiBaseUrl:string; provider:string; endpoint:string; model:string }>();
const emit = defineEmits<{ saved:[config:{provider:string;endpoint:string;model:string}] }>();
const provider = ref(['meshy','tripo','rodin','hunyuan3d'].includes(props.provider) ? props.provider : 'meshy');
const endpoint = ref(props.endpoint);
const model = ref(props.model);
const secret = ref('');
const saving = ref(false);
const message = ref('');
async function save() {
  message.value = '';
  try {
    let url: URL;
    try { url = new URL(endpoint.value.trim()); }
    catch { throw new Error('请填写有效的 3D 服务地址。'); }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('请填写有效的服务地址，不包含凭据、查询参数或片段。');
    saving.value = true;
    if (secret.value.trim()) {
      const response = await fetch(`${props.apiBaseUrl}/api/providers/${provider.value}/credential`, {
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret:secret.value.trim()}),
      });
      if (!response.ok) throw new Error('凭据未保存，请检查本地服务后重试。');
      secret.value = '';
    }
    const config = {provider:provider.value,endpoint:endpoint.value.trim(),model:model.value.trim()};
    localStorage.setItem('aics.threeDProvider',config.provider);
    localStorage.setItem('aics.threeDEndpoint',config.endpoint);
    localStorage.setItem('aics.threeDModel',config.model);
    emit('saved',config);
    message.value = '3D 配置已保存；生成前会检查凭据。本次未调用模型。';
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败'; }
  finally { saving.value = false; }
}
</script>
<template>
  <details class="settings-pane" aria-label="独立 3D 服务">
    <summary>独立 3D 服务</summary>
    <div class="three-d-settings-body">
    <p>3D 模型需要单独的服务地址和 Key。EvoLink 文本、图片、视频与语音配置不受影响。</p>
    <label>3D 服务<select v-model="provider" :disabled="saving"><option value="meshy">Meshy</option><option value="tripo">Tripo</option><option value="rodin">Rodin</option><option value="hunyuan3d">Hunyuan3D</option></select></label>
    <label>3D 服务地址<input v-model="endpoint" :disabled="saving" placeholder="填写所选服务的生成接口地址" /></label>
    <label>3D 模型（可选）<input v-model="model" :disabled="saving" placeholder="留空使用服务默认模型" /></label>
    <label>3D API Key<input v-model="secret" :disabled="saving" type="password" autocomplete="new-password" placeholder="留空保留已保存的 Key" /></label>
    <small>Key 仅保存到本机安全存储。</small>
    <div class="three-d-settings-actions">
      <button type="button" class="ghost-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 3D 配置' }}</button>
    </div>
    <p v-if="message" role="status">{{ message }}</p>
    </div>
  </details>
</template>

<style scoped>
.three-d-settings-body {
  display: grid;
  gap: 18px;
  padding-top: 18px;
}
.three-d-settings-body > label {
  display: grid;
  gap: 9px;
  min-width: 0;
}
.three-d-settings-body > p {
  margin: 0;
}
.three-d-settings-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
