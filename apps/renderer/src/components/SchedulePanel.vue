<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { Bell, Bot, Check, CircleAlert, Clock3, Inbox, LoaderCircle, Pause, Pencil, Play, Save, ShieldCheck, Sparkles, Trash2, X } from 'lucide-vue-next';
import { arrangeSchedule, scheduleCountdown, type PlanningProgress } from '../features/scheduleProgress';
import EmptyState from './shared/EmptyState.vue';

type Timing = { kind: 'once' | 'daily' | 'weekly' | 'interval'; timezone: string; time?: string | null; weekdays: number[]; at?: string | null; intervalMinutes?: number | null };
type Job = { id: string; title: string; prompt: string; mode: 'agent' | 'reminder'; timing: Timing; status: string; nextRunAt?: string | null; projectId?: string | null };
type Notice = { id: string; title: string; body: string; projectId?: string | null; createdAt: string; readAt?: string | null };
const props = defineProps<{ apiBaseUrl: string; projects: { id: string; name: string }[]; provider?: { key: string; baseUrl: string; model: string }; imageModel?: string; allowExternalNetwork: boolean }>();
const emit = defineEmits<{ 'open-project': [id: string]; 'open-settings': []; changed: [] }>();
const prompt = ref('');
const planPlaceholder = '例如：\n每周一上午 9 点，整理一份设计趋势简报。\n每天 18 点，提醒我回顾今天的项目进度。';
const timezone = ref(Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai');
const projectId = ref('');
const repeat = ref<'daily' | 'weekly'>('daily');
const scheduledTime = ref('09:00');
const scheduledWeekdays = ref([0]);
const jobs = ref<Job[]>([]);
const notices = ref<Notice[]>([]);
const busy = ref(false);
const loading = ref(true);
const error = ref('');
const result = ref('');
const questions = ref<string[]>([]);
const progress = ref<PlanningProgress[]>([]);
const clockNow = ref(Date.now());
const planningStartedAt = ref(0);
const planningElapsed = computed(() => Math.max(0, Math.floor((clockNow.value - planningStartedAt.value) / 1000)));
let planningController: AbortController | undefined;
const requestId = ref(crypto.randomUUID());
const editing = ref<Job | null>(null);
const actionId = ref('');
const pane = ref<'tasks' | 'notifications'>('tasks');
const weekLabels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const activeCount = computed(() => jobs.value.filter((job) => job.status === 'active').length);
const unreadCount = computed(() => notices.value.filter((notice) => !notice.readAt).length);
let refreshTimer: number | undefined;
let clockTimer: number | undefined;
let pollInFlight = false;
let disposed = false;
const timingInstruction = computed(() => repeat.value === 'weekly'
  ? `每周 ${scheduledWeekdays.value.map(day => weekLabels[day]).join('、')} ${scheduledTime.value}`
  : `每天 ${scheduledTime.value}`);
const timezoneLabel = computed(() => timezone.value === 'Asia/Shanghai' ? '中国时间' : timezone.value);
const planningPrompt = computed(() => `${prompt.value.trim()}\n\n【已设置的执行时间】${timingInstruction.value}（${timezone.value}）。请严格按此时间创建计划；不要改成其他周期或时间。`);
watch([prompt, timezone, projectId, repeat, scheduledTime, scheduledWeekdays], () => { requestId.value = crypto.randomUUID(); result.value = ''; questions.value = []; });
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${props.apiBaseUrl}${path}`, { ...options, headers: { 'Content-Type': 'application/json' } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : '请求失败，请检查时间和任务内容。');
  }
  return response.json();
}
async function load() {
  if (pollInFlight || disposed) return;
  pollInFlight = true;
  try {
    const [nextJobs, nextNotices] = await Promise.all([api<Job[]>('/api/schedules'), api<Notice[]>('/api/schedule-notifications')]);
    if (disposed) return;
    jobs.value = nextJobs; notices.value = nextNotices; clockNow.value = Date.now();
  } catch (cause) { if (!disposed) error.value = cause instanceof Error ? cause.message : '定时任务读取失败'; }
  finally { loading.value = false; pollInFlight = false; }
}
async function arrange() {
  if (!prompt.value.trim() || busy.value) return;
  if (!props.provider) { emit('open-settings'); return; }
  busy.value = true; error.value = ''; result.value = ''; questions.value = []; progress.value = [];
  planningStartedAt.value = clockNow.value = Date.now();
  planningController = new AbortController();
  try {
    const planned = await arrangeSchedule<{ schedules: Job[]; questions: string[] }>(`${props.apiBaseUrl}/api/schedules/arrange/stream`, { prompt: planningPrompt.value, timezone: timezone.value, projectId: projectId.value || null, requestId: requestId.value, textProvider: props.provider, imageModel: props.imageModel || null, allowExternalNetwork: props.allowExternalNetwork }, planningController.signal, event => {
      if (disposed) return;
      const index = progress.value.findIndex(item => item.id === event.id);
      if (index === -1) progress.value.push(event);
      else progress.value[index] = event;
    });
    if (disposed) return;
    questions.value = planned.questions;
    if (planned.schedules.length) {
      result.value = `Agent 已设置 ${planned.schedules.length} 个定时任务。`;
      await load(); emit('changed');
    }
  } catch (cause) {
    if (disposed) return;
    error.value = cause instanceof Error ? cause.message : '计划设置失败，请重试';
    progress.value = progress.value.map(event => event.status === 'running' ? { ...event, status: 'failed', label: error.value } : event);
    await load();
  }
  finally { busy.value = false; }
}
function progressIcon(event: PlanningProgress) {
  if (event.status === 'failed' || event.status === 'waiting') return CircleAlert;
  return { received: Inbox, context: Clock3, planning: Bot, validation: ShieldCheck, saving: Save }[event.id] || Sparkles;
}
function timeLabel(value?: string | null, zone?: string) {
  if (!value) return '—';
  return new Date(value).toLocaleString('zh-CN', { timeZone: zone || timezone.value, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}
function timingLabel(timing: Timing) {
  if (timing.kind === 'once') return `${timeLabel(timing.at, timing.timezone)} · 单次`;
  if (timing.kind === 'interval') return `每 ${timing.intervalMinutes} 分钟`;
  if (timing.kind === 'weekly') return `${timing.weekdays.map((day) => weekLabels[day]).join('、')} ${timing.time}`;
  return `每天 ${timing.time}`;
}
async function changeStatus(job: Job, status: string) {
  if (actionId.value) return;
  actionId.value = job.id; error.value = '';
  try { await api(`/api/schedules/${job.id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); await load(); emit('changed'); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败'; }
  finally { actionId.value = ''; }
}
function edit(job: Job) { editing.value = JSON.parse(JSON.stringify(job)); }
function toggleWeekday(day: number) {
  if (!editing.value) return;
  const days = editing.value.timing.weekdays;
  editing.value.timing.weekdays = days.includes(day) ? days.filter((item) => item !== day) : [...days, day].sort();
}
function toggleScheduledWeekday(day: number) {
  const days = scheduledWeekdays.value;
  if (days.includes(day)) {
    if (days.length === 1) return;
    scheduledWeekdays.value = days.filter(item => item !== day);
  } else {
    scheduledWeekdays.value = [...days, day].sort();
  }
}
async function saveEdit() {
  if (!editing.value || actionId.value) return;
  const { id, title, prompt, mode, timing } = editing.value;
  actionId.value = id; error.value = '';
  try { await api(`/api/schedules/${id}`, { method: 'PUT', body: JSON.stringify({ title, prompt, mode, timing }) }); editing.value = null; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '保存失败'; }
  finally { actionId.value = ''; }
}
async function readNotice(notice: Notice) {
  try { await api(`/api/schedule-notifications/${encodeURIComponent(notice.id)}/read`, { method: 'POST' }); notice.readAt = new Date().toISOString(); emit('changed'); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '通知更新失败'; }
}
onMounted(() => {
  void load();
  refreshTimer = window.setInterval(() => { void load(); }, 5000);
  clockTimer = window.setInterval(() => { clockNow.value = Date.now(); }, 1000);
});
onUnmounted(() => { disposed = true; planningController?.abort(); window.clearInterval(refreshTimer); window.clearInterval(clockTimer); });
</script>

