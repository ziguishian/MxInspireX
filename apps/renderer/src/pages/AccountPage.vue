<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';
import { Pencil, Check, Save, Folder, ArrowUpRight, X } from 'lucide-vue-next';
import { accountServices, projectLibraryServices } from '../features/pageServices';
import CountUp from '../components/motion/CountUp.vue';
import { creditSummary, creditUsageNote } from '../features/credits';
const { userNickname, userBio, userAvatarIndex, activeAvatarOption, userAvatarOptions, userProfileSaving, saveUserProfile, monthlyTokenTotal, weeklyTokenTotal, monthlyTokenHeatmap, weeklyTokenUsage, formatTokenUsage } = accountServices.use();
const { projects, selectProject } = projectLibraryServices.use();
type ProfileField = 'nickname' | 'bio' | 'avatar';
const editing = ref<ProfileField | null>(null);
const editor = ref<HTMLDialogElement>();
const textInput = ref<HTMLInputElement | HTMLTextAreaElement>();
const avatarEditButton = ref<HTMLButtonElement>();
const nicknameEditButton = ref<HTMLButtonElement>();
const bioEditButton = ref<HTMLButtonElement>();
const draftText = ref('');
const draftAvatar = ref(0);
const recentProjects = computed(() => [...projects.value].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 3));
const activeDays = computed(() => monthlyTokenHeatmap.value.filter(day => day.day && day.value > 0).length);
async function editProfile(field: ProfileField) {
  if (editing.value) return;
  editing.value = field;
  draftText.value = field === 'nickname' ? userNickname.value : userBio.value;
  draftAvatar.value = userAvatarIndex.value;
  await nextTick();
  if (field === 'avatar') editor.value?.showModal();
  else textInput.value?.focus();
}
async function cancelEdit(restoreFocus = true) {
  const field = editing.value;
  if (field === 'avatar') editor.value?.close();
  editing.value = null;
  if (!restoreFocus) return;
  await nextTick();
  if (field === 'nickname') nicknameEditButton.value?.focus();
  else if (field === 'bio') bioEditButton.value?.focus();
  else if (field === 'avatar') avatarEditButton.value?.focus();
}
function handleInlineKeydown(event: KeyboardEvent) {
  if (event.isComposing) return;
  if (event.key === 'Escape') { event.preventDefault(); void cancelEdit(); }
  else if (event.key === 'Enter' && (editing.value === 'nickname' || event.ctrlKey || event.metaKey)) { event.preventDefault(); saveProfile(); }
}
function saveProfile(restoreFocus = true) {
  const field = editing.value;
  if (!field) return;
  const text = draftText.value.trim();
  if (field === 'nickname' && !text) { void cancelEdit(restoreFocus); return; }
  const changed = field === 'nickname' ? text !== userNickname.value
    : field === 'bio' ? text !== userBio.value : draftAvatar.value !== userAvatarIndex.value;
  if (changed) {
    if (field === 'nickname') userNickname.value = text;
    else if (field === 'bio') userBio.value = text;
    else userAvatarIndex.value = draftAvatar.value;
    saveUserProfile();
  }
  void cancelEdit(restoreFocus);
}
function dismissOutside(event: MouseEvent) {
  const rect = editor.value?.getBoundingClientRect();
  if (rect && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) cancelEdit();
}
</script>

