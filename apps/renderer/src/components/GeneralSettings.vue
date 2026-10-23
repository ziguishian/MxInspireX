<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { generalSettings as settings } from '../features/generalSettings';
const props = defineProps<{ queue: boolean; apiBaseUrl: string }>();
const emit = defineEmits<{ 'update:queue': [value: boolean] }>();
const storage = ref<{ path: string; bytes: number; partial: boolean }>();
const busy = ref(false), error = ref(''), notice = ref('');
const desktop = Boolean(window.studio?.openWorkspaceFolder);
const canChangeLocation = Boolean(window.studio?.changeWorkspaceLocation);
const changingLocation = ref(false);
const permission = ref(typeof Notification === 'undefined' ? 'unsupported' : Notification.permission);
const groups = [
  { title: '输入与任务', items: [{ key: 'notifications', label: '任务完成通知', detail: '仅在后台或其他项目中提醒完成、失败和需要补充信息的任务。' }] },
  { title: '启动与画布', items: [{ key: 'restoreProject', label: '启动时恢复上次项目', detail: '从首页启动时回到上次项目；直接访问其他页面不受影响。' }, { key: 'focusNewOutputs', label: '自动定位新产物', detail: '新作品出现时调整视野；手动浏览画布期间不抢视野。' }] },
  { title: '删除确认', items: [{ key: 'confirmProjectDelete', label: '删除项目前确认', detail: '项目及其历史记录删除后无法恢复。' }, { key: 'confirmAssetDelete', label: '删除资产和资料前确认', detail: '包含资产库和知识资料中的文件。' }, { key: 'confirmNodeDelete', label: '删除画布节点前确认', detail: '关闭后直接删除，仍可使用画布撤销。' }] },
] as const;
async function storageAction(clear = false) {
  busy.value = true; error.value = ''; notice.value = '';
  try {
    if (clear) {
      const response = await fetch(`${props.apiBaseUrl}/api/storage/cache`, { method: 'DELETE' });
      if (!response.ok) throw new Error('清理缓存失败');
      await window.studio?.clearAppCache?.();
      notice.value = '已清理预览缓存；项目、原图、草稿和运行记录均保留。';
    }
    const response = await fetch(`${props.apiBaseUrl}/api/storage`);
    if (!response.ok) throw new Error('无法读取工作区占用，请检查本地服务');
    storage.value = await response.json();
  } catch (e) { error.value = e instanceof Error ? e.message : '操作失败'; }
  finally { busy.value = false; }
}
async function requestPermission() {
  try { permission.value = await Notification.requestPermission(); }
  catch { permission.value = 'denied'; }
}
async function openFolder() {
  try { await window.studio?.openWorkspaceFolder?.(); }
  catch { error.value = '打开目录失败，请使用下方路径手动打开。'; }
}
async function changeLocation(mode: 'migrate' | 'existing') {
  if (changingLocation.value || busy.value) return;
  changingLocation.value = true; error.value = ''; notice.value = '';
  try {
    const selected = await window.studio?.changeWorkspaceLocation?.(mode);
    if (selected) notice.value = '存储位置已更新，正在重启应用…';
  } catch (e) { error.value = e instanceof Error ? e.message : '无法更改存储位置，原数据仍然保留。'; }
  finally { changingLocation.value = false; }
}
onMounted(() => { void storageAction(); });
</script>

<template>
  <section class="settings-pane general-settings">
    <small>更改后自动保存，立即生效。</small>
    <section v-for="group in groups" :key="group.title" class="general-settings-group">
      <h3>{{ group.title }}</h3>
      <template v-if="group.title === '输入与任务'">
        <label class="settings-switch toggle-control"><input :checked="queue" type="checkbox" role="switch" @change="emit('update:queue', ($event.target as HTMLInputElement).checked)" /><span class="toggle-track" /><span>发送时默认加入队列<small>任务运行时开启则加入下一项，关闭则文字补充当前任务；附件、引用和技能仍加入队列。</small></span></label>
        <label class="general-settings-select"><span>发送快捷键</span><select v-model="settings.sendWithEnter" aria-label="发送快捷键"><option :value="false">Ctrl / ⌘ + Enter 发送，Enter 换行</option><option :value="true">Enter 发送，Shift + Enter 换行</option></select></label>
      </template>
      <label v-for="item in group.items" :key="item.key" class="settings-switch toggle-control"><input v-model="settings[item.key]" type="checkbox" role="switch" /><span class="toggle-track" /><span>{{ item.label }}<small>{{ item.detail }}</small></span></label>
      <div v-if="group.title === '输入与任务' && settings.notifications">
        <button type="button" v-if="permission === 'default'" class="ghost-button" @click="requestPermission">允许系统通知</button>
        <small v-else-if="permission === 'denied'">系统通知已被阻止，可在浏览器权限中开启；应用内仍会提醒。</small>
        <small v-else-if="permission === 'unsupported'">当前环境不支持系统通知，使用应用内提醒。</small>
      </div>
    </section>
    <section class="general-settings-group">
      <h3>存储管理</h3>
      <strong>数据存储位置</strong>
      <p v-if="storage">工作区占用：{{ (storage.bytes / 1024 / 1024).toFixed(1) }} MB{{ storage.partial ? '（部分文件无法读取）' : '' }}</p>
      <p v-if="storage" class="general-storage-path">{{ storage.path }}</p>
      <template v-if="canChangeLocation">
        <small>项目、上传资料、生成产物与运行记录保存在此工作区。迁移将复制数据到空目录并保留原目录；打开已有工作区不会合并数据。完成后自动重启。</small>
        <div class="general-settings-actions"><button type="button" class="ghost-button" :disabled="busy || changingLocation" @click="changeLocation('migrate')">{{ changingLocation ? '正在处理，请稍候…' : '更改存储位置（迁移数据）' }}</button><button type="button" class="ghost-button" :disabled="busy || changingLocation" @click="changeLocation('existing')">打开已有工作区</button></div>
      </template>
      <small v-else>更改数据存储位置请使用桌面端。</small>
      <small>清理可重建的预览缓存；桌面端同时清理浏览器资源缓存。不删除项目、原图、草稿和运行记录。</small>
      <div class="general-settings-actions"><button type="button" class="ghost-button" :disabled="busy" @click="storageAction()">{{ busy ? '处理中…' : '刷新占用' }}</button><button type="button" class="ghost-button" :disabled="busy" @click="storageAction(true)">清理缓存</button><button type="button" v-if="desktop" class="ghost-button" @click="openFolder">打开工作区目录</button></div>
      <p v-if="notice" role="status">{{ notice }}</p><p v-if="error" role="alert">{{ error }}</p>
    </section>
  </section>
</template>