<template>
  <section class="schedule-panel" aria-label="定时任务">
    <header class="schedule-page-header"><div><span class="eyebrow">SCHEDULE / AGENT</span><h2><Clock3 :size="25" />定时任务</h2><p>写下要做的事，再直接设定重复方式和执行时间。</p></div></header>
    <div class="schedule-layout">
      <form class="schedule-planner" @submit.prevent="arrange">
        <div class="schedule-card-heading"><Sparkles :size="18" /><strong>让 Agent 安排计划</strong></div>
        <label>你的计划<textarea v-model="prompt" :disabled="busy" rows="6" maxlength="12000" :placeholder="planPlaceholder" /></label>
        <fieldset class="schedule-timing-settings" :disabled="busy">
          <legend>执行时间</legend>
          <div class="schedule-timing-row"><label>重复<select v-model="repeat"><option value="daily">每天</option><option value="weekly">每周</option></select></label><label>时间<input v-model="scheduledTime" type="time" required /></label></div>
          <div v-if="repeat === 'weekly'" class="schedule-weekdays schedule-planner-weekdays" aria-label="选择每周执行日"><button v-for="(day, index) in weekLabels" :key="day" type="button" :class="{ active: scheduledWeekdays.includes(index) }" :aria-pressed="scheduledWeekdays.includes(index)" @click="toggleScheduledWeekday(index)">{{ day }}</button></div>
          <p>{{ timezoneLabel }} {{ scheduledTime }} · {{ timingInstruction }}</p>
        </fieldset>
        <div class="schedule-form-row"><label>时区<input v-model="timezone" :disabled="busy" placeholder="Asia/Shanghai" /></label><label>关联项目<select v-model="projectId" :disabled="busy"><option value="">执行时创建独立项目</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label></div>
        <p class="schedule-runtime-note">任务保存在本机。应用运行时按计划执行；关机或休眠错过的周期，在恢复后补执行一次。执行结果可在通知和关联项目中查看。</p>
        <p v-if="!provider" class="schedule-config-note">先在设置中选择可用的文本模型，Agent 才能安排计划。<button type="button" class="text-button" @click="emit('open-settings')">打开模型设置</button></p>
        <button class="primary-button schedule-arrange" :disabled="busy || !prompt.trim() || !provider"><LoaderCircle v-if="busy" :size="16" class="spin-icon" /><Sparkles v-else :size="16" />{{ busy ? 'Agent 正在组织计划…' : '创建定时任务' }}</button>
        <div v-if="busy || progress.length" class="schedule-planning-progress">
          <div class="schedule-progress-heading"><span>{{ busy ? 'Agent 正在组织计划' : error ? '计划组织遇到问题' : questions.length ? '等待补充信息' : '计划组织完成' }}</span><small v-if="busy">已用时 {{ planningElapsed }} 秒</small></div>
          <ol aria-label="计划组织过程" aria-live="polite" aria-relevant="additions text">
            <li v-if="busy && !progress.length" class="running"><LoaderCircle :size="15" class="spin-icon" aria-hidden="true" /><span>正在连接计划组织服务</span></li>
            <li v-for="event in progress" :key="event.id" :class="event.status">
              <component :is="progressIcon(event)" :size="15" class="schedule-progress-icon" aria-hidden="true" /><span>{{ event.label }}</span>
              <LoaderCircle v-if="event.status === 'running'" :size="12" class="spin-icon" aria-label="进行中" /><Check v-else-if="event.status === 'completed'" :size="12" class="schedule-progress-check" aria-label="已完成" />
            </li>
          </ol>
        </div>
        <div v-if="questions.length" class="schedule-questions"><strong>Agent 还需要补充</strong><p v-for="question in questions" :key="question">{{ question }}</p><small>请在上方计划中补充，然后再次提交。</small></div>
        <p v-if="result" class="schedule-success" role="status"><Check :size="15" />{{ result }}</p>
      </form>
      <div class="schedule-records">
        <div class="schedule-tabs"><button type="button" :class="{ active: pane === 'tasks' }" @click="pane = 'tasks'"><Clock3 :size="15" />计划 <span>{{ activeCount }} 进行中</span></button><button type="button" :class="{ active: pane === 'notifications' }" @click="pane = 'notifications'"><Bell :size="15" />通知 <span v-if="unreadCount">{{ unreadCount }}</span></button></div>
        <EmptyState v-if="loading">正在读取…</EmptyState>
        <template v-else-if="pane === 'tasks'">
          <EmptyState v-if="!jobs.length" :icon="Clock3" title="把规律性的工作交给 Agent">输入计划后，这里会显示任务内容、周期和下次执行时间。</EmptyState>
          <article v-for="job in jobs" :key="job.id" class="schedule-job" :class="{ paused: job.status !== 'active' }">
            <div class="schedule-job-title"><h3>{{ job.title }}</h3><div class="schedule-job-next" :class="{ inactive: job.status !== 'active' }" :title="job.nextRunAt ? `下次执行：${timeLabel(job.nextRunAt, job.timing.timezone)}` : undefined"><small>下次执行</small><span class="schedule-countdown" role="timer" :aria-label="`下次执行：${scheduleCountdown(job, clockNow)}`"><Clock3 :size="12" aria-hidden="true" />{{ scheduleCountdown(job, clockNow) }}</span></div></div><p>{{ job.prompt }}</p>
            <div class="schedule-timing"><Clock3 :size="14" /><strong>{{ timingLabel(job.timing) }}</strong><small>{{ job.timing.timezone }}</small></div>
            <div class="schedule-job-meta"><span>{{ job.mode === 'reminder' ? '仅提醒' : 'Agent 自动执行' }}</span><span class="schedule-status">{{ { active: '已启用', paused: '已暂停', completed: '已到期' }[job.status] || job.status }}</span><span v-if="job.nextRunAt">下次 {{ timeLabel(job.nextRunAt, job.timing.timezone) }}</span></div>
            <footer><button type="button" @click="edit(job)"><Pencil :size="13" />编辑</button><button v-if="job.status !== 'completed'" type="button" :disabled="!!actionId" @click="changeStatus(job, job.status === 'active' ? 'paused' : 'active')"><Pause v-if="job.status === 'active'" :size="13" /><Play v-else :size="13" />{{ job.status === 'active' ? '暂停' : '恢复' }}</button><button v-if="job.projectId" type="button" @click="emit('open-project', job.projectId)">查看项目</button><button class="schedule-delete" type="button" :disabled="!!actionId" @click="changeStatus(job, 'deleted')"><Trash2 :size="13" />移除</button></footer>
          </article>
        </template>
        <template v-else><EmptyState v-if="!notices.length" :icon="Bell" title="暂无任务通知">定时任务到期、完成或失败后，会在这里通知你。</EmptyState><article v-for="notice in notices" :key="notice.id" class="schedule-notice" :class="{ unread: !notice.readAt }"><div class="schedule-job-title"><h3>{{ notice.title }}</h3><small>{{ timeLabel(notice.createdAt) }}</small></div><p>{{ notice.body }}</p><footer><button v-if="notice.projectId" type="button" @click="readNotice(notice); emit('open-project', notice.projectId)">查看结果</button><button v-if="!notice.readAt" type="button" @click="readNotice(notice)"><Check :size="13" />标为已读</button></footer></article></template>
      </div>
    </div>
    <p v-if="error" class="schedule-error" role="alert">{{ error }}</p>
    <div v-if="editing" class="schedule-edit-overlay" @click.self="editing = null"><form class="schedule-edit-card" @submit.prevent="saveEdit"><header><h3>编辑定时任务</h3><button class="icon-button" type="button" aria-label="关闭编辑" @click="editing = null"><X :size="18" /></button></header><label>任务名称<input v-model="editing.title" required maxlength="120" /></label><label>任务内容<textarea v-model="editing.prompt" required rows="4" /></label><label>执行方式<select v-model="editing.mode"><option value="agent">Agent 自动执行</option><option value="reminder">仅提醒</option></select></label><label>周期<select v-model="editing.timing.kind"><option value="once">单次</option><option value="daily">每天</option><option value="weekly">每周</option><option value="interval">固定间隔</option></select></label><label v-if="editing.timing.kind === 'daily' || editing.timing.kind === 'weekly'">时间<input v-model="editing.timing.time" type="time" required /></label><label v-if="editing.timing.kind === 'once'">执行时间（含时区）<input v-model="editing.timing.at" required placeholder="2026-09-15T09:00:00+08:00" /></label><label v-if="editing.timing.kind === 'interval'">间隔分钟<input v-model.number="editing.timing.intervalMinutes" type="number" min="1" max="525600" required /></label><div v-if="editing.timing.kind === 'weekly'" class="schedule-weekdays"><button v-for="(day, index) in weekLabels" :key="day" type="button" :class="{ active: editing.timing.weekdays.includes(index) }" @click="toggleWeekday(index)">{{ day }}</button></div><label>时区<input v-model="editing.timing.timezone" required /></label><p v-if="error" class="schedule-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="!!actionId">{{ actionId ? '保存中…' : '保存修改' }}</button></form></div>
  </section>
</template>