<template>
  <div class="account-overview">
    <header class="account-identity">
      <div class="account-editable account-editable-avatar">
        <span class="user-avatar user-avatar-sprite account-portrait" :style="{ backgroundPosition: activeAvatarOption.position }" role="img" :aria-label="`${userNickname}的头像`" />
        <button ref="avatarEditButton" type="button" class="account-field-edit" aria-label="更换头像" title="更换头像" aria-haspopup="dialog" @click="editProfile('avatar')"><Pencil :size="15" /></button>
      </div>
      <h2 class="account-inline-text account-inline-name">
        <template v-if="editing === 'nickname'">
          <span class="account-text-measure" aria-hidden="true">{{ draftText || userNickname }}</span>
          <input ref="textInput" v-model="draftText" aria-label="昵称" title="点击空白处保存，Esc 取消" maxlength="32" @blur="saveProfile(false)" @keydown.stop="handleInlineKeydown" />
        </template>
        <button v-else ref="nicknameEditButton" type="button" aria-label="编辑昵称" title="点击修改昵称" @click="editProfile('nickname')">{{ userNickname }}</button>
      </h2>
      <p class="account-inline-text account-inline-bio">
        <template v-if="editing === 'bio'">
          <span class="account-text-measure" aria-hidden="true">{{ (draftText || '介绍一下你的创作方向') + '\u200b' }}</span>
          <textarea ref="textInput" v-model="draftText" aria-label="个人简介" title="点击空白处保存，Esc 取消" maxlength="120" rows="1" placeholder="介绍一下你的创作方向" @blur="saveProfile(false)" @keydown.stop="handleInlineKeydown" />
        </template>
        <button v-else ref="bioEditButton" type="button" aria-label="编辑个人简介" title="点击修改简介" @click="editProfile('bio')">{{ userBio }}</button>
      </p>
      <span class="account-local-label">MxinspireX · 本地工作区</span>
    </header>
    <Teleport to="body">
      <dialog ref="editor" class="modal account-profile-dialog" aria-labelledby="account-editor-title" @cancel.prevent="cancelEdit()" @click.self="dismissOutside" @keydown.stop>
        <form v-if="editing === 'avatar'" class="account-editor" @submit.prevent="saveProfile()">
          <header class="account-editor-heading"><h2 id="account-editor-title">更换头像</h2><button type="button" class="account-editor-close" aria-label="关闭编辑" @click="cancelEdit()"><X :size="18" /></button></header>
          <p class="account-editor-hint">选择一个简笔画头像，保存后在整个工作区同步。</p>
          <div class="avatar-picker-grid" role="group" aria-label="选择预设头像">
            <button v-for="avatar in userAvatarOptions" :key="avatar.index" type="button" class="avatar-option" :class="{ selected: draftAvatar === avatar.index }" :aria-pressed="draftAvatar === avatar.index" :aria-label="`${avatar.label}头像`" @click="draftAvatar = avatar.index"><span class="user-avatar user-avatar-sprite" :style="{ backgroundPosition: avatar.position }" /><small>{{ avatar.label }}</small><Check v-if="draftAvatar === avatar.index" :size="12" /></button>
          </div>
          <div class="account-editor-actions"><span>仅保存在本机</span><button type="button" class="ghost-button" @click="cancelEdit()">取消</button><button type="submit" class="primary-button" :disabled="userProfileSaving"><Save :size="14" />{{ userProfileSaving ? '保存中…' : '保存' }}</button></div>
        </form>
      </dialog>
    </Teleport>
    <dl class="account-stats" aria-label="工作区概览">
      <div><dt>本月 Token </dt><dd>{{ creditSummary ? formatTokenUsage(monthlyTokenTotal) : '—' }}</dd></div>
      <div><dt>本周 Token </dt><dd>{{ creditSummary ? formatTokenUsage(weeklyTokenTotal) : '—' }}</dd></div>
      <div><dt>项目数量</dt><dd><CountUp :to="projects.length" /></dd></div>
      <div><dt>本月 Token 消耗天数</dt><dd><CountUp :to="activeDays" /><small> 天</small></dd></div>
    </dl>
    <section class="account-section">
      <div class="account-section-heading"><h3>最近项目</h3><span>{{ projects.length }} 个项目</span></div>
      <div v-if="recentProjects.length" class="account-projects">
        <button v-for="project in recentProjects" :key="project.id" type="button" class="account-project" @click="selectProject(project.id)"><span class="account-project-icon"><Folder :size="24" :stroke-width="1.4" /></span><strong>{{ project.name }}</strong><small>{{ project.brief || '从一个想法开始，继续完善你的设计。' }}</small><span class="account-project-date">{{ new Date(project.updatedAt).toLocaleDateString('zh-CN') }}<ArrowUpRight :size="14" /></span></button>
      </div>
      <div v-else class="account-project-empty"><Folder :size="34" :stroke-width="1.2" /><p>你的设计项目会展示在这里</p><small>从首页输入需求，开始第一份设计。</small></div>
    </section>
    <section class="account-section">
      <div class="account-section-heading"><h3>使用活动</h3><span>{{ new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' }) }}</span></div>
      <div v-if="creditSummary" class="account-activity">
        <div class="account-month"><p>本月每日 Token </p><div class="account-weekdays"><span v-for="day in ['日', '一', '二', '三', '四', '五', '六']" :key="day">{{ day }}</span></div><div class="account-calendar" aria-label="本月 Token 使用热力图"><i v-for="day in monthlyTokenHeatmap" :key="day.key" :class="[`level-${day.level}`, { empty: !day.day }]" :title="day.day ? `${day.label} · ${day.value.toLocaleString()}  Token ` : ''"><span>{{ day.day || '' }}</span></i></div><div class="account-heatmap-legend" aria-label=" Token 消耗从零到多的颜色刻度"><span>0</span><i class="level-0" /><i class="level-1" /><i class="level-2" /><i class="level-3" /><i class="level-4" /><span>多</span></div></div>
        <div class="account-week"><p>近 7 天 Token </p><div class="account-week-bars" aria-label="本周每日 Token 使用对比"><div v-for="day in weeklyTokenUsage" :key="day.key"><span>{{ formatTokenUsage(day.value) }}</span><div class="account-bar-track"><i :style="{ height: `${day.height}%` }" /></div><small>{{ day.weekday }}</small></div></div><p class="account-week-total">本周合计 <strong>{{ creditSummary ? formatTokenUsage(weeklyTokenTotal) : '—' }}</strong>  Token </p></div>
      </div>
      <p class="account-usage-note">图表仅包含已返回的 Token，不受价格是否可用影响。{{ creditUsageNote }}</p>
    </section>
  </div>
</template>
