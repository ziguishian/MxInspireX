<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Download, X } from 'lucide-vue-next';
import type { UpdateState } from '../../../desktop/src/appUpdates';
const api = window.studio?.updates;
const state = ref<UpdateState>();
const dialog = ref<HTMLDialogElement>();
const bridgeError = ref('');
const notified = new Set<string>();
let unsubscribe: (() => void) | undefined;
const highlighted = computed(() => !!state.value?.latestVersion);
const title = computed(() => state.value?.status === 'installing' ? '正在安装更新' : state.value?.status === 'downloading' ? '正在下载更新' : state.value?.status === 'downloaded' ? '更新已下载' : highlighted.value ? '发现新版本' : '软件更新');
const notes = computed(() => {
  const raw = state.value?.notes || '此版本未提供更新说明。';
  return /<\/?[a-z][^>]*>/i.test(raw) ? new DOMParser().parseFromString(raw, 'text/html').body.textContent || raw : raw;
});
function receive(next: UpdateState) {
  if (state.value && next.revision < state.value.revision) return;
  state.value = next;
  if (['available', 'downloaded'].includes(next.status)) {
    const key = `${next.latestVersion}:${next.status}`;
    if (!notified.has(key)) { notified.add(key); dialog.value?.showModal(); }
  }
}
async function act(action: 'state' | 'check' | 'download' | 'install') {
  bridgeError.value = '';
  try { if (api) receive(await api[action]()); }
  catch { bridgeError.value = '无法连接更新服务，请重启软件后重试。'; }
}
onMounted(() => { if (api) { unsubscribe = api.subscribe(receive); void act('state'); } });
onUnmounted(() => unsubscribe?.());
</script>

<template>
  <template v-if="api">
    <button class="app-update-entry" :class="{ 'has-update': highlighted }" :title="title" :aria-label="title" @click="dialog?.showModal()"><Download :size="19" /></button>
    <Teleport to="body">
      <dialog ref="dialog" class="app-update-dialog" aria-labelledby="app-update-title">
        <header><h2 id="app-update-title">{{ title }}</h2><button aria-label="关闭" @click="dialog?.close()"><X :size="18" /></button></header>
        <p>当前版本 {{ state?.currentVersion || '—' }}<template v-if="state?.latestVersion"> → {{ state.latestVersion }}</template></p>
        <pre v-if="state?.latestVersion" class="app-update-notes">{{ notes }}</pre>
        <p v-if="state?.status === 'disabled'">{{ state.reason }}</p>
        <p v-else-if="state?.status === 'checking'" role="status">正在检查新版本…</p>
        <p v-else-if="state?.status === 'idle'" role="status">暂无可用更新，可手动检查。</p>
        <div v-if="state?.status === 'downloading'" role="status"><progress :value="state.percent" max="100" /><p>正在下载 {{ state.percent.toFixed(1) }}%</p></div>
        <p v-if="state?.status === 'downloaded'">安装将关闭软件，请先保存正在编辑的内容。稍后重启会保留本次下载，正常退出不会自动安装。</p>
        <p v-if="state?.status === 'installing'" role="status">正在启动安装程序…</p>
        <p v-if="state?.error || bridgeError" role="alert">{{ bridgeError || state?.error }}</p>
        <footer>
          <button @click="dialog?.close()">{{ state?.status === 'downloaded' ? '稍后重启' : state?.status === 'installing' ? '关闭' : '稍后更新' }}</button>
          <button v-if="state?.status === 'available' || state?.status === 'error' && state.retry === 'download'" class="update-primary" @click="act('download')">{{ state.status === 'error' ? '重新下载' : '立即下载' }}</button>
          <button v-if="state?.status === 'downloaded'" class="update-primary" @click="act('install')">立即重启更新</button>
          <button v-if="state?.status === 'idle' || state?.status === 'error' && state.retry === 'check'" @click="act('check')">{{ state.status === 'error' ? '重试检查' : '检查更新' }}</button>
        </footer>
      </dialog>
    </Teleport>
  </template>
</template>

<style scoped>
.app-update-entry { position: fixed; left: calc((var(--mx-rail, 72px) - 40px) / 2); bottom: 76px; width: 40px; height: 40px; display: grid; place-items: center; padding: 0; border: 1px solid var(--theme-border); border-radius: 10px; background: var(--theme-surface); color: var(--theme-text); }
.app-update-entry.has-update, .update-primary { background: #3478db; color: #fff; border-color: #3478db; }
.app-update-dialog { width: min(480px, calc(100vw - 40px)); box-sizing: border-box; padding: 24px; border: 1px solid var(--theme-border); border-radius: 20px; background: var(--theme-surface-floating); color: var(--theme-text); }
.app-update-dialog::backdrop { background: #0008; }
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
h2 { margin: 0; font-size: var(--ui-font-section, 18px); }
header button { display: grid; place-items: center; padding: 6px; }
p, pre { font-size: 13px; line-height: 1.6; }
.app-update-notes { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; font-family: inherit; }
progress { width: 100%; accent-color: #3478db; }
footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
footer button { min-height: 40px; border-radius: 10px; padding: 0 14px; }
</style>
