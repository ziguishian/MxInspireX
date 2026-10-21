<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { Wrench, Plus, X, Github, Download, ArrowLeft, ArrowUpRight, ChevronDown, ChevronRight, FileText, Folder } from 'lucide-vue-next';
import LibraryPageLayout from '../components/shared/LibraryPageLayout.vue';
import EmptyState from '../components/shared/EmptyState.vue';
import { skillLibraryServices } from '../features/pageServices';
import { createSkillsApi } from '../features/skills';
import { buildSkillFileTree } from '../features/skillFileTree';
import type { SkillDetail, SkillList, SkillSummary, SkillVersion, GitHubSkillInspection } from '../../../../packages/contracts/skills';

const { apiBaseUrl, createInChat } = skillLibraryServices.use();
const api = createSkillsApi(apiBaseUrl);
const list = ref<SkillSummary[]>([]), total = ref(0), offset = ref(0), query = ref('');
const loading = ref(false), saving = ref(false), error = ref(''), dialogError = ref(''), notice = ref('');
const detailLoading = ref(false), selected = ref<SkillDetail|null>(null), versions = ref<SkillVersion[]>([]);
const deleteTarget = ref<SkillSummary|null>(null), installing = ref(false);
const githubUrl = ref(''), githubRef = ref(''), githubPath = ref('');
const inspection = ref<GitHubSkillInspection|null>(null), chosenPath = ref<string|null>(null);
const selectedFilePath = ref('SKILL.md'), collapsedDirectories = ref<Set<string>>(new Set());
let loadSequence = 0, detailSequence = 0, disposed = false;
let searchDebounce: ReturnType<typeof setTimeout> | undefined;
let pendingOperation: { signature: string; key: string }|null = null;
const historical = computed(() => !!selected.value && selected.value.version !== selected.value.currentVersion);
const candidate = computed(() => inspection.value?.candidates.find(item => item.path === chosenPath.value && !item.error));
const modalOpen = computed(() => selected.value || detailLoading.value || installing.value);
const skillPackageFiles = computed(() => selected.value ? [{ path: 'SKILL.md' }, ...selected.value.resources] : []);
const skillFileTree = computed(() => buildSkillFileTree(skillPackageFiles.value, collapsedDirectories.value));
const activeSkillFile = computed(() => skillPackageFiles.value.find(file => file.path === selectedFilePath.value) || skillPackageFiles.value[0]);
const viewingInstructions = computed(() => activeSkillFile.value?.path === 'SKILL.md');
const skillCardSpriteUrl = new URL(`${import.meta.env.BASE_URL}assets/skill-card-sprite-v1.png`, document.baseURI).href;
const skillCardFrames: Record<string, string> = {
  'logo-mockup-suite': '0% 0%',
  'tourism-ip-design': '50% 0%',
  'notebook-print-design': '100% 0%',
  'scenic-wayfinding-design': '0% 100%',
  'xiaohongshu-visual-post': '50% 100%',
  'exhibition-hall-design': '100% 100%',
};
const message = (e: unknown) => e instanceof Error ? e.message : String(e);
function skillCardStyle(skill: SkillSummary) {
  const backgroundPosition = skillCardFrames[skill.name];
  return backgroundPosition ? { backgroundImage: `url(${skillCardSpriteUrl})`, backgroundPosition } : undefined;
}
function operation(signature: string) {
  if(pendingOperation?.signature !== signature) pendingOperation = { signature, key: crypto.randomUUID() };
  return { 'idempotency-key': pendingOperation.key };
}
async function load(reset = false) {
  if(reset) offset.value = 0;
  const sequence = ++loadSequence;
  loading.value = true; error.value = '';
  try {
    const result = await api<SkillList>(`?query=${encodeURIComponent(query.value)}&offset=${offset.value}&limit=20&include_disabled=true`);
    if(sequence !== loadSequence || disposed) return;
    list.value = result.skills; total.value = result.total;
    if(offset.value >= total.value && offset.value > 0) { offset.value = Math.max(0, offset.value - 20); void load(); }
  } catch(e) { if(sequence === loadSequence && !disposed) error.value = message(e); }
  finally { if(sequence === loadSequence && !disposed) loading.value = false; }
}
async function open(skill: SkillSummary, version?: number) {
  if(saving.value) return;
  const sequence = ++detailSequence; dialogError.value = ''; installing.value = false;
  selectedFilePath.value = 'SKILL.md'; collapsedDirectories.value = new Set();
  selected.value = null; detailLoading.value = true;
  try {
    const [detail, history] = await Promise.all([api<SkillDetail>(`/${skill.id}${version ? `?version=${version}` : ''}`), api<{versions:SkillVersion[]}>(`/${skill.id}/versions`)]);
    if(sequence !== detailSequence || disposed) return;
    selected.value = detail; versions.value = history.versions;
  } catch(e) { if(sequence === detailSequence && !disposed) error.value = message(e); }
  finally { if(sequence === detailSequence && !disposed) detailLoading.value = false; }
}
async function chat(skill?: SkillSummary) {
  try { await createInChat(skill); } catch(e) { error.value = message(e); }
}
async function toggle() {
  const target = selected.value;
  if(!target || saving.value || historical.value) return;
  saving.value = true; dialogError.value = '';
  try {
    const body = JSON.stringify({expected_version:target.currentVersion, enabled:!target.enabled});
    selected.value = await api<SkillDetail>(`/${target.id}`, {method:'PATCH', headers:operation(target.id + body), body});
    pendingOperation = null;
    await load(); versions.value = (await api<{versions:SkillVersion[]}>(`/${target.id}/versions`)).versions;
  } catch(e) { dialogError.value = message(e); } finally { saving.value = false; }
}
async function remove() {
  const target = deleteTarget.value; if(!target || saving.value) return;
  saving.value = true; dialogError.value = '';
  try {
    const path = `/${target.id}?expected_version=${target.currentVersion}`;
    await api(path, {method:'DELETE', headers:operation('delete' + path)});
    pendingOperation = null; deleteTarget.value = null; selected.value = null;
    notice.value = '已卸载，历史任务仍保留原版本。'; await load();
  } catch(e) { dialogError.value = message(e); } finally { saving.value = false; }
}
function showInstall() {
  close(); installing.value = true; inspection.value = null; chosenPath.value = null;
}
function resetInspection() { inspection.value = null; chosenPath.value = null; dialogError.value = ''; }
async function inspectGitHub() {
  if(saving.value) return;
  saving.value = true; dialogError.value = ''; inspection.value = null; chosenPath.value = null;
  try {
    const result = await api<GitHubSkillInspection>('/github/inspect', {method:'POST', body:JSON.stringify({url:githubUrl.value, ref:githubRef.value || null, path:githubPath.value || null})});
    if(disposed) return;
    inspection.value = result; chosenPath.value = result.candidates.find(item => !item.error)?.path ?? null;
  } catch(e) { if(!disposed) dialogError.value = message(e); } finally { if(!disposed) saving.value = false; }
}
async function installGitHub() {
  if(saving.value || !inspection.value || !candidate.value) return;
  saving.value = true; dialogError.value = '';
  try {
    // Pin the exact commit shown during inspection, even if the branch advances.
    const body = JSON.stringify({url:inspection.value.source.url, ref:inspection.value.source.commit, path:candidate.value.path});
    const result = await api<SkillDetail>('/github/install', {method:'POST', headers:operation(body), body});
    if(disposed) return;
    pendingOperation = null; installing.value = false;
    notice.value = `已安装「${result.title}」，可在对话中指定使用。`;
    query.value = ''; await load(true);
  } catch(e) { if(!disposed) dialogError.value = message(e); } finally { if(!disposed) saving.value = false; }
}
function resourceUrl(path: string) { return `${apiBaseUrl}/api/skills/${selected.value!.id}/versions/${selected.value!.version}/resources/${path.split('/').map(encodeURIComponent).join('/')}`; }
function exportUrl() { return `${apiBaseUrl}/api/skills/${selected.value!.id}/export?version=${selected.value!.version}`; }
function selectSkillFile(path: string) { selectedFilePath.value = path; }
function toggleDirectory(path: string) {
  const next = new Set(collapsedDirectories.value);
  next.has(path) ? next.delete(path) : next.add(path);
  collapsedDirectories.value = next;
}
function treeRowStyle(depth: number) { return { paddingInlineStart: `${12 + depth * 18}px` }; }
function fileSize(byteSize?: number) {
  if(byteSize === undefined) return '说明文件';
  return byteSize < 1024 ? `${byteSize} B` : `${Math.ceil(byteSize / 1024)} KB`;
}
function close() { detailSequence++; detailLoading.value = false; selected.value = null; installing.value = false; dialogError.value = ''; selectedFilePath.value = 'SKILL.md'; collapsedDirectories.value = new Set(); }
watch(query, () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => void load(true), 250);
});
onMounted(() => void load());
onUnmounted(() => { disposed = true; clearTimeout(searchDebounce); loadSequence++; detailSequence++; });
</script>

