<script setup lang="ts">
import GeneralSettings from './components/GeneralSettings.vue';
import VoiceInput from './components/composer/VoiceInput.vue';
import AppUpdate from './components/AppUpdate.vue';
import DesktopToolbar from './components/DesktopToolbar.vue';
import ModelBrandIcon from './components/ModelBrandIcon.vue';
import { canvasTextModel, canvasTaskTerminalPatch, createCanvasSubmissionGate } from './features/canvasGeneration';
import AppearanceSettings from './components/AppearanceSettings.vue';
import { applyAppearance } from './features/appearance';
import { generalSettings, shouldSendMessage } from './features/generalSettings';
import { useDesignDemoPlayback } from './features/home/designDemoPlayback';
import { useShowcasePlayback } from './features/home/showcasePlayback';
import { readyShowcaseSlugs } from './features/home/designExamples';
import { skillChatPrompt } from './features/skills';
import TaskRequestInspector from './components/TaskRequestInspector.vue';
import ThreeDSettings from './components/ThreeDSettings.vue';
import ModelRouterSettings from './components/ModelRouterSettings.vue';
import ThemeSwitcher from './components/ThemeSwitcher.vue';
import HomeUsageSummary from './components/home/HomeUsageSummary.vue';
import { creditSummary, creditLoadError, type CreditSummary } from './features/credits';
import MascotSettings from './components/MascotSettings.vue';
import { createMascotSettings, mascotSettingsKey } from './features/home/mascot';
import LocalCapabilities from './components/LocalCapabilities.vue';
import BetaTestingAbout from './components/BetaTestingAbout.vue';
import { recordBetaUsage } from './features/betaTesting';
import StylePicker from './components/composer/StylePicker.vue';
import AnchoredPopover from './components/composer/AnchoredPopover.vue';
import { designComposerPlaceholders } from './features/composer/placeholders';
import ReferencePreview from './components/composer/ReferencePreview.vue';
import SkillMentionMenu from './components/composer/SkillMentionMenu.vue';
import { skillMentionQuery, skillReferences, skillToken, selectedSkillMentions, type SkillMention } from './features/composer/skillMentions';
import FirstRequestCelebration from './components/FirstRequestCelebration.vue';
import AchievementCelebration from './components/AchievementCelebration.vue';
import { referenceSegments, referencedKeys, type InlineReference } from './features/composer/references';
import { messageReferences, type TaskReferenceSnapshot } from './features/composer/messageReferences';
import { taskReferences } from './features/composer/taskReferences';
import { createCanvasClickReferences } from './features/composer/canvasClickReferences';
import { replaceConversationTurn, resubmissionReferences, type EditedTask } from './features/composer/messageResubmission';
import './features/composer/composer.css';
import './mx-theme.css';
import './features/motion/motion.css';
import StarBorder from './components/motion/StarBorder.vue';
import AnimatedList from './components/motion/AnimatedList.vue';
import './settings.css';

import { DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, IMAGE_ROUTE_LABEL, usdToCny, modelPrices, modelDisplayName, formatTokens, preferMediaModel, routingChoices, type RoutingMode } from './modelEconomy';

import { computed, nextTick, onMounted, onUnmounted, provide, ref, watch } from 'vue';

import { RouterView } from 'vue-router';

import type { SettingsSection } from './features/pageServices';
import type { WorkspaceView } from './features/navigation/routes';

import { homeServices, projectLibraryServices, assetLibraryServices, knowledgeLibraryServices, skillLibraryServices, helpServices, accountServices, settingsServices, scheduleServices, projectWorkspaceServices } from './features/pageServices';

import { useWorkspaceNavigation } from './features/navigation/useWorkspaceNavigation';
import { createTaskQueue, type QueueTask } from './features/taskQueue';
import { canDispatchQueue, createQueueMessage, moveQueueItem, shouldAdvanceQueue, queuePauseReason, queueTaskResult, supplementUnavailableReason, queueItemCanStart, type QueuedComposerMessage } from './features/messageQueue';

import { ArrowUp, House, Wrench, BookOpen, Bot, Box, CircleHelp, ClipboardList, Clock3, ChevronDown, ChevronRight, ChevronUp, FileText, Folder, GripVertical, Images, ListPlus, LoaderCircle, Monitor, Sun, Moon, Palette, Paperclip, Pencil, Play, Settings2, Square as StopIcon, Trash2, Upload, Volume2, X } from 'lucide-vue-next';

import type { Project, ProjectCreateInput } from '@contracts/project';

import { followTask } from './designTaskStream';
import { mergeProjectTitles } from './features/projectTitles';
import { localServiceHint, taskIssue, taskErrorMessage, type TaskIssue } from './features/taskErrors';
import { publicAssistantMessage } from './features/generationErrors';
import { taskDeliveryFindings } from './features/deliveryFindings';
import type { ConversationMessage, MessageResubmission } from './features/pageServices';
import { pendingReferenceSelection, type ReferenceSubmission } from './features/references';
import { pendingClarification, type ClarificationSubmission } from './features/clarification';
import { ComposerDraftStore } from './features/composerDrafts';

import { useSupplementalProvider, createProviderModelCatalog, selectAvailableModel, type DetectedModel, type ModelCatalogResponse } from './providerModels';

import { completedDeliveryReply, designLiveText, designSteps, type DesignStep } from './designPresentation';
import { isCosmicFutureQuestion } from './features/easterEggs';

const apiBaseUrl = window.studio?.apiBaseUrl ?? import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765';
const mascotSettings = createMascotSettings(apiBaseUrl);
provide(mascotSettingsKey, mascotSettings);

const appVersion = '0.2.0';


const isDesktopApp = Boolean(window.studio?.isDesktop || /Electron\//i.test(navigator.userAgent));

const projects = ref<Project[]>([]);
let projectTitleTimer: number | undefined;
let projectTitleRefreshRunning = false;
let projectTitlesDisposed = false;

function scheduleProjectTitleRefresh() {
  window.clearTimeout(projectTitleTimer);
  if (!projectTitlesDisposed && projects.value.some((project) => project.titlePending)) {
    projectTitleTimer = window.setTimeout(() => { void refreshProjectTitles(); }, 2500);
  }
}

async function refreshProjectTitles() {
  if (projectTitleRefreshRunning || projectTitlesDisposed) return;
  projectTitleRefreshRunning = true;
  const before = [...projects.value];
  try {
    const loaded = await request<Project[]>('/api/projects');
    if (!projectTitlesDisposed) projects.value = mergeProjectTitles(projects.value, loaded, before);
  } catch {
    // Titles are optional metadata; keep the conversation available offline.
  } finally {
    projectTitleRefreshRunning = false;
    scheduleProjectTitleRefresh();
  }
}

watch(projects, scheduleProjectTitleRefresh);

const activeProjectId = ref<string | null>(null);

const activeProjectStorageKey = 'langjuart.activeProjectId';

const backgroundProjectStorageKey = 'langjuart.backgroundProjectId';

let projectListLoadSequence = 0;

let missingProjectRecoveryInFlight = false;

let apiRecoveryTimer: number | null = null;

let apiRecoveryAttempts = 0;

let globalLibraryLoadSequence = 0;

let designCanvasLoadSequence = 0;

const isCreating = ref(false);

const isLoading = ref(true);

const projectCatalogReady = ref(false);

const isSaving = ref(false);

const isRunningTask = ref(false);

const taskAbortController = ref<AbortController | null>(null);
const canvasTaskControllers = new Map<string, AbortController>();

const runningTaskId = ref<string | null>(null);

const runningTaskProjectId = ref<string | null>(null);

const isStoppingTask = ref(false);
const queueMessagesByDefault = ref(localStorage.getItem('aics.queueMessagesByDefault') === 'true');
watch(queueMessagesByDefault, value => localStorage.setItem('aics.queueMessagesByDefault', String(value)));
const composerRunMode = computed(() => queueMessagesByDefault.value || intakeFiles.value.length || intakeMentionAssets.value.length || intakeSkills.value.length ? 'queue' : 'supplement');
const sendingSupplement = ref(false);

const stopRequested = ref(false);

type AgentLogEntry = { id: number; at: string; message: string; kind?: 'info' | 'success' | 'error' };

const agentLogs = ref<AgentLogEntry[]>([]);

let agentLogSequence = 0;

type TaskTraceEntry = { at?: string; phase?: string; message?: string; data?: Record<string, string | number | boolean> };

const seenTaskTraceEntries = new Set<string>();

const errorMessage = ref('');

type TaskRecord = EditedTask & { updates?: Array<{ id: string; text: string; revision: number; appliedAt?: string; createdAt: string }>; taskSurface?: 'conversation' | 'canvas_node'; canvasNodeId?: string; designBatch?: import('../../../packages/contracts/designBatches').DesignBatch; conversationMemory?: import('../../../packages/contracts/conversationMemory').ConversationMemorySnapshot; skillBindings?: import('../../../packages/contracts/skills').SkillBinding[]; designState?: { brief?: import('../../../packages/contracts/designBrief').DesignBrief; decisions?: Record<string, { label: string; value: string; status: string }> }; designPlan?: { deliverables?: Array<{ id: string; title: string; kind: string }> }; deliveryProgress?: import('./features/taskProgress').DeliveryProgress[]; references?: TaskReferenceSnapshot; id: string; userMessage?: string; agentKey: string; workflowStep?: string; status: string; output?: { next_actions?: string[]; warnings?: string[]; provenance?: Record<string, unknown>; citations?: Array<Record<string, unknown>>; usage?: { requests?: number; total_tokens?: number; input_tokens?: number; output_tokens?: number }; structured_data?: Record<string, any> } | null; error?: { message?: string } | null; trace?: TaskTraceEntry[]; mode?: string; updatedAt?: string; createdAt?: string };

const inspectedTaskId = ref<string | null>(null);
const latestTask = ref<TaskRecord | null>(null);

const taskHistory = ref<TaskRecord[]>([]);

const projectTaskStatus = ref<Record<string, string>>({});

const workspaceView = ref<WorkspaceView>('intake');

const settingsReturnPath = ref('/');

const sidebarSection = ref<'home' | 'new' | 'projects' | 'assets' | 'knowledge' | 'schedules' | 'skills' | 'workflows'>('home');

const settingsHostReady = ref(false);

const sidebarNavItems = [
  { key: 'schedules', label: '定时器' },
  { key: 'skills', label: '技能库' },
  { key: 'projects', label: '项目' },
  { key: 'workflows', label: '工作流' },
  { key: 'assets', label: '资产' },
  { key: 'knowledge', label: '参考库' },
] as const;

type DesignMessage = ConversationMessage;

const designProgress = ref('');

const designCanvasVisible = ref(localStorage.getItem('langjuart.showCanvas') !== 'false');

watch(designCanvasVisible, (visible) => localStorage.setItem('langjuart.showCanvas', String(visible)));

const designConversation = ref<DesignMessage[]>([]);
const messageEditRequest = ref<{ taskId: string; requestId: number }>();

type DesignCanvasDocument = { schemaVersion?: string; lockedNodeIds?: string[]; nodes: Array<Record<string, any>>; edges: Array<Record<string, any>> };

const designCanvasDocument = ref<DesignCanvasDocument>({ nodes: [], edges: [] });

const projectCanvasPreviews = ref<Record<string, DesignCanvasDocument>>({});

type AssetRecord = { id: string; kind: string; pathRelative: string; byteSize: number; mime?: string; projectId?: string; projectName?: string };

type ChatAssetMention = AssetRecord & { nodeId?: string };

type IntakeFileResult = { filename: string; parser?: string; warning?: string; status?: string; documentId?: string; pathRelative?: string };

type IntakeMentionOption =
  | { type: 'asset'; asset: ChatAssetMention }
  | { type: 'knowledge'; document: GlobalKnowledgeDocument }
  | { type: 'file'; file: File; index: number };

const globalAssets = ref<AssetRecord[]>([]);

const intakeMentionAssets = ref<ChatAssetMention[]>([]);
const canvasClickReferences = createCanvasClickReferences();
const confirmCanvasReferences = () => canvasClickReferences.confirm();

const intakeMentionFiles = ref<number[]>([]);

const intakeComposerRef = ref<HTMLDivElement | null>(null);

const designComposerEpoch = ref(0);

const intakeMentionQuery = ref('');

const intakeMentionStart = ref<number | null>(null);

const intakeMentionCaret = ref<number | null>(null);

const intakeMentionActiveIndex = ref(0);
const intakeSkillQuery = ref<ReturnType<typeof skillMentionQuery>>(null);
const intakeSkillMenu = ref<InstanceType<typeof SkillMentionMenu> | null>(null);
const intakeSkills = ref<SkillMention[]>([]);

const intakeName = ref('');

const intakeBrief = ref('');

const designChatInput = computed({ get: () => intakeBrief.value, set: (value: string) => { intakeBrief.value = value; } });

const intakeFiles = ref<File[]>([]);

const intakeFileResults = ref<IntakeFileResult[]>([]);

type ComposerDraft = { text: string; files: File[]; results: IntakeFileResult[]; assets: ChatAssetMention[]; mentionedFiles: number[]; skills?: SkillMention[] };
const composerDrafts = new ComposerDraftStore<ComposerDraft>();
type QueuedMessage = QueuedComposerMessage<ComposerDraft>;
const queuedMessageStore = new ComposerDraftStore<QueuedMessage[]>();
type PendingTaskRequest = { requestId: string; signature: string };
const pendingTaskRequests = new ComposerDraftStore<PendingTaskRequest>();
const queuedMessagesByProject = ref<Record<string, QueuedMessage[]>>({});
const loadedMessageQueues = new Set<string>();
const loadingMessageQueues = new Map<string, Promise<QueuedMessage[]>>();
const dispatchingMessageQueues = new Set<string>();
const queuedMessageDragId = ref<string | null>(null);
const queueStorageKey = (projectId: string) => `message-queue:${projectId}`;
const activeQueuedMessages = computed(() => activeProjectId.value ? queuedMessagesByProject.value[activeProjectId.value] || [] : []);
const activeQueuePauseReason = computed(() => queuePauseReason(latestTask.value ? queueTaskResult(latestTask.value) : null));
const editingQueuedMessage = ref<string | null>(null);
const queuedEditText = ref('');

function setQueuedMessages(projectId: string, messages: QueuedMessage[]) {
  queuedMessagesByProject.value = { ...queuedMessagesByProject.value, [projectId]: messages };
}

async function loadQueuedMessages(projectId: string): Promise<QueuedMessage[]> {
  if (loadedMessageQueues.has(projectId)) return queuedMessagesByProject.value[projectId] || [];
  const existing = loadingMessageQueues.get(projectId);
  if (existing) return existing;
  const operation = queuedMessageStore.load(queueStorageKey(projectId))
    .then(messages => {
      const loaded = Array.isArray(messages) ? messages : [];
      setQueuedMessages(projectId, loaded);
      loadedMessageQueues.add(projectId);
      return loaded;
    })
    .finally(() => loadingMessageQueues.delete(projectId));
  loadingMessageQueues.set(projectId, operation);
  return operation;
}

function persistQueuedMessages(projectId: string, messages: QueuedMessage[]) {
  loadedMessageQueues.add(projectId);
  setQueuedMessages(projectId, messages);
  return messages.length
    ? queuedMessageStore.save(queueStorageKey(projectId), messages)
    : queuedMessageStore.remove(queueStorageKey(projectId));
}

watch(activeProjectId, projectId => { if (projectId) void loadQueuedMessages(projectId); }, { immediate: true });
const draftSaveLabel = ref('');
let composerDraftKey = 'home';
let draftHydrating = false;
let draftActivation = 0;
let draftRevision = 0;
const snapshotComposerDraft = (): ComposerDraft => ({ text: intakeBrief.value, files: [...intakeFiles.value], results: JSON.parse(JSON.stringify(intakeFileResults.value)), assets: JSON.parse(JSON.stringify(intakeMentionAssets.value)), mentionedFiles: [...intakeMentionFiles.value], skills: selectedSkillMentions(intakeBrief.value, intakeSkills.value) });
function applyComposerDraft(draft?: ComposerDraft) {
  confirmCanvasReferences();
  draftHydrating = true;
  intakeBrief.value = draft?.text || '';
  intakeFiles.value = draft?.files || [];
  intakeFileResults.value = draft?.results || [];
  intakeMentionAssets.value = draft?.assets || [];
  intakeMentionFiles.value = draft?.mentionedFiles || [];
  intakeSkills.value = draft?.skills || [];
  intakeSkillQuery.value = null;
  draftHydrating = false;
}
function saveComposerDraft() {
  if (draftHydrating) return;
  const key = composerDraftKey, draft = snapshotComposerDraft(), revision = ++draftRevision;
  draftSaveLabel.value = '保存草稿中…';
  const persist = draft.text || draft.files.length || draft.assets.length ? composerDrafts.save(key, draft) : composerDrafts.remove(key);
  void persist.then(() => { if (key === composerDraftKey && revision === draftRevision) draftSaveLabel.value = draft.text || draft.files.length ? '草稿已保存' : ''; })
    .catch(() => { if (key === composerDraftKey) draftSaveLabel.value = '草稿暂未保存到磁盘，请保留当前页面'; });
}
async function activateComposerDraft(projectId: string | null) {
  const key = projectId || 'home';
  if (key !== composerDraftKey) saveComposerDraft();
  composerDraftKey = key;
  const activation = ++draftActivation;
  applyComposerDraft();
  const revision = draftRevision;
  draftSaveLabel.value = '';
  try {
    const draft = await composerDrafts.load(key);
    if (activation !== draftActivation || revision !== draftRevision) return;
    applyComposerDraft(draft);
    draftSaveLabel.value = draft ? '已恢复草稿' : '';
  } catch { if (activation === draftActivation) draftSaveLabel.value = '暂时无法读取本地草稿'; }
}
watch([intakeBrief, intakeFiles, intakeFileResults, intakeMentionAssets, intakeMentionFiles, intakeSkills], saveComposerDraft, { deep: true, flush: 'sync' });

const isCreatingIntake = ref(false);

const intakeReady = ref(false);

const isIntakeComposerComposing = ref(false);

const intakeFileInput = ref<HTMLInputElement | null>(null);

const intakeRequestTimeoutMs = 12_000;

const agentDisplayTitle = (_agentKey: string) => '设计 Agent';

const taskQueue = createTaskQueue(projects, projectId => request<TaskRecord[]>(`/api/projects/${projectId}/tasks`), () => request<QueueTask[]>('/api/tasks/activity'), notifyTaskFinished);
function notifyTaskFinished(task: QueueTask) {
  if (!generalSettings.notifications || (!document.hidden && document.hasFocus() && activeProjectId.value === task.projectId && workspaceView.value === 'design-agent')) return;
  const data = task.output?.structured_data || {};
  const needsInput = data.clarification?.questions?.length || (data.referenceSelection?.items?.length && data.referenceSelection.status === 'pending' && !data.referenceSelection.submittedAction);
  const state = task.status === 'failed' ? '任务未完成，请查看原因' : needsInput ? '任务需要补充信息' : data.deliveryStatus && data.deliveryStatus !== 'passed' ? '任务有待处理事项' : '任务已完成';
  const title = projects.value.find(project => project.id === task.projectId)?.name || 'MxinspireX';
  pushToast(`${title}：${state}`, task.status === 'failed' ? 'error' : 'info');
  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try {
      const notification = new Notification(title, { body: state, tag: `task:${task.id}` });
      notification.onclick = () => { window.focus(); void selectProject(task.projectId); notification.close(); };
    } catch { /* The in-app notification remains available. */ }
  }
}
const activeQueueTasks = computed(() => taskQueue.activeTasks.value.filter(task => task.status === 'running'));
const taskQueueCount = computed(() => activeQueueTasks.value.length);
const taskQueueLabel = computed(() => taskQueueCount.value ? `正在运行的任务 · ${taskQueueCount.value}` : '当前没有正在运行的任务');
const taskFocus = ref<{ projectId: string; taskId: string; nodeId?: string; requestId: number }>();
let taskFocusSequence = 0;
let taskQueueTimer: number | undefined;
watch(projects, () => { void taskQueue.refresh().catch(() => undefined); });

function openQueueTask(task: QueueTask) {
  if (!projects.value.some(project => project.id === task.projectId)) {
    pushToast('该任务所属项目已不存在。', 'info');
    return;
  }
  showAssistantCard.value = false;
  taskFocus.value = { projectId: task.projectId, taskId: task.id, nodeId: task.canvasNodeId, requestId: ++taskFocusSequence };
  if (activeProjectId.value !== task.projectId) selectProject(task.projectId);
  else {
    // Returning from a library or revealing a collapsed chat is navigation;
    // retain the current task stream, draft and canvas.
    sidebarSection.value = 'projects';
    workspaceView.value = 'design-agent';
  }
}

function openTaskQueue() {
  showAssistantCard.value = !showAssistantCard.value;
  if (showAssistantCard.value) { showComposerAgentMenu.value = false; showComposerStyleMenu.value = false; }
}

const reduceAnimations = ref(localStorage.getItem('langjuart.reduceAnimations') === 'true');
watch(reduceAnimations, value => { localStorage.setItem('langjuart.reduceAnimations', String(value)); document.documentElement.dataset.reduceAnimations = String(value); }, { immediate: true });
const allowExternalNetwork = ref(localStorage.getItem('aics.allowExternalNetwork') !== 'false');

const leftPanelWidth = ref(Number(localStorage.getItem('langjuart.sidebarWidth') || 238));

const isResizingSidebar = ref(false);

const pendingDeleteProjectId = ref<string | null>(null);

const pendingDeleteAsset = ref<AssetRecord | null>(null);

type PendingDeleteKnowledge = { id: string; title: string; scope: 'global' | 'project'; projectId?: string };

const pendingDeleteKnowledge = ref<PendingDeleteKnowledge | null>(null);

const isDeletingAsset = ref(false);

const isDeletingKnowledge = ref(false);

const userNickname = ref(localStorage.getItem('langjuart.userNickname') || 'Avery Chen');

const userBio = ref(localStorage.getItem('langjuart.userBio') || '用文化线索做当代产品，让每个灵感都能落地。');

const userAvatarIndex = ref(Number(localStorage.getItem('langjuart.userAvatarIndex') || 0));

const userProfileSaving = ref(false);

const userAvatarOptions = [
  { index: 0, label: '初见', position: '0% 0%' },
  { index: 1, label: '探索', position: '50% 0%' },
  { index: 2, label: '悦动', position: '100% 0%' },
  { index: 3, label: '博识', position: '0% 50%' },
  { index: 4, label: '灵感', position: '50% 50%' },
  { index: 5, label: '专注', position: '100% 50%' },
  { index: 6, label: '开怀', position: '0% 100%' },
  { index: 7, label: '好奇', position: '50% 100%' },
  { index: 8, label: '悠然', position: '100% 100%' },
] as const;

const activeAvatarOption = computed(() => userAvatarOptions[userAvatarIndex.value] ?? userAvatarOptions[0]);

const showUserSummary = ref(false);
const userSummaryButton = ref<HTMLButtonElement | null>(null);
const userSummaryCard = ref<HTMLElement | null>(null);

function closeUserSummary(restoreFocus = false) {
  showUserSummary.value = false;
  if (restoreFocus) userSummaryButton.value?.focus();
}

async function toggleUserSummary() {
  showUserSummary.value = !showUserSummary.value;
  if (!showUserSummary.value) return;
  showAssistantCard.value = false;
  showComposerAgentMenu.value = false;
  showComposerStyleMenu.value = false;
  void refreshTokenUsageFromWorkspace();
  await nextTick();
  userSummaryCard.value?.focus({ preventScroll: true });
}

const showAssistantCard = ref(false);
const taskQueueAnchor = ref<HTMLElement | null>(null);

const isDeletingProject = ref(false);

const knowledgeDocs = ref<Array<{ id: string; title: string; pathRelative: string; status: string }>>([]);

type GlobalKnowledgeDocument = { id: string; title: string; pathRelative: string; status: string; parser?: string; warning?: string | null; chunkCount?: number; parserVersion?: number; pageCount?: number; imageCount?: number; partCount?: number; createdAt?: string; checksum?: string; scope?: 'global' | 'project' };

const globalKnowledgeDocs = ref<GlobalKnowledgeDocument[]>([]);

const isUploadingGlobalKnowledge = ref(false);

const isReindexingGlobalKnowledge = ref(false);

type DesignSearchResult = { title: string; url: string; snippet?: string; domain?: string; image?: string | null; imageSource?: 'network' | null };

const researchSearchResults = ref<DesignSearchResult[]>([]);

const failedReferenceImages = ref<Set<string>>(new Set());

const providers = ref<Array<{ key: string; kind: string; label: string; configured: boolean; requiresKey?: boolean; local?: boolean; capabilities?: string[]; defaultBaseUrl?: string | null; defaultModel?: string | null; credentialHint?: string | null; catalogCredentialConfigured?: boolean; catalogCredentialHint?: string | null }>>([]);

const assets = ref<Array<{ id: string; kind: string; pathRelative: string; byteSize: number; mime?: string }>>([]);

const imageStyle = ref(localStorage.getItem('aics.imageStyle') || '智能识别');

const imageProvider = ref(localStorage.getItem('aics.imageProvider') || 'openai-image');

const imageModel = ref(localStorage.getItem('aics.imageModel')?.trim() || '');

const threeDProvider = ref(localStorage.getItem('aics.threeDProvider') || 'auto');

const threeDEndpoint = ref(localStorage.getItem('aics.threeDEndpoint') || '');

const renderProvider = ref('openai-image');

const renderModel = ref('');

const videoProvider = ref(localStorage.getItem('aics.videoProvider') || 'openrouter');

const videoModel = ref(localStorage.getItem('aics.videoModel') || '');

const audioModel = ref(localStorage.getItem('aics.audioModel') || '');

const videoEndpoint = ref(localStorage.getItem('aics.videoEndpoint') || '');

const defaultOpenRouterBaseUrl = 'https://openrouter.ai/api/v1';
const defaultEvoLinkBaseUrl = 'https://api.evolink.ai/v1';

type SavedProviderProfile = {
  providerKey: string;
  baseUrl: string;
  textModel: string;
  imageModel: string;
  videoModel?: string;
  threeDModel?: string;
  models: string[];
  textModels: string[];
  imageModels: string[];
  modelCatalog: DetectedModel[];
  detectedAt?: string;
};

function readStoredRecord<T extends Record<string, any>>(key: string): T {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value as T : {} as T;
  } catch {
    return {} as T;
  }
}

function normalizeStringArray(value: unknown) {
  return Array.isArray(value) ? [...new Set(value.map(String).map((item) => item.trim()).filter(Boolean))] : [];
}

function normalizeModelCatalog(value: unknown): DetectedModel[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, any> => Boolean(item && typeof item === 'object' && !Array.isArray(item) && String(item.id || '').trim()))
    .map((item) => ({
      id: String(item.id).trim(),
      name: item.name ? String(item.name) : undefined,
      ownedBy: item.ownedBy ? String(item.ownedBy) : null,
      kind: item.kind ? String(item.kind) : undefined,
      kinds: normalizeStringArray(item.kinds),
      modality: item.modality ? String(item.modality) : null,
      inputModalities: normalizeStringArray(item.inputModalities),
      outputModalities: normalizeStringArray(item.outputModalities),
      supportedParameters: normalizeStringArray(item.supportedParameters),
      contextLength: Number.isFinite(Number(item.contextLength)) ? Number(item.contextLength) : null,
      description: item.description ? String(item.description) : null,
      created: Number.isFinite(Number(item.created)) ? Number(item.created) : null,
      pricing: item.pricing && typeof item.pricing === 'object' && !Array.isArray(item.pricing) ? item.pricing as Record<string, unknown> : null,
      category: typeof item.category === 'string' || Array.isArray(item.category) ? item.category : null,
      providerCategory: typeof item.providerCategory === 'string' || Array.isArray(item.providerCategory) ? item.providerCategory : null,
      catalogSource: item.catalogSource ? String(item.catalogSource) : null,
    }));
}

function normalizeSavedProviderProfile(providerKey: string, value: unknown): SavedProviderProfile | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const item = value as Record<string, any>;
  return {
    providerKey,
    baseUrl: providerKey === 'evolink' ? defaultEvoLinkBaseUrl : String(item.baseUrl || '').trim(),
    textModel: String(item.textModel || '').trim(),
    imageModel: String(item.imageModel || '').trim(),
    videoModel: String(item.videoModel || '').trim(),
    threeDModel: String(item.threeDModel || '').trim(),
    models: normalizeStringArray(item.models),
    textModels: normalizeStringArray(item.textModels),
    imageModels: normalizeStringArray(item.imageModels),
    modelCatalog: normalizeModelCatalog(item.modelCatalog),
    detectedAt: item.detectedAt ? String(item.detectedAt) : undefined,
  };
}

const persistedTextProvider = localStorage.getItem('aics.textProvider') || '';

const persistedCredentialProvider = localStorage.getItem('aics.credentialProvider') || '';

const selectedTextProvider = ref(persistedCredentialProvider || persistedTextProvider || 'openrouter');

const activeTextProvider = computed(() => providers.value.some((provider) => provider.key === selectedTextProvider.value && provider.configured) ? selectedTextProvider.value : '');


const selectedCredentialProvider = ref(persistedCredentialProvider || persistedTextProvider || 'openrouter');

const credentialProviderOptions = computed(() => {
  const available = providers.value.filter((provider) => provider.kind === 'llm' && ['openrouter', 'evolink', 'openai-compatible', 'ollama'].includes(provider.key));
  return available.length
    ? available
    : [
        { key: 'openrouter', kind: 'llm', label: 'OpenRouter · 多模型路由', configured: false, requiresKey: true, defaultBaseUrl: defaultOpenRouterBaseUrl },
        { key: 'evolink', kind: 'llm', label: 'EvoLink · 文本 / 图像 / 视频 / 语音', configured: false, requiresKey: true, defaultBaseUrl: defaultEvoLinkBaseUrl },
        { key: 'openai-compatible', kind: 'llm', label: '中转站（OpenAI Compatible）', configured: false, requiresKey: true, defaultBaseUrl: 'https://api.openai-proxy.org/v1' },
        { key: 'ollama', kind: 'llm', label: 'Ollama · 本地模型', configured: true, requiresKey: false, local: true, defaultBaseUrl: 'http://127.0.0.1:11434/v1', defaultModel: 'gpt-oss:20b' },
      ];
});

const providerProfiles = ref<Record<string, SavedProviderProfile>>(readStoredRecord('aics.providerProfiles'));
const supplementalMedia = ref<Record<string, Partial<Record<'image' | 'video' | 'audio', string>>>>(readStoredRecord('aics.supplementalMedia'));
const mediaKinds = ['image', 'video', 'audio'] as const;
const mediaLabels = { image: '图像', video: '视频', audio: '音频' };
const supplementalScope = () => `${credentialTargetProvider.value}:${providerBaseUrl.value.trim().replace(/\/+$/, '')}`;
function setSupplementalMedia(kind: 'image' | 'video' | 'audio', value: string) {
  supplementalMedia.value = { ...supplementalMedia.value, [supplementalScope()]: { ...supplementalMedia.value[supplementalScope()], [kind]: value } };
  localStorage.setItem('aics.supplementalMedia', JSON.stringify(supplementalMedia.value));
}
function profileMediaModels(profile: SavedProviderProfile, kind: 'image' | 'video' | 'audio' | '3d') {
  const ids = kind === 'image' ? profile.imageModels : profile.modelCatalog.filter(model => model.kinds?.includes(kind) || model.kind === kind).map(model => model.id);
  return ids.filter(id => profile.models.includes(id));
}
function supplementalChoices(kind: 'image' | 'video' | 'audio') {
  return providers.value.filter(provider => provider.key !== credentialTargetProvider.value && provider.configured && !provider.local && profileForProvider(provider.key)?.baseUrl && profileMediaModels(profileForProvider(provider.key)!, kind).length);
}

const profileForProvider = (providerKey: string) => normalizeSavedProviderProfile(providerKey, providerProfiles.value[providerKey]);

function savedRemoteMediaProvider(kind: 'image' | 'video' | 'audio' | '3d') {
  const selected = kind === '3d' ? undefined : supplementalMedia.value[supplementalScope()]?.[kind];
  const preferred = selected ? [selected] : isOllamaProvider.value ? [imageProvider.value, 'openrouter', 'evolink', 'openai-compatible'] : [];
  const key = [...new Set(preferred)].find((candidate) => {
    const spec = providers.value.find((provider) => provider.key === candidate);
    const profile = profileForProvider(candidate);
    if (!spec?.configured || spec.local || !profile?.baseUrl) return false;
    return profileMediaModels(profile, kind).length > 0;
  });
  return key ? { key, profile: profileForProvider(key)! } : undefined;
}

function taskMediaProvider(kind: 'image' | 'video' | 'audio') {
  const textKey = activeTextProvider.value || selectedTextProvider.value;
  const textSpec = providers.value.find((provider) => provider.key === textKey);
  const supplemental = useSupplementalProvider(liveModelCatalog.status.value, liveModelCatalog.data.value[kind], supplementalMedia.value[supplementalScope()]?.[kind]);
  if (!textSpec?.local && !supplemental) {
    return kind === 'video'
      ? { key: textKey, endpoint: providerBaseUrl.value, model: videoModel.value, manual: videoModelManual.value }
      : kind === 'image'
        ? { key: textKey, baseUrl: providerBaseUrl.value, model: imageModel.value, manual: imageModelManual.value }
        : { key: textKey, baseUrl: providerBaseUrl.value, model: audioModel.value };
  }
  const remote = savedRemoteMediaProvider(kind);
  if (!remote) {
    return kind === 'video'
      ? { key: textKey, endpoint: providerBaseUrl.value, model: videoModel.value, manual: videoModelManual.value }
      : kind === 'image'
        ? { key: textKey, baseUrl: providerBaseUrl.value, model: imageModel.value, manual: imageModelManual.value }
        : { key: textKey, baseUrl: providerBaseUrl.value, model: audioModel.value };
  }
  const { key: remoteKey, profile } = remote;
  const options = profileMediaModels(profile, kind);
  const selectedModel = kind === 'image' ? imageModel.value : kind === 'video' ? videoModel.value : audioModel.value;
  const savedModel = options.includes(selectedModel) ? selectedModel : kind === 'image' ? profile.imageModel : kind === 'video' ? profile.videoModel || '' : '';
  const model = selectAvailableModel(savedModel, options);
  return kind === 'video'
    ? { key: remoteKey, endpoint: profile.baseUrl, model, manual: Boolean(savedModel) }
    : kind === 'image'
      ? { key: remoteKey, baseUrl: profile.baseUrl, model, manual: Boolean(savedModel) }
      : { key: remoteKey, baseUrl: profile.baseUrl, model };
}

const storedProviderProfile = profileForProvider(selectedCredentialProvider.value);

const storedBaseUrl = localStorage.getItem('aics.providerBaseUrl') || '';

const providerBaseUrl = ref(
  selectedCredentialProvider.value === 'evolink' ? defaultEvoLinkBaseUrl
    : (storedProviderProfile?.baseUrl && !(selectedCredentialProvider.value === 'openrouter' && storedProviderProfile.baseUrl.includes('api.openai-proxy.org')) ? storedProviderProfile.baseUrl : '')
    || (selectedCredentialProvider.value === 'openrouter' && (!storedBaseUrl || storedBaseUrl.includes('api.openai-proxy.org')) ? defaultOpenRouterBaseUrl : storedBaseUrl)
    || providerDefaultBaseUrl(selectedCredentialProvider.value),
);

const providerModel = ref(storedProviderProfile?.textModel || localStorage.getItem('aics.providerModel') || '');

const providerSecret = ref('');

const closeAICatalogSecret = ref('');

const providerTestResult = ref('');

const isProviderSettingsOpen = computed(() => workspaceView.value === 'settings');

const isSavingProvider = ref(false);

const settingsTab = ref<SettingsSection>('account');

type RuntimeComponentState = { id: string; label: string; description: string; installed: boolean; available: boolean; bytes: number; source: 'download' | 'file' };
const runtimeComponents = ref<RuntimeComponentState[]>([]);
const runtimeComponentLoading = ref('');
const runtimeComponentMessage = ref('');

const mediaDefaults = ref({ image: { draft: DEFAULT_DRAFT_IMAGE_MODEL, standard: DEFAULT_IMAGE_MODEL, final: DEFAULT_IMAGE_MODEL }, video: DEFAULT_VIDEO_MODEL });

const imageModelManual = ref(localStorage.getItem('aics.imageModelManual') === 'true' || (localStorage.getItem('aics.imageModelManual') === null && Boolean(imageModel.value) && !/^(openai\/)?gpt-image-(?:1|2|2\.5-flare|2\.5-sunburst)$/.test(imageModel.value)));

const videoModelManual = ref(localStorage.getItem('aics.videoModelManual') === 'true' || (localStorage.getItem('aics.videoModelManual') === null && Boolean(videoModel.value) && !['seedream-video', DEFAULT_VIDEO_MODEL].includes(videoModel.value)));

function setMediaOverride(kind: 'image' | 'video') {
  if (kind === 'image') imageModelManual.value = true;
  else videoModelManual.value = true;
  localStorage.setItem(`aics.${kind}ModelManual`, 'true');
}

const routingMode = ref<RoutingMode>((localStorage.getItem('aics.routingMode') as RoutingMode) || 'auto');

watch(routingMode, (mode) => localStorage.setItem('aics.routingMode', mode));

const routingLabel = computed(() => routingChoices.find((choice) => choice.id === routingMode.value)?.label || '手动模型');

const credentialTargetProvider = computed(() => selectedCredentialProvider.value || 'openrouter');

const selectedProviderStatus = computed(() => providers.value.find((provider) => provider.key === credentialTargetProvider.value));

const selectedProviderRequiresKey = computed(() => selectedProviderStatus.value?.requiresKey !== false);

const isOllamaProvider = computed(() => credentialTargetProvider.value === 'ollama');

const selectedProviderCredentialHint = computed(() => selectedProviderStatus.value?.credentialHint || '');

const isCloseAIEndpoint = computed(() => {
  if (credentialTargetProvider.value !== 'openai-compatible') return false;
  try {
    const hostname = new URL(providerBaseUrl.value.trim()).hostname.toLowerCase();
    return hostname === 'api.openai-proxy.org' || hostname.endsWith('.openai-proxy.org');
  } catch { return false; }
});

const closeAICatalogCredentialHint = computed(() => selectedProviderStatus.value?.catalogCredentialHint || '');

const liveModelCatalog = createProviderModelCatalog((source, signal) => request<ModelCatalogResponse>(
  '/api/providers/openai-compatible/detect', { method: 'POST', signal, body: JSON.stringify(source) },
));

const detectedAllModels = computed(() => liveModelCatalog.data.value.models);

const detectedModelCatalog = computed(() => liveModelCatalog.data.value.catalog);

const detectedTextModels = computed(() => liveModelCatalog.data.value.text);

const detectedImageModels = computed(() => liveModelCatalog.data.value.image);

const textModelOptions = detectedTextModels;

function effectiveMediaOptions(kind: 'image' | 'video' | 'audio') {
  const primary = liveModelCatalog.data.value[kind];
  if (!isOllamaProvider.value && !useSupplementalProvider(liveModelCatalog.status.value, primary, supplementalMedia.value[supplementalScope()]?.[kind])) return primary;
  const remote = savedRemoteMediaProvider(kind);
  return remote ? profileMediaModels(remote.profile, kind) : [];
}
const imageModelOptions = computed(() => effectiveMediaOptions('image'));
const videoModelOptions = computed(() => effectiveMediaOptions('video'));
const audioModelOptions = computed(() => effectiveMediaOptions('audio'));

const threeDModelOptions = computed(() => isOllamaProvider.value
  ? savedRemoteMediaProvider('3d')?.profile.modelCatalog.filter((model) => model.kinds?.includes('3d') || model.kind === '3d').map((model) => model.id) || []
  : liveModelCatalog.data.value.threeD);

const unknownModelOptions = computed(() => liveModelCatalog.data.value.unknown);

const isDetectingModels = liveModelCatalog.loading;

const hasDetectedModelCatalog = computed(() => liveModelCatalog.status.value === 'ready' || detectedAllModels.value.length > 0);

const modelCatalogMessage = computed(() => {
  if (isDetectingModels.value) return isOllamaProvider.value ? '正在读取本机 Ollama 模型列表…' : '正在从服务商 API 读取模型列表…';
  if (liveModelCatalog.error.value) return liveModelCatalog.error.value;
  if (!hasDetectedModelCatalog.value) return isOllamaProvider.value ? '请确认 Ollama 已启动，然后同步本机模型列表。' : credentialTargetProvider.value === 'evolink' ? '请在设置中保存 EvoLink API Key 并同步目录，即可选择文本、图像、视频和已接入的语音模型。' : '请配置服务地址和 API Key，然后同步模型列表。';
  if (isOllamaProvider.value) {
    const remote = savedRemoteMediaProvider('image') || savedRemoteMediaProvider('video') || savedRemoteMediaProvider('audio');
    return `本机 Ollama 已同步 ${textModelOptions.value.length} 个文本模型。${remote ? `媒体继续使用已保存的 ${remote.key} 目录。` : '尚未配置远程媒体服务。'}`;
  }
  const missing = liveModelCatalog.data.value.unavailable;
  const coverage = liveModelCatalog.data.value.coverage === 'complete' ? '完整目录' : liveModelCatalog.data.value.coverage === 'partial' ? '兼容目录（可能不完整）' : '标准目录';
  const warnings = liveModelCatalog.data.value.warnings;
  const routeAvailability = liveModelCatalog.data.value.routeAvailability;
  return `本地已保存 ${detectedAllModels.value.length} 个模型（${coverage}）：文本 ${textModelOptions.value.length} 个、图像 ${imageModelOptions.value.length} 个、视频 ${videoModelOptions.value.length} 个、音频 ${audioModelOptions.value.length} 个、3D ${threeDModelOptions.value.length} 个、待识别 ${unknownModelOptions.value.length} 个。`
    + (missing.length ? ` 中转站尚未确认这些默认模型：${missing.join('、')}。` : '')
    + (routeAvailability && !routeAvailability.autoReady ? ` 自动路由缺少档位：${routeAvailability.missingTiers.join('、')}。` : '')
    + (warnings.length ? ` ${warnings.join(' ')}` : '');
});

const settingsCatalogMessage = computed(() => {
  if (isDetectingModels.value) return '正在同步模型目录…';
  if (liveModelCatalog.error.value) return liveModelCatalog.error.value;
  if (!hasDetectedModelCatalog.value) return '尚未同步模型目录。保存后可在首页选择可用模型。';
  if (isOllamaProvider.value) return `已同步 ${textModelOptions.value.length} 个本机文本模型；当前为手动模型模式，本地运行不产生 API 费用。`;
  const coverage = liveModelCatalog.data.value.coverage === 'complete' ? '完整目录' : liveModelCatalog.data.value.coverage === 'partial' ? '兼容目录' : '标准目录';
  const warnings = liveModelCatalog.data.value.warnings;
  return `已同步 ${detectedAllModels.value.length} 个模型（${coverage}），已按输出类型分类；待识别 ${unknownModelOptions.value.length} 个。${warnings.length ? ` ${warnings.join(' ')}` : ''}`;
});

const modelConnection = computed(() => {
  if (isDetectingModels.value) return 'checking';
  if (!providers.value.length || liveModelCatalog.status.value === 'error') return 'unavailable';
  if (!activeTextProvider.value) return 'unconfigured';
  if (routingMode.value !== 'manual' && liveModelCatalog.data.value.routeAvailability && !liveModelCatalog.data.value.routeAvailability?.autoReady) return 'unverified';
  return hasDetectedModelCatalog.value && (routingMode.value !== 'manual' ? textModelOptions.value.length > 0 : textModelOptions.value.includes(providerModel.value)) ? 'connected' : 'unverified';
});

const modelConnectionHint = computed(() => liveModelCatalog.error.value
  || (activeTextProvider.value && routingMode.value !== 'manual' && liveModelCatalog.data.value.routeAvailability && !liveModelCatalog.data.value.routeAvailability.autoReady
    ? `Provider 已连接，但自动路由缺少：${liveModelCatalog.data.value.routeAvailability.missingTiers.join('、')}` : '')
  || ({
  checking: '正在读取模型目录', connected: '使用已保存的本地模型目录',
  unconfigured: '模型尚未配置 API Key', unavailable: localServiceHint,
  unverified: '尚未从 API 获取可用的文本模型',
}[modelConnection.value]));

let localCatalogSequence = 0;

const settingsTabs = [
  { key: 'general', label: '常规设置', icon: 'G' },
  { key: 'account', label: '用户中心', icon: 'U' },
  { key: 'text', label: '模型与连接', icon: 'T' },
  { key: 'routing', label: '用量与计费', icon: '⇄' },
  { key: 'appearance', label: '外观', icon: '◐' },
  { key: 'components', label: '能力组件', icon: '□' },
  { key: 'about', label: '关于', icon: 'i' },
  { key: 'help', label: '使用说明', icon: '?' },
] as const;

const threeDConfigProvider = ref(localStorage.getItem('aics.threeDProvider') || 'auto');

const threeDConfigEndpoint = ref(localStorage.getItem('aics.threeDEndpoint') || '');

const threeDConfigModel = ref(localStorage.getItem('aics.threeDModel') || '');

const videoConfigProvider = ref(localStorage.getItem('aics.videoProvider') || 'openrouter');

const videoConfigEndpoint = ref(localStorage.getItem('aics.videoEndpoint') || '');

const videoConfigModel = ref(localStorage.getItem('aics.videoModel') || '');

const storedTheme = localStorage.getItem('langjuart.theme');

const themeMode = ref<'system' | 'dark' | 'light'>(storedTheme === 'dark' || storedTheme === 'light' || storedTheme === 'system' ? storedTheme : 'system');

const resolvedTheme = ref<'dark' | 'light'>(window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

const brandLogoSrc = computed(() => `${import.meta.env.BASE_URL}assets/mxinspirex-app-icon-${resolvedTheme.value}.png`);

const tokenUsageByDay = computed(() => creditSummary.value?.tokenByDay || {});
const creditPending = computed(() => creditSummary.value?.awaitingReconciliation || 0);

let tokenClockTimer: number | null = null;

let tokenUsageRefreshTimer: number | null = null;

let tokenUsageRefreshInFlight = false;

const tokenNow = ref(new Date());

const tokenHeatmap = computed(() => {
  const max = Math.max(1, ...Object.values(tokenUsageByDay.value));
  return Array.from({ length: 30 }, (_, index) => {
  const date = new Date(tokenNow.value);
  date.setDate(date.getDate() - (29 - index));
  const key = formatTokenDate(date);
  const value = tokenUsageByDay.value[key] || 0;
  const ratio = value / max;
  return { key, value, level: value === 0 ? 0 : ratio <= 0.25 ? 1 : ratio <= 0.5 ? 2 : ratio <= 0.75 ? 3 : 4 };
  });
});

const formatTokenDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const tokenLevel = (value: number, max: number) => {
  if (!value) return 0;
  const ratio = value / Math.max(1, max);
  return ratio <= 0.25 ? 1 : ratio <= 0.5 ? 2 : ratio <= 0.75 ? 3 : 4;
};

const monthlyTokenHeatmap = computed(() => {
  const now = new Date(tokenNow.value);
  const year = now.getFullYear();
  const month = now.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstWeekday = new Date(year, month, 1).getDay();
  const totalCells = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
  const values = Array.from({ length: daysInMonth }, (_, index) => tokenUsageByDay.value[formatTokenDate(new Date(year, month, index + 1))] || 0);
  const max = Math.max(1, ...values);
  return Array.from({ length: totalCells }, (_, index) => {
    const day = index - firstWeekday + 1;
    if (day < 1 || day > daysInMonth) return { key: `empty-${index}`, day: null, value: 0, level: 0, label: '' };
    const date = new Date(year, month, day);
    const key = formatTokenDate(date);
    const value = tokenUsageByDay.value[key] || 0;
    return { key, day, value, level: tokenLevel(value, max), label: `${month + 1}月${day}日` };
  });
});

const monthlyTokenTotal = computed(() => monthlyTokenHeatmap.value.reduce((total, day) => total + day.value, 0));

const weeklyTokenUsage = computed(() => {
  const now = new Date(tokenNow.value);
  const values = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(now);
    date.setHours(0, 0, 0, 0);
    date.setDate(now.getDate() - (6 - index));
    const key = formatTokenDate(date);
    return { key, label: `${date.getMonth() + 1}/${date.getDate()}`, weekday: ['日', '一', '二', '三', '四', '五', '六'][date.getDay()], value: tokenUsageByDay.value[key] || 0 };
  });
  const max = Math.max(1, ...values.map((day) => day.value));
  return values.map((day) => ({ ...day, height: day.value ? Math.max(8, Math.round((day.value / max) * 100)) : 4 }));
});

const weeklyTokenTotal = computed(() => weeklyTokenUsage.value.reduce((total, day) => total + day.value, 0));

const recentTokenTotal = computed(() => tokenHeatmap.value.reduce((total, day) => total + day.value, 0));

function formatTokenUsage(tokens: number) {
  const value = Math.max(0, Number(tokens) || 0);
  if (value < 1_000) return formatTokens(value);
  const units = value >= 100_000_000
    ? { divisor: 100_000_000, suffix: '亿' }
    : value >= 10_000
      ? { divisor: 10_000, suffix: 'W' }
      : { divisor: 1_000, suffix: 'K' };
  const compact = value / units.divisor;
  const digits = compact >= 100 ? 0 : compact >= 10 ? 1 : 1;
  return `${compact.toFixed(digits).replace(/\.0+$|(?<=\.\d)0+$/, '')}${units.suffix}`;
}

const showComposerAgentMenu = ref(false);
const composerModelButton = ref<HTMLButtonElement | null>(null);

const showComposerStyleMenu = ref(false);

const agentModelTab = ref<'text' | 'image' | 'video' | 'audio'>('text');

const agentModelTabs = [
  { key: 'text', label: '文本' },
  { key: 'image', label: '图像' },
  { key: 'video', label: '视频' },
  { key: 'audio', label: '音频' },
] as const;

const aboutClicks = ref(0);

const confettiUnlocked = ref(false);

let confettiLoader: Promise<void> | null = null;
let confettiSession = 0;

watch(isProviderSettingsOpen, open => {
  if (open) return;
  confettiSession += 1;
  aboutClicks.value = 0;
  confettiUnlocked.value = false;
  (window as unknown as { confetti?: ConfettiFn }).confetti?.reset?.();
}, { flush: 'sync' });

const showAhaMoment = ref(false);

type UnlockedAchievement = {
  id: string;
  title: string;
  description: string;
  milestone: number;
  imageGenerationCount: number;
};

const unlockedAchievement = ref<UnlockedAchievement | null>(null);
let achievementRefreshRunning = false;

const composerPlaceholders = designComposerPlaceholders;

const activePlaceholderIndex = ref(0);

const intakeFilePreviews = ref<Record<string, string>>({});

let placeholderTimer: number | undefined;

type Toast = { id: number; kind: 'success' | 'error' | 'info'; message: string };

const toasts = ref<Toast[]>([]);

let toastSequence = 0;

// The old firstUseCompleted flag was consumed at intake creation, even when
// no request reached MxinspireX. Track the actual first accepted request separately.
const firstRequestCelebrationKey = 'langjuart.firstRequestCelebrated';
const firstUseCompleted = ref(localStorage.getItem(firstRequestCelebrationKey) === 'true');

const clientSessionId = ref(localStorage.getItem('langjuart.clientSessionId') || crypto.randomUUID());

localStorage.setItem('langjuart.clientSessionId', clientSessionId.value);

const greetingName = computed(() => userNickname.value.trim() || 'Avery Chen');

const greetingCopy = computed(() => {
  const hour = new Date().getHours();
  if (hour >= 22 || hour < 6) return `夜深了，${greetingName.value}，不要再加班了，剩下的任务就交给我吧。`;
  if (hour < 11) return `早上好，${greetingName.value}。`;
  if (hour < 14) return `午间好，${greetingName.value}。`;
  if (hour < 18) return `下午好，${greetingName.value}。`;
  return `晚上好，${greetingName.value}。`;
});

function addAgentLog(message: string, kind: AgentLogEntry['kind'] = 'info', at?: string) {
  const parsedAt = at ? new Date(at) : null;
  const timestamp = parsedAt && !Number.isNaN(parsedAt.getTime()) ? parsedAt : new Date();
  agentLogs.value = [...agentLogs.value, { id: ++agentLogSequence, at: timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }), message, kind }].slice(-40);
}

function appendTaskTrace(task: TaskRecord | null | undefined) {
  if (!task) return;
  for (const entry of task.trace ?? []) {
    const message = String(entry?.message || '').trim();
    if (!message) continue;
    const key = `${task.id}:${entry.at || ''}:${entry.phase || ''}:${message}`;
    if (seenTaskTraceEntries.has(key)) continue;
    seenTaskTraceEntries.add(key);
    const phase = String(entry.phase || '');
    addAgentLog(message, phase === 'succeeded' ? 'success' : ['failed', 'cancelled'].includes(phase) ? 'error' : 'info', entry.at);
  }
  // A durable task can reach a terminal state before its trace is read by the
  // renderer. The API still persists the authoritative error in error_json;
  // surface it explicitly so a retry never leaves the user with only a
  // generic “需重试” label.
  const taskError = String(task.error?.message || '').trim();
  if (taskError && ['failed', 'cancelled'].includes(task.status)) {
    const key = `${task.id}:error:${taskError}`;
    if (!seenTaskTraceEntries.has(key)) {
      seenTaskTraceEntries.add(key);
      addAgentLog(`${agentDisplayTitle(task.agentKey)}：${task.status === 'cancelled' ? '已取消' : '失败'} · ${taskError}`, 'error');
    }
  }
}

function celebrateFirstUse() {
  if (firstUseCompleted.value) return;
  firstUseCompleted.value = true;
  try { localStorage.setItem(firstRequestCelebrationKey, 'true'); }
  catch { /* Optional UI state must never interrupt an accepted task. */ }
  showAhaMoment.value = true;
}

function pushToast(message: string, kind: Toast['kind'] = 'info') {
  if (!message) return;
  const toast = { id: ++toastSequence, kind, message };
  toasts.value = [...toasts.value, toast].slice(-4);
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((item) => item.id !== toast.id);
  }, 4200);
}

function dismissToast(id: number) {
  toasts.value = toasts.value.filter((item) => item.id !== id);
}

async function renameProject(project: Project, name: string) {
  const updated = await request<Project>(`/api/projects/${project.id}`, { method: 'PUT', body: JSON.stringify({ name }) });
  projects.value = projects.value.map((item) => item.id === updated.id ? updated : item);
  pushToast('任务名称已保存。', 'success');
}