<template>
  <div class="skill-library">
    <LibraryPageLayout
      v-model:search="query"
      class="skills-page"
      eyebrow="SKILLS / WORKSPACE LIBRARY"
      title="技能库"
      description="管理工作区的专业方法，在对话中创建、调用和持续维护。"
      search-label="搜索技能"
      search-placeholder="搜索名称、用途或适用场景…"
    >
      <template #actions>
        <button class="ghost-button" @click="showInstall"><Github :size="16"/>从 GitHub 加载</button>
        <button class="primary-button" @click="chat()"><Plus :size="16"/>新建技能</button>
      </template>
      <template #meta><span>已安装 {{ total }} 个技能</span></template>

      <div class="skill-scope">
        <span class="skill-scope-icon"><Wrench :size="17"/></span>
        <div><strong>当前工作区共享</strong><p>兼容标准 SKILL.md；新建与修改将在对话中完成。</p></div>
      </div>
      <p v-if="notice" role="status" class="skill-notice">{{ notice }}</p>
      <EmptyState v-if="error">{{ error }}<template #action><button class="ghost-button" @click="load()">重新加载</button></template></EmptyState>
      <EmptyState v-else-if="loading && !list.length">正在读取已安装技能…</EmptyState>
      <EmptyState v-else-if="!list.length" :icon="Wrench" :title="query ? '没有找到匹配的技能' : '为设计添加专业方法'">{{ query ? '试试其他名称或关键词。' : '从 GitHub 加载技能，或在首页描述需求来创建。' }}</EmptyState>
      <div v-else class="skill-list library-grid" :aria-busy="loading">
        <button v-for="skill in list" :key="skill.id" class="skill-list-row" :class="{'has-cover':Boolean(skillCardFrames[skill.name])}" :aria-label="`查看技能 ${skill.title}`" @click="open(skill)">
          <span v-if="skillCardFrames[skill.name]" class="skill-card-cover" :style="skillCardStyle(skill)" aria-hidden="true" />
          <div class="skill-card-top">
            <span class="skill-card-icon"><Wrench :size="19"/></span>
            <span class="skill-status" :class="{disabled:!skill.enabled, warning:skill.missingTools.length}">{{ skill.missingTools.length ? '缺少工具' : skill.enabled ? '已启用' : '已停用' }}</span>
          </div>
          <div class="skill-name"><strong>{{ skill.title }}</strong><small>{{ skill.name }} · v{{ skill.version }}</small></div>
          <p class="skill-description">{{ skill.description }}</p>
          <div class="skill-card-footer">
            <span class="skill-source">{{ skill.builtin ? '内置技能' : skill.source ? `${skill.source.owner}/${skill.source.repo}` : '对话创建' }}</span>
            <span class="skill-open">查看详情 <ArrowUpRight :size="15"/></span>
          </div>
        </button>
      </div>
      <div v-if="total>20" class="skill-pagination"><button class="ghost-button" :disabled="offset===0 || loading" @click="offset-=20;load()">上一页</button><span>{{ offset+1 }}–{{ Math.min(offset+20,total) }} / {{ total }}</span><button class="ghost-button" :disabled="offset+20>=total || loading" @click="offset+=20;load()">下一页</button></div>
    </LibraryPageLayout>

    <Teleport to="body"><div class="skill-library skill-dialog-layer">
      <div v-if="modalOpen" class="skill-backdrop" @click="!saving && close()"></div>
      <section v-if="modalOpen" class="skill-sheet" role="dialog" aria-modal="true" :aria-label="installing ? '从 GitHub 加载技能' : '技能详情'" @keydown.esc.stop="!saving && close()">
        <div class="skill-sheet-top"><h2>{{ installing ? '从 GitHub 加载技能' : selected?.title || '技能详情' }}</h2><button class="icon-button" aria-label="关闭技能详情" :disabled="saving" @click="close"><X :size="20"/></button></div>
        <p v-if="dialogError && !deleteTarget" role="alert" class="skill-error">{{ dialogError }}</p>
        <p v-if="detailLoading" role="status">正在读取技能与历史版本…</p>
        <template v-if="installing">
          <p class="muted">粘贴公开仓库或技能目录链接，选择其中的 SKILL.md 技能包。</p>
          <form class="skill-install-form" @submit.prevent="inspectGitHub">
            <fieldset :disabled="saving">
              <label>GitHub 链接<input v-model="githubUrl" type="url" required placeholder="https://github.com/owner/repo/tree/main/skills/my-skill" @input="resetInspection"/></label>
              <details><summary>指定分支和目录（可选）</summary><label>分支、标签或提交<input v-model="githubRef" placeholder="默认分支" @input="resetInspection"/></label><label>技能目录<input v-model="githubPath" placeholder="例如 skills/my-skill" @input="resetInspection"/></label></details>
              <button class="ghost-button">{{ saving && !inspection ? '正在识别…' : '识别技能' }}</button>
            </fieldset>
          </form>
          <div v-if="inspection" class="skill-candidates">
            <p class="muted">{{ inspection.source.owner }}/{{ inspection.source.repo }} · {{ inspection.source.commit.slice(0,8) }}</p>
            <label v-for="item in inspection.candidates" :key="item.path" class="skill-candidate" :class="{chosen:chosenPath===item.path}">
              <input v-model="chosenPath" type="radio" name="github-skill" :value="item.path" :disabled="saving || !!item.error"/>
              <span><strong>{{ item.title || item.path || '仓库根目录' }}</strong><small>{{ item.path || '/' }}</small><p>{{ item.error || item.description }}</p></span>
            </label>
            <p v-for="warning in candidate?.warnings || []" :key="warning" class="skill-notice">{{ warning }}</p>
            <p class="muted">保留 SKILL.md、Codex 配置及附带文件。脚本和外部工具依赖不会自动执行或安装。</p>
            <div class="skill-actions"><button class="primary-button" :disabled="saving || !candidate" @click="installGitHub"><Download :size="16"/>{{ saving ? '正在安装…' : '安装所选技能' }}</button></div>
          </div>
        </template>
        <template v-else-if="selected">
          <p class="muted">{{ selected.name }} · 当前查看 v{{ selected.version }}</p><p>{{ selected.description }}</p>
          <p v-if="selected.builtin" class="muted">内置技能 · {{ selected.builtin.revision }}{{ selected.builtin.modifiedLocally ? ' · 已在本地修改，升级时保留你的版本' : '' }}</p>
          <p v-if="selected.source" class="muted">来源：<a :href="selected.source.url" target="_blank" rel="noopener noreferrer">{{ selected.source.owner }}/{{ selected.source.repo }}</a> · {{ selected.source.commit.slice(0,8) }}{{ selected.source.modifiedLocally ? ' · 已在本地修改' : '' }}</p>
          <div class="skill-detail-toolbar"><label>版本 <select :value="selected.version" :disabled="saving" @change="open(selected,Number(($event.target as HTMLSelectElement).value))"><option v-for="version in versions" :key="version.version" :value="version.version">v{{ version.version }} · {{ new Date(version.createdAt).toLocaleString() }}</option></select><a class="ghost-button" :href="exportUrl()" download><Download :size="15"/>导出技能包</a></label></div>
          <p v-if="historical" class="skill-notice">这是只读历史版本。<button class="ghost-button" @click="open(selected)"><ArrowLeft :size="14"/>返回当前版本</button></p>
          <p v-if="selected.explicitOnly" class="skill-notice">按 Codex 配置，此技能只在用户明确指定时使用。</p>
          <p v-for="warning in selected.compatibilityWarnings || []" :key="warning" class="skill-notice">{{ warning }}</p>
          <section class="skill-package-preview" aria-label="技能包文件">
            <div class="skill-package-heading"><div><strong>技能包文件</strong><small>{{ skillPackageFiles.length }} 个文件</small></div><span>选择文件查看</span></div>
            <div class="skill-package-layout">
              <div class="skill-file-tree" role="tree" aria-label="技能文件树">
                <template v-for="row in skillFileTree" :key="`${row.kind}:${row.path}`">
                  <button v-if="row.kind === 'directory'" type="button" class="skill-tree-row skill-tree-directory" role="treeitem" :aria-level="row.depth + 1" :aria-expanded="!row.collapsed" :style="treeRowStyle(row.depth)" @click="toggleDirectory(row.path)">
                    <ChevronRight v-if="row.collapsed" :size="15" aria-hidden="true"/><ChevronDown v-else :size="15" aria-hidden="true"/><Folder :size="15" aria-hidden="true"/><span>{{ row.name }}</span>
                  </button>
                  <button v-else type="button" class="skill-tree-row skill-tree-file" :class="{active: activeSkillFile?.path === row.path}" role="treeitem" :aria-level="row.depth + 1" :aria-current="activeSkillFile?.path === row.path ? 'true' : undefined" :style="treeRowStyle(row.depth)" @click="selectSkillFile(row.path)">
                    <FileText :size="15" aria-hidden="true"/><span>{{ row.name }}</span><small>{{ fileSize(row.byteSize) }}</small>
                  </button>
                </template>
              </div>
              <div class="skill-file-preview">
                <div class="skill-file-preview-header"><code>{{ activeSkillFile?.path }}</code><a v-if="activeSkillFile && !viewingInstructions" class="ghost-button" :href="resourceUrl(activeSkillFile.path)" download><Download :size="14"/>下载文件</a></div>
                <pre v-if="viewingInstructions" class="skill-body">{{ selected.instructions }}</pre>
                <div v-else class="skill-resource-download"><FileText :size="20" aria-hidden="true"/><p>资源文件保留在技能包中；为安全起见，请下载后在本地查看。</p></div>
              </div>
            </div>
          </section>
          <p><strong>依赖工具：</strong>{{ selected.requiredTools.join('、') || '无额外依赖' }}</p>
          <p v-if="selected.missingTools.length" class="skill-error">缺少工具：{{ selected.missingTools.join('、') }}</p>
          <div v-if="!historical" class="skill-actions"><button class="ghost-button skill-danger" :disabled="saving" @click="deleteTarget=selected">卸载</button><button class="ghost-button" :disabled="saving" @click="toggle">{{ selected.enabled ? '停用' : '启用' }}</button><button class="primary-button" :disabled="saving" @click="chat(selected)">在对话中修改<ArrowUpRight :size="15"/></button></div>
        </template>
      </section>
      <div v-if="deleteTarget" class="skill-delete-backdrop"><section role="alertdialog" aria-label="卸载技能" class="skill-delete-dialog"><h3>卸载“{{ deleteTarget.title }}”？</h3><p>所有项目将无法再发现它。已加载的任务保留原版本。</p><p v-if="dialogError" role="alert" class="skill-error">{{ dialogError }}</p><div class="skill-actions"><button class="ghost-button" :disabled="saving" @click="deleteTarget=null;dialogError=''">取消</button><button class="primary-button" :disabled="saving" @click="remove">{{ saving ? '卸载中…' : '卸载技能' }}</button></div></section></div>
    </div></Teleport>
  </div>