type ConfettiFn = ((options: { particleCount: number; spread: number; origin: { x?: number; y?: number } }) => void) & { reset?: () => void };

function loadConfetti() {
  const existing = (window as unknown as { confetti?: ConfettiFn }).confetti;
  if (existing) return Promise.resolve(existing);
  if (confettiLoader) return confettiLoader;
  confettiLoader = new Promise<void>((resolve) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => resolve();
    document.head.appendChild(script);
  });
  return confettiLoader;
}

function fireConfetti(event: MouseEvent) {
  if (!isProviderSettingsOpen.value || !confettiUnlocked.value) return;
  const session = confettiSession;
  const origin = { x: event.clientX / innerWidth, y: (event.clientY + 10) / innerHeight };
  void loadConfetti().then(() => {
    // A delayed script load must not fire after settings closes or reopens.
    if (session !== confettiSession || !isProviderSettingsOpen.value || !confettiUnlocked.value) return;
    const confetti = (window as unknown as { confetti?: ConfettiFn }).confetti;
    if (!confetti) return;
    confetti({ particleCount: 200, spread: 70, origin });
  });
}

function handleAboutClick(event: MouseEvent) {
  if (!isProviderSettingsOpen.value || settingsTab.value !== 'about') return;
  aboutClicks.value += 1;
  if (aboutClicks.value >= 5) {
    aboutClicks.value = 0;
    confettiUnlocked.value = true;
    fireConfetti(event);
  }
}

function handleSettingsConfettiClick(event: MouseEvent) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target?.closest('.about-pane')) fireConfetti(event);
}

function dismissAhaMoment() {
  showAhaMoment.value = false;
}

async function refreshAchievements() {
  if (achievementRefreshRunning || unlockedAchievement.value) return;
  achievementRefreshRunning = true;
  try {
    const status = await request<{
      imageGenerationCount: number;
      achievements: Array<{ id: string; title: string; description: string; milestone: number; unlocked: boolean; claimed: boolean }>;
    }>('/api/achievements');
    const pending = status.achievements.find(item => item.unlocked && !item.claimed);
    if (pending) unlockedAchievement.value = { ...pending, imageGenerationCount: status.imageGenerationCount };
  } catch {
    // Achievements are optional UI; API recovery can retry on the next task.
  } finally {
    achievementRefreshRunning = false;
  }
}

async function dismissAchievement() {
  const achievement = unlockedAchievement.value;
  if (!achievement) return;
  unlockedAchievement.value = null;
  try {
    await request(`/api/achievements/${encodeURIComponent(achievement.id)}/claim`, { method: 'POST' });
  } catch {
    unlockedAchievement.value = achievement;
    pushToast('成就暂时未能保存，请稍后再试。', 'error');
  }
}

const pendingDeleteProject = computed(() => projects.value.find((project) => project.id === pendingDeleteProjectId.value) ?? null);

function syncTaskTokenUsage(_tasks: TaskRecord[]) { void refreshTokenUsageFromWorkspace(); }

async function refreshTokenUsageFromWorkspace() {
  if (tokenUsageRefreshInFlight) return;
  tokenUsageRefreshInFlight = true;
  try {
    const summary = await request<CreditSummary>('/api/credits');
    if (typeof summary.totalTokens !== 'number' || typeof summary.costCny !== 'number' || typeof summary.reportedRequests !== 'number') throw new Error('用量接口尚未就绪');
    creditSummary.value = summary;
    creditLoadError.value = '';
  } catch { creditLoadError.value = '用量账本暂时不可用'; }
  finally { tokenUsageRefreshInFlight = false; }
}

function handleTokenStorageChange(_event: StorageEvent) { void refreshTokenUsageFromWorkspace(); }

watch(errorMessage, (message) => {
  if (message) pushToast(publicAssistantMessage(message), 'error');
});

watch(providerTestResult, (message) => {
  if (message) pushToast(message, 'success');
});

watch(imageStyle, (style) => {
  localStorage.setItem('aics.imageStyle', style);
});

watch(providers, () => {
  const credentialKey = credentialProviderOptions.value.some((provider) => provider.key === selectedCredentialProvider.value)
    ? selectedCredentialProvider.value
    : 'openrouter';
  if (credentialKey !== selectedCredentialProvider.value) applyProviderProfile(credentialKey);
  const textKey = credentialProviderOptions.value.some((provider) => provider.key === selectedTextProvider.value)
    ? selectedTextProvider.value
    : 'openrouter';
  if (textKey !== selectedTextProvider.value) selectedTextProvider.value = textKey;
}, { deep: true });

watch([selectedCredentialProvider, providerBaseUrl], () => { void loadLocalModelCatalog(); });

watch(detectedModelCatalog, (models) => { modelPrices.value = models; });

async function loadLocalModelCatalog() {
  const sequence = ++localCatalogSequence;
  const provider = credentialTargetProvider.value;
  const baseUrl = providerBaseUrl.value.trim();
  liveModelCatalog.reset();
  try {
    const catalog = await request<ModelCatalogResponse>(`/api/providers/model-catalog?provider=${encodeURIComponent(provider)}&baseUrl=${encodeURIComponent(baseUrl)}`);
    if (sequence !== localCatalogSequence) return;
    liveModelCatalog.hydrate(catalog, { provider, baseUrl });
    selectSavedModels();
    if (!isOllamaProvider.value) imageProvider.value = renderProvider.value = provider;
    if (!isOllamaProvider.value && ['openrouter', 'evolink', 'openai-compatible', 'seedream'].includes(videoConfigProvider.value)) {
      videoProvider.value = videoConfigProvider.value = provider;
      videoEndpoint.value = videoConfigEndpoint.value = baseUrl;
    }
    const config = await request<{ credits: { usdToCny: number }; media: Record<string, Record<string, string>> }>('/api/model-settings');
    usdToCny.value = config.credits.usdToCny;
    mediaDefaults.value = {
      image: {
        draft: config.media.image.draft || DEFAULT_DRAFT_IMAGE_MODEL,
        standard: config.media.image.standard || DEFAULT_IMAGE_MODEL,
        final: config.media.image.final || DEFAULT_IMAGE_MODEL,
      },
      video: config.media.video.standard,
    };
    selectSavedModels();
  } catch { /* A missing local service must not trigger upstream requests. */ }
}

function selectSavedModels() {
  providerModel.value = selectAvailableModel(providerModel.value, textModelOptions.value);
  imageModel.value = preferMediaModel(imageModelManual.value ? imageModel.value || localStorage.getItem('aics.imageModel') || '' : mediaDefaults.value.image.standard, imageModelOptions.value, DEFAULT_IMAGE_MODEL);
  renderModel.value = imageModel.value;
  videoModel.value = videoConfigModel.value = preferMediaModel(videoModelManual.value ? videoModel.value || localStorage.getItem('aics.videoModel') || '' : mediaDefaults.value.video, videoModelOptions.value, DEFAULT_VIDEO_MODEL);
}

function applyTheme() {
  const resolved = themeMode.value === 'system'
    ? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : themeMode.value;
  resolvedTheme.value = resolved;
  document.documentElement.dataset.theme = resolved;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'light' ? '#f3f2ef' : '#181818');
  applyAppearance(resolved);
  document.querySelector<HTMLLinkElement>('#app-favicon')?.setAttribute('href', `${import.meta.env.BASE_URL}assets/mxinspirex-favicon-${resolvedTheme.value}.png`);
  // Keep the native Dock/window artwork in lockstep with the renderer theme.
  // `system` lets the main process continue listening to nativeTheme updates;
  // an explicit mode intentionally overrides the OS appearance for this app.
  void window.studio?.setAppIconAppearance?.(themeMode.value === 'system' ? 'system' : resolved);
  if (themeMode.value === 'system') localStorage.removeItem('langjuart.theme');
  else localStorage.setItem('langjuart.theme', themeMode.value);
}

function handleDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (!target?.closest('.composer-popover-wrap, .agent-popover, .style-picker-dialog')) {
    showComposerAgentMenu.value = false;
    showComposerStyleMenu.value = false;
  }
  if (!target?.closest('.intake-mention-anchor')) {
    intakeSkillQuery.value = null;
    intakeMentionQuery.value = '';
    intakeMentionStart.value = null;
    intakeMentionCaret.value = null;
  }
  if (!target?.closest('.composer-task-wrap, .composer-task-list')) showAssistantCard.value = false;
  if (!target?.closest('.profile-summary-card, .sidebar-user-mini')) closeUserSummary();
}

const scheduleUnreadCount = ref(0);

let scheduleNotificationTimer: number | undefined;

let scheduleNoticesLoading = false;

let unsubscribeScheduleNotification: (() => void) | undefined;

const seenScheduleNotifications = new Set<string>();

const scheduleProvider = computed(() => activeTextProvider.value && textModelOptions.value.includes(providerModel.value)
  ? { key: activeTextProvider.value, baseUrl: providerBaseUrl.value, model: providerModel.value } : undefined);

function openSchedules() {
  workspaceView.value = 'schedules'; sidebarSection.value = 'schedules';
  void refreshScheduleNotifications();
}

async function openScheduledProject(projectId: string) {
  await loadProjects();
  await selectProject(projectId);
}

async function refreshScheduleNotifications() {
  if (scheduleNoticesLoading) return;
  scheduleNoticesLoading = true;
  try {
    const notices = await requestWithTimeout<Array<{ id: string; title: string }>>('/api/schedule-notifications?unread=true', undefined, 4000);
    const fresh = notices.filter((notice) => !seenScheduleNotifications.has(notice.id));
    scheduleUnreadCount.value = notices.length;
    notices.forEach((notice) => seenScheduleNotifications.add(notice.id));
    if (fresh.length) pushToast(fresh.length === 1 ? fresh[0].title : `你有 ${fresh.length} 条新的定时任务通知，请打开定时器查看。`, 'info');
  } catch { /* Keep local notification polling quiet while the sidecar starts. */ }
  finally { scheduleNoticesLoading = false; }
}

function navigateSidebar(section: typeof sidebarSection.value) {
  if (section === 'schedules') { openSchedules(); return; }
  sidebarSection.value = section;
  if (section === 'home') startNewIntake();
  if (section === 'workflows') workspaceView.value = 'workflows';
  if (section === 'skills') workspaceView.value = 'skills';
  if (section === 'assets') workspaceView.value = 'asset-library';
  if (section === 'knowledge') {
    workspaceView.value = 'knowledge-library';
    void loadGlobalLibraries();
  }
  if (section === 'projects') {
    workspaceView.value = 'projects-library';
    void loadGlobalLibraries();
  }
  const paths = { workflows: '/workflows', home: '/', new: '/', projects: '/projects', assets: '/assets', knowledge: '/references', skills: '/skills' };
  void router.push(paths[section]);
}

watch(allowExternalNetwork, (enabled) => {
  localStorage.setItem('aics.allowExternalNetwork', String(enabled));
});

function resizeSidebar(event: PointerEvent) {
  if (!isResizingSidebar.value) return;
  leftPanelWidth.value = Math.min(380, Math.max(190, event.clientX));
  localStorage.setItem('langjuart.sidebarWidth', String(leftPanelWidth.value));
}

function stopSidebarResize() {
  isResizingSidebar.value = false;
  document.body.classList.remove('is-resizing-sidebar');
  window.removeEventListener('pointermove', resizeSidebar);
}

watch(themeMode, applyTheme);

function handleSystemThemeChange() {
  if (themeMode.value === 'system') applyTheme();
}

function providerDefaultBaseUrl(providerKey: string) {
  if (providerKey === 'evolink') return defaultEvoLinkBaseUrl;
  const provider = providers.value.find((item) => item.key === providerKey);
  return provider?.defaultBaseUrl || (providerKey === 'openrouter' ? defaultOpenRouterBaseUrl : providerKey === 'ollama' ? 'http://127.0.0.1:11434/v1' : 'https://api.openai-proxy.org/v1');
}

function applyProviderProfile(providerKey: string, { resetSecret = true } = {}) {
  const profile = profileForProvider(providerKey);
  selectedCredentialProvider.value = providerKey;
  const savedBaseUrl = profile?.baseUrl && !(providerKey === 'openrouter' && profile.baseUrl.includes('api.openai-proxy.org'))
    ? profile.baseUrl
    : '';
  providerBaseUrl.value = providerKey === 'evolink' ? providerDefaultBaseUrl(providerKey) : savedBaseUrl || providerDefaultBaseUrl(providerKey);
  providerModel.value = profile?.textModel || '';
  imageModel.value = profile?.imageModel || DEFAULT_IMAGE_MODEL;
  videoModel.value = videoConfigModel.value = profile?.videoModel || DEFAULT_VIDEO_MODEL;
  liveModelCatalog.reset();
  if (resetSecret) providerSecret.value = '';
  if (resetSecret) closeAICatalogSecret.value = '';
  localStorage.setItem('aics.credentialProvider', providerKey);
  localStorage.setItem('aics.textProvider', providerKey);
  selectedTextProvider.value = providerKey;
  void loadLocalModelCatalog();
}

watch(selectedTextProvider, (providerKey) => {
  const provider = providers.value.find((item) => item.key === providerKey);
  if (!provider) return;
  if (selectedCredentialProvider.value !== providerKey) applyProviderProfile(providerKey);
  else {
    if (!providerBaseUrl.value.trim()) providerBaseUrl.value = providerDefaultBaseUrl(providerKey);
  }
  localStorage.setItem('aics.textProvider', providerKey);
  void request('/api/model-settings/preferred-provider', {
    method: 'PUT',
    body: JSON.stringify({ key: providerKey, baseUrl: providerBaseUrl.value.trim() }),
  }).catch(() => undefined);
});

const form = ref<ProjectCreateInput>({
  name: '',
  brief: '',
  budgetMinor: null,
  currency: 'CNY',
});

const activeProject = computed(() =>
  projects.value.find((project) => project.id === activeProjectId.value) ?? null,
);

watch([intakeBrief, intakeFiles, workspaceView], () => {
  requestAnimationFrame(syncIntakeComposerEditor);
}, { immediate: true });



const defaultImageModel = computed(() => preferMediaModel(mediaDefaults.value.image.standard, imageModelOptions.value, DEFAULT_IMAGE_MODEL));
const composerModelOptions = computed(() => {
  const options = ({ text: textModelOptions.value, image: imageModelOptions.value, video: videoModelOptions.value, audio: audioModelOptions.value })[agentModelTab.value];
  return agentModelTab.value === 'image' && defaultImageModel.value
    ? [defaultImageModel.value, ...options.filter(model => model !== defaultImageModel.value)] : options;
});

function useDefaultImageModel() {
  imageModelManual.value = false;
  localStorage.setItem('aics.imageModelManual', 'false');
  imageModel.value = defaultImageModel.value || mediaDefaults.value.image.standard;
  persistProviderSettings();
  showComposerAgentMenu.value = false;
  pushToast(IMAGE_ROUTE_LABEL, 'success');
}

const composerSelectedModel = computed(() => ({ text: providerModel.value, image: imageModel.value, video: videoModel.value, audio: audioModel.value })[agentModelTab.value]);

function toggleComposerAgentMenu() {
  const nextOpen = !showComposerAgentMenu.value;

  showComposerAgentMenu.value = nextOpen;
  if (nextOpen) showComposerStyleMenu.value = false;
}

function toggleComposerStyleMenu() {
  const nextOpen = !showComposerStyleMenu.value;
  showComposerStyleMenu.value = nextOpen;
  if (nextOpen) showComposerAgentMenu.value = false;
}

function selectComposerStyle(style: string) {
  imageStyle.value = style;
  localStorage.setItem('aics.imageStyle', style);
  showComposerStyleMenu.value = false;
  pushToast(`已选择视觉预设：${style}`, 'success');
}

function selectComposerModel(kind: 'text' | 'image' | 'video' | 'audio' | 'threeD', model: string) {
  const options = { text: textModelOptions.value, image: imageModelOptions.value, video: videoModelOptions.value, audio: audioModelOptions.value, threeD: threeDModelOptions.value };
  if (!options[kind].includes(model)) return;
  if (kind === 'text') {
    routingMode.value = 'manual';
    providerModel.value = model;
    localStorage.setItem('aics.providerModel', model);
    localStorage.setItem('aics.textProvider', activeTextProvider.value || selectedTextProvider.value);
  } else if (kind === 'image') {
    setMediaOverride('image');
    imageModel.value = model;
    localStorage.setItem('aics.imageModel', model);
  } else if (kind === 'video') { setMediaOverride('video'); videoModel.value = videoConfigModel.value = model; }
  else if (kind === 'audio') { audioModel.value = model; localStorage.setItem('aics.audioModel', model); }
  else threeDConfigModel.value = model;
  persistProviderSettings();
  showComposerAgentMenu.value = false;
  pushToast(`${kind === 'text' ? '文本' : kind === 'image' ? '图像' : kind === 'video' ? '视频' : kind === 'audio' ? '音频' : '3D'}模型已切换为 ${model}`, 'success');
}

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function assetDisplayName(asset: AssetRecord) {
  const filename = asset.pathRelative.split('/').pop() || asset.id;
  return filename.replace(/^[0-9a-f]{32}-/i, '');
}

function assetKindLabel(kind: string) {
  return ({ image: '图像', video: '视频', '3d': '3D', cad: 'CAD', document: '文档' } as Record<string, string>)[kind] || kind;
}

const maxInlinePasteLength = 6000;

const intakeMentionResults = computed<IntakeMentionOption[]>(() => {
  const query = intakeMentionQuery.value.trim().toLowerCase();
  const localFiles: IntakeMentionOption[] = intakeFiles.value
    .map((file, index) => ({ type: 'file' as const, file, index }))
    .filter(({ file, index }) => !query || `${index + 1} ${file.name} ${file.type}`.toLowerCase().includes(query));
  const assets: IntakeMentionOption[] = globalAssets.value
    .filter((asset) => !query || `${assetDisplayName(asset)} ${asset.pathRelative} ${asset.projectName || ''} ${asset.kind}`.toLowerCase().includes(query))
    .map((asset) => ({ type: 'asset' as const, asset }));
  const documents: IntakeMentionOption[] = globalKnowledgeDocs.value
    .filter(document => !query || `${document.title} ${document.pathRelative}`.toLowerCase().includes(query))
    .map(document => ({ type: 'knowledge' as const, document }));
  return [...localFiles, ...assets, ...documents].slice(0, 12);
});

function updateIntakeMentionState(value: string, caret: number) {
  intakeSkillQuery.value = skillMentionQuery(value, caret);
  const beforeCaret = value.slice(0, caret);
  const match = beforeCaret.match(/(?:^|\s)@([^\s@]*)$/);
  if (!match) {
    intakeMentionQuery.value = '';
    intakeMentionStart.value = null;
    intakeMentionCaret.value = null;
    return;
  }
  intakeMentionQuery.value = match[1] || '';
  intakeMentionStart.value = caret - (match[1]?.length || 0) - 1;
  intakeMentionCaret.value = caret;
  intakeMentionActiveIndex.value = 0;
}

function handleIntakeComposerInput(event: Event) {
  confirmCanvasReferences();
  const editor = event.currentTarget as HTMLDivElement;
  const caret = intakeComposerCaretOffset();
  const value = intakeComposerText(editor);
  if (!value && editor.textContent) editor.replaceChildren();
  intakeBrief.value = value;
  syncIntakeMentionsFromText();
  if (!isIntakeComposerComposing.value) updateIntakeMentionState(value, caret);
}

function refreshComposerMentionCaret() {
  if (!isIntakeComposerComposing.value && document.activeElement === intakeComposerRef.value)
    updateIntakeMentionState(intakeBrief.value, intakeComposerCaretOffset());
}

function selectIntakeSkill(skill: SkillMention) {
  const query = intakeSkillQuery.value;
  if (!query) return;
  const token = skillToken(skill.id);
  intakeSkills.value = [...intakeSkills.value.filter(s => s.id !== skill.id), { id: skill.id, name: skill.name, title: skill.title, version: skill.version }];
  intakeBrief.value = `${intakeBrief.value.slice(0, query.start)}${token} ${intakeBrief.value.slice(query.caret)}`;
  intakeSkillQuery.value = null;
  requestAnimationFrame(() => {
    intakeComposerRef.value?.focus();
    syncIntakeComposerEditor();
    setIntakeComposerCaret(query.start + token.length + 1);
  });
}

function handleIntakeComposerCompositionStart() {
  isIntakeComposerComposing.value = true;
  intakeSkillQuery.value = null;
}

function handleIntakeComposerCompositionEnd(event: CompositionEvent) {
  isIntakeComposerComposing.value = false;
  handleIntakeComposerInput(event);
}

function selectIntakeMention(option: IntakeMentionOption) {
  const start = intakeMentionStart.value;
  const caret = intakeMentionCaret.value;
  if (start === null || caret === null) return;
  const token = option.type === 'file' ? `@${option.index + 1}` : option.type === 'knowledge' ? `@knowledge:${option.document.id}` : `@asset:${option.asset.id}`;
  if (option.type === 'asset' && !intakeMentionAssets.value.some(item => item.id === option.asset.id && item.projectId === option.asset.projectId)) intakeMentionAssets.value.push(option.asset);
  intakeBrief.value = `${intakeBrief.value.slice(0, start)}${token} ${intakeBrief.value.slice(caret)}`;
  syncIntakeMentionsFromText();
  intakeMentionQuery.value = '';
  intakeMentionStart.value = null;
  intakeMentionCaret.value = null;
  intakeMentionActiveIndex.value = 0;
  requestAnimationFrame(() => {
    const editor = intakeComposerRef.value;
    if (!editor) return;
    const nextCaret = start + token.length + 1;
    editor.focus();
    syncIntakeComposerEditor();
    setIntakeComposerCaret(nextCaret);
  });
}

function handleIntakeMentionKeydown(event: KeyboardEvent) {
  if (intakeMentionStart.value === null || !intakeMentionResults.value.length) return;
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    intakeMentionActiveIndex.value = (intakeMentionActiveIndex.value + 1) % intakeMentionResults.value.length;
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    intakeMentionActiveIndex.value = (intakeMentionActiveIndex.value - 1 + intakeMentionResults.value.length) % intakeMentionResults.value.length;
  } else if (event.key === 'Enter' || event.key === 'Tab') {
    event.preventDefault();
    const option = intakeMentionResults.value[intakeMentionActiveIndex.value];
    if (option) selectIntakeMention(option);
  } else if (event.key === 'Escape') {
    event.preventDefault();
    intakeMentionQuery.value = '';
    intakeMentionStart.value = null;
    intakeMentionCaret.value = null;
  }
}

function handleIntakeComposerKeydown(event: KeyboardEvent) {
  if (isIntakeComposerComposing.value || event.isComposing || event.keyCode === 229) return;
  if (intakeSkillQuery.value) { intakeSkillMenu.value?.keydown(event); return; }
  if (intakeMentionStart.value !== null) {
    handleIntakeMentionKeydown(event);
    return;
  }
  if (shouldSendMessage(event, generalSettings.sendWithEnter)) {
    event.preventDefault();
    void submitComposer();
  }
}

function syncIntakeMentionsFromText() {
  const selected = referencedKeys(intakeBrief.value, inlineReferences.value);
  const candidates = [...intakeMentionAssets.value, ...globalAssets.value];
  intakeMentionAssets.value = candidates.filter((asset, index) => selected.has(`asset:${asset.id}`) && candidates.findIndex(item => item.id === asset.id && item.projectId === asset.projectId) === index);
  intakeMentionFiles.value = intakeFiles.value.flatMap((_, index) => selected.has(`file:${index}`) ? [index] : []);
}

const intakeFileAccept = '.txt,.md,.markdown,.csv,.json,.html,.htm,.pdf,.docx,.pptx,.png,.jpg,.jpeg,.webp';
const isDraggingComposerFiles = ref(false);
let composerFileDragDepth = 0;

function composerDragHasFiles(event: DragEvent) {
  return Boolean(event.dataTransfer && (Array.from(event.dataTransfer.types).includes('Files')
    || Array.from(event.dataTransfer.items).some(item => item.kind === 'file')));
}

function resetComposerFileDrag() {
  composerFileDragDepth = 0;
  isDraggingComposerFiles.value = false;
}

function handleComposerFileDragEnter(event: DragEvent) {
  if (workspaceView.value !== 'design-agent') return;
  if (!composerDragHasFiles(event)) return;
  event.preventDefault();
  composerFileDragDepth += 1;
  isDraggingComposerFiles.value = true;
}

function handleComposerFileDragOver(event: DragEvent) {
  if (workspaceView.value !== 'design-agent') return;
  if (!composerDragHasFiles(event)) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = isCreatingIntake.value ? 'none' : 'copy';
}

function handleComposerFileDragLeave(_event: DragEvent) {
  if (workspaceView.value !== 'design-agent') { resetComposerFileDrag(); return; }
  if (!isDraggingComposerFiles.value) return;
  composerFileDragDepth = Math.max(0, composerFileDragDepth - 1);
  if (!composerFileDragDepth) resetComposerFileDrag();
}

function handleComposerFileDrop(event: DragEvent) {
  if (workspaceView.value !== 'design-agent') { resetComposerFileDrag(); return; }
  const fileDrop = composerDragHasFiles(event);
  resetComposerFileDrag();
  if (!fileDrop || !event.dataTransfer) return;
  event.preventDefault();
  event.stopPropagation();
  const items = Array.from(event.dataTransfer.items).filter(item => item.kind === 'file');
  const files = items.length
    ? items.filter(item => !item.webkitGetAsEntry?.()?.isDirectory).map(item => item.getAsFile()).filter((file): file is File => Boolean(file))
    : Array.from(event.dataTransfer.files);
  handleDroppedIntakeFiles(files);
}

function addIntakeFiles(incoming: File[]) {
  const existing = new Set(intakeFiles.value.map(fileKey));
  const accepted = incoming.filter((file) => {
    const key = fileKey(file);
    if (file.size <= 0 || existing.has(key)) return false;
    existing.add(key);
    return true;
  });
  accepted.forEach(handleFilePreview);
  if (accepted.length) intakeFiles.value = [...intakeFiles.value, ...accepted];
  return accepted;
}

function handleDroppedIntakeFiles(files: File[]) {
  if (isCreatingIntake.value) {
    pushToast('正在上传资料，请稍后再添加附件。', 'info');
    return;
  }
  const extensions = new Set(intakeFileAccept.split(','));
  const supported = files.filter(file => file.size > 0 && extensions.has(file.name.slice(file.name.lastIndexOf('.')).toLowerCase()));
  const accepted = addIntakeFiles(supported);
  const messages: string[] = [];
  if (accepted.length) messages.push(`已添加 ${accepted.length} 个附件，发送时上传。`);
  if (supported.length > accepted.length) messages.push('重复附件已跳过。');
  if (files.length > supported.length || !files.length) messages.push('已跳过空文件、文件夹或不支持的格式，请添加图片、PDF、DOCX、PPTX、CSV 或文本文件。');
  pushToast(messages.join(''), accepted.length ? 'success' : 'info');
  if (accepted.length) void nextTick(() => intakeComposerRef.value?.focus({ preventScroll: true }));
}

function handleIntakePaste(event: ClipboardEvent) {
  const clipboard = event.clipboardData;
  if (!clipboard) return;
  const pastedFiles = Array.from(clipboard.items)
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((file): file is File => Boolean(file));
  if (pastedFiles.length) {
    event.preventDefault();
    const accepted = addIntakeFiles(pastedFiles);
    if (accepted.length) pushToast(`已添加 ${accepted.length} 个粘贴附件，可用 @编号引用。`, 'success');
    return;
  }
  const text = clipboard.getData('text/plain');
  if (text.length <= maxInlinePasteLength) return;
  event.preventDefault();
  const file = new File([text], `粘贴文本-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`, { type: 'text/plain', lastModified: Date.now() });
  addIntakeFiles([file]);
  pushToast(`已将 ${text.length.toLocaleString()} 字的长文本转为 TXT 附件，可用 @编号引用。`, 'info');
}

function handleFilePreview(file: File) {
  if (!file.type.startsWith('image/')) return;
  const key = fileKey(file);
  if (!intakeFilePreviews.value[key]) intakeFilePreviews.value[key] = URL.createObjectURL(file);
}

function fileIcon(file: File) {
  if (file.type.startsWith('image/')) return 'IMG';
  if (file.type.includes('pdf')) return 'PDF';
  if (file.type.includes('spreadsheet') || /csv|excel/i.test(file.name)) return 'CSV';
  if (file.type.includes('presentation') || /pptx?/i.test(file.name)) return 'PPT';
  if (file.type.includes('word') || /docx?/i.test(file.name)) return 'DOC';
  return 'FILE';
}

function intakeComposerNodeText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
  if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return '';
  const element = node.nodeType === Node.ELEMENT_NODE ? node as HTMLElement : null;
  if (element?.dataset.mentionToken) return element.dataset.mentionToken;
  if (element?.tagName === 'BR') return '\n';
  let result = '';
  Array.from(node.childNodes).forEach((child) => {
    const childText = intakeComposerNodeText(child);
    const childElement = child.nodeType === Node.ELEMENT_NODE ? child as HTMLElement : null;
    if (childElement && ['DIV', 'P'].includes(childElement.tagName) && result && !result.endsWith('\n')) result += '\n';
    result += childText;
  });
  if (element && ['DIV', 'P'].includes(element.tagName) && result && !result.endsWith('\n')) result += '\n';
  return result;
}

function intakeComposerText(editor = intakeComposerRef.value) {
  if (!editor) return '';
  return intakeComposerNodeText(editor).replace(/\u00a0/g, ' ').replace(/\n+$/g, '');
}

function intakeComposerCaretOffset() {
  const editor = intakeComposerRef.value;
  const selection = window.getSelection();
  if (!editor || !selection?.rangeCount || !selection.anchorNode || !editor.contains(selection.anchorNode)) return intakeBrief.value.length;
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.setEnd(selection.anchorNode, selection.anchorOffset);
  return intakeComposerNodeText(range.cloneContents()).replace(/\u00a0/g, ' ').length;
}

function setIntakeComposerCaret(offset: number) {
  const editor = intakeComposerRef.value;
  if (!editor) return;
  const range = document.createRange();
  const selection = window.getSelection();
  let remaining = Math.max(0, offset);
  let placed = false;
  const place = (parent: Node): boolean => {
    for (let index = 0; index < parent.childNodes.length; index += 1) {
      const child = parent.childNodes[index];
      if (child.nodeType === Node.TEXT_NODE) {
        const length = child.textContent?.length || 0;
        if (remaining <= length) {
          range.setStart(child, remaining);
          range.collapse(true);
          return true;
        }
        remaining -= length;
        continue;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      const element = child as HTMLElement;
      const token = element.dataset.mentionToken;
      if (token) {
        if (remaining <= token.length) {
          range.setStart(parent, remaining === 0 ? index : index + 1);
          range.collapse(true);
          return true;
        }
        remaining -= token.length;
        continue;
      }
      if (element.tagName === 'BR') {
        if (remaining <= 1) {
          range.setStart(parent, remaining === 0 ? index : index + 1);
          range.collapse(true);
          return true;
        }
        remaining -= 1;
        continue;
      }
      if (place(element)) return true;
    }
    return false;
  };
  placed = place(editor);
  if (!placed) {
    range.selectNodeContents(editor);
    range.collapse(false);
  }
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function composerReferencesForDraft(draft: ComposerDraft, projectId: string): InlineReference[] {
  const files = draft.files.map((file, index) => ({ key: `file:${index}`, token: `@${index + 1}`, label: file.name, kind: fileIcon(file), badge: `@${index + 1}`, preview: intakeFilePreviews.value[fileKey(file)] }));
  const availableAssets = [...draft.assets, ...globalAssets.value];
  const media = availableAssets.filter((asset, index) => availableAssets.findIndex(item => item.id === asset.id) === index).map(asset => ({
    key: `asset:${asset.id}`, token: `@asset:${asset.id}`, aliases: [`@${assetDisplayName(asset)}`], label: assetDisplayName(asset), kind: assetKindLabel(asset.kind), badge: '@', assetId: asset.id, projectId: asset.projectId, nodeId: 'nodeId' in asset ? asset.nodeId : undefined,
    preview: (asset.mime?.startsWith('image/') || /\.(png|jpe?g|webp|gif)$/i.test(asset.pathRelative)) && asset.projectId ? `${apiBaseUrl}/api/projects/${asset.projectId}/assets/${asset.id}/content` : undefined,
  }));
  const documents = globalKnowledgeDocs.value.map(document => ({ key: `knowledge:${document.id}`, token: `@knowledge:${document.id}`, label: document.title, kind: '知识文档', badge: '@',
    preview: /\.(png|jpe?g|webp|gif)$/i.test(document.pathRelative) ? `${apiBaseUrl}/api/knowledge/documents/${document.id}/content` : undefined,
  }));
  const nodes = messageReferences({ text: draft.text, projectId, apiBaseUrl,
    assets: availableAssets, documents: [], nodes: designCanvasDocument.value.nodes }).filter(reference => reference.key.startsWith('node:'));
  return [...files, ...media, ...documents, ...nodes, ...skillReferences(draft.skills || [])];
}

const inlineReferences = computed<InlineReference[]>(() => {
  return composerReferencesForDraft(snapshotComposerDraft(), activeProjectId.value || '');
});
const referencePreview = ref<{ item: InlineReference; x: number; y: number } | null>(null);
function showInlineReferencePreview(event: PointerEvent | FocusEvent) {
  const chip = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-reference-key]') : null;
  const item = inlineReferences.value.find(reference => reference.key === chip?.dataset.referenceKey);
  if (!chip || !item) return;
  const rect = chip.getBoundingClientRect(), height = item.preview ? 245 : 165;
  referencePreview.value = { item, x: Math.max(8, Math.min(rect.left, window.innerWidth - 232)), y: rect.top > height + 8 ? rect.top - height : Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - height - 8)) };
}
function hideInlineReferencePreview(event?: PointerEvent | FocusEvent) {
  const chip = event?.target instanceof Element ? event.target.closest('[data-reference-key]') : null;
  if (event?.relatedTarget instanceof Node && chip?.contains(event.relatedTarget)) return;
  referencePreview.value = null;
}
function mentionOptionKey(option: IntakeMentionOption) { return option.type === 'file' ? `file:${option.index}` : option.type === 'asset' ? `asset:${option.asset.id}` : `knowledge:${option.document.id}`; }
function mentionOptionLabel(option: IntakeMentionOption) { return option.type === 'file' ? `@${option.index + 1} · ${option.file.name}` : option.type === 'asset' ? assetDisplayName(option.asset) : option.document.title; }
function mentionOptionPreview(option: IntakeMentionOption) { return inlineReferences.value.find(item => item.key === mentionOptionKey(option))?.preview; }
function mentionOptionMeta(option: IntakeMentionOption) { return option.type === 'file' ? `${fileIcon(option.file)} · 当前附件` : option.type === 'knowledge' ? '知识库文档' : `${option.asset.projectName || '当前工作区'} · ${assetKindLabel(option.asset.kind)}`; }
function renderIntakeComposerEditor() {
  const editor = intakeComposerRef.value;
  if (!editor) return;
  const fragment = document.createDocumentFragment();
  for (const segment of referenceSegments(intakeBrief.value, inlineReferences.value)) {
    const reference = segment.reference;
    if (!reference) { fragment.append(document.createTextNode(segment.text)); continue; }
    const chip = document.createElement('span');
    chip.className = 'intake-inline-mention'; chip.contentEditable = 'false'; chip.tabIndex = 0;
    chip.dataset.mentionToken = segment.text; chip.dataset.referenceKey = reference.key;
    chip.setAttribute('role', 'img'); chip.setAttribute('aria-label', `引用：${reference.label}`);
    if (reference.key.startsWith('skill:')) {
      chip.classList.add('intake-inline-skill');
      chip.textContent = `# ${reference.label}`;
      chip.title = reference.textContent || reference.label;
      fragment.append(chip); continue;
    }
    const preview = document.createElement('span'); preview.className = 'intake-inline-mention-preview';
    if (reference.preview) { const image = document.createElement('img'); image.src = reference.preview; image.alt = reference.label; image.draggable = false; preview.append(image); }
    else if (reference.key.startsWith('node:')) {
      // Match Lucide FileText without mounting Vue components inside the
      // contenteditable DOM. Keep the stable node token on the outer chip.
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('fill', 'none'); icon.setAttribute('stroke', 'currentColor');
      icon.setAttribute('stroke-width', '1.7'); icon.setAttribute('stroke-linecap', 'round'); icon.setAttribute('stroke-linejoin', 'round');
      icon.setAttribute('aria-hidden', 'true'); icon.setAttribute('class', 'intake-inline-node-icon');
      for (const d of ['M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z', 'M14 2v4a2 2 0 0 0 2 2h4', 'M10 9H8', 'M16 13H8', 'M16 17H8']) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', d); icon.append(path);
      }
      preview.append(icon);
    }
    else { const icon = document.createElement('span'); icon.className = 'intake-inline-mention-file-icon'; icon.textContent = reference.kind; preview.append(icon); }
    const badge = document.createElement('span'); badge.className = 'intake-inline-mention-number'; badge.setAttribute('aria-hidden', 'true'); badge.textContent = reference.badge;
    chip.append(preview, badge); fragment.append(chip);
  }
  editor.replaceChildren(fragment);
  editor.dataset.renderedText = intakeBrief.value;
}
watch(inlineReferences, () => { if (intakeComposerRef.value) { delete intakeComposerRef.value.dataset.renderedText; syncIntakeComposerEditor(); } }, { flush: 'post' });
watch(workspaceView, () => {
  recordBetaUsage('page_view', { page: workspaceView.value, projectId: activeProjectId.value || undefined });
  referencePreview.value = null; showComposerStyleMenu.value = false;
  intakeSkillQuery.value = null;
  // Returning to a page shows the text already received; only new updates type.
  designConversation.value.forEach(message => { message.animateReply = false; });
});

watch(intakeComposerRef, (editor) => { if (editor) syncIntakeComposerEditor(); }, { flush: 'post' });

function syncIntakeComposerEditor() {
  const editor = intakeComposerRef.value;
  if (!editor || isIntakeComposerComposing.value || editor.dataset.renderedText === intakeBrief.value) return;
  const isFocused = document.activeElement === editor;
  const caret = isFocused ? intakeComposerCaretOffset() : null;
  renderIntakeComposerEditor();
  if (isFocused && caret !== null) setIntakeComposerCaret(caret);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const rawDetail = await response.text();
    let detail = rawDetail;
    try {
      const parsed = JSON.parse(rawDetail) as { detail?: unknown; message?: unknown; error?: { message?: unknown } | unknown };
      if (typeof parsed.detail === 'string') detail = parsed.detail;
      else if (parsed.error && typeof parsed.error === 'object' && typeof (parsed.error as { message?: unknown }).message === 'string') detail = String((parsed.error as { message: string }).message);
      else if (typeof parsed.message === 'string') detail = parsed.message;
    } catch {
      // Keep plain-text gateway errors as-is.
    }
    const requestError = new Error(detail || `Request failed: ${response.status}`) as Error & { status?: number };
    requestError.status = response.status;
    throw requestError;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function waitForApi(maxAttempts = 1) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 700);
    try {
      const response = await fetch(`${apiBaseUrl}/health`, { signal: controller.signal });
      if (response.ok) return;
    } catch {
      // Electron may still be starting the local sidecar; retry below.
    } finally {
      window.clearTimeout(timeout);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 350));
  }
  throw new Error('本地 API 未能在启动窗口内就绪，请使用 npm run dev:web 同时启动网页和 API。');
}

async function loadProjects() {
  const loadSequence = ++projectListLoadSequence;
  // A case can be submitted while the initial project list is still loading.
  // Keep the active id from that newer action so a late response cannot reset
  // the freshly-created project back to the intake page.
  const activeProjectAtStart = activeProjectId.value;
  isLoading.value = true;
  errorMessage.value = '';
  try {
    await waitForApi();
    const loadedProjects = await request<Project[]>('/api/projects');
    if (loadSequence !== projectListLoadSequence) return;
    if (!providers.value.length) void loadProviders();
    if (activeProjectId.value !== activeProjectAtStart) {
      const currentActive = projects.value.find((project) => project.id === activeProjectId.value);
      projects.value = currentActive && !loadedProjects.some((project) => project.id === currentActive.id)
        ? [currentActive, ...loadedProjects]
        : loadedProjects;
      apiRecoveryAttempts = 0;
      if (apiRecoveryTimer !== null) {
        window.clearTimeout(apiRecoveryTimer);
        apiRecoveryTimer = null;
      }
      projectCatalogReady.value = true;
      void loadGlobalLibraries();
      return;
    }
    projects.value = loadedProjects;
    projectCatalogReady.value = true;
    apiRecoveryAttempts = 0;
    if (apiRecoveryTimer !== null) {
      window.clearTimeout(apiRecoveryTimer);
      apiRecoveryTimer = null;
    }
    void loadGlobalLibraries();
  } catch (error) {
    const message = error instanceof Error ? error.message : '无法读取本地项目';
    const apiUnavailable = message.includes('本地 API 未能') || message.includes('Failed to fetch') || message.includes('NetworkError');
    if (apiUnavailable && apiRecoveryAttempts < 12) {
      apiRecoveryAttempts += 1;
      errorMessage.value = '';
      if (apiRecoveryTimer !== null) window.clearTimeout(apiRecoveryTimer);
      apiRecoveryTimer = window.setTimeout(() => {
        apiRecoveryTimer = null;
        void loadProjects();
      }, 1800);
    } else {
      errorMessage.value = message;
    }
  } finally {
    isLoading.value = false;
  }
}

function requestStatus(error: unknown) {
  return error instanceof Error ? (error as Error & { status?: number }).status : undefined;
}

async function recoverMissingProject(projectId: string) {
  if (missingProjectRecoveryInFlight || activeProjectId.value !== projectId) return;
  missingProjectRecoveryInFlight = true;
  // A sidecar restart can briefly answer before its catalog is ready. Confirm
  // the 404 against a fresh project list twice before clearing the active
  // context; otherwise stopping a run can make a healthy project look gone.
  try {
    let latestProjects: Project[] | null = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        await waitForApi(8);
        latestProjects = await request<Project[]>('/api/projects');
        if (latestProjects.some((project) => project.id === projectId)) {
          projects.value = latestProjects;
          addAgentLog('项目记录已恢复，已继续保留当前工作区。', 'success');
          return;
        }
      } catch {
        // Keep the active project while the sidecar is still starting.
      }
      if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 450));
    }
    if (activeProjectId.value !== projectId) return;
    if (!latestProjects) {
      errorMessage.value = '本地 API 暂时不可用，已保留当前项目；恢复后可继续运行。';
      addAgentLog('暂时无法确认项目目录，已保留当前项目上下文。', 'error');
      return;
    }
    startNewIntake();
    projects.value = latestProjects;
    pushToast('当前项目已确认不存在，已返回首页。', 'info');
  } finally {
    missingProjectRecoveryInFlight = false;
  }
}

function handleProjectRequestError(projectId: string, error: unknown, fallback: string) {
  if (requestStatus(error) === 404) {
    recoverMissingProject(projectId);
    return;
  }
  errorMessage.value = error instanceof Error ? error.message : fallback;
}

const libraryLoading = ref(false);
const libraryError = ref('');
const libraryLoadState = { loading: libraryLoading, error: libraryError, retry: () => { void loadProjects().then(loadGlobalLibraries); } };

const previewLoads = new Map<string, Promise<void>>();
const previewRevisions = new Map<string, string>();
async function loadProjectPreview(project: Project) {
  const revision = project.previewRevision || 'empty';
  if (previewRevisions.get(project.id) === revision) return;
  if (previewLoads.has(project.id)) return previewLoads.get(project.id);
  const operation = (async () => {
    try {
      const preview = await request<DesignCanvasDocument>(`/api/projects/${project.id}/preview`);
      if (!projects.value.some(item => item.id === project.id)) return;
      projectCanvasPreviews.value = { ...projectCanvasPreviews.value, [project.id]: preview };
      previewRevisions.set(project.id, revision);
    } catch { /* A missing preview does not block opening the project. */ }
    finally {
      previewLoads.delete(project.id);
      const current = projects.value.find(item => item.id === project.id);
      if (current && (current.previewRevision || 'empty') !== revision) void loadProjectPreview(current);
    }
  })();
  previewLoads.set(project.id, operation);
  return operation;
}
let libraryRequest: Promise<void> | null = null;
async function loadGlobalLibraries() {
  if (libraryRequest) return libraryRequest;
  libraryLoading.value = true;
  libraryError.value = '';
  libraryRequest = (async () => {
    const results = await Promise.allSettled([
      request<GlobalKnowledgeDocument[]>('/api/knowledge/documents'),
      request<AssetRecord[]>('/api/library/assets'),
    ]);
    if (results[0].status === 'fulfilled') globalKnowledgeDocs.value = results[0].value;
    if (results[1].status === 'fulfilled') globalAssets.value = results[1].value;
    if (results.some(result => result.status === 'rejected')) libraryError.value = '部分资料暂时读取失败，已保留上次加载的内容。';
  })().finally(() => { libraryLoading.value = false; libraryRequest = null; });
  return libraryRequest;
}
watch(projects, list => {
  for (const project of list) if (project.latestTaskStatus) projectTaskStatus.value[project.id] = project.latestTaskStatus;
});

async function createProject() {
  if (!form.value.name.trim()) return;
  isSaving.value = true;
  errorMessage.value = '';
  try {
    const project = await request<Project>('/api/projects', {
      method: 'POST',
      body: JSON.stringify(form.value),
    });
    projects.value = [project, ...projects.value];
    activeProjectId.value = project.id;
    localStorage.setItem(activeProjectStorageKey, project.id);
    workspaceView.value = 'design-agent';
    designConversation.value = project.brief.trim() ? [{ role: 'user', content: project.brief }] : [];
    designChatInput.value = '';
    await Promise.all([loadTasks(project.id), loadDesignCanvas(project.id), loadKnowledge(project.id), loadAssets(project.id)]);
    void loadGlobalLibraries();
    form.value = { name: '', brief: '', budgetMinor: null, currency: 'CNY' };
    isCreating.value = false;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '项目创建失败';
  } finally {
    isSaving.value = false;
  }
}

function detachProjectObservation() {
  // Leaving a project stops only local observation; the server keeps its task.
  taskAbortController.value?.abort();
  for (const controller of canvasTaskControllers.values()) controller.abort();
  canvasTaskControllers.clear();
  taskAbortController.value = null;
  isRunningTask.value = false;
  runningTaskId.value = null;
  runningTaskProjectId.value = null;
}

function selectProject(id: string) {
  detachProjectObservation();
  errorMessage.value = '';
  designCanvasDocument.value = { nodes: [], edges: [] };
  sidebarSection.value = 'projects';
  activeProjectId.value = id;
  localStorage.setItem(activeProjectStorageKey, id);
  workspaceView.value = 'design-agent';
  designConversation.value = [];
  taskHistory.value = [];
  latestTask.value = null;
  void activateComposerDraft(id);
  agentLogs.value = [];
  seenTaskTraceEntries.clear();
  researchSearchResults.value = [];
  failedReferenceImages.value = new Set();
  addAgentLog('已切换到当前项目，正在读取任务上下文。');
  void loadDesignCanvas(id);
  void loadKnowledge(id);
  void loadAssets(id);
  // Load task history once. The previous implementation fetched it both
  // above and here, which doubled stale-project 404s and could race the
  // active-stage calculation.
  void Promise.all([loadTasks(id), loadQueuedMessages(id)]).then(() => {
    if (activeProjectId.value !== id) return;
    restoreDesignConversation(id);
    const running = taskHistory.value.find((task) => task.agentKey === 'design' && task.taskSurface !== 'canvas_node' && ['running', 'queued'].includes(task.status));
    if (running && runningTaskId.value !== running.id) void observeDesignTask(id, running);
    else if (!queueNeedsUserInput(id)) scheduleQueuedMessages(id);
  });
  void loadGlobalLibraries();
}

async function createBlankCanvas() {
  if (isCreating.value) return;
  isCreating.value = true;
  errorMessage.value = '';
  try {
    const project = await request<Project>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name: '未命名项目', brief: '', budgetMinor: null, currency: 'CNY' }),
    });
    projects.value = [project, ...projects.value];
    selectProject(project.id);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新建画布失败，请重试';
  } finally {
    isCreating.value = false;
  }
}

function requestDeleteProject(project: Project) {
  if (!generalSettings.confirmProjectDelete) { void deleteProject(project); return; }
  pendingDeleteProjectId.value = pendingDeleteProjectId.value === project.id ? null : project.id;
  errorMessage.value = '';
}

function cancelDeleteProject() {
  pendingDeleteProjectId.value = null;
}

function requestDeleteAsset(asset: AssetRecord, projectId = asset.projectId) {
  if (!projectId) return;
  if (!generalSettings.confirmAssetDelete) { void deleteAsset({ ...asset, projectId }); return; }
  pendingDeleteAsset.value = { ...asset, projectId };
  pendingDeleteKnowledge.value = null;
  errorMessage.value = '';
}

function cancelDeleteAsset() {
  pendingDeleteAsset.value = null;
}

async function deleteAsset(asset: AssetRecord) {
  const projectId = asset.projectId;
  if (!projectId || isDeletingAsset.value) return;
  isDeletingAsset.value = true;
  errorMessage.value = '';
  try {
    await request(`/api/projects/${projectId}/assets/${asset.id}`, { method: 'DELETE' });
    globalAssets.value = globalAssets.value.filter((item) => !(item.id === asset.id && item.projectId === projectId));
    intakeMentionAssets.value = intakeMentionAssets.value.filter((item) => !(item.id === asset.id && item.projectId === projectId));
    if (activeProjectId.value === projectId) {
      assets.value = assets.value.filter((item) => item.id !== asset.id);
      await loadAssets(projectId);
    }
    pendingDeleteAsset.value = null;
    pushToast(`已删除资产：${assetDisplayName(asset)}`, 'success');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资产删除失败';
  } finally {
    isDeletingAsset.value = false;
  }
}

function requestDeleteKnowledge(document: { id: string; title: string }, scope: 'global' | 'project', projectId?: string) {
  if (scope === 'project' && !projectId) return;
  if (!generalSettings.confirmAssetDelete) { void deleteKnowledge({ ...document, scope, projectId }); return; }
  pendingDeleteKnowledge.value = { id: document.id, title: document.title, scope, projectId };
  pendingDeleteAsset.value = null;
  errorMessage.value = '';
}

function cancelDeleteKnowledge() {
  pendingDeleteKnowledge.value = null;
}

async function deleteKnowledge(document: PendingDeleteKnowledge) {
  if (isDeletingKnowledge.value) return;
  const path = document.scope === 'global'
    ? `/api/knowledge/documents/${document.id}`
    : `/api/projects/${document.projectId}/knowledge/documents/${document.id}`;
  isDeletingKnowledge.value = true;
  errorMessage.value = '';
  try {
    await request(path, { method: 'DELETE' });
    if (document.scope === 'global') {
      globalKnowledgeDocs.value = globalKnowledgeDocs.value.filter((item) => item.id !== document.id);
    } else {
      knowledgeDocs.value = knowledgeDocs.value.filter((item) => item.id !== document.id);
    }
    pendingDeleteKnowledge.value = null;
    pushToast(`已删除知识文档：${document.title}`, 'success');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '知识文档删除失败';
  } finally {
    isDeletingKnowledge.value = false;
  }
}

async function deleteProject(project: Project) {
  if (isDeletingProject.value) return;
  isDeletingProject.value = true;
  errorMessage.value = '';
  try {
    await request(`/api/projects/${project.id}`, { method: 'DELETE' });
    projects.value = projects.value.filter((item) => item.id !== project.id);
    void loadGlobalLibraries();
    pendingDeleteProjectId.value = null;
    if (activeProjectId.value === project.id) startNewIntake();
    void composerDrafts.remove(project.id).catch(() => undefined);
    void queuedMessageStore.remove(queueStorageKey(project.id)).catch(() => undefined);
    loadedMessageQueues.delete(project.id);
    const nextQueues = { ...queuedMessagesByProject.value };
    delete nextQueues[project.id];
    queuedMessagesByProject.value = nextQueues;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '项目删除失败';
  } finally {
    isDeletingProject.value = false;
  }
}

async function loadDesignCanvas(projectId: string) {
  const loadSequence = ++designCanvasLoadSequence;
  try {
    const canvas = await request<DesignCanvasDocument>(`/api/projects/${projectId}/canvas`);
    if (activeProjectId.value === projectId && loadSequence === designCanvasLoadSequence) {
      designCanvasDocument.value = {
        schemaVersion: canvas.schemaVersion,
        lockedNodeIds: canvas.lockedNodeIds || [],
        nodes: Array.isArray(canvas.nodes) ? canvas.nodes : [],
        edges: Array.isArray(canvas.edges) ? canvas.edges : [],
      };
    }
  } catch (error) {
    handleProjectRequestError(projectId, error, '无法读取设计画布');
  }
}

async function loadTasks(projectId: string) {
  try {
    const loadedTasks = await request<TaskRecord[]>(`/api/projects/${projectId}/tasks`);
    taskQueue.replace(projectId, loadedTasks);
    syncTaskTokenUsage(loadedTasks);
    if (activeProjectId.value !== projectId) return;
    taskHistory.value = loadedTasks;
    latestTask.value = taskHistory.value.find(task => task.taskSurface !== 'canvas_node') ?? null;
    // Report/visual tasks can finish while another task becomes the newest
    // row. Include all terminal failures in the live log, then append the
    // latest task for its normal progress trace.
    loadedTasks
      .filter((task) => task.taskSurface !== 'canvas_node' && ['failed', 'cancelled'].includes(task.status))
      .forEach((task) => appendTaskTrace(task));
    appendTaskTrace(latestTask.value);
    const activeTask = taskHistory.value.find((task) => task.taskSurface !== 'canvas_node' && ['running', 'queued', 'pending'].includes(task.status)) || latestTask.value;
    if (activeTask) projectTaskStatus.value = { ...projectTaskStatus.value, [projectId]: activeTask.status };
    for (const task of loadedTasks.filter(task => task.taskSurface === 'canvas_node' && task.canvasNodeId && taskIsActive(task))) {
      if (!canvasTaskControllers.has(task.id)) void observeCanvasNodeTask(projectId, task);
    }
  } catch (error) {
    handleProjectRequestError(projectId, error, '无法读取任务历史');
  }
}