</template>

<style scoped>
.skill-actions,.skill-sheet-top,.skill-pagination{display:flex;align-items:center;gap:12px}.skill-library button{font-family:inherit}
.skill-sheet{position:fixed;right:20px;top:20px;bottom:20px;width:min(700px,calc(100vw - 40px));padding:28px;background:var(--theme-surface);color:var(--theme-text);border:1px solid var(--theme-border);border-radius:var(--ui-radius-dialog);overflow:auto;z-index:601;box-shadow:0 20px 80px #0003}.skill-sheet-top{justify-content:space-between;margin-bottom:18px}.skill-sheet h2{margin:0;font-size:var(--ui-font-section);line-height:var(--ui-line-heading)}.skill-backdrop{position:fixed;inset:0;background:#0005;z-index:600}.skill-library input:not([type=radio]),.skill-library select{font:inherit;color:var(--theme-text);background:var(--theme-bg);border:1px solid var(--theme-border);border-radius:var(--ui-radius-control);padding:10px 12px;max-width:100%}.skill-actions{justify-content:flex-end;flex-wrap:wrap;margin-top:22px}.skill-body{min-height:320px;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:var(--ui-font-body);line-height:1.8;background:var(--theme-bg);border:1px solid var(--theme-border);border-radius:10px;padding:16px}.skill-library a{color:var(--theme-accent-strong);overflow-wrap:anywhere}.skill-notice{background:#77777712;padding:12px;border-radius:8px;font-size:var(--ui-font-control);line-height:1.7}.skill-error{color:#6c6c6c;font-size:var(--ui-font-control);overflow-wrap:anywhere}.skill-pagination{justify-content:center;margin-top:24px}.skill-danger{color:#6c6c6c}.skill-delete-backdrop{position:fixed;inset:0;background:#0006;display:grid;place-items:center;z-index:610}.skill-delete-dialog{background:var(--theme-surface);padding:28px;border-radius:var(--ui-radius-dialog);max-width:440px;margin:20px}.skill-detail-toolbar{margin:20px 0}.skill-detail-toolbar label{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.skill-library .primary-button,.skill-library .ghost-button{display:inline-flex;align-items:center;justify-content:center;gap:7px}.skill-library .icon-button{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;padding:6px}.skill-library input:focus{outline:2px solid var(--theme-accent-strong);outline-offset:1px}
.skill-package-preview{margin:20px 0;border:1px solid var(--theme-border);border-radius:14px;overflow:hidden}.skill-package-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 16px;border-bottom:1px solid var(--theme-border);background:color-mix(in srgb,var(--theme-bg) 70%,transparent);font-size:var(--ui-font-control)}.skill-package-heading strong{display:block}.skill-package-heading small{display:block;margin-top:3px;color:var(--theme-text-muted);font-size:var(--ui-font-caption)}.skill-package-heading>span{color:var(--theme-text-muted);font-size:var(--ui-font-caption)}.skill-package-layout{display:grid;grid-template-columns:minmax(180px,35%) minmax(0,1fr);min-height:360px}.skill-file-tree{padding:8px 0;border-right:1px solid var(--theme-border);background:color-mix(in srgb,var(--theme-bg) 55%,transparent);overflow:auto}.skill-tree-row{display:flex;align-items:center;width:100%;min-height:32px;gap:7px;padding-block:6px;padding-inline-end:10px;border:0;border-radius:0;background:transparent;color:var(--theme-text);font-size:var(--ui-font-caption);line-height:1.4;text-align:left}.skill-tree-row:hover{background:color-mix(in srgb,var(--theme-accent-strong) 9%,transparent)}.skill-tree-row.active{background:color-mix(in srgb,var(--theme-accent-strong) 16%,transparent);color:var(--theme-accent-strong)}.skill-tree-row svg{flex:0 0 auto;color:var(--theme-text-muted)}.skill-tree-row.active svg{color:inherit}.skill-tree-row span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.skill-tree-row small{margin-left:auto;color:var(--theme-text-muted);font-size:var(--ui-font-caption);white-space:nowrap}.skill-tree-directory{font-weight:600}.skill-file-preview{min-width:0;padding:14px;background:var(--theme-surface)}.skill-file-preview-header{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:30px;margin-bottom:10px}.skill-file-preview-header code{min-width:0;overflow:hidden;color:var(--theme-text-muted);font-size:var(--ui-font-caption);text-overflow:ellipsis;white-space:nowrap}.skill-file-preview-header .ghost-button{flex:0 0 auto;padding:6px 9px;font-size:var(--ui-font-caption)}.skill-resource-download{display:grid;min-height:320px;place-content:center;justify-items:center;gap:10px;padding:20px;color:var(--theme-text-muted);text-align:center}.skill-resource-download p{max-width:230px;margin:0;font-size:var(--ui-font-caption);line-height:1.7}
.skill-install-form fieldset{border:0;padding:0;display:grid;gap:20px;min-width:0}.skill-install-form label{display:grid;gap:8px;font-size:var(--ui-font-control);margin:12px 0}.skill-install-form summary{cursor:pointer;color:var(--theme-text-muted);font-size:var(--ui-font-control)}.skill-install-form button{justify-self:start}.skill-candidates{margin-top:24px}.skill-candidate{display:flex;align-items:flex-start;gap:12px;padding:15px;border:1px solid var(--theme-border);border-radius:10px;margin-bottom:10px;cursor:pointer}.skill-candidate.chosen{border-color:var(--theme-accent-strong)}.skill-candidate span{min-width:0}.skill-candidate small{display:block;color:var(--theme-text-muted);font-size:var(--ui-font-caption);overflow-wrap:anywhere;margin-top:4px}.skill-candidate p{margin:7px 0 0;font-size:var(--ui-font-control);line-height:1.6;overflow-wrap:anywhere}
@media(max-width:700px){.skill-sheet{right:10px;top:10px;bottom:10px;width:calc(100vw - 20px);padding:20px;border-radius:var(--ui-radius-dialog)}.skill-package-layout{grid-template-columns:1fr}.skill-file-tree{max-height:190px;border-right:0;border-bottom:1px solid var(--theme-border)}.skill-body,.skill-resource-download{min-height:220px}.skill-package-heading>span{display:none}}