async function refreshRecoveredMedia() {
  const projectId = activeProjectId.value;
  const taskId = inspectedTaskId.value;
  if (!projectId || !taskId) return;
  await Promise.all([loadDesignCanvas(projectId), loadAssets(projectId)]);
  // Read-only observation while the browser checks the recovered media file.
  for (let attempt = 0; attempt < 30 && activeProjectId.value === projectId; attempt++) {
    await loadTasks(projectId);
    if (taskHistory.value.find(task => task.id === taskId)?.output?.structured_data?.deliveryStatus !== 'pending') break;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

function taskIsActive(task: TaskRecord | null | undefined) {
  return Boolean(task && ['queued', 'pending', 'running'].includes(task.status));
}

function rememberBackgroundProject(projectId: string) {
  localStorage.setItem(backgroundProjectStorageKey, projectId);
}

function clearBackgroundProject(projectId?: string) {
  if (!projectId || localStorage.getItem(backgroundProjectStorageKey) === projectId) {
    localStorage.removeItem(backgroundProjectStorageKey);
  }
}

function upsertTaskRecord(projectId: string, task: TaskRecord) {
  if (activeProjectId.value !== projectId) return;
  if (task.replacesTaskId) taskHistory.value = taskHistory.value.filter(item => item.id !== task.replacesTaskId);
  const exists = taskHistory.value.some((item) => item.id === task.id);
  taskHistory.value = exists
    ? taskHistory.value.map((item) => item.id === task.id ? task : item)
    : [task, ...taskHistory.value];
  if (task.taskSurface !== 'canvas_node') {
    latestTask.value = task;
    projectTaskStatus.value = { ...projectTaskStatus.value, [projectId]: task.status };
    appendTaskTrace(task);
  }
  syncTaskTokenUsage([task]);
}

function handleIntakeFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  addIntakeFiles(Array.from(input.files ?? []));
  input.value = '';
}

function removeIntakeFile(index: number) {
  const removed = intakeFiles.value[index];
  if (removed) {
    const key = fileKey(removed);
    const preview = intakeFilePreviews.value[key];
    if (preview) URL.revokeObjectURL(preview);
    const next = { ...intakeFilePreviews.value };
    delete next[key];
    intakeFilePreviews.value = next;
  }
  intakeFiles.value = intakeFiles.value.filter((_, itemIndex) => itemIndex !== index);
  intakeFileResults.value = intakeFileResults.value.filter((_, itemIndex) => itemIndex !== index);
  intakeMentionFiles.value = intakeMentionFiles.value
    .filter((fileIndex) => fileIndex !== index)
    .map((fileIndex) => fileIndex > index ? fileIndex - 1 : fileIndex);
}

function startNewIntake() {
  const previousProjectId = activeProjectId.value;
  const previousProjectHasWork = Boolean(previousProjectId && (
    isRunningTask.value
    || taskHistory.value.some(taskIsActive)
  ));
  detachProjectObservation();
  void activateComposerDraft(null);
  sidebarSection.value = 'home';
  activeProjectId.value = null;
  localStorage.removeItem(activeProjectStorageKey);
  if (previousProjectId && previousProjectHasWork) rememberBackgroundProject(previousProjectId);
  else clearBackgroundProject(previousProjectId ?? undefined);
  workspaceView.value = 'intake';
  intakeMentionQuery.value = '';
  intakeMentionStart.value = null;
  intakeMentionCaret.value = null;
  intakeMentionActiveIndex.value = 0;
  intakeReady.value = false;
  intakeName.value = '';
  Object.values(intakeFilePreviews.value).forEach((url) => URL.revokeObjectURL(url));
  intakeFilePreviews.value = {};
  designConversation.value = [];
  designCanvasDocument.value = { nodes: [], edges: [] };
  errorMessage.value = '';
  agentLogs.value = [];
  seenTaskTraceEntries.clear();
  researchSearchResults.value = [];
  failedReferenceImages.value = new Set();
}

async function createIntakeRecord() {
  const name = intakeName.value.trim() || '新对话';
  if (!intakeBrief.value.trim() && !intakeFiles.value.length) {
    errorMessage.value = '请先输入需求或至少上传一个资料文件。';
    return;
  }
  isCreatingIntake.value = true;
  errorMessage.value = '';
  intakeFileResults.value = [];
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), intakeRequestTimeoutMs);
  try {
    const data = new FormData();
    data.append('name', name);
    data.append('autoTitle', String(!intakeName.value.trim()));
    data.append('brief', intakeBrief.value.trim());
    data.append('currency', form.value.currency || 'CNY');
    if (form.value.budgetMinor !== null && form.value.budgetMinor !== undefined) data.append('budgetMinor', String(form.value.budgetMinor));
    intakeFiles.value.forEach((file) => data.append('files', file, file.name));
    const response = await fetch(`${apiBaseUrl}/api/intake`, { method: 'POST', body: data, signal: controller.signal });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json() as { project: Project; files: typeof intakeFileResults.value };
    projects.value = [result.project, ...projects.value.filter((project) => project.id !== result.project.id)];
    composerDraftKey = result.project.id;
    ++draftActivation;
    void composerDrafts.remove('home').catch(() => undefined);
    activeProjectId.value = result.project.id;
    localStorage.setItem(activeProjectStorageKey, result.project.id);
    intakeName.value = result.project.name;
    intakeFileResults.value = result.files ?? [];
    saveComposerDraft();
    intakeReady.value = true;
    workspaceView.value = 'intake';
    let hydrationTimedOut = false;
    const hydration = Promise.all([loadTasks(result.project.id), loadDesignCanvas(result.project.id), loadKnowledge(result.project.id), loadAssets(result.project.id)]);
    let hydrationTimer: number | undefined;
    const hydrationTimeout = new Promise<void>((resolve) => {
      hydrationTimer = window.setTimeout(() => {
        hydrationTimedOut = true;
        resolve();
      }, 8_000);
    });
    await Promise.race([hydration, hydrationTimeout]);
    if (hydrationTimer !== undefined) window.clearTimeout(hydrationTimer);
    if (hydrationTimedOut) {
      addAgentLog('项目已创建；部分详情读取超时，已保留输入并继续连接 Agent。', 'info');
    }
    void loadGlobalLibraries();
  } catch (error) {
    if ((error instanceof DOMException && error.name === 'AbortError') || error instanceof TypeError) {
      errorMessage.value = localServiceHint;
    } else {
      errorMessage.value = error instanceof Error ? error.message : '需求解析失败';
    }
  } finally {
    window.clearTimeout(timeout);
    isCreatingIntake.value = false;
  }
}

async function uploadComposerDraft(project: Project, draft: ComposerDraft): Promise<ComposerDraft | null> {
  const nextResults = [...draft.results];
  try {
    for (let index = 0; index < draft.files.length; index += 1) {
      const file = draft.files[index];
      if (!file || nextResults[index]?.pathRelative) continue;
      const data = new FormData();
      data.append('file', file, file.name);
      const response = await fetch(`${apiBaseUrl}/api/projects/${project.id}/knowledge/upload`, { method: 'POST', body: data });
      if (!response.ok) throw new Error(await response.text());
      nextResults[index] = await response.json() as IntakeFileResult;
    }
    const next = { ...draft, results: nextResults } as ComposerDraft & { referenceModes?: unknown };
    delete next.referenceModes;
    return next;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '附件上传失败';
    return null;
  }
}

async function uploadPendingIntakeFiles() {
  const project = activeProject.value;
  if (!project) return true;
  const uploaded = await uploadComposerDraft(project, snapshotComposerDraft());
  if (!uploaded) return false;
  intakeFileResults.value = uploaded.results;
  return true;
}

function designTaskReply(task: TaskRecord | null): string {
  const completed = completedDeliveryReply(task?.status, task?.output);
  if (completed) return completed;
  const structured = task?.output?.structured_data || {};
  const answer = structured.answer || structured.llmResponse || structured.content || structured.summary;
  if (typeof answer === 'string' && answer.trim()) return answer.trim();
  const data = structured.contentOutput?.data;
  if (data && typeof data === 'object') {
    const text = (data as Record<string, unknown>).answer || (data as Record<string, unknown>).summary;
    if (typeof text === 'string' && text.trim()) return text.trim();
  }
  if (task?.output?.next_actions?.length) return `已完成本轮判断。下一步：${task.output.next_actions.join('；')}`;
  return task?.status === 'succeeded' ? '本轮设计任务已完成，结果已写入画布。' : 'Agent 暂时没有返回可展示的文字结果。';
}

function normalizeDesignError(value: unknown): string {
  return taskErrorMessage(value);
}

function automaticImageReferenceParams(params: Record<string, any>) {
  const next = { ...params };
  delete next.referenceModes;
  return next;
}

async function handleTaskAction(taskId: string, action: TaskIssue['action']) {
  if (action === 'settings') { openProviderSettings(); return; }
  const project = activeProject.value;
  const task = taskHistory.value.find(item => item.id === taskId);
  if (!project || !task) return;
  if (action === 'inspect') { inspectedTaskId.value = taskId; return; }
  if (isRunningTask.value) return;
  if (action === 'repair') {
    await runDesignTurn(project, '继续原设计任务，仅补齐原计划尚未生成的交付项。保留已保存产物、参考和设计要求，不重复制作，完成后直接保存到画布。', {}, { repairMissingTaskId: taskId });
    return;
  }
  if (action === 'edit') {
    messageEditRequest.value = { taskId, requestId: (messageEditRequest.value?.requestId || 0) + 1 };
    taskFocus.value = { projectId: project.id, taskId, requestId: Date.now() };
    return;
  }
  try {
    const resumed = await request<TaskRecord>(`/api/projects/${project.id}/tasks/${taskId}/retry`, { method: 'POST' });
    if (activeProjectId.value === project.id) await observeDesignTask(project.id, resumed);
  } catch (error) {
    errorMessage.value = error instanceof TypeError ? localServiceHint : taskIssue(error).code !== 'unknown'
      ? normalizeDesignError(error) : error instanceof Error ? error.message : '暂时无法恢复，请稍后继续';
  }
}

async function sendDesignMessage() {
  const message = designChatInput.value.trim() || (intakeFiles.value.length ? '请分析这些资料并给出设计建议。' : '');
  if (message && activeProject.value && !isRunningTask.value) await runDesignTurn(activeProject.value, message);
}

async function resendDesignMessage({ taskId, text }: MessageResubmission): Promise<boolean> {
  const project = activeProject.value;
  const task = taskHistory.value.find(item => item.id === taskId);
  const originalMessage = designConversation.value.find(item => item.taskId === taskId && item.role === 'user');
  if (!project || !task || !originalMessage || !text.trim() || isRunningTask.value) return false;
  const original = task.references || originalMessage.referenceSnapshot || {};
  const references = messageReferences({ text: originalMessage.content, projectId: project.id, apiBaseUrl, snapshot: original,
    assets: globalAssets.value, documents: globalKnowledgeDocs.value, nodes: designCanvasDocument.value.nodes });
  const added = taskReferences({ message: text, projectId: project.id, references, assets: globalAssets.value, documents: globalKnowledgeDocs.value, files: [] });
  const inputs = resubmissionReferences(originalMessage.content, text, original, references, added);
  // Close the editor once the original turn has been updated durably.
  return new Promise(resolve => {
    void runDesignTurn(project, text, {}, { resubmission: inputs, resubmittedTaskId: taskId, onSubmitted: () => resolve(true) })
      .then(resolve).catch(() => resolve(false));
  });
}

function referenceDesignCanvas(value: string, tentative = false) {
  if (!value) return;
  if (!tentative) confirmCanvasReferences();
  const previous = intakeBrief.value;
  const node = designCanvasDocument.value.nodes.find((item) => value === `@node:${item.id}` || value === `@asset:${item.data?.assetId || item.data?.asset?.id}`);
  const assetId = value.startsWith('@asset:') ? value.slice(7) : '';
  const referencedAsset = node?.data?.asset || assets.value.find(asset => asset.id === assetId)
    || globalAssets.value.find(asset => asset.id === assetId && asset.projectId === activeProjectId.value);
  if (referencedAsset) {
    const projectId = referencedAsset.projectId || activeProjectId.value;
    if (!intakeMentionAssets.value.some(asset => asset.id === referencedAsset.id && asset.projectId === projectId)) {
      intakeMentionAssets.value.push({ ...referencedAsset, projectId, nodeId: node?.id });
    } else if (node) {
      const existing = intakeMentionAssets.value.find(asset => asset.id === referencedAsset.id && asset.projectId === projectId);
      if (existing) existing.nodeId = node.id;
    }
  }
  if (referencedAsset) {
    const token = `@asset:${referencedAsset.id}`;
    if (!referencedKeys(intakeBrief.value, inlineReferences.value).has(`asset:${referencedAsset.id}`)) intakeBrief.value = `${intakeBrief.value.trimEnd()} ${token} `.trimStart();
  } else {
    const references: string[] = designChatInput.value.match(/@(asset|node):[A-Za-z0-9_-]+/g) || [];
    if (!references.includes(value)) designChatInput.value = `${designChatInput.value.trim()} ${value} `.trimStart();
  }
  if (tentative) canvasClickReferences.record(previous, intakeBrief.value);
  void nextTick(syncIntakeComposerEditor);
}

function cancelCanvasReferences() {
  const restored = canvasClickReferences.cancel(intakeBrief.value);
  if (restored === intakeBrief.value) return;
  intakeBrief.value = restored;
  syncIntakeMentionsFromText();
  referencePreview.value = null;
  void nextTick(syncIntakeComposerEditor);
}

async function moveDesignNode(id: string, position: { x: number; y: number }) {
  const projectId = activeProjectId.value;
  if (!projectId) return;
  try {
    await request(`/api/projects/${projectId}/agent-tools/canvas_update_node`, { method: 'POST', body: JSON.stringify({ node_id: id, patch: { position } }) });
    const node = designCanvasDocument.value.nodes.find((item) => item.id === id);
    if (node) node.position = position;
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '画布位置保存失败'; }
}

async function generateCanvasNode(kind: 'image' | 'video' | 'audio' | 'text' | 'html' | 'cad' | 'upload', prompt: string, _position: { x: number; y: number }, params: Record<string, any> = {}) {
  const project = params.canvasProjectId ? projects.value.find(item => item.id === params.canvasProjectId) : activeProject.value;
  const { canvasProjectId: _projectId, ...generationParams } = params;
  if (!project || !prompt.trim()) return;
  const labels = { image: '图像', video: '视频', audio: '音频', text: '文本', html: '网页 HTML', cad: 'CAD 模型', upload: '图像' };
  return await runCanvasNodeTask(project, `请在当前空白画布节点中生成${labels[kind]}。\n用户提示词：${prompt}`, { ...generationParams, kind });
}

async function patchCanvasNodeTaskState(projectId: string, nodeId: string, data: Record<string, any>) {
  await request(`/api/projects/${projectId}/agent-tools/canvas_update_node`, {
    method: 'POST', body: JSON.stringify({ node_id: nodeId, patch: { data } }),
  });
}

async function observeCanvasNodeTask(projectId: string, initial: TaskRecord, controller = new AbortController()) {
  const nodeId = initial.canvasNodeId;
  if (!nodeId || canvasTaskControllers.has(initial.id)) return false;
  canvasTaskControllers.set(initial.id, controller);
  let refreshing = false;
  const refresh = async () => {
    if (refreshing || controller.signal.aborted || activeProjectId.value !== projectId) return;
    refreshing = true;
    try { await loadDesignCanvas(projectId); } catch { /* The task observer handles connection recovery. */ } finally { refreshing = false; }
  };
  const timer = window.setInterval(() => { void refresh(); }, 1200);
  try {
    const result = await followTask(`${apiBaseUrl}/api/projects/${projectId}/tasks/${initial.id}`, initial, controller.signal, task => {
      taskQueue.update(projectId, task);
      upsertTaskRecord(projectId, task);
      void refresh();
    });
    await Promise.allSettled([loadDesignCanvas(projectId), loadAssets(projectId)]);
    if (result.status === 'succeeded') void refreshAchievements();
    const node = activeProjectId.value === projectId ? designCanvasDocument.value.nodes.find(item => item.id === nodeId) : undefined;
    const terminalPatch = node && canvasTaskTerminalPatch(result, node.data);
    if (terminalPatch) {
      await patchCanvasNodeTaskState(projectId, nodeId, terminalPatch);
      await loadDesignCanvas(projectId);
    }
    return result.status === 'succeeded';
  } catch (error) {
    if (!controller.signal.aborted) {
      const message = error instanceof Error ? error.message : '节点任务连接中断，重新打开项目后可继续查看';
      pushToast(message, 'error');
      if (activeProjectId.value === projectId) await loadDesignCanvas(projectId).catch(() => undefined);
    }
    return false;
  } finally {
    window.clearInterval(timer);
    if (canvasTaskControllers.get(initial.id) === controller) canvasTaskControllers.delete(initial.id);
  }
}

const guardCanvasSubmission = createCanvasSubmissionGate();
async function runCanvasNodeTask(project: Project, message: string, canvasParams: Record<string, any>): Promise<boolean> {
  return guardCanvasSubmission(project.id, String(canvasParams.canvasNodeId || ''), () => submitCanvasNodeTask(project, message, canvasParams));
}
async function submitCanvasNodeTask(project: Project, message: string, canvasParams: Record<string, any>): Promise<boolean> {
  canvasParams = automaticImageReferenceParams(canvasParams);
  const nodeId = String(canvasParams.canvasNodeId || '');
  if (!nodeId || taskHistory.value.some(task => task.taskSurface === 'canvas_node' && task.canvasNodeId === nodeId && taskIsActive(task))) return false;
  let submitted = false;
  try {
    const previousError = errorMessage.value;
    const providerReady = await ensureTextProvider();
    const providerError = errorMessage.value;
    errorMessage.value = previousError;
    if (!providerReady) throw new Error(providerError || '请先配置文本模型');
    const input = {
      taskSurface: 'canvas_node', canvasNodeId: nodeId,
      referencedSkills: [],
      referencedAssets: (canvasParams.reference_asset_ids || []).map((id: string) => ({ id, projectId: project.id })),
      referencedNodes: [...new Set<string>((canvasParams.reference_node_ids || []) as string[])].map(id => ({ id, projectId: project.id })),
      referencedFiles: [], imageStyle: imageStyle.value, allowExternalNetwork: allowExternalNetwork.value,
      canvasParams: { ...canvasParams, canvasNodeId: nodeId },
      modelRouting: { mode: ['text', 'html', 'cad'].includes(canvasParams.kind) && canvasParams.model ? 'manual' : routingMode.value },
      textProvider: { key: activeTextProvider.value, baseUrl: providerBaseUrl.value, model: canvasTextModel(canvasParams.kind, canvasParams.model, providerModel.value) },
      mediaProvider: {
        threeD: { key: threeDConfigProvider.value, endpoint: threeDConfigEndpoint.value, model: threeDConfigModel.value },
        audio: taskMediaProvider('audio'),
        image: taskMediaProvider('image'),
        video: taskMediaProvider('video'),
      },
    };
    const requestPayload = { agentKey: 'design', workflowStep: 'design', brief: message, async: true, input };
    submitted = true;
    const task = await request<TaskRecord>(`/api/projects/${project.id}/tasks`, {
      method: 'POST', body: JSON.stringify({ ...requestPayload, requestId: crypto.randomUUID() }),
    });
    taskQueue.update(project.id, task);
    upsertTaskRecord(project.id, task);
    if (activeProjectId.value === project.id) await loadDesignCanvas(project.id).catch(() => undefined);
    return await observeCanvasNodeTask(project.id, task);
  } catch (error) {
    const messageText = error instanceof Error ? error.message : '节点生成未能开始';
    const status = Number((error as { status?: number })?.status);
    if (!submitted || status >= 400 && status < 500 && status !== 409) {
      await patchCanvasNodeTaskState(project.id, nodeId, { generating: false, status: '生成失败', error: messageText }).catch(() => undefined);
    } else {
      pushToast('暂时无法确认任务受理状态，请重新打开项目查看原任务，避免重复生成。', 'error');
    }
    if (activeProjectId.value === project.id) await loadDesignCanvas(project.id).catch(() => undefined);
    return false;
  }
}

async function cancelCanvasNodeTask(nodeId: string, taskId: string) {
  const projectId = activeProjectId.value;
  if (!projectId) return;
  try {
    const task = await request<TaskRecord>(`/api/projects/${projectId}/tasks/${taskId}/cancel`, { method: 'POST' });
    taskQueue.update(projectId, task);
    upsertTaskRecord(projectId, task);
    // The server may return a result that finished just before cancellation.
    // Reload the persisted node instead of overwriting it with a local stop state.
    await loadDesignCanvas(projectId);
  } catch (error) {
    pushToast(error instanceof Error ? error.message : '暂时无法确认是否停止，任务状态会继续同步', 'error');
    await loadDesignCanvas(projectId);
  }
}

async function answerReferenceSelection(submission: ReferenceSubmission) {
  const project = activeProject.value;
  if (!project || isRunningTask.value || pendingReferenceSelection(designConversation.value)?.id !== submission.id) return;
  const message = submission.action === 'skip' ? '跳过参考，继续原设计任务。' : submission.action === 'refresh' ? '换一批视觉参考。' : '按已选择的参考方向继续原设计任务。';
  await runDesignTurn(project, message + (submission.notes ? '\n' + submission.notes : ''), {}, { referenceSelection: submission });
}

async function answerDesignClarification({ taskId, answers, entries }: ClarificationSubmission) {
  const project = activeProject.value;
  if (!project || isRunningTask.value || pendingClarification(designConversation.value)?.taskId !== taskId) return;
  await runDesignTurn(project, `根据以下补充信息继续原设计任务。跳过项尚未确定，不视为同意改变已有设计要求。\n\n${answers}`, {}, { clarificationTaskId: taskId, clarificationAnswers: entries });
}

function showDesignTask(projectId: string, task: TaskRecord, animateReply = false) {
  taskQueue.update(projectId, task);
  if (task.taskSurface === 'canvas_node') { upsertTaskRecord(projectId, task); return; }
  if (activeProjectId.value !== projectId) return;
  upsertTaskRecord(projectId, task);
  designConversation.value = replaceConversationTurn(designConversation.value, task);
  designProgress.value = [...(task.trace || [])].reverse().find((event) => event.phase !== 'text')?.message || '正在分析…';
  const existingMessage = designConversation.value.find((item) => item.role === 'assistant' && item.taskId === task.id);
  let content = designLiveText(task.trace, task.output?.structured_data?.answer, existingMessage?.content);
  if (task.status === 'succeeded') content = designTaskReply(task);
  if (task.status === 'failed') content = normalizeDesignError(task.error?.message);
  if (task.status === 'cancelled') content = '已停止发起新的调用。已经提交的请求仍可能完成并产生费用，已保存产物会保留。可查看本轮请求记录核对。';
  const clarification = task.output?.structured_data?.clarification;
  const referenceSelection = task.output?.structured_data?.referenceSelection;
  const steps = designSteps(task.trace || [], task.status);
  const sources = Array.isArray(task.output?.structured_data?.sources) ? task.output.structured_data.sources : [];
  const delivery = task.output?.structured_data?.delivery;
  const artifacts = Array.isArray(delivery?.artifacts) ? delivery.artifacts : [];
  const factStates = artifacts.map((item: any) => item.facts?.status);
  const verification = artifacts.length ? {
    technical: artifacts.every((item: any) => item.ready) && !delivery.pendingMedia?.length ? '产物已保存' : '产物仍在生成',
    content: factStates.includes('source_matched') && !factStates.some((state: string) => ['needs_confirmation', 'illustrative'].includes(state)) ? '技术参数已匹配引用来源' : '',
  } : undefined;
  const message = designConversation.value.find((item) => item.role === 'assistant' && item.taskId === task.id);
  const update: DesignMessage = { role: 'assistant', content, sources, referenceSelection, taskId: task.id, conversationTurnId: task.conversationTurnId || task.id, error: task.status === 'failed', steps, status: task.status, clarification: clarification?.questions?.length ? clarification : undefined,
    animateReply: !['failed', 'cancelled'].includes(task.status) && (animateReply || Boolean(existingMessage?.animateReply)),
    verification, execution: { failureReason: task.error?.message || task.output?.structured_data?.executionError, updates: task.updates, findings: taskDeliveryFindings(task.output?.structured_data, task.error), brief: task.designState?.brief, batch: task.designBatch || delivery?.designBatch, memory: task.conversationMemory, assetBaseUrl: `${apiBaseUrl}/api/projects/${projectId}/assets`, skills: task.skillBindings || [], trace: task.trace, createdAt: task.createdAt, updatedAt: task.updatedAt, deliveryStatus: task.output?.structured_data?.deliveryStatus, deliverables: delivery?.deliverables || task.deliveryProgress, plan: task.designPlan?.deliverables, decisions: Object.values(task.designState?.decisions || {}) }, issue: task.status === 'failed' ? taskIssue(task.error?.message) : task.status === 'cancelled' ? { code: 'cancelled', title: '已停止', message: '', action: 'inspect', actionLabel: '查看已提交请求和计费' } : undefined };
  if (message) Object.assign(message, update);
  else designConversation.value.push(update);
}

function restoreDesignConversation(projectId: string) {
  const history = taskHistory.value.filter((task) => task.agentKey === 'design' && task.taskSurface !== 'canvas_node').reverse().sort((a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
  designConversation.value = [];
  for (const [index, task] of history.entries()) {
    designConversation.value.push({ role: 'user', content: task.userMessage || (index === 0 ? projects.value.find((p) => p.id === projectId)?.brief || '' : '继续设计'), taskId: task.id, conversationTurnId: task.conversationTurnId || task.id, referenceSnapshot: task.references });
    showDesignTask(projectId, task);
  }
}

async function observeDesignTask(projectId: string, initial: TaskRecord, controller = new AbortController()) {
  taskAbortController.value = controller;
  runningTaskId.value = initial.id;
  runningTaskProjectId.value = projectId;
  isRunningTask.value = true;
  let canvasEvents = '';
  let refreshingCanvas = false;
  let completed = false;
  const refreshCanvas = async () => {
    if (refreshingCanvas || controller.signal.aborted) return;
    refreshingCanvas = true;
    try { await loadDesignCanvas(projectId); } finally { refreshingCanvas = false; }
  };
  const canvasTimer = window.setInterval(() => { void refreshCanvas(); }, 1200);
  try {
    const result = await followTask(`${apiBaseUrl}/api/projects/${projectId}/tasks/${initial.id}`, initial, controller.signal, (task) => {
      showDesignTask(projectId, task, true);
      const next = (task.trace || []).filter((entry) => entry.phase === 'tool' && /^(调用工具|工具完成)/.test(entry.message || '')).map((entry) => entry.at).join('|');
      if (next !== canvasEvents) { canvasEvents = next; void refreshCanvas(); }
    }, reconnecting => {
      if (activeProjectId.value !== projectId) return;
      const message = designConversation.value.find(item => item.taskId === initial.id && item.role === 'assistant');
      if (message?.execution) message.execution.reconnecting = reconnecting;
    });
    const sentKey = `sent:${projectId}:${initial.id}`;
    if (result.status === 'failed' && taskIssue(result.error?.message).action !== 'inspect') {
      const saved = await composerDrafts.load(sentKey).catch(() => undefined);
      const draft = await composerDrafts.load(projectId).catch(() => undefined);
      if (saved && !draft?.text && !draft?.files.length) {
        if (activeProjectId.value === projectId && !intakeBrief.value && !intakeFiles.value.length) { applyComposerDraft(saved); saveComposerDraft(); }
        else if (activeProjectId.value !== projectId) void composerDrafts.save(projectId, saved).catch(() => undefined);
      }
    } else { void composerDrafts.remove(sentKey).catch(() => undefined); }
    if (result.output?.provenance?.executionFlow !== 'local_easter_egg') void refreshProjectTitles();
    await Promise.allSettled([loadDesignCanvas(projectId), loadAssets(projectId), loadGlobalLibraries()]);
    if (result.status === 'succeeded') void refreshAchievements();
    clearBackgroundProject(projectId);
    completed = shouldAdvanceQueue(queueTaskResult(result));
    return completed;
  } catch (error) {
    if (stopRequested.value) showDesignTask(projectId, { ...initial, status: 'cancelled' });
    else if (!controller.signal.aborted && activeProjectId.value === projectId) {
      const detail = error instanceof Error ? error.message : '';
      errorMessage.value = /401|missing authentication header/i.test(detail) ? normalizeDesignError(detail) : `进度连接中断，任务已保留。重新打开项目可继续查看。 ${detail}`;
    }
    return false;
  } finally {
    window.clearInterval(canvasTimer);
    if (taskAbortController.value === controller) {
      isRunningTask.value = false;
      taskAbortController.value = null;
      runningTaskId.value = null;
      runningTaskProjectId.value = null;
    }
    if (completed) scheduleQueuedMessages(projectId);
  }
}

async function ensureTextProvider() {
  if (!providers.value.length && !await loadProviders()) {
    errorMessage.value = localServiceHint;
    return false;
  }
  const catalogError = liveModelCatalog.error.value;
  if (catalogError && !textModelOptions.value.length && ['network', 'local_service'].includes(taskIssue(catalogError).code)) {
    errorMessage.value = catalogError;
    return false;
  }
  if (!activeTextProvider.value || (routingMode.value === 'manual' ? !textModelOptions.value.includes(providerModel.value) : !textModelOptions.value.length)) {
    openProviderSettings(isOllamaProvider.value ? '请先启动 Ollama 并同步本机文本模型。' : '请先设置 API Key 和文本模型。');
    return false;
  }
  return true;
}

async function runDesignTurn(project: Project, message: string, canvasParams: Record<string, any> = {}, continuation: { repairMissingTaskId?: string; referenceSelection?: ReferenceSubmission; clarificationTaskId?: string; clarificationAnswers?: ClarificationSubmission['entries']; resubmission?: TaskReferenceSnapshot; resubmittedTaskId?: string; requestId?: string; queuedDraft?: ComposerDraft; onDraftPrepared?: (draft: ComposerDraft) => void | Promise<void>; onSubmitted?: () => void | Promise<void> } = {}): Promise<boolean> {
  canvasParams = automaticImageReferenceParams(canvasParams);
  if (isRunningTask.value) return false;
  errorMessage.value = '';
  stopRequested.value = false;
  isRunningTask.value = true;
  runningTaskProjectId.value = project.id;
  designProgress.value = '正在准备资料…';
  const controller = new AbortController();
  taskAbortController.value = controller;
  try {
    if (!isCosmicFutureQuestion(message) && !await ensureTextProvider()) return false;
    const isContinuation = Boolean(continuation.repairMissingTaskId || continuation.clarificationTaskId || continuation.referenceSelection || continuation.resubmission);
    let sentDraft: ComposerDraft = isContinuation
      ? { text: message, files: [], results: [], assets: [], mentionedFiles: [], skills: [] }
      : continuation.queuedDraft || snapshotComposerDraft();
    if (!canvasParams.canvasNodeId && !isContinuation) {
      const uploaded = await uploadComposerDraft(project, sentDraft);
      if (!uploaded) return false;
      sentDraft = uploaded;
      await continuation.onDraftPrepared?.(sentDraft);
      if (!continuation.queuedDraft) intakeFileResults.value = uploaded.results;
    }
    const sentRevision = draftRevision;
    const input = {
      taskSurface: 'conversation' as const,
      ...(continuation.referenceSelection ? { referenceSelection: continuation.referenceSelection } : {}),
      referencedSkills: selectedSkillMentions(message, sentDraft.skills || intakeSkills.value),
      ...(continuation.repairMissingTaskId ? { repairMissingTaskId: continuation.repairMissingTaskId, referencedAssets: [], referencedNodes: [], referencedFiles: [] } : continuation.resubmission ? { ...continuation.resubmission, resubmittedTaskId: continuation.resubmittedTaskId } : continuation.clarificationTaskId ? {
        clarificationTaskId: continuation.clarificationTaskId, clarificationAnswers: continuation.clarificationAnswers,
        referencedAssets: [], referencedNodes: [], referencedFiles: [],
      } : canvasParams.canvasNodeId ? {
        referencedAssets: (canvasParams.reference_asset_ids || []).map((id: string) => ({ id, projectId: project.id })),
        referencedNodes: [...new Set<string>((canvasParams.reference_node_ids || []) as string[])].map(id => ({ id, projectId: project.id })),
        referencedFiles: [],
      } : taskReferences({message,projectId:project.id,references:composerReferencesForDraft(sentDraft, project.id),
        assets:[...sentDraft.assets,...globalAssets.value],documents:globalKnowledgeDocs.value,
        files:sentDraft.files.map((file,index)=>({filename:file.name,mime:file.type,byteSize:file.size,result:sentDraft.results[index]}))})),
      imageStyle: imageStyle.value, allowExternalNetwork: allowExternalNetwork.value,
      ...(continuation.resubmission ? {} : { canvasParams }),
      modelRouting: { mode: ['text', 'html'].includes(canvasParams.kind) && canvasParams.model ? 'manual' : routingMode.value },
      textProvider: { key: activeTextProvider.value, baseUrl: providerBaseUrl.value, model: ['text', 'html'].includes(canvasParams.kind) && canvasParams.model ? canvasParams.model : providerModel.value },
      mediaProvider: {
        threeD: { key: threeDConfigProvider.value, endpoint: threeDConfigEndpoint.value, model: threeDConfigModel.value },
        audio: taskMediaProvider('audio'),
        image: taskMediaProvider('image'),
        video: taskMediaProvider('video'),
      },
    };
    const editingTaskId = continuation.resubmittedTaskId;
    const requestPayload = { agentKey: 'design', workflowStep: 'design', brief: message, async: true, input };
    let requestId = continuation.requestId;
    const pendingRequestKey = `task-request:${project.id}`;
    if (!editingTaskId && !requestId) {
      const signature = JSON.stringify(requestPayload);
      const pending = await pendingTaskRequests.load(pendingRequestKey).catch(() => undefined);
      requestId = pending?.signature === signature ? pending.requestId : crypto.randomUUID();
      await pendingTaskRequests.save(pendingRequestKey, { requestId, signature });
    }
    const task = await request<TaskRecord>(`/api/projects/${project.id}/tasks${editingTaskId ? `/${editingTaskId}` : ''}`, { method: editingTaskId ? 'PATCH' : 'POST', signal: controller.signal, body: JSON.stringify(editingTaskId ? requestPayload : { ...requestPayload, requestId }) });
    if (!editingTaskId && !continuation.requestId) void pendingTaskRequests.remove(pendingRequestKey).catch(() => undefined);
    if (task.id) celebrateFirstUse();
    void composerDrafts.save(`sent:${project.id}:${task.id}`, { ...sentDraft, text: message }).catch(() => undefined);
    rememberBackgroundProject(project.id);
    if (activeProjectId.value === project.id) {
      if (editingTaskId) showDesignTask(project.id, task);
      else designConversation.value.push({ role: 'user', content: message, taskId: task.id, conversationTurnId: task.conversationTurnId || task.id, referenceSnapshot: task.references || { referencedAssets: input.referencedAssets, referencedFiles: input.referencedFiles, referencedNodes: input.referencedNodes, referencedSkills: input.referencedSkills } });
      if (!canvasParams.canvasNodeId && !continuation.clarificationTaskId && !continuation.referenceSelection && !continuation.resubmission && !continuation.queuedDraft) {
        if (draftRevision === sentRevision) { applyComposerDraft(); saveComposerDraft(); }
        intakeReady.value = false;
      }
    }
    await continuation.onSubmitted?.();
    if (stopRequested.value) {
      showDesignTask(project.id, await request<TaskRecord>(`/api/projects/${project.id}/tasks/${task.id}/cancel`, { method: 'POST' }));
      return false;
    }
    return await observeDesignTask(project.id, task, controller);
  } catch (error) {
    if (activeProjectId.value === project.id && !controller.signal.aborted) {
      const detail = error instanceof Error ? error.message : '消息发送失败，请重试。';
      const issue = taskIssue(error);
      errorMessage.value = error instanceof TypeError ? localServiceHint : issue.code !== 'unknown' ? normalizeDesignError(error) : detail;
    }
    return false;
  } finally {
    if (taskAbortController.value === controller) {
      isRunningTask.value = false; taskAbortController.value = null; runningTaskProjectId.value = null;
    }
  }
}

const queuedMessageTimers = new Map<string, number>();

function queueNeedsUserInput(projectId: string) {
  return activeProjectId.value === projectId && Boolean(activeQueuePauseReason.value || pendingReferenceSelection(designConversation.value) || pendingClarification(designConversation.value));
}

function scheduleQueuedMessages(projectId: string) {
  if (queuedMessageTimers.has(projectId)) return;
  const timer = window.setTimeout(() => {
    queuedMessageTimers.delete(projectId);
    void runNextQueuedMessage(projectId);
  }, 0);
  queuedMessageTimers.set(projectId, timer);
}

async function replaceQueuedMessageDraft(projectId: string, messageId: string, draft: ComposerDraft) {
  const messages = queuedMessagesByProject.value[projectId] || [];
  if (!messages.some(item => item.id === messageId)) return;
  await persistQueuedMessages(projectId, messages.map(item => item.id === messageId ? { ...item, draft } : item));
}

async function removeQueuedMessage(projectId: string, messageId: string) {
  const messages = queuedMessagesByProject.value[projectId] || [];
  await persistQueuedMessages(projectId, messages.filter(item => item.id !== messageId));
}

async function enqueueComposerMessage(): Promise<boolean> {
  const project = activeProject.value;
  if (!project) return false;
  const message = designChatInput.value.trim() || (intakeFiles.value.length ? '请分析这些资料并给出设计建议。' : '');
  if (!message) return false;
  const draft = { ...snapshotComposerDraft(), text: message };
  try {
    const messages = await loadQueuedMessages(project.id);
    await persistQueuedMessages(project.id, [...messages, createQueueMessage(message, draft)]);
    applyComposerDraft();
    saveComposerDraft();
    intakeReady.value = false;
    pushToast(`已加入队列 · 第 ${messages.length + 1} 项`, 'success');
    return true;
  } catch {
    errorMessage.value = '消息队列暂时无法保存，请保留当前输入后重试。';
    return false;
  }
}

async function moveQueuedMessage(messageId: string, offset: number) {
  const projectId = activeProjectId.value;
  if (!projectId) return;
  const messages = await loadQueuedMessages(projectId);
  const fromIndex = messages.findIndex(item => item.id === messageId);
  const next = moveQueueItem(messages, fromIndex, fromIndex + offset);
  if (next.every((item, index) => item === messages[index])) return;
  await persistQueuedMessages(projectId, next).catch(() => { errorMessage.value = '队列顺序暂时无法保存。'; });
}

function beginQueuedMessageDrag(messageId: string, event: DragEvent) {
  queuedMessageDragId.value = messageId;
  event.dataTransfer?.setData('text/plain', messageId);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
}

async function dropQueuedMessage(targetId: string) {
  const projectId = activeProjectId.value;
  const draggedId = queuedMessageDragId.value;
  queuedMessageDragId.value = null;
  if (!projectId || !draggedId || draggedId === targetId) return;
  const messages = await loadQueuedMessages(projectId);
  const fromIndex = messages.findIndex(item => item.id === draggedId);
  const toIndex = messages.findIndex(item => item.id === targetId);
  await persistQueuedMessages(projectId, moveQueueItem(messages, fromIndex, toIndex)).catch(() => { errorMessage.value = '队列顺序暂时无法保存。'; });
}

async function saveQueuedMessageEdit(message: QueuedMessage) {
  const projectId = activeProjectId.value;
  const text = queuedEditText.value.trim();
  if (!projectId || !text) return;
  try {
    const messages = await loadQueuedMessages(projectId);
    await persistQueuedMessages(projectId, messages.map(item => item.id === message.id ? { ...item, text, draft: { ...item.draft, text } } : item));
    editingQueuedMessage.value = null;
    if (!queueNeedsUserInput(projectId)) scheduleQueuedMessages(projectId);
  } catch { errorMessage.value = '修改暂时无法保存，输入已保留。'; }
}

async function removeActiveQueuedMessage(messageId: string) {
  const projectId = activeProjectId.value;
  if (!projectId) return;
  await removeQueuedMessage(projectId, messageId).catch(() => { errorMessage.value = '暂时无法删除队列消息。'; });
}

function queuedMessageMeta(message: QueuedMessage) {
  const details: string[] = [];
  if (message.draft.files.length) details.push(`${message.draft.files.length} 个附件`);
  if (message.draft.assets.length) details.push(`${message.draft.assets.length} 个引用`);
  if (message.draft.skills?.length) details.push(`${message.draft.skills.length} 个技能`);
  return details.join(' · ') || '纯文本';
}

async function runNextQueuedMessage(projectId = activeProjectId.value || '') {
  if (!projectId || activeProjectId.value !== projectId || isRunningTask.value || sendingSupplement.value || dispatchingMessageQueues.has(projectId) || queueNeedsUserInput(projectId)) return;
  const project = projects.value.find(item => item.id === projectId);
  if (!project) return;
  dispatchingMessageQueues.add(projectId);
  try {
    await loadQueuedMessages(projectId);
    while (true) {
      const messages = queuedMessagesByProject.value[projectId] || [];
      if (!canDispatchQueue({ activeProject: activeProjectId.value === projectId, running: isRunningTask.value, awaitingInput: queueNeedsUserInput(projectId), dispatching: false, hasMessages: Boolean(messages.length) })) break;
      const message = messages[0];
      if (!queueItemCanStart(message, editingQueuedMessage.value, sendingSupplement.value)) break;
      let submitted = false;
      const completed = await runDesignTurn(project, message.text, {}, {
        requestId: message.id,
        queuedDraft: message.draft,
        onDraftPrepared: async draft => {
          await replaceQueuedMessageDraft(projectId, message.id, draft).catch(() => { errorMessage.value = '附件已就绪，但队列状态暂时无法保存。'; });
        },
        onSubmitted: async () => {
          submitted = true;
          await removeQueuedMessage(projectId, message.id).catch(() => { errorMessage.value = '消息已发送，但队列状态暂时无法保存。'; });
        },
      });
      if (!submitted || !completed) break;
    }
  } finally {
    dispatchingMessageQueues.delete(projectId);
  }
}

async function handoffIntake() {
  const project = activeProject.value;
  if (!project) return;
  // The homepage can be submitted before the initial Provider request has
  // completed. Refresh it here so a configured gateway is not mistaken for a
  // missing credential during the handoff.
  if (!await ensureTextProvider()) return;
  if (!await uploadPendingIntakeFiles()) return;
  designConversation.value = [];
  workspaceView.value = 'design-agent';
  await runDesignTurn(project, project.brief);
}

async function supplementCurrentTask(queued?: QueuedMessage) {
  const projectId = activeProjectId.value;
  const taskId = queued?.supplementTaskId || runningTaskId.value;
  const text = (queued?.text || designChatInput.value).trim();
  if (!projectId || !taskId || !text || sendingSupplement.value) return;
  if (!queued?.supplementTaskId && (!isRunningTask.value || runningTaskProjectId.value !== projectId)) return;
  const unavailable = supplementUnavailableReason(queued?.draft || snapshotComposerDraft());
  if (unavailable) { errorMessage.value = unavailable; return; }
  sendingSupplement.value = true;
  const revision = draftRevision;
  const key = queued ? `queue-update:${queued.id}` : `task-update:${taskId}`;
  try {
    const pending = await pendingTaskRequests.load(key).catch(() => undefined);
    const requestId = queued ? `queue-update:${queued.id}` : pending?.signature === text ? pending.requestId : crypto.randomUUID();
    if (queued) {
      const messages = queuedMessagesByProject.value[projectId] || [];
      await persistQueuedMessages(projectId, messages.map(item => item.id === queued.id ? { ...item, supplementTaskId: taskId } : item));
    }
    await pendingTaskRequests.save(key, { requestId, signature: text });
    await request(`/api/projects/${projectId}/tasks/${taskId}/updates`, { method: 'POST', body: JSON.stringify({ requestId, text }) });
    await pendingTaskRequests.remove(key);
    if (queued) await removeQueuedMessage(projectId, queued.id);
    else if (activeProjectId.value === projectId && draftRevision === revision) { applyComposerDraft(); saveComposerDraft(); }
    const task = await request<TaskRecord>(`/api/projects/${projectId}/tasks/${taskId}`);
    if (activeProjectId.value === projectId) showDesignTask(projectId, task);
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '补充未确认送达，输入已保留。'; }
  finally { sendingSupplement.value = false; }
}

async function submitComposer() {
  if (designDemo.active.value || showcasePlayback.active.value) return;
  confirmCanvasReferences();
  if (isRunningTask.value && workspaceView.value !== 'design-agent') return;
  syncIntakeMentionsFromText();
  if (!activeProject.value) { await createIntakeRecord(); if (activeProject.value) await handoffIntake(); return; }
  if (workspaceView.value === 'intake') { if (!intakeReady.value) await createIntakeRecord(); if (intakeReady.value) await handoffIntake(); return; }
  if (workspaceView.value === 'design-agent') {
    if (isRunningTask.value && composerRunMode.value === 'supplement' && !supplementUnavailableReason(snapshotComposerDraft())) { await supplementCurrentTask(); return; }
    const messages = await loadQueuedMessages(activeProject.value.id);
    if (!isRunningTask.value && activeQueuePauseReason.value) { await sendDesignMessage(); return; }
    if (isRunningTask.value || messages.length) {
      const queued = await enqueueComposerMessage();
      if (queued && !isRunningTask.value) scheduleQueuedMessages(activeProject.value.id);
      return;
    }
    await sendDesignMessage();
  }
}

async function loadKnowledge(projectId: string) {
  try {
    knowledgeDocs.value = await request(`/api/projects/${projectId}/knowledge/documents`);
  } catch (error) {
    handleProjectRequestError(projectId, error, '无法读取知识文档');
  }
}

async function loadAssets(projectId: string) {
  try {
    assets.value = await request(`/api/projects/${projectId}/assets`);
  } catch (error) {
    handleProjectRequestError(projectId, error, '无法读取项目资产');
  }
}

async function loadProviders(): Promise<boolean> {
  try {
    providers.value = await requestWithTimeout('/api/providers', undefined, 3500);
    const selectedKey = credentialProviderOptions.value.some((provider) => provider.key === selectedCredentialProvider.value)
      ? selectedCredentialProvider.value
      : 'openrouter';
    if (selectedCredentialProvider.value !== selectedKey) selectedCredentialProvider.value = selectedKey;
    return true;
  } catch {
    // Provider availability is a passive startup status. Do not turn a
    // missing/unreachable configuration into a scary toast before the user
    // has submitted anything; submission guards surface the actionable prompt
    // and open the settings page when configuration is actually needed.
    providers.value = [];
    return false;
  }
}

function openProviderSettings(message: unknown = '') {
  // A bare @click="openProviderSettings" passes the PointerEvent as the
  // first argument. Only carry forward an intentional string prompt; never
  // render the event object as "[object PointerEvent]" in the settings page.
  const prompt = typeof message === 'string' ? message : '';
  providerTestResult.value = '';
  openSettings('text');
  const selectedKey = selectedCredentialProvider.value || selectedTextProvider.value || 'openrouter';
  if (!isSavingProvider.value) applyProviderProfile(selectedKey);
  showAssistantCard.value = false;
  // Keep an actionable submission-time prompt visible after opening the page.
  errorMessage.value = prompt;
  if (!providers.value.length) {
    void loadProviders().then(() => {
      if (isProviderSettingsOpen.value) applyProviderProfile(selectedCredentialProvider.value || 'openrouter');
    });
  }
}

function handleCredentialProviderChange() {
  const providerKey = credentialTargetProvider.value || 'openrouter';
  applyProviderProfile(providerKey);
  providerTestResult.value = '';
}

function selectCredentialProvider(providerKey: string) {
  selectedCredentialProvider.value = providerKey;
  handleCredentialProviderChange();
}

function openSettings(section: SettingsSection = 'account') {
  if (workspaceView.value !== 'settings') settingsReturnPath.value = router.currentRoute.value.fullPath;
  closeUserSummary();
  showAssistantCard.value = false;
  showComposerAgentMenu.value = false;
  showComposerStyleMenu.value = false;
  void router.push('/settings/' + section);
}

function closeSettings() {
  void router.push(settingsReturnPath.value.startsWith('/settings') || settingsReturnPath.value === '/account' ? '/' : settingsReturnPath.value);
}

function openUserCenter() { openSettings('account'); }
function closeUserCenter() { closeSettings(); }

function openHelpCenter() {
  openSettings('help');
}

function saveUserProfile() {
  userProfileSaving.value = true;
  const nickname = userNickname.value.trim() || 'Avery Chen';
  const bio = userBio.value.trim() || '用文化线索做当代产品，让每个灵感都能落地。';
  userNickname.value = nickname;
  userBio.value = bio;
  localStorage.setItem('langjuart.userNickname', nickname);
  localStorage.setItem('langjuart.userBio', bio);
  localStorage.setItem('langjuart.userAvatarIndex', String(userAvatarIndex.value));
  window.setTimeout(() => {
    userProfileSaving.value = false;
    pushToast('个人资料已保存。', 'success');
  }, 180);
}

async function requestWithTimeout<T>(path: string, init?: RequestInit, timeoutMs = 12000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request<T>(path, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error(localServiceHint);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function validateProviderSettings() {
  const baseUrl = providerBaseUrl.value.trim();
  const secret = providerSecret.value.trim();
  const isConfigured = Boolean(providers.value.find((provider) => provider.key === credentialTargetProvider.value)?.configured);
  if (!baseUrl) {
    errorMessage.value = credentialTargetProvider.value === 'openai-compatible' ? '请先填写中转站 Base URL。' : '请先填写 Provider Base URL。';
    return null;
  }
  try {
    const parsed = new URL(baseUrl);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('protocol');
  } catch {
    errorMessage.value = 'Base URL 格式不正确，请填写 http:// 或 https:// 地址。';
    return null;
  }
  if (selectedProviderRequiresKey.value && !secret && !isConfigured) {
    errorMessage.value = '请先填写 API Key，再探测并保存模型设置。';
    return null;
  }
  return { baseUrl, secret };
}

function persistProviderProfile() {
  const providerKey = credentialTargetProvider.value || selectedTextProvider.value || 'openrouter';
  const profile: SavedProviderProfile = {
    providerKey,
    baseUrl: providerBaseUrl.value.trim() || providerDefaultBaseUrl(providerKey),
    textModel: providerModel.value.trim(),
    imageModel: imageModel.value.trim(),
    videoModel: videoModel.value.trim(),
    threeDModel: threeDConfigModel.value.trim(),
    models: [...new Set(detectedAllModels.value.map(String).filter(Boolean))],
    textModels: [...new Set(detectedTextModels.value.map(String).filter(Boolean))],
    imageModels: [...new Set(detectedImageModels.value.map(String).filter(Boolean))],
    modelCatalog: detectedModelCatalog.value,
    detectedAt: liveModelCatalog.savedAt.value || undefined,
  };
  providerProfiles.value = { ...providerProfiles.value, [providerKey]: profile };
  localStorage.setItem('aics.providerProfiles', JSON.stringify(providerProfiles.value));
}

function persistProviderSettings() {
  localStorage.setItem('aics.providerBaseUrl', providerBaseUrl.value.trim());
  localStorage.setItem('aics.providerModel', providerModel.value.trim());
  localStorage.setItem('aics.threeDProvider', threeDConfigProvider.value);
  localStorage.setItem('aics.threeDEndpoint', threeDConfigEndpoint.value.trim());
  localStorage.setItem('aics.threeDModel', threeDConfigModel.value.trim());
  localStorage.setItem('aics.videoProvider', videoConfigProvider.value);
  localStorage.setItem('aics.videoEndpoint', videoConfigEndpoint.value.trim());
  localStorage.setItem('aics.videoModel', videoConfigModel.value.trim());
  localStorage.setItem('aics.imageProvider', imageProvider.value);
  localStorage.setItem('aics.imageModel', imageModel.value);
  renderModel.value = imageModel.value;
  localStorage.setItem('aics.detectedTextModels', JSON.stringify(detectedTextModels.value));
  localStorage.setItem('aics.detectedImageModels', JSON.stringify(detectedImageModels.value));
  localStorage.setItem('aics.detectedAllModels', JSON.stringify(detectedAllModels.value));
  localStorage.setItem('aics.detectedModelCatalog', JSON.stringify({ models: detectedModelCatalog.value }));
  persistProviderProfile();
  threeDProvider.value = threeDConfigProvider.value;
  threeDEndpoint.value = threeDConfigEndpoint.value.trim();
  videoProvider.value = videoConfigProvider.value;
  videoEndpoint.value = videoConfigEndpoint.value.trim();
  videoModel.value = videoConfigModel.value.trim();
}

async function detectAndSaveProviderSettings() {
  const values = validateProviderSettings();
  if (!values) return;
  isSavingProvider.value = true;
  ++localCatalogSequence;
  try {
    // Only this explicit save (or settings refresh) contacts /models.
    const detected = await detectProviderModels(values.secret, { saveCredential: true, saveCatalogCredential: true });
    if (!detected) return;
    if (values.secret) {
      providerSecret.value = '';
    }
    if (closeAICatalogSecret.value.trim()) closeAICatalogSecret.value = '';
    await loadProviders();
    selectedTextProvider.value = credentialTargetProvider.value;
    localStorage.setItem('aics.credentialProvider', credentialTargetProvider.value);
    localStorage.setItem('aics.textProvider', selectedTextProvider.value);
    if (!isOllamaProvider.value) {
      imageProvider.value = credentialTargetProvider.value;
      videoProvider.value = videoConfigProvider.value = credentialTargetProvider.value;
      videoEndpoint.value = videoConfigEndpoint.value = providerBaseUrl.value;
    } else {
      routingMode.value = 'manual';
    }
    if (credentialTargetProvider.value === 'evolink' && !liveModelCatalog.data.value.routeAvailability?.autoReady) {
      routingMode.value = 'manual';
    }
    if (credentialTargetProvider.value === 'evolink') {
      // EvoLink route IDs can differ from the product's default media IDs.
      // Keep the actual catalog selections in Agent and canvas requests.
      imageModelManual.value = videoModelManual.value = true;
      localStorage.setItem('aics.imageModelManual', 'true');
      localStorage.setItem('aics.videoModelManual', 'true');
    }
    persistProviderSettings();
    providerTestResult.value = `设置已保存。${settingsCatalogMessage.value}`;
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '设置保存失败'; }
  finally { isSavingProvider.value = false; }
}

async function detectProviderModels(secretOverride?: string, { silent = false, saveCredential = false, saveCatalogCredential = false } = {}): Promise<boolean> {
  if (!silent) { providerTestResult.value = ''; errorMessage.value = ''; }
  if (!providerBaseUrl.value.trim() || (selectedProviderRequiresKey.value && !secretOverride?.trim() && !providerSecret.value.trim() && !selectedProviderStatus.value?.configured)) return false;
  const source = { provider: credentialTargetProvider.value, baseUrl: providerBaseUrl.value.trim(), saveCredential,
    secret: secretOverride?.trim() || providerSecret.value.trim() || undefined,
    catalogSecret: isCloseAIEndpoint.value ? closeAICatalogSecret.value.trim() || undefined : undefined,
    saveCatalogCredential: isCloseAIEndpoint.value && saveCatalogCredential };
  ++localCatalogSequence;
  const loaded = await liveModelCatalog.refresh(source);
  if (!loaded) {
    if (!silent && liveModelCatalog.error.value) errorMessage.value = liveModelCatalog.error.value;
    return false;
  }
  selectSavedModels();
  persistProviderSettings();
  if (!silent) providerTestResult.value = modelCatalogMessage.value;
  return true;
}

function saveAppearanceSettings() {
  providerTestResult.value = '';
  errorMessage.value = '';
  applyTheme();
  localStorage.setItem('aics.allowExternalNetwork', String(allowExternalNetwork.value));
  providerTestResult.value = '外观与流程设置已保存。';
}

function switchSettingsTab(tab: typeof settingsTab.value) {
  openSettings(tab);
}

async function loadRuntimeComponents() {
  runtimeComponentMessage.value = '';
  if (!window.studio?.runtimeComponents) {
    runtimeComponents.value = [];
    runtimeComponentMessage.value = isDesktopApp ? '当前构建不是轻量版，无需额外安装能力组件。' : '网页开发模式使用本机 API 环境，不管理桌面能力组件。';
    return;
  }
  try {
    runtimeComponents.value = await window.studio.runtimeComponents();
    if (!runtimeComponents.value.length) runtimeComponentMessage.value = '当前是完整版本，所有本地能力已经随应用安装。';
  } catch (reason) {
    runtimeComponentMessage.value = reason instanceof Error ? reason.message : '无法读取能力组件状态。';
  }
}

function formatComponentSize(bytes: number) {
  return bytes > 1024 ** 2 ? `${Math.round(bytes / 1024 / 1024)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

async function installRuntimeComponent(component: RuntimeComponentState) {
  if (!window.studio?.installRuntimeComponent || runtimeComponentLoading.value) return;
  runtimeComponentLoading.value = component.id;
  runtimeComponentMessage.value = component.available ? `正在下载并校验“${component.label}”…` : `请选择与当前版本配套的“${component.label}”能力包。`;
  try {
    const result = await window.studio.installRuntimeComponent(component.id);
    runtimeComponents.value = result.components;
    runtimeComponentMessage.value = result.cancelled ? '已取消安装。' : `“${component.label}”已安装，本地服务已自动重启。`;
    if (!result.cancelled) pushToast(`${component.label}已可以使用。`, 'success');
  } catch (reason) {
    runtimeComponentMessage.value = reason instanceof Error ? reason.message : '能力组件安装失败。';
  } finally {
    runtimeComponentLoading.value = '';
  }
}

function handleSettingsSubmit() {
  if (settingsTab.value === 'text') {
    void detectAndSaveProviderSettings();
  } else if (settingsTab.value === 'appearance') {
    saveAppearanceSettings();
  }
}

async function uploadGlobalKnowledge(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  isUploadingGlobalKnowledge.value = true;
  errorMessage.value = '';
  try {
    const data = new FormData();
    data.append('file', file);
    const response = await fetch(`${apiBaseUrl}/api/knowledge/upload`, { method: 'POST', body: data });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json() as GlobalKnowledgeDocument;
    await loadGlobalLibraries();
    input.value = '';
    const chunkLabel = result.chunkCount ? `已生成 ${result.chunkCount} 个文本片段` : '暂未生成可检索文本';
    const visualLabel = result.partCount ? `，识别 ${result.partCount} 个页面或图片子资源` : '';
    pushToast(result.warning ? `${file.name} 已处理：${chunkLabel}${visualLabel}。${result.warning}` : `${file.name} 上传完成，${chunkLabel}${visualLabel}。`, result.warning ? 'info' : 'success');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '知识库文档导入失败';
  } finally {
    isUploadingGlobalKnowledge.value = false;
  }
}

async function reindexGlobalKnowledge() {
  if (!globalKnowledgeDocs.value.length || isReindexingGlobalKnowledge.value) return;
  isReindexingGlobalKnowledge.value = true;
  errorMessage.value = '';
  try {
    const result = await request<{ indexedChunks?: number; upgradedDocuments?: number; extractedParts?: number; warnings?: string[] }>('/api/knowledge/reindex', { method: 'POST' });
    await loadGlobalLibraries();
    const upgraded = result.upgradedDocuments ? ` · 升级 ${result.upgradedDocuments} 份旧文档` : '';
    const parts = result.extractedParts ? ` · 补提 ${result.extractedParts} 个页面或图片` : '';
    pushToast(`文档解析与索引已就绪${result.indexedChunks ? ` · ${result.indexedChunks} 个文本片段` : ''}${upgraded}${parts}。`, result.warnings?.length ? 'info' : 'success');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'RAG 向量索引重建失败';
  } finally {
    isReindexingGlobalKnowledge.value = false;
  }
}

async function stopAgent() {
  if ((!isRunningTask.value) || isStoppingTask.value) return;
  isStoppingTask.value = true;
  stopRequested.value = true;
  const projectId = runningTaskProjectId.value || activeProject.value?.id;
  const taskId = runningTaskId.value || latestTask.value?.id;
  const hasActiveTask = isRunningTask.value && Boolean(runningTaskId.value);
  if (projectId && taskId && hasActiveTask) {
    try {
      latestTask.value = await request<TaskRecord>(`/api/projects/${projectId}/tasks/${taskId}/cancel`, { method: 'POST' });
      // Abort only after the durable cancel request has landed. This avoids
      // racing the polling request and losing the terminal cancelled trace.
      taskAbortController.value?.abort();
      appendTaskTrace(latestTask.value);
      if (activeProjectId.value === projectId) taskHistory.value = taskHistory.value.map((task) => task.id === latestTask.value?.id ? latestTask.value : task);
      addAgentLog('已停止发起新的调用；已提交给服务商的请求仍可能产生费用，系统会保留待核对记录。', 'error');
      pushToast('任务已停止。', 'info');
    } catch (error) {
      if (projectId) handleProjectRequestError(projectId, error, '停止任务失败');
    }
  } else if (isRunningTask.value && !runningTaskId.value) {
    // The POST that creates an async task is still in flight. Do not abort it:
    // runAgent checks stopRequested after the response and cancels the durable
    // task as soon as its ID is available.
    addAgentLog('已登记停止请求，等待任务 ID 后取消。', 'info');
  } else {
    taskAbortController.value?.abort();
    addAgentLog('已停止当前运行。', 'info');
  }
  if (projectId) clearBackgroundProject(projectId);
  isRunningTask.value = false;
  isStoppingTask.value = false;
}

const { router } = useWorkspaceNavigation({ workspaceView, sidebarSection, activeProjectId, projects, catalogReady: projectCatalogReady, selectProject, startNewIntake, loadLibraries: () => { void refreshProjectTitles(); void loadGlobalLibraries(); }, missingProject: () => pushToast('该项目不存在或已被删除，请从项目列表重新选择。', 'info') });
watch(() => router.currentRoute.value.fullPath, () => {
  closeUserSummary();
  if (router.currentRoute.value.meta.view !== 'settings') { settingsHostReady.value = false; return; }
  const section = String(router.currentRoute.value.params.section);
  settingsTab.value = settingsTabs.find(tab => tab.key === section)?.key || 'account';
  providerTestResult.value = '';
  if (settingsTab.value === 'account') void refreshTokenUsageFromWorkspace();
  if (settingsTab.value === 'components') void loadRuntimeComponents();
  if (settingsTab.value === 'text' && !isSavingProvider.value) {
    applyProviderProfile(selectedCredentialProvider.value || 'openrouter');
    if (!providers.value.length) void loadProviders();
  }
}, { immediate: true });
provide(settingsServices.key, { current: settingsTab, tabs: settingsTabs, select: switchSettingsTab, close: closeSettings, ready: mounted => { settingsHostReady.value = mounted; } });

const designDemo = useDesignDemoPlayback({ apiBaseUrl, projects, projectId: activeProjectId,
  visible: () => workspaceView.value === 'design-agent', board: designCanvasDocument, selectProject,
  updateBoard: document => { designCanvasLoadSequence += 1; designCanvasDocument.value = document; },
  saved: id => { void loadAssets(id); void loadGlobalLibraries(); },
});
const showcasePlayback = useShowcasePlayback({ projects, projectId: activeProjectId,
  visible: () => workspaceView.value === 'design-agent', board: designCanvasDocument, selectProject,
});
const activePlayback = computed(() => designDemo.active.value ? designDemo : showcasePlayback.active.value ? showcasePlayback : null);
const composerHostReady = ref(false);

watch([workspaceView, activeProjectId], () => {
  composerHostReady.value = false;
  showComposerAgentMenu.value = false;
  showAssistantCard.value = false;
}, { flush: 'sync' });

function markComposerReady() { composerHostReady.value = true; designComposerEpoch.value += 1; }

provide(homeServices.key, { greetingCopy, errorMessage: computed(() => errorMessage.value || designDemo.error.value || showcasePlayback.error.value), isSubmitting: computed(() => isCreatingIntake.value || designDemo.preparing.value || showcasePlayback.preparing.value), showcaseSlugs: computed(() => readyShowcaseSlugs(projects.value)), startDemo: id => { void designDemo.open(id); }, openFeaturedProject: slug => { showcasePlayback.open(slug); }, addFiles: handleDroppedIntakeFiles, composerReady: markComposerReady, useExample: async (prompt) => {
  if (!intakeBrief.value.includes(prompt)) intakeBrief.value = intakeBrief.value.trim() ? `${intakeBrief.value.trimEnd()}\n\n${prompt}` : prompt;
  await nextTick();
  syncIntakeComposerEditor();
  intakeComposerRef.value?.focus({ preventScroll: true });
  setIntakeComposerCaret(intakeBrief.value.length);
  intakeComposerRef.value?.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
} });

provide(projectLibraryServices.key, { projects, isLoading, errorMessage, apiBaseUrl, projectCanvasPreviews, loadPreview: loadProjectPreview, selectProject, createBlankCanvas, renameProject, requestDeleteProject });

provide(assetLibraryServices.key, { loadState: libraryLoadState, globalAssets, apiBaseUrl, assetDisplayName, requestDeleteAsset, openProject: selectProject });

provide(skillLibraryServices.key, { apiBaseUrl, createInChat: async (skill) => {
  startNewIntake();
  await activateComposerDraft(null);
  await router.push('/');
  intakeBrief.value = skillChatPrompt(intakeBrief.value, skill);
  await nextTick();
  syncIntakeComposerEditor();
  intakeComposerRef.value?.focus({ preventScroll: true });
  setIntakeComposerCaret(intakeBrief.value.length);
} });
provide(knowledgeLibraryServices.key, { loadState: libraryLoadState, apiBaseUrl, globalKnowledgeDocs, isUploadingGlobalKnowledge, isReindexingGlobalKnowledge, uploadGlobalKnowledge, reindexGlobalKnowledge, deleteDocument: document => requestDeleteKnowledge(document, 'global') });

provide(helpServices.key, { appVersion });

provide(accountServices.key, { userNickname, userBio, userAvatarIndex, activeAvatarOption, userAvatarOptions, userProfileSaving, saveUserProfile, closeUserCenter, monthlyTokenTotal, weeklyTokenTotal, monthlyTokenHeatmap, weeklyTokenUsage, formatTokenUsage, creditPending, creditLoadError });

provide(scheduleServices.key, {
  options: computed(() => ({ apiBaseUrl, projects: projects.value, provider: scheduleProvider.value, imageModel: imageModelOptions.value.includes(imageModel.value) ? imageModel.value : undefined, allowExternalNetwork: allowExternalNetwork.value })),
  openProject: openScheduledProject, openSettings: () => openProviderSettings(), changed: refreshScheduleNotifications,
});

provide(projectWorkspaceServices.key, {
  isLoading, errorMessage, designCanvasVisible,
  options: computed(() => {
    const playback = activePlayback.value;
    return activeProject.value ? ({ runWorkflowNode: generateCanvasNode, messageEditRequest: messageEditRequest.value, resendMessage: resendDesignMessage, taskFocus: taskFocus.value?.projectId === activeProject.value!.id ? taskFocus.value : undefined, messages: playback ? playback.messages.value : [...showcasePlayback.savedMessages.value, ...designConversation.value.map(message => message.role === 'user' ? { ...message, references: messageReferences({ text: message.content, projectId: activeProject.value!.id, apiBaseUrl, snapshot: message.referenceSnapshot, assets: globalAssets.value, documents: globalKnowledgeDocs.value, nodes: designCanvasDocument.value.nodes }) } : message)], busy: playback ? playback.playing.value : isRunningTask.value && runningTaskProjectId.value === activeProject.value.id, progress: playback ? playback.progress.value : designProgress.value, error: playback?.error.value || errorMessage.value, apiBaseUrl, projectId: activeProject.value.id, demoMode: Boolean(playback), canvasDocument: playback ? playback.canvasDocument.value : designCanvasDocument.value, modelOptions: imageModelOptions.value, textModelOptions: textModelOptions.value, audioModelOptions: audioModelOptions.value, videoModelOptions: videoModelOptions.value }) : null;
  }),
  events: { 'return-home': () => { startNewIntake(); void router.push('/'); }, 'task-action': handleTaskAction, reference: referenceDesignCanvas, 'cancel-canvas-reference': cancelCanvasReferences, 'move-node': moveDesignNode, 'generate-node': generateCanvasNode, 'cancel-node-task': cancelCanvasNodeTask, 'canvas-error': message => { errorMessage.value = message; pushToast(publicAssistantMessage(message), 'error'); }, 'canvas-change': document => { designCanvasDocument.value = document; }, 'composer-ready': markComposerReady, clarify: answerDesignClarification, 'select-reference': answerReferenceSelection },
});

onMounted(async () => {
  const startupPath = router.currentRoute.value.fullPath;
  const restoreId = localStorage.getItem(activeProjectStorageKey);
  window.addEventListener('model-prices-changed', loadLocalModelCatalog);
  void mascotSettings.load();
  void activateComposerDraft(activeProjectId.value);
  applyTheme();
  document.addEventListener('click', handleDocumentClick);
  window.addEventListener('storage', handleTokenStorageChange);
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', handleSystemThemeChange);
  tokenClockTimer = window.setInterval(() => { tokenNow.value = new Date(); }, 30_000);
  tokenUsageRefreshTimer = window.setInterval(() => { if (!document.hidden) void refreshTokenUsageFromWorkspace(); }, 3_000);
  taskQueueTimer = window.setInterval(() => { void taskQueue.refresh().catch(() => undefined); }, 5000);
  placeholderTimer = window.setInterval(() => {
    activePlaceholderIndex.value = (activePlaceholderIndex.value + 1) % composerPlaceholders.length;
  }, 4200);
  void refreshScheduleNotifications();
  scheduleNotificationTimer = window.setInterval(() => { void refreshScheduleNotifications(); }, 5000);
  unsubscribeScheduleNotification = window.studio?.onScheduleNotification?.((projectId) => { if (projectId) void openScheduledProject(projectId); else openSchedules(); });
  await loadProjects();
  if (generalSettings.restoreProject && startupPath === '/' && router.currentRoute.value.fullPath === startupPath
      && !activeProjectId.value && !intakeBrief.value.trim() && !intakeFiles.value.length
      && restoreId && projects.value.some(project => project.id === restoreId)) await selectProject(restoreId);
  void refreshAchievements();
  recordBetaUsage('app_open', { page: workspaceView.value });
  await loadLocalModelCatalog();
  await refreshTokenUsageFromWorkspace();
  await loadProviders();
  await loadGlobalLibraries();
});

onUnmounted(() => {
  window.removeEventListener('model-prices-changed', loadLocalModelCatalog);
  mascotSettings.dispose();
  projectTitlesDisposed = true;
  window.clearTimeout(projectTitleTimer);
  window.clearInterval(taskQueueTimer);
  window.clearInterval(scheduleNotificationTimer);
  unsubscribeScheduleNotification?.();
  stopSidebarResize();
  document.removeEventListener('click', handleDocumentClick);
  window.removeEventListener('storage', handleTokenStorageChange);
  window.matchMedia?.('(prefers-color-scheme: dark)').removeEventListener?.('change', handleSystemThemeChange);
  if (tokenClockTimer) window.clearInterval(tokenClockTimer);
  if (tokenUsageRefreshTimer) window.clearInterval(tokenUsageRefreshTimer);
  if (placeholderTimer) window.clearInterval(placeholderTimer);
  if (apiRecoveryTimer !== null) window.clearTimeout(apiRecoveryTimer);
  for (const timer of queuedMessageTimers.values()) window.clearTimeout(timer);
  queuedMessageTimers.clear();
  liveModelCatalog.reset();
  Object.values(intakeFilePreviews.value).forEach((url) => URL.revokeObjectURL(url));
});
</script>

<template>
  <TaskRequestInspector v-if="inspectedTaskId && activeProjectId" :key="inspectedTaskId" :api-base-url="apiBaseUrl" :project-id="activeProjectId" :task-id="inspectedTaskId" @recovered="refreshRecoveredMedia" @close="inspectedTaskId = null" @locate="nodeId => { taskFocus = { projectId: activeProjectId!, taskId: inspectedTaskId!, nodeId, requestId: Date.now() }; inspectedTaskId = null; }" />
  <main class="shell" :class="{ 'desktop-shell': isDesktopApp, 'shell-general-chat': workspaceView === 'design-agent', 'canvas-open': workspaceView === 'design-agent' && designCanvasVisible, 'settings-open': workspaceView === 'settings' }">
    <DesktopToolbar v-if="isDesktopApp" />
    <header v-if="!isDesktopApp && workspaceView === 'intake'" class="mx-app-heading">
      <HomeUsageSummary v-if="!isDesktopApp && workspaceView === 'intake'" />

    </header>
              <div v-if="workspaceView !== 'design-agent'" class="sidebar-task-wrap top-task-wrap">
                <button ref="taskQueueAnchor" type="button" class="sidebar-nav-item" :class="{ active: showAssistantCard, running: taskQueueCount > 0 }" aria-label="任务列表" aria-haspopup="dialog" :title="taskQueueLabel" :aria-expanded="showAssistantCard" @click.stop="openTaskQueue"><span class="nav-icon"><ClipboardList :size="17" /></span><strong>任务</strong><span v-if="taskQueueCount" class="composer-task-count">{{ taskQueueCount }}</span></button>
                <AnchoredPopover v-if="showAssistantCard" :anchor="taskQueueAnchor" :top-inset="isDesktopApp ? 42 : 12" label="任务列表" @close="showAssistantCard = false">
                  <div class="composer-task-list">
                    <div class="panel-heading"><span>任务<span v-if="taskQueueCount"> · {{ taskQueueCount }}</span></span><button class="icon-button assistant-collapse-button" title="关闭任务列表" aria-label="关闭任务列表" @click="showAssistantCard = false">×</button></div>
                    <section class="task-queue-section" aria-label="正在运行的任务" aria-live="polite">
                      <AnimatedList v-if="taskQueueCount" class="task-queue-animated"><button v-for="task in activeQueueTasks" :key="task.id" type="button" class="task-queue-item" :title="`进入任务：${task.userMessage || task.projectName}`" :aria-label="`进入任务：${task.userMessage || task.projectName}`" @click="openQueueTask(task)"><span class="task-queue-item-copy"><strong>{{ task.userMessage || task.projectName }}</strong><small>{{ task.projectName }} · 运行中</small><span class="task-queue-progress" role="progressbar" aria-label="任务运行中，进度未知"><i /></span></span><ChevronRight :size="14" aria-hidden="true" /></button></AnimatedList>
                      <p v-else class="task-queue-empty">暂无运行任务</p>
                    </section>
                  </div>
                </AnchoredPopover>
              </div>
    <section class="workspace-grid">
      <nav v-if="workspaceView !== 'design-agent'" class="top-left-nav-card" :style="{ '--nav-count': sidebarNavItems.length + 2 }" aria-label="工作台导航">
        <button class="sidebar-nav-item brand-home-button" :class="{ active: workspaceView === 'intake' }" type="button" aria-label="返回首页" @click="startNewIntake(); router.push('/')"><span class="nav-icon" aria-hidden="true"><House :size="18" :stroke-width="1.7" /></span><strong>首页</strong></button>
        <button v-for="(item, index) in sidebarNavItems" :key="item.key" :style="{ '--nav-index': index + 1 }" class="sidebar-nav-item" :class="{ active: workspaceView !== 'settings' && sidebarSection === item.key }" :aria-label="item.label" @click="navigateSidebar(item.key)"><span class="nav-icon" aria-hidden="true"><Clock3 v-if="item.key === 'schedules'" :size="17" :stroke-width="1.7" /><Folder v-else-if="item.key === 'projects'" :size="17" :stroke-width="1.7" /><Images v-else-if="item.key === 'assets'" :size="17" :stroke-width="1.7" /><Wrench v-else-if="item.key === 'skills'" :size="17" :stroke-width="1.7" /><BookOpen v-else :size="17" :stroke-width="1.7" /></span><strong>{{ item.label }}</strong><i v-if="item.key === 'schedules' && scheduleUnreadCount" class="schedule-nav-badge">{{ scheduleUnreadCount > 99 ? '99+' : scheduleUnreadCount }}</i></button>

      </nav>
      <div class="top-left-profile-wrap">
        <template v-if="workspaceView !== 'design-agent'"><AppUpdate /><ThemeSwitcher v-model="themeMode" /></template>
        <button ref="userSummaryButton" class="sidebar-user sidebar-user-mini" type="button" aria-label="用户概览" aria-haspopup="dialog" :aria-expanded="showUserSummary" aria-controls="user-summary-card" @click.stop="toggleUserSummary"><span class="user-avatar user-avatar-sprite" :style="{ backgroundPosition: activeAvatarOption.position }"><span class="sr-only">{{ userNickname }}</span></span></button>
        <section v-if="showUserSummary" id="user-summary-card" ref="userSummaryCard" class="profile-summary-card" role="dialog" aria-label="用户概览" tabindex="-1" @keydown.esc.stop.prevent="closeUserSummary(true)">
          <header class="profile-summary-identity">
            <span class="user-avatar user-avatar-sprite" :style="{ backgroundPosition: activeAvatarOption.position }" aria-hidden="true" />
            <div><strong>{{ userNickname }}</strong><small>{{ userBio }}</small></div>
          </header>
          <div class="profile-summary-model"><span>当前模型</span><strong :title="routingMode !== 'manual' ? routingLabel : providerModel || '未选择可用模型'">{{ routingMode !== 'manual' ? routingLabel : providerModel || '未选择可用模型' }}</strong><span class="model-status-light" :class="modelConnection" role="img" :aria-label="modelConnectionHint" :title="modelConnectionHint" /></div>
          <div class="profile-summary-activity">
            <div class="profile-summary-activity-heading"><span>使用活动</span><small>最近一周</small></div>
            <div v-if="creditSummary && !creditLoadError" class="profile-summary-bars" aria-label="近七天活动预览，柱高表示相对用量"><div v-for="day in weeklyTokenUsage" :key="day.key" :title="`周${day.weekday} · ${day.value ? '有使用' : '暂无活动'}`" :aria-label="`周${day.weekday} · ${day.value ? '有使用' : '暂无活动'}`"><span :class="{ 'is-empty': !day.value }"><i v-if="day.value" :style="{ height: `${day.height}%` }" /></span><small>{{ day.weekday }}</small></div></div>
            <small v-else class="profile-summary-note">{{ creditLoadError ? '活动暂不可用' : '正在读取活动…' }}</small>
          </div>
          <button class="profile-summary-settings" type="button" @click="openUserCenter"><Settings2 :size="16" /><span>设置</span><ChevronRight :size="14" /></button>
        </section>
      </div>

      <section class="canvas-panel">
        <RouterView v-slot="{ Component, route }">
          <component :is="Component" :key="route.meta.view === 'settings' ? 'settings' : route.path" v-if="route.meta.view === workspaceView || route.name === 'not-found'" />
        </RouterView>
      </section>

      <button v-if="workspaceView !== 'settings'" type="button" class="support-fab" aria-label="打开使用说明" title="打开使用说明" @click.stop="openHelpCenter"><CircleHelp :size="19" :stroke-width="1.8" /></button>
    </section>

    <Teleport v-if="composerHostReady && (workspaceView === 'intake' || workspaceView === 'design-agent')" :key="designComposerEpoch" defer :to="workspaceView === 'design-agent' ? '#design-composer-host' : '#intake-composer-host'">
            <section v-if="workspaceView === 'design-agent' && activeQueuedMessages.length" class="composer-message-queue" aria-label="待发送消息队列" aria-live="polite">
              <header class="composer-message-queue-header">
                <span><ListPlus :size="15" /><strong>待发送 · {{ activeQueuedMessages.length }}</strong></span>
                <small v-if="activeQueuePauseReason" role="status">{{ activeQueuePauseReason }}<button v-if="!isRunningTask && latestTask" type="button" @click="inspectedTaskId = latestTask.id">查看当前请求</button></small>
                <button v-else type="button" class="queue-continue-button" @click="runNextQueuedMessage()">继续执行</button>
              </header>
              <TransitionGroup tag="ol" name="queue-message" class="composer-message-queue-list">
                <li v-for="(message, index) in activeQueuedMessages" :key="message.id" class="composer-message-queue-item" :class="{ dragging: queuedMessageDragId === message.id }" draggable="true" @dragstart="beginQueuedMessageDrag(message.id, $event)" @dragend="queuedMessageDragId = null" @dragover.prevent @drop.prevent="dropQueuedMessage(message.id)">
                  <GripVertical :size="15" class="queue-drag-handle" aria-hidden="true" />
                  <span class="queue-message-index">{{ index + 1 }}</span>
                  <span class="queue-message-copy">
                    <template v-if="editingQueuedMessage === message.id"><textarea v-model="queuedEditText" aria-label="编辑待发送消息" @keydown.esc="editingQueuedMessage = null" /><span class="queue-edit-actions"><button type="button" :disabled="!queuedEditText.trim()" @click="saveQueuedMessageEdit(message)">保存</button><button type="button" @click="editingQueuedMessage = null">取消</button></span></template>
                    <strong v-else>{{ message.text }}</strong><small>{{ queuedMessageMeta(message) }}</small>
                  </span>
                  <span class="queue-message-actions"><button type="button" class="queue-supplement-button" :disabled="sendingSupplement || editingQueuedMessage === message.id || (!isRunningTask && !message.supplementTaskId) || !!supplementUnavailableReason(message.draft)" :title="supplementUnavailableReason(message.draft) || (message.supplementTaskId ? '确认原补充请求，不会创建新任务' : isRunningTask ? '补充当前任务' : '当前没有运行中的任务')" :aria-label="`补充当前任务：${message.text}`" @click="supplementCurrentTask(message)">{{ message.supplementTaskId ? '确认补充' : '补充' }}</button><button type="button" :disabled="sendingSupplement || !!message.supplementTaskId" aria-label="编辑待发送消息" title="编辑" @click="editingQueuedMessage = message.id; queuedEditText = message.text"><Pencil :size="14" /></button>
                    <button type="button" :disabled="index === 0" :aria-label="`上移：${message.text}`" title="上移" @click="moveQueuedMessage(message.id, -1)"><ChevronUp :size="14" /></button>
                    <button type="button" :disabled="index === activeQueuedMessages.length - 1" :aria-label="`下移：${message.text}`" title="下移" @click="moveQueuedMessage(message.id, 1)"><ChevronDown :size="14" /></button>
                    <button type="button" :aria-label="`移出队列：${message.text}`" title="移出队列" @click="removeActiveQueuedMessage(message.id)"><X :size="14" /></button>
                  </span>
                </li>
              </TransitionGroup>
            </section>
            <div class="intake-composer composer-hero" :class="{ 'is-file-dragging': isDraggingComposerFiles }" @dragenter="handleComposerFileDragEnter" @dragover="handleComposerFileDragOver" @dragleave="handleComposerFileDragLeave" @drop="handleComposerFileDrop">
              <StarBorder :flowing="workspaceView === 'intake'" />
            <div v-if="intakeFiles.length" class="intake-file-list" aria-label="已添加的附件"><div v-for="(file, index) in intakeFiles" :key="`${file.name}-${file.lastModified}`" class="intake-file-chip" :class="{ referenced: intakeMentionFiles.includes(index) }" :title="`${index + 1}. ${file.name}`"><span class="intake-file-index">{{ index + 1 }}</span><span v-if="intakeFilePreviews[fileKey(file)]" class="file-thumb"><img :src="intakeFilePreviews[fileKey(file)]" :alt="file.name" /></span><span v-else class="file-type-icon" aria-hidden="true">{{ fileIcon(file) }}</span><span class="sr-only">{{ file.name }}</span><button type="button" class="icon-button" :aria-label="`移除附件 ${file.name}`" @click="removeIntakeFile(index)"><X :size="14" /></button></div></div>
            <label class="intake-label intake-main-label intake-mention-anchor">
              <span class="sr-only">输入需求</span>
              <div ref="intakeComposerRef" class="intake-composer-editor" contenteditable="true" role="textbox" aria-label="输入需求" aria-multiline="true" :aria-activedescendant="intakeSkillQuery ? intakeSkillMenu?.activeId : undefined" :aria-controls="intakeSkillQuery ? 'skill-mention-options' : undefined" :aria-haspopup="intakeSkillQuery ? 'listbox' : undefined" :aria-expanded="!!intakeSkillQuery" :data-placeholder="composerPlaceholders[activePlaceholderIndex]" @pointerdown="confirmCanvasReferences" @focus="confirmCanvasReferences" @input="handleIntakeComposerInput" @paste="handleIntakePaste" @keydown="handleIntakeComposerKeydown" @keyup.left="refreshComposerMentionCaret" @keyup.right="refreshComposerMentionCaret" @click="refreshComposerMentionCaret" @compositionstart="handleIntakeComposerCompositionStart" @compositionend="handleIntakeComposerCompositionEnd" @pointerover="showInlineReferencePreview" @pointerout="hideInlineReferencePreview" @focusin="showInlineReferencePreview" @focusout="hideInlineReferencePreview" @scroll="referencePreview = null"></div>
              <div v-if="isDraggingComposerFiles" class="composer-file-drop-hint" role="status" aria-live="polite"><Upload :size="22" :stroke-width="1.7" aria-hidden="true" /><strong>{{ isCreatingIntake ? '正在上传，请稍候' : '松开鼠标，添加为附件' }}</strong><small>支持图片、PDF、文档、表格和文本文件</small></div>
              <SkillMentionMenu v-if="intakeSkillQuery" ref="intakeSkillMenu" :query="intakeSkillQuery.query" :api-base-url="apiBaseUrl" @select="selectIntakeSkill" @close="intakeSkillQuery = null" />
              <div v-if="intakeMentionQuery || intakeMentionStart !== null" class="asset-mention-menu" role="listbox" aria-label="搜索资产或附件">
                <button v-for="(option, optionIndex) in intakeMentionResults" :key="mentionOptionKey(option)" type="button" :class="['asset-mention-option', { active: optionIndex === intakeMentionActiveIndex }]" @mousedown.prevent="selectIntakeMention(option)">
                  <span class="asset-mention-option-icon"><img v-if="mentionOptionPreview(option)" :src="mentionOptionPreview(option)" :alt="mentionOptionLabel(option)" /><FileText v-else :size="19" /></span>
                  <span><strong>{{ mentionOptionLabel(option) }}</strong><small>{{ mentionOptionMeta(option) }}</small></span>
                </button>
                <div v-if="!intakeMentionResults.length" class="asset-mention-empty">没有匹配的资产</div>
              </div>
            </label>
            <div class="composer-toolbar">
              <label class="composer-tool file-tool" title="添加、粘贴或拖拽图片、文档或表格"><Paperclip :size="17" /><span>资料</span><input ref="intakeFileInput" type="file" multiple :accept="intakeFileAccept" @change="handleIntakeFiles" /></label>
              <div class="composer-popover-wrap composer-agent-wrap">
                <button ref="composerModelButton" type="button" class="composer-tool" title="快速切换文本 / 图像 / 视频 / 音频模型" aria-haspopup="dialog" :aria-expanded="showComposerAgentMenu" @click="toggleComposerAgentMenu"><span class="model-status-light composer-model-status" :class="modelConnection" role="img" :aria-label="modelConnectionHint" :title="modelConnectionHint" /><Bot :size="17" /><span>模型</span><ChevronDown :size="14" /></button>
                <AnchoredPopover v-if="showComposerAgentMenu" :anchor="composerModelButton" :top-inset="isDesktopApp ? 42 : 12" @close="showComposerAgentMenu = false">
                  <div class="agent-model-tabs"><button v-for="tab in agentModelTabs" :key="tab.key" :class="{ active: agentModelTab === tab.key }" @click="agentModelTab = tab.key"><Bot v-if="tab.key === 'text'" :size="16" /><Images v-else-if="tab.key === 'image'" :size="16" /><Play v-else-if="tab.key === 'video'" :size="16" /><Volume2 v-else :size="16" /><span>{{ tab.label }}</span></button></div>
                  <p v-if="isDetectingModels || liveModelCatalog.error.value" class="model-select-hint" role="status">{{ isDetectingModels ? '正在读取模型…' : liveModelCatalog.error.value }}</p>
                  <div class="agent-model-list">
                    <div v-if="agentModelTab === 'text'" class="routing-choices"><button v-for="choice in routingChoices" :key="choice.id" type="button" class="popover-option model-option" :class="{ selected: routingMode === choice.id }" :aria-pressed="routingMode === choice.id" @click="routingMode = choice.id"><Bot :size="20" /><span class="model-option-copy"><strong>{{ choice.label }}</strong></span></button></div>
                    <button v-for="model in composerModelOptions" :key="`${agentModelTab}-${model}`" type="button" class="popover-option model-option" :class="{ selected: composerSelectedModel === model && (agentModelTab !== 'text' || routingMode === 'manual') }" :aria-pressed="composerSelectedModel === model && (agentModelTab !== 'text' || routingMode === 'manual')" @click="selectComposerModel(agentModelTab, model)"><ModelBrandIcon :model="model" /><span class="model-option-copy"><strong :title="modelDisplayName(model)">{{ modelDisplayName(model) }}</strong></span></button>
                    <p v-if="hasDetectedModelCatalog && !composerModelOptions.length" class="model-select-hint">中转站 API 未返回此类模型。</p>
                  </div>
                  <button v-if="agentModelTab === 'image'" type="button" class="popover-settings image-default-action" @click="useDefaultImageModel">自动选择模型</button>
                  <button type="button" class="popover-settings" @click="openProviderSettings">管理本地模型目录</button>
                </AnchoredPopover>
              </div>
              <div class="composer-popover-wrap">
                <button type="button" class="composer-tool" :aria-expanded="showComposerStyleMenu" @click="toggleComposerStyleMenu"><Palette :size="17" /><span>风格</span><ChevronDown :size="14" /></button>

              </div>
              <span class="composer-toolbar-spacer" />
              <VoiceInput :key="`${workspaceView}:${activeProjectId || 'home'}`" :api-base-url="apiBaseUrl" @text="intakeBrief += (intakeBrief.trim() ? '\n' : '') + $event; syncIntakeComposerEditor()" />
              <button v-if="workspaceView === 'design-agent' && isRunningTask" type="button" class="composer-send composer-stop" :aria-label="isStoppingTask ? '正在停止生成' : '停止生成'" :title="isStoppingTask ? '正在停止…' : '停止生成'" :disabled="isStoppingTask" @click="stopAgent"><LoaderCircle v-if="isStoppingTask" :size="19" class="spin-icon" aria-hidden="true" /><StopIcon v-else :size="14" fill="currentColor" :stroke-width="0" aria-hidden="true" /></button>
              <button v-else type="button" class="composer-send" :disabled="isCreatingIntake || (!intakeBrief.trim() && !intakeFiles.length)" :aria-label="workspaceView === 'design-agent' ? (activeQueuedMessages.length ? '加入队列并继续执行' : '发送消息') : isCreatingIntake ? '正在连接本地 API' : intakeReady ? '交给 Agent 分析' : '解析并创建记录'" :title="isCreatingIntake ? '正在连接本地 API…' : ''" @click="submitComposer"><LoaderCircle v-if="isCreatingIntake" :size="19" class="spin-icon" /><ArrowUp v-else :size="19" /></button>
            </div>
            <div class="composer-caption"><span>{{ draftSaveLabel || '支持粘贴或拖拽图片与文件' }} · @ 引用资料 · # 选择技能</span></div>
            <div v-if="intakeFileResults.length" class="intake-results"><div v-for="result in intakeFileResults" :key="result.filename" class="intake-result-row"><span class="status-dot" :class="{ warning: Boolean(result.warning) }" /><strong>{{ result.filename }}</strong><span>{{ result.parser || result.status || '已解析' }}</span><small v-if="result.warning">{{ result.warning }}</small></div></div>
            <div v-if="intakeReady && workspaceView === 'intake'" class="intake-ready-note"><span class="status-dot" />资料已解析，点击箭头交给MxinspireX</div>
            </div>
    </Teleport>

    <StylePicker v-model:open="showComposerStyleMenu" :selected="imageStyle" @select="selectComposerStyle" />
    <ReferencePreview v-if="referencePreview" v-bind="referencePreview" />
    <div class="toast-stack" aria-live="polite"><div v-for="toast in toasts" :key="toast.id" class="toast" :class="`toast-${toast.kind}`"><span>{{ toast.kind === 'success' ? '✓' : toast.kind === 'error' ? '!' : '·' }}</span><p>{{ toast.message }}</p><button aria-label="关闭提示" @click="dismissToast(toast.id)">×</button></div></div>
    <FirstRequestCelebration v-if="showAhaMoment" @close="dismissAhaMoment" />
    <AchievementCelebration v-if="unlockedAchievement" :title="unlockedAchievement.title" :description="unlockedAchievement.description" :image-generation-count="unlockedAchievement.imageGenerationCount" @close="dismissAchievement" />

    <div v-if="isCreating" class="modal-backdrop" @click.self="isCreating = false">
      <form class="modal" @submit.prevent="createProject">
        <div class="modal-header"><div><p class="eyebrow">NEW PROJECT</p><h2>创建设计项目</h2></div><button type="button" class="icon-button" @click="isCreating = false">×</button></div>
        <label>项目名称<input v-model="form.name" autofocus placeholder="例如：船舶客舱体验设计方案" /></label>
        <label>项目 Brief<textarea v-model="form.brief" rows="4" placeholder="目标、预算、数量、客群或任何已知约束"></textarea></label>
        <div class="form-row"><label>预算（分）<input v-model.number="form.budgetMinor" type="number" min="0" placeholder="15000000" /></label><label>币种<select v-model="form.currency"><option>CNY</option><option>USD</option><option>EUR</option></select></label></div>
        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        <div class="modal-actions"><button type="button" class="ghost-button" @click="isCreating = false">取消</button><button class="primary-button" :disabled="isSaving || !form.name.trim()">{{ isSaving ? '保存中…' : '创建项目' }}</button></div>
      </form>
    </div>
    <div v-if="pendingDeleteProject" class="modal-backdrop delete-modal-backdrop" @click.self="cancelDeleteProject">
      <section class="delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-project-title">
        <div class="delete-modal-icon"><Trash2 :size="24" :stroke-width="1.8" aria-hidden="true" /></div>
        <p class="eyebrow">DELETE LOCAL RECORD</p><h2 id="delete-project-title">删除这个设计项目？</h2><p>将同时删除项目记录、任务历史、上传资产与研究快照。此操作无法撤销。</p><strong>{{ pendingDeleteProject.name }}</strong>
        <div class="modal-actions"><button class="ghost-button" :disabled="isDeletingProject" @click="cancelDeleteProject">取消</button><button class="danger-button" :disabled="isDeletingProject" @click="deleteProject(pendingDeleteProject)">{{ isDeletingProject ? '删除中…' : '确认删除' }}</button></div>
      </section>
    </div>
    <div v-if="pendingDeleteAsset" class="modal-backdrop delete-modal-backdrop" @click.self="cancelDeleteAsset">
      <section class="delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-asset-title">
        <div class="delete-modal-icon"><Trash2 :size="20" /></div>
        <p class="eyebrow">DELETE ASSET</p><h2 id="delete-asset-title">删除这个资产？</h2><p>将删除本地文件及其资产记录；关联的预览引用会被清空。此操作无法撤销。</p><strong>{{ assetDisplayName(pendingDeleteAsset) }}</strong>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <div class="modal-actions"><button type="button" class="ghost-button" :disabled="isDeletingAsset" @click="cancelDeleteAsset">取消</button><button type="button" class="danger-button" :disabled="isDeletingAsset" @click="deleteAsset(pendingDeleteAsset)">{{ isDeletingAsset ? '删除中…' : '确认删除' }}</button></div>
      </section>
    </div>
    <div v-if="pendingDeleteKnowledge" class="modal-backdrop delete-modal-backdrop" @click.self="cancelDeleteKnowledge">
      <section class="delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-knowledge-title">
        <div class="delete-modal-icon"><Trash2 :size="20" /></div>
        <p class="eyebrow">DELETE KNOWLEDGE DOCUMENT</p><h2 id="delete-knowledge-title">删除这个知识文档？</h2><p>将删除原文件、解析片段与向量索引；后续 Agent 不会再检索到它。此操作无法撤销。</p><strong>{{ pendingDeleteKnowledge.title }}</strong>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <div class="modal-actions"><button type="button" class="ghost-button" :disabled="isDeletingKnowledge" @click="cancelDeleteKnowledge">取消</button><button type="button" class="danger-button" :disabled="isDeletingKnowledge" @click="deleteKnowledge(pendingDeleteKnowledge)">{{ isDeletingKnowledge ? '删除中…' : '确认删除' }}</button></div>
      </section>
    </div>
    <Teleport v-if="isProviderSettingsOpen && settingsHostReady && !['account', 'help'].includes(settingsTab)" defer to="#settings-content-host">
      <form class="settings-workspace-form" @submit.prevent="handleSettingsSubmit" @click="handleSettingsConfettiClick">
        <GeneralSettings v-if="settingsTab === 'general'" v-model:queue="queueMessagesByDefault" :api-base-url="apiBaseUrl" />
        <section v-else-if="settingsTab === 'text'" class="settings-pane">
          <div class="provider-auto-note"><span class="status-dot" :class="{ unconfigured: !activeTextProvider }" /><div><strong>{{ isOllamaProvider ? 'Ollama · 本地 Agent 测试' : credentialTargetProvider === 'evolink' ? 'EvoLink · 设计 Agent 与多媒体生成' : isCloseAIEndpoint ? 'CloseAI · 完整模型目录与路由' : credentialTargetProvider === 'openai-compatible' ? '中转站 · 设计 Agent 模型路由' : 'OpenRouter · 设计 Agent 默认模型路由' }}</strong><small>{{ isOllamaProvider ? '连接本机 Ollama，无需 API Key；同步后自动使用手动模型模式，本地运行不产生 API 费用。' : credentialTargetProvider === 'evolink' ? '一个 API Key 连接文本、图像、视频和已接入的语音模型。保存后同步可用模型，首页与项目画布共用选择。' : isCloseAIEndpoint ? '普通 API Key 用于生成；可选目录管理密钥只在手动同步完整模型目录时使用。' : credentialTargetProvider === 'openai-compatible' ? '填写兼容服务 URL 和 API Key，保存时同步一次模型目录。' : '保存 API Key 时同步一次模型目录，之后从本地读取。' }}</small></div></div>
          <div class="provider-mode-control">
            <div class="provider-mode-heading"><span>Provider 模式</span><small>{{ isOllamaProvider ? '使用本机 Ollama' : credentialTargetProvider === 'evolink' ? '使用 EvoLink 官方入口' : credentialTargetProvider === 'openai-compatible' ? '使用 OpenAI 兼容服务' : '使用 OpenRouter 官方入口' }}</small></div>
            <div class="provider-mode-options" role="radiogroup" aria-label="选择文本模型 Provider"><button v-for="provider in credentialProviderOptions" :key="provider.key" type="button" :class="{ selected: credentialTargetProvider === provider.key }" role="radio" :aria-checked="credentialTargetProvider === provider.key" :disabled="isSavingProvider" @click="selectCredentialProvider(provider.key)">{{ provider.key === 'openai-compatible' ? '兼容模式' : provider.key === 'ollama' ? '本地 Ollama' : provider.key === 'evolink' ? 'EvoLink' : 'OpenRouter' }}</button></div>
          </div>
          <label v-if="credentialTargetProvider === 'openai-compatible' || isOllamaProvider">{{ isOllamaProvider ? 'Ollama URL' : '兼容服务 URL' }}<input v-model="providerBaseUrl" :disabled="isSavingProvider" :placeholder="providerDefaultBaseUrl(credentialTargetProvider)" /><small v-if="isOllamaProvider">默认连接 http://127.0.0.1:11434/v1；请保持 Ollama 服务运行。</small></label>
          <div v-if="selectedProviderRequiresKey" class="provider-credential-row">
            <label>API Key（仅保存到本机安全存储）<input v-model="providerSecret" :disabled="isSavingProvider" type="password" autocomplete="new-password" :placeholder="selectedProviderCredentialHint ? '已保存 Key；留空即可继续使用，输入新 Key 可替换' : '输入 API Key，探测并保存时使用'" /></label>
            <div class="provider-credential-status" :class="{ configured: Boolean(selectedProviderStatus?.configured) }"><span class="status-dot" :class="{ unconfigured: !selectedProviderStatus?.configured }" /><span v-if="selectedProviderStatus?.configured">已保存 · {{ selectedProviderCredentialHint || '••••••••' }}</span><span v-else>尚未保存</span></div>
          </div>
          <div v-else class="provider-credential-status configured"><span class="status-dot" /><span>无需 API Key · 仅访问本机服务</span></div>
          <div v-if="isCloseAIEndpoint" class="provider-credential-row">
            <label>CloseAI 目录管理密钥（可选）<input v-model="closeAICatalogSecret" :disabled="isSavingProvider" type="password" autocomplete="new-password" :placeholder="closeAICatalogCredentialHint ? '已保存目录密钥；留空继续使用' : 'sk-admin-…；用于读取完整模型类别与报价'" /><small>仅请求 CloseAI 管理模型目录，不会用于生成、Agent 任务或导出。未配置时仍可使用普通目录，但可能遗漏媒体模型。</small></label>
            <div class="provider-credential-status" :class="{ configured: Boolean(selectedProviderStatus?.catalogCredentialConfigured) }"><span class="status-dot" :class="{ unconfigured: !selectedProviderStatus?.catalogCredentialConfigured }" /><span v-if="selectedProviderStatus?.catalogCredentialConfigured">已保存 · {{ closeAICatalogCredentialHint || '••••••••' }}</span><span v-else>未配置完整目录</span></div>
          </div>
          <label>Agent 执行方式<select v-model="routingMode"><option v-for="choice in routingChoices" :key="choice.id" :value="choice.id">{{ choice.label }}</option><option value="manual">手动模型（在首页选择）</option></select><small>文本、图像、视频和音频模型统一在首页输入框中切换。</small></label>
          <p class="model-catalog-summary" role="status">{{ settingsCatalogMessage }}</p>
          <div class="provider-capabilities" aria-label="模型能力检测">
            <div class="provider-capability-row"><strong>文本</strong><span>{{ liveModelCatalog.status.value === 'ready' ? `${detectedTextModels.length} 个模型` : '等待目录确认' }}</span></div>
            <div v-for="kind in mediaKinds" :key="kind" class="provider-capability-row">
              <strong>{{ mediaLabels[kind] }}</strong>
              <span v-if="liveModelCatalog.status.value !== 'ready'">{{ liveModelCatalog.status.value === 'error' ? '同步失败，保留已存配置' : '等待目录确认' }}</span>
              <span v-else-if="liveModelCatalog.data.value[kind].length">当前服务商 · {{ liveModelCatalog.data.value[kind].length }} 个模型</span>
              <span v-else>{{ savedRemoteMediaProvider(kind) ? '使用补充服务商' : '当前目录未发现' }}</span>
            </div>
            <div class="provider-capability-row"><strong>3D</strong><span>{{ liveModelCatalog.status.value === 'ready' && liveModelCatalog.data.value.threeD.length ? `目录发现 ${liveModelCatalog.data.value.threeD.length} 个 · 仍需配置已适配的生成接口` : '使用下方独立服务' }}</span></div>
            <small>模型列表用于发现能力，不等于已验证生成接口；同步失败不会清空补充配置。</small>
          </div>
          <template v-if="liveModelCatalog.status.value === 'ready'">
            <div v-for="kind in mediaKinds.filter(item => !liveModelCatalog.data.value[item].length)" :key="`supplemental-${kind}`" class="provider-supplemental">
              <label>{{ mediaLabels[kind] }} · 补充服务商
                <select :value="supplementalMedia[supplementalScope()]?.[kind] || ''" @change="setSupplementalMedia(kind, ($event.target as HTMLSelectElement).value)">
                  <option value="">{{ isOllamaProvider ? '沿用已有远程配置' : '暂不配置' }}</option>
                  <option v-if="supplementalMedia[supplementalScope()]?.[kind] && !supplementalChoices(kind).some(item => item.key === supplementalMedia[supplementalScope()]?.[kind])" :value="supplementalMedia[supplementalScope()]?.[kind]" disabled>已选服务不可用，请重新配置</option>
                  <option v-for="provider in supplementalChoices(kind)" :key="provider.key" :value="provider.key">{{ provider.label }} · {{ profileMediaModels(profileForProvider(provider.key)!, kind).length }} 个模型</option>
                </select>
              </label>
              <small>{{ supplementalChoices(kind).length ? '仅补充当前服务缺少的能力；首页、画布和任务调用使用同一选择，自动保存。' : '先在上方选择其他服务商，保存 Key 并同步目录，再切回当前服务商选择。' }}</small>
            </div>
          </template>
          <p v-if="unknownModelOptions.length" class="model-catalog-summary">{{ unknownModelOptions.length }} 个模型尚未识别能力，暂不自动加入生成列表。{{ liveModelCatalog.data.value.warnings.join('；') }}</p>
          <ThreeDSettings :api-base-url="apiBaseUrl" :provider="threeDConfigProvider" :endpoint="threeDConfigEndpoint" :model="threeDConfigModel" @saved="config => { threeDConfigProvider = config.provider; threeDConfigEndpoint = config.endpoint; threeDConfigModel = config.model; }" />
        </section>
        <ModelRouterSettings v-else-if="settingsTab === 'routing'" :api-base-url="apiBaseUrl" />
        <section v-else-if="settingsTab === 'appearance'" class="settings-pane"><AppearanceSettings v-model="themeMode" :resolved="resolvedTheme" /><label class="settings-switch toggle-control"><input v-model="reduceAnimations" type="checkbox" role="switch" /><span class="toggle-track" /><span>减少动画 <small>MxinspireX保持静止表情，减少画布和对话中的装饰动画；也尊重系统设置</small></span></label><label class="settings-switch toggle-control"><input v-model="allowExternalNetwork" type="checkbox" role="switch" /><span class="toggle-track" /><span>允许联网研究 <small>Agent 可调用 OpenAI 联网搜索并提供来源，可随时关闭</small></span></label><MascotSettings :provider="taskMediaProvider('image')" :model-options="imageModelOptions" /><button type="button" class="about-link" @click="switchSettingsTab('about')">关于灵矩绘境 →</button></section>
        <section v-else-if="settingsTab === 'components'" class="settings-pane runtime-components-pane"><LocalCapabilities /><div class="provider-config-heading"><span>按需能力组件</span><small>只在使用时安装，不包含项目或个人数据</small></div><article v-for="component in runtimeComponents" :key="component.id" class="runtime-component-card"><div class="runtime-component-icon"><Box :size="18" /></div><div><strong>{{ component.label }}</strong><p>{{ component.description }}</p><small>{{ formatComponentSize(component.bytes) }} · {{ component.installed ? '已安装' : component.available ? '可在线下载' : '从能力包安装' }}</small></div><button type="button" :disabled="component.installed || !!runtimeComponentLoading" @click="installRuntimeComponent(component)">{{ component.installed ? '已安装' : runtimeComponentLoading === component.id ? '安装中…' : '按需安装' }}</button></article><p v-if="runtimeComponentMessage" class="runtime-component-message" role="status">{{ runtimeComponentMessage }}</p></section>
        <section v-else class="settings-pane about-pane" @click="handleAboutClick"><div class="about-mark"><img class="about-logo" :src="brandLogoSrc" alt="MxInspireX Logo" /></div><p class="eyebrow">MxinspireX · 灵矩绘境</p><h3>与你一起推进设计的 AI Agent</h3><p>MxinspireX 将需求理解、资料检索、视觉生成与画布编辑整合在同一个工作区。从品牌视觉、产品概念到内容设计，让想法形成方案，让方案持续迭代。</p><p>我们相信，设计始于人的观察与判断。AI 帮助探索可能、完成繁复工作，让创作者把精力留给想法与取舍。</p><p>以本地工作区保存创作过程，用可追溯的引用连接灵感与成果，让每一次修改都有来处，也有继续生长的空间。</p><p>由灵矩绘境研发，与设计师一起从探索走向交付。</p><button type="button" class="about-link" @click.stop="switchSettingsTab('help')">查看使用说明 →</button><p>联系邮箱：<a class="help-contact-link" href="mailto:ziguishian@foxmail.com">ziguishian@foxmail.com</a></p><p>开发者：<strong>AlexiShi</strong></p><small>版本 {{ appVersion }} · Beta 测试版</small><BetaTestingAbout :api-base-url="apiBaseUrl" /><div class="about-footer-meta"><span>© 2026 灵矩绘境 · MxinspireX</span><span>需求梳理 · 方案生成 · 持续迭代</span></div></section>
        <p v-if="providerTestResult && settingsTab !== 'about'" class="provider-test-result" role="status" aria-live="polite">{{ providerTestResult }}</p><p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <div v-if="settingsTab !== 'about'" class="settings-page-actions"><button v-if="settingsTab === 'text'" type="submit" class="primary-button" :disabled="isSavingProvider || isDetectingModels">{{ isSavingProvider || isDetectingModels ? '同步并保存中…' : '保存并同步模型目录' }}</button><button v-else-if="settingsTab === 'appearance'" type="submit" class="primary-button">保存外观设置</button></div>
      </form>
    </Teleport>
  </main>
</template>