/* The library landing view follows the same visual system as projects, assets and references. */
.skills-page :deep(.collection-toolbar){margin-bottom:18px}
.skill-scope{display:flex;align-items:center;gap:12px;margin:0 0 22px;padding:13px 15px;border:1px solid var(--theme-border);border-radius:12px;background:color-mix(in srgb,var(--theme-surface) 72%,transparent);font-size:var(--ui-font-caption);line-height:1.55}
.skill-scope-icon{display:grid;place-items:center;width:34px;height:34px;flex:0 0 auto;border:1px solid color-mix(in srgb,var(--theme-accent-strong) 28%,var(--theme-border));border-radius:10px;background:color-mix(in srgb,var(--theme-accent-strong) 9%,transparent);color:var(--theme-accent-strong)}
.skill-scope strong{display:block;color:var(--theme-text);font-size:var(--ui-font-caption);font-weight:650}.skill-scope p{margin:2px 0 0;color:var(--theme-text-muted)}
.skill-list{margin:0;border-top:0}.skill-list-row{position:relative;display:flex;min-width:0;min-height:228px;flex-direction:column;align-items:stretch;gap:0;padding:20px;border:1px solid var(--theme-border);border-radius:16px;background:color-mix(in srgb,var(--theme-surface) 80%,transparent);color:var(--theme-text);text-align:left;box-shadow:0 10px 30px #00000016;overflow:hidden;isolation:isolate;transform:translateZ(0);transition:transform .18s cubic-bezier(.2,.7,.2,1),border-color .18s ease,background .18s ease,box-shadow .18s ease}
.skill-list-row>*:not(.skill-card-cover){position:relative;z-index:2}.skill-list-row::before{content:'';position:absolute;inset:0 0 auto;height:76px;z-index:1;background:radial-gradient(circle at 12% 0%,color-mix(in srgb,var(--theme-accent-strong) 14%,transparent),transparent 72%);pointer-events:none}
.skill-card-cover{position:absolute;top:50%;left:0;z-index:0;width:100%;aspect-ratio:1;background-color:#181818;background-repeat:no-repeat;background-size:300% 200%;filter:saturate(.92) contrast(1.03) brightness(.86);pointer-events:none;transform:translate3d(0,-50%,0) scale(1.015);transform-origin:center;transition:transform .42s cubic-bezier(.2,.7,.2,1),filter .3s ease}
.skill-list-row.has-cover{border-color:#ffffff24;background:#151515;color:#f7f7f7;box-shadow:0 12px 34px #00000038}.skill-list-row.has-cover::before{inset:0;height:auto;background:linear-gradient(180deg,#0d0d0da8 0%,#0e0e0e59 28%,#0e0e0ec4 61%,#090909f5 100%),linear-gradient(90deg,#0d0d0d8f 0%,transparent 78%)}
.skill-list-row.has-cover:hover{border-color:color-mix(in srgb,var(--theme-accent-strong) 54%,#ffffff26);background:#151515;box-shadow:0 17px 42px #00000055}.skill-list-row.has-cover:hover .skill-card-cover{filter:saturate(1) contrast(1.03) brightness(.96);transform:translate3d(0,-50%,0) scale(1.06)}
.skill-list-row:hover{border-color:color-mix(in srgb,var(--theme-accent-strong) 34%,var(--theme-border));background:var(--theme-surface);box-shadow:0 15px 38px #00000026;transform:translate3d(0,-3px,0)}
.skill-list-row:focus-visible{outline:2px solid var(--theme-accent-strong);outline-offset:3px}
.skill-card-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:17px}.skill-card-icon{display:grid;place-items:center;width:39px;height:39px;border:1px solid color-mix(in srgb,var(--theme-accent-strong) 28%,var(--theme-border));border-radius:11px;background:color-mix(in srgb,var(--theme-accent-strong) 10%,var(--theme-surface));color:var(--theme-accent-strong)}
.skill-name{display:block;min-width:0}.skill-name strong{display:block;overflow:hidden;font-size:var(--ui-font-card);font-weight:650;line-height:1.45;text-overflow:ellipsis;white-space:nowrap}.skill-name small{display:block;margin-top:4px;overflow:hidden;color:var(--theme-text-muted);font-size:var(--ui-font-caption);line-height:1.5;text-overflow:ellipsis;white-space:nowrap}
.skill-description{display:-webkit-box;min-height:60px;margin:12px 0 18px;overflow:hidden;color:color-mix(in srgb,var(--theme-text) 78%,var(--theme-text-muted));font-size:var(--ui-font-caption);line-height:1.68;-webkit-box-orient:vertical;-webkit-line-clamp:3}
.skill-card-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:auto;padding-top:13px;border-top:1px solid color-mix(in srgb,var(--theme-border) 78%,transparent)}
.skill-source{min-width:0;overflow:hidden;color:var(--theme-text-muted);font-size:var(--ui-font-caption);line-height:1.5;text-overflow:ellipsis;white-space:nowrap}.skill-open{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;color:var(--theme-text-muted);font-size:var(--ui-font-caption);transition:color .16s ease}.skill-list-row:hover .skill-open{color:var(--theme-accent-strong)}
.skill-status{display:inline-flex;align-items:center;justify-content:center;justify-self:auto;min-height:24px;padding:4px 9px;border:1px solid #9c9c9c24;border-radius:999px;background:#7777771a;color:#a1a1a1;font-size:var(--ui-font-caption);line-height:1.4}.skill-status.disabled{border-color:var(--theme-border);background:#8882;color:var(--theme-text-muted)}.skill-status.warning{border-color:#6c6c6c2b;background:#6c6c6c12;color:#8d8d8d}
.skill-list-row.has-cover .skill-card-icon{border-color:#e9e9e957;background:#111111c7;color:#e9e9e9;box-shadow:0 6px 18px #0006;backdrop-filter:blur(10px)}.skill-list-row.has-cover .skill-status{border-color:#dedede42;background:#1d1d1dc9;color:#dddddd;box-shadow:0 5px 16px #0005;backdrop-filter:blur(10px)}.skill-list-row.has-cover .skill-status.disabled{border-color:#ffffff2b;background:#1a1a1acf;color:#c2c2c2}.skill-list-row.has-cover .skill-status.warning{border-color:#afafaf52;background:#1e1e1ed6;color:#c2c2c2}
.skill-list-row.has-cover .skill-name strong{color:#fafafa;text-shadow:0 2px 10px #000}.skill-list-row.has-cover .skill-name small,.skill-list-row.has-cover .skill-description,.skill-list-row.has-cover .skill-source,.skill-list-row.has-cover .skill-open{color:#dadada;text-shadow:0 1px 7px #000}.skill-list-row.has-cover .skill-card-footer{border-top-color:#ffffff26}.skill-list-row.has-cover:hover .skill-open{color:#e9e9e9}
.skill-pagination{margin:26px 0 4px}.skill-pagination>span{color:var(--theme-text-muted);font-size:var(--ui-font-caption)}
@media(max-width:920px){.skill-list-row{min-height:210px}}
@media(max-width:700px){.skill-list-row{min-height:0;padding:17px}.skill-source{display:block}.skill-description{min-height:auto}.skill-card-footer{padding-top:12px}.skill-scope{align-items:flex-start}}
@media(prefers-reduced-motion:reduce){.skill-list-row,.skill-open,.skill-card-cover{transition:none}.skill-list-row.has-cover:hover .skill-card-cover{transform:translate3d(0,-50%,0) scale(1.015)}}
.skill-sheet .muted { font-size: var(--ui-font-caption); line-height: var(--ui-line-body); }
</style>
