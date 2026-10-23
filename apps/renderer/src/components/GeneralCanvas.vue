<script setup lang="ts">
import { generalSettings } from '../features/generalSettings';
import { publicAssistantMessage } from '../features/generationErrors';
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue';
import { VueFlow, useVueFlow, useKeyPress, getRectOfNodes, ConnectionLineType, SelectionMode, type Connection, type Edge, type Node } from '@vue-flow/core';
import { Background, BackgroundVariant } from '@vue-flow/background';
import { alignBoardNodes, boardChanges, cleanBoard, savedBoardEdit, type Board } from '../canvasEditing';
import { canvasEditHistory } from '../features/canvasHistory';
import { snapRect, arrangeRects, nearestOpenPosition, type Guide, type LayoutRect, type Alignment } from '../canvasLayout';
import { House, Pencil, ArrowDown, ArrowUpRight, Circle, CircleX, Download, FileImage, FileText, Images, LoaderCircle, Map as MapIcon, Maximize2, Minimize2, MousePointer2, Hand, Music2, Minus, Keyboard, Copy, Trash2, Undo2, Redo2, Plus, Upload, Video, X } from 'lucide-vue-next';
import { Columns2, Layers, AlignStartVertical, AlignCenterVertical, AlignEndVertical, AlignStartHorizontal, AlignCenterHorizontal, AlignEndHorizontal, AlignHorizontalSpaceBetween, AlignVerticalSpaceBetween } from 'lucide-vue-next';
import GeneralCanvasNode from './GeneralCanvasNode.vue';
import GeneralCanvasEdge from './GeneralCanvasEdge.vue';
import CanvasVersionCompare from './CanvasVersionCompare.vue';
import CanvasOverview from './CanvasOverview.vue';
import CanvasZoomControls from './CanvasZoomControls.vue';
import CanvasPromptPanel from './CanvasPromptPanel.vue';
import XiaojuAvatar from './XiaojuAvatar.vue';
import { useMascotSettings } from '../features/home/mascot';
import { useMotionPolicy } from '../features/motion/useMotion';
import { xiaojuState } from '../features/xiaojuState';
import TaskProgress from './TaskProgress.vue';
import TaskFeedbackPrompt from './TaskFeedback.vue';
import { readyForFeedback, recordBetaUsage, type TaskFeedback } from '../features/betaTesting';
import DesignStepIcon from './DesignStepIcon.vue';
import AgentMarkdown from './AgentMarkdown.vue';
import DesignClarificationCard from './DesignClarificationCard.vue';
import ReferenceSelectionCard from './ReferenceSelectionCard.vue';
import { pendingReferenceSelection, type ReferenceSubmission } from '../features/references';
import { pendingClarification, type ClarificationSubmission } from '../features/clarification';
import UserMessageBubble from './composer/UserMessageBubble.vue';
import AssistantMessageCopy from './composer/AssistantMessageCopy.vue';
import { canvasNodeKind, nodePreviewSize, nodeAspectPatch, type NodePreviewSize } from '../nodeSizing';
import { canExportNode, exportNode, nodeMediaUrl, nodeSaveLabel, type NodeExportFormat } from '../nodeExport';
import { MAX_CANVAS_ZOOM, parseViewport, canvasContentRevision, fitCanvasContents, type FocusRect, type CanvasControlsRect } from '../features/canvasWorkspace';
import { connectedReferences, canvasReferenceParams } from '../features/canvasReferences';
import type { ConversationMessage, MessageResubmission } from '../features/pageServices';
import type { TaskIssue } from '../features/taskErrors';
import { canvasReply, type DesignStep } from '../designPresentation';

type CanvasKind = 'image' | 'video' | 'audio' | 'text' | 'html' | 'cad' | 'upload';
type CanvasCreationKind = CanvasKind | 'drawing';
type MenuPosition = { x: number; y: number };
type DeleteTarget = { projectId: string; nodeIds: string[]; edgeIds: string[]; label: string };
const props = defineProps<{ demoMode?: boolean; messageEditRequest?: { taskId: string; requestId: number }; resendMessage?: (submission: MessageResubmission) => Promise<boolean>; taskFocus?: { taskId: string; nodeId?: string; requestId: number }; messages: ConversationMessage[]; busy: boolean; progress?: string; error?: string; apiBaseUrl: string; projectId: string; canvasDocument?: { lockedNodeIds?: string[]; nodes?: Record<string, any>[]; edges?: Record<string, any>[] }; modelOptions?: string[]; videoModelOptions?: string[]; textModelOptions?: string[]; audioModelOptions?: string[] }>();
const emit = defineEmits<{ 'return-home': []; 'select-reference': [submission: ReferenceSubmission]; 'task-action': [taskId: string, action: TaskIssue['action']]; reference: [value: string, tentative?: boolean]; 'cancel-canvas-reference': []; 'move-node': [id: string, position: { x: number; y: number }]; 'generate-node': [kind: CanvasKind, prompt: string, position: { x: number; y: number }, params: Record<string, any>]; 'cancel-node-task': [nodeId: string, taskId: string]; 'canvas-error': [message: string]; 'canvas-change': [document: Board]; 'composer-ready': []; clarify: [submission: ClarificationSubmission] }>();
type CanvasNode = Node & { selected?: boolean };
const mascot = useMascotSettings();
const agentName = computed(() => mascot?.activeName.value || '点阵机器人');
const resubmitMessage = (submission: MessageResubmission) => props.resendMessage?.(submission) || Promise.resolve(false);
type CanvasEdge = Edge & { selected?: boolean };
// Annotate the refs to avoid recursively unwrapping Vue Flow's component types.
const nodes: Ref<CanvasNode[]> = ref([]);
const edges: Ref<CanvasEdge[]> = ref([]);
// Decoded dimensions also size the outer frame (handles and prompt panel).
// Key by source URL so replacing an image cannot inherit its previous ratio.
const mediaRatios = ref<Record<string, number>>({});
const previewSizeFor = (data: Record<string, any>) => nodePreviewSize(data, mediaRatios.value[nodeMediaUrl(data)]);
const nodeHasContent = (data: Record<string, any>) => Boolean(
  data.assetId || data.asset?.id || data.localFile || data.job || data.cad ||
  (Array.isArray(data.imageAssetIds) && data.imageAssetIds.length) ||
  (typeof data.text === 'string' && data.text.trim()) ||
  (typeof data.summary === 'string' && data.summary.trim()) ||
  (typeof data.html === 'string' && data.html.trim()),
);
watch(() => props.projectId, () => { mediaRatios.value = {}; });
const nodeReferences = computed(() => Object.fromEntries(nodes.value.map(node => [node.id,
  connectedReferences(node.id, nodes.value, edges.value, props.apiBaseUrl, props.projectId)])));
const { setViewport, screenToFlowCoordinate, onInit, getSelectedNodes, getSelectedEdges, removeSelectedNodes, removeSelectedEdges, zoomIn, zoomOut, viewport, multiSelectionActive, nodesSelectionActive } = useVueFlow('design-canvas');
const spacePanning = useKeyPress('Space', { actInsideInputWithModifier: false });
const canvasArea = ref<HTMLElement | null>(null);
// Update one inherited CSS variable instead of making every node's render
// depend on the live zoom. Panning does not touch the controls' dimensions.
watch([canvasArea, () => viewport.value.zoom], ([area, zoom]) => {
  area?.style.setProperty('--canvas-control-scale', String(1 / zoom));
}, { flush: 'sync' });
const overviewToggle = ref<HTMLButtonElement | null>(null);
const overviewVisibilityKey = 'langjuart.canvasOverviewVisible';
const overviewVisible = ref((() => { try { return localStorage.getItem(overviewVisibilityKey) !== 'false'; } catch { return true; } })());
watch(overviewVisible, value => { try { localStorage.setItem(overviewVisibilityKey, String(value)); } catch { /* Storage unavailable. */ } });
function navigateOverview(center: { x: number; y: number }) {
  if (!canvasArea.value) return;
  stopAutoFraming(); closeMenus();
  const zoom = viewport.value.zoom;
  void setViewport({ x: canvasArea.value.clientWidth / 2 - center.x * zoom, y: canvasArea.value.clientHeight / 2 - center.y * zoom, zoom });
}
async function hideOverview() { overviewVisible.value = false; await nextTick(); overviewToggle.value?.focus({ preventScroll: true }); }
const chatPanel = ref<HTMLElement | null>(null);
const { enabled: motionEnabled } = useMotionPolicy();
const showCanvas = defineModel<boolean>('canvasVisible', { default: true });
const isChatMinimized = ref(false);
const compactDock = ref<HTMLElement | null>(null);
const chatToggle = ref<HTMLButtonElement | null>(null);
const agentToggle = ref<HTMLButtonElement | null>(null);
const canvasTool = ref<'select' | 'pan'>('select');
async function toggleChat() {
  isChatMinimized.value = !isChatMinimized.value;
  closeMenus();
  await nextTick();
  (isChatMinimized.value ? agentToggle : chatToggle).value?.focus({ preventScroll: true });
}
const chatWidthKey = 'langjuart.designChatWidth';
const savedChatWidth = Number(localStorage.getItem(chatWidthKey));
const preferredChatWidth = ref(Number.isFinite(savedChatWidth) && savedChatWidth > 0 ? savedChatWidth : Math.min(440, Math.max(350, window.innerWidth * .31)));
const workspaceWidth = ref(window.innerWidth);
const maxChatWidth = computed(() => Math.max(0, Math.min(760, workspaceWidth.value - (workspaceWidth.value <= 700 ? 24 : 80))));
const minChatWidth = computed(() => Math.min(maxChatWidth.value, Math.round(Math.min(440, Math.max(320, workspaceWidth.value * .31)))));
const chatWidth = computed(() => Math.round(Math.min(maxChatWidth.value, Math.max(minChatWidth.value, preferredChatWidth.value))));
const isResizingChat = ref(false);
let chatResize: { pointerId: number; startX: number; startWidth: number; handle: HTMLElement } | null = null;
let workspaceObserver: ResizeObserver | undefined;
let composerObserver: ResizeObserver | undefined;
let chatScrollObserver: ResizeObserver | undefined;
const composerHeight = ref(220);

function startChatResize(event: PointerEvent) {
  if (event.button !== 0 || isChatMinimized.value) return;
  event.preventDefault();
  const handle = event.currentTarget as HTMLElement;
  chatResize = { pointerId: event.pointerId, startX: event.clientX, startWidth: chatPanel.value?.getBoundingClientRect().width || chatWidth.value, handle };
  handle.setPointerCapture(event.pointerId);
  isResizingChat.value = true;
  document.body.classList.add('is-resizing-design-chat');
}
function moveChatResize(event: PointerEvent) {
  if (!chatResize || event.pointerId !== chatResize.pointerId) return;
  preferredChatWidth.value = Math.min(maxChatWidth.value, Math.max(minChatWidth.value, chatResize.startWidth + event.clientX - chatResize.startX));
}
function stopChatResize() {
  const drag = chatResize;
  chatResize = null;
  if (drag?.handle.hasPointerCapture(drag.pointerId)) drag.handle.releasePointerCapture(drag.pointerId);
  if (isResizingChat.value) localStorage.setItem(chatWidthKey, String(chatWidth.value));
  isResizingChat.value = false;
  document.body.classList.remove('is-resizing-design-chat');
}
function resizeChatWithKeyboard(event: KeyboardEvent) {
  const delta = event.shiftKey ? 40 : 16;
  const sizes: Record<string, number> = { ArrowLeft: chatWidth.value - delta, ArrowRight: chatWidth.value + delta, Home: minChatWidth.value, End: maxChatWidth.value };
  if (!(event.key in sizes)) return;
  event.preventDefault();
  preferredChatWidth.value = Math.min(maxChatWidth.value, Math.max(minChatWidth.value, sizes[event.key]));
  localStorage.setItem(chatWidthKey, String(chatWidth.value));
}
onMounted(() => {
  // A reused Vue Flow store has already emitted init when switching projects.
  // Mounting a new board must still schedule its initial overview.
  canvasInitialized = true;
  void restoreCanvasView();
  emit('composer-ready');
  workspaceObserver = new ResizeObserver(([entry]) => { if (entry) workspaceWidth.value = entry.contentRect.width; if (autoFraming) scheduleAutoFocus(); });
  if (canvasArea.value) workspaceObserver.observe(canvasArea.value);
  composerObserver = new ResizeObserver(([entry]) => { const height = entry?.target.getBoundingClientRect().height; if (height) composerHeight.value = Math.ceil(height); });
  const composerHost = chatPanel.value?.querySelector('#design-composer-host');
  if (composerHost) composerObserver.observe(composerHost);
  chatScrollObserver = new ResizeObserver(updateChatScroll);
  if (scrollArea.value) {
    chatScrollObserver.observe(scrollArea.value);
    const messages = scrollArea.value.querySelector('.design-messages');
    if (messages) chatScrollObserver.observe(messages);
  }
  window.addEventListener('blur', stopChatResize);
});
onUnmounted(() => { stopChatResize(); clearTimeout(chatScrollTimer); workspaceObserver?.disconnect(); composerObserver?.disconnect(); chatScrollObserver?.disconnect(); window.removeEventListener('blur', stopChatResize); });
watch(isChatMinimized, minimized => { stopChatResize(); if (!minimized) canvasTool.value = 'select'; });
const scrollArea = ref<HTMLElement | null>(null);
const showReturnToBottom = ref(false);
const isChatScrolling = ref(false);
let chatScrollTimer: ReturnType<typeof setTimeout> | undefined;
function updateChatScroll() {
  const element = scrollArea.value;
  showReturnToBottom.value = Boolean(element && element.clientHeight > 0 && element.scrollHeight - element.scrollTop - element.clientHeight >= 160);
}
function handleChatScroll() {
  updateChatScroll();
  isChatScrolling.value = true;
  clearTimeout(chatScrollTimer);
  chatScrollTimer = setTimeout(() => { isChatScrolling.value = false; }, 900);
}
function returnToBottom() {
  scrollArea.value?.scrollTo({ top: scrollArea.value.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
}
const createMenu = ref<MenuPosition | null>(null);
const contextMenu = ref<(MenuPosition & { nodeId?: string }) | null>(null);
const contextMenuElement = ref<HTMLElement | null>(null);
const contextNode = computed(() => nodes.value.find(node => node.id === contextMenu.value?.nodeId));
const exportingNodes = ref(new Set<string>());
const dirtyDrawings = ref(new Set<string>());
function drawingSaved(result: { projectId: string; node: Record<string, any> }) {
  if (result.projectId !== props.projectId) return;
  const node = nodes.value.find(item => item.id === result.node.id);
  if (!node) return;
  const { drawing, asset, assetId, draft, error, status, referenceRole } = result.node.data;
  node.data = { ...node.data, drawing, asset, assetId, draft, error, status, referenceRole };
  const document = { ...snapshot(), lockedNodeIds: props.canvasDocument?.lockedNodeIds || [] };
  emit('canvas-change', document);
}
function drawingDirty(id: string, dirty: boolean) { if (dirty) dirtyDrawings.value.add(id); else dirtyDrawings.value.delete(id); }
const contextExportDisabled = computed(() => !contextNode.value || !canExportNode(contextNode.value.data)
  || uploadingNodes.value.has(contextNode.value.id) || exportingNodes.value.has(contextNode.value.id));
watch(contextMenu, async value => {
  await nextTick();
  if (!value || contextMenu.value !== value || !contextMenuElement.value) return;
  const bounds = contextMenuElement.value.getBoundingClientRect();
  value.x = Math.max(10, Math.min(value.x, window.innerWidth - bounds.width - 10));
  value.y = Math.max(10, Math.min(value.y, window.innerHeight - bounds.height - 10));
});
const deleteDialog = ref<HTMLDialogElement | null>(null);
const cancelDeleteButton = ref<HTMLButtonElement | null>(null);
const pendingDelete = ref<DeleteTarget | null>(null);
const deleteError = ref('');
const deleteActionLabel = computed(() => getSelectedNodes.value.length > 1 ? `删除 ${getSelectedNodes.value.length} 个节点` : getSelectedNodes.value.length ? '删除节点' : '删除选中连线');
watch(pendingDelete, async target => {
  await nextTick();
  if (target && pendingDelete.value === target) {
    if (!deleteDialog.value?.open) deleteDialog.value?.showModal();
    cancelDeleteButton.value?.focus();
  } else if (!pendingDelete.value) deleteDialog.value?.close();
});
watch(() => props.projectId, () => { pendingDelete.value = null; closeMenus(); });
const showShortcuts = ref(false);
const canvasToolTab = ref<'actions' | 'shortcuts'>('actions');
const selectedNodeId = computed(() => getSelectedNodes.value[0]?.id ?? null);
const selectingNodes = ref(false);
let marquee: { target: HTMLElement; pointerId: number; previous: Set<string>; additive: boolean } | null = null;
const alignmentActions: { mode: Alignment; label: string; icon: typeof AlignStartVertical; minimum: number }[] = [
  { mode: 'left', label: '左对齐', icon: AlignStartVertical, minimum: 2 },
  { mode: 'center-x', label: '水平居中', icon: AlignCenterVertical, minimum: 2 },
  { mode: 'right', label: '右对齐', icon: AlignEndVertical, minimum: 2 },
  { mode: 'top', label: '顶对齐', icon: AlignStartHorizontal, minimum: 2 },
  { mode: 'center-y', label: '垂直居中', icon: AlignCenterHorizontal, minimum: 2 },
  { mode: 'bottom', label: '底对齐', icon: AlignEndHorizontal, minimum: 2 },
  { mode: 'distribute-x', label: '水平等距分布', icon: AlignHorizontalSpaceBetween, minimum: 3 },
  { mode: 'distribute-y', label: '垂直等距分布', icon: AlignVerticalSpaceBetween, minimum: 3 },
];
const selectionToolbarPosition = computed(() => {
  const bounds = getRectOfNodes(getSelectedNodes.value);
  const { x, y, zoom } = viewport.value;
  // Keep controls at screen size while following the entire selection through
  // moves, alignment, pan and zoom. Leave room for the group drag handle.
  return { left: `${x + (bounds.x + bounds.width / 2) * zoom}px`, top: `${y + (bounds.y - 26) * zoom - 12}px` };
});
let selectionBeforeClick = new Set<string>();
let edgeSelectionBeforeClick = new Set<string>();
let disconnectGesture: { edgeId: string; projectId: string; x: number; y: number } | null = null;
function rememberSelection(event: MouseEvent | PointerEvent) {
  edgeSelectionBeforeClick = new Set(getSelectedEdges.value.map(edge => edge.id));
  selectionBeforeClick = new Set(getSelectedNodes.value.map(node => node.id)); multiSelectionActive.value = event.shiftKey || event.metaKey || event.ctrlKey;
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest('.canvas-drawing-pad')) stopAutoFraming();
  // Arm before Vue Flow's drag threshold: the first fast move may already be
  // inside an iframe, whose document cannot send mousemove/up to our window.
  if (event.button === 0 && target?.closest('.canvas-node-stack, .vue-flow__nodesselection-rect') && !target.closest('.nodrag, .vue-flow__handle, button, input, textarea, select, a')) interactingWithNode.value = true;
}
function startSelection(event: MouseEvent) {
  stopAutoFraming(); closeMenus(); selectingNodes.value = true; interactingWithNode.value = true;
  canvasArea.value?.focus({ preventScroll: true });
  marquee = { target: event.target as HTMLElement, pointerId: (event as PointerEvent).pointerId,
    previous: new Set(selectionBeforeClick), additive: event.shiftKey || event.metaKey || event.ctrlKey };
}
function finishSelection() {
  const gesture = marquee; marquee = null;
  if (gesture?.additive) {
    const ids = new Set([...gesture.previous, ...getSelectedNodes.value.map(node => node.id)]);
    nodes.value.forEach(node => { node.selected = ids.has(node.id); });
  }
  // A marquee selects nodes; external connections must not lock their layout
  // or become an unexpected delete target along with the selected nodes.
  removeSelectedEdges(getSelectedEdges.value);
  selectingNodes.value = false; interactingWithNode.value = false;
}
function cancelMarquee() {
  if (!marquee) return;
  const gesture = marquee;
  gesture.target.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, button: 0, pointerId: gesture.pointerId }));
  if (marquee) finishSelection();
}
function clearSelection() {
  cancelMarquee();
  // Clear Vue Flow's selection synchronously before the gesture-ending board
  // reconciliation runs; updating only v-model would restore stale selection.
  removeSelectedNodes(getSelectedNodes.value);
  removeSelectedEdges(getSelectedEdges.value);
  nodesSelectionActive.value = false;
}
watch([() => getSelectedNodes.value.map(node => node.id).join('|'), selectingNodes], () => {
  nodesSelectionActive.value = !selectingNodes.value && getSelectedNodes.value.length > 1;
}, { flush: 'post' });
// Keep the editor in view when a portrait preview or an expanded prompt makes the node taller.
let revealFrame = 0;
async function revealSelectedEditor() {
  if (nodes.value.find(node => node.id === selectedNodeId.value)?.data.editor === 'drawing') return;
  if (resizeBefore || dragBefore || autoFraming || selectingNodes.value || getSelectedNodes.value.length !== 1) return;
  await nextTick();
  cancelAnimationFrame(revealFrame);
  revealFrame = requestAnimationFrame(async () => {
    if (resizeBefore || dragBefore || autoFraming || selectingNodes.value || getSelectedNodes.value.length !== 1) return;
    const id = selectedNodeId.value, area = canvasArea.value;
    if (!id || !area) return;
    const element = area.querySelector<HTMLElement>(`.vue-flow__node[data-id="${CSS.escape(id)}"]`);
    if (!element) return;
    const boxes = [...element.querySelectorAll<HTMLElement>('.design-asset-node, .canvas-prompt-panel, .design-text-tools')].map(item => item.getBoundingClientRect()).filter(box => box.width && box.height);
    if (!boxes.length) return;
    const bounds = area.getBoundingClientRect(), panel = (isChatMinimized.value ? compactDock : chatPanel).value;
    const left = Math.min(...boxes.map(box => box.left)), top = Math.min(...boxes.map(box => box.top));
    const width = Math.max(...boxes.map(box => box.right)) - left, height = Math.max(...boxes.map(box => box.bottom)) - top;
    const insetLeft = bounds.left + Math.max(24, panel ? panel.offsetLeft + panel.offsetWidth + 20 : 24);
    const insetTop = bounds.top + 65, right = bounds.right - 24, bottom = bounds.bottom - 82;
    if (left >= insetLeft && left + width <= right && top >= insetTop && top + height <= bottom) return;
    const node = nodes.value.find(item => item.id === id);
    if (node) await focusOutputs([node], 0, false, viewport.value.zoom);
  });
}
watch([selectedNodeId, isChatMinimized], revealSelectedEditor);
onUnmounted(() => cancelAnimationFrame(revealFrame));
const createPosition = ref({ x: 120, y: 120 });
const uploadInput = ref<HTMLInputElement | null>(null);
const uploadingNodes = ref(new Set<string>());
const activeClarification = computed(() => pendingClarification(props.messages));
watch(() => activeClarification.value?.taskId, taskId => { if (taskId) isChatMinimized.value = false; });
const { undo: undoHistory, redo: redoHistory } = canvasEditHistory(props.apiBaseUrl, props.projectId);
const savingEdit = ref(false);
const lockedNodeIds = computed(() => new Set([...(props.canvasDocument?.lockedNodeIds || []), ...nodes.value.filter(node => node.data?.generating).map(node => node.id)]));
const nodeLocked = (id: string) => lockedNodeIds.value.has(id);
const edgeLocked = (id: string) => { const edge = edges.value.find(item => item.id === id); return Boolean(edge && (nodeLocked(edge.source) || nodeLocked(edge.target))); };
const selectionLocked = computed(() => getSelectedNodes.value.some(node => nodeLocked(node.id)) || getSelectedEdges.value.some(edge => edgeLocked(edge.id)));
const selectedNodesLocked = computed(() => getSelectedNodes.value.some(node => nodeLocked(node.id)));
let canvasInitialized = false;
let viewportReady = false;
const minCanvasZoom = ref(.2);
let autoFraming = true;
let autoFocusTimer: ReturnType<typeof setTimeout> | undefined;
let autoFocusPending = false;
let disposed = false;
let contentRevisions = new Map<string, string>();
let autoFocusNodeIds = new Set<string>();
const pendingContentIds = new Set<string>();
const observedNodes = new Set<Element>();
let autoLayoutRepairTimer: ReturnType<typeof setTimeout> | undefined;
let repairingAutomaticLayout = false;
const automaticallyPositioned = (node?: CanvasNode) => Boolean(node?.data?.autoPositioned);
function scheduleAutomaticLayoutRepair() {
  if (disposed || props.demoMode || savingEdit.value || repairingAutomaticLayout || interactingWithNode.value || !nodes.value.some(node => automaticallyPositioned(node) && !nodeLocked(node.id))) return;
  clearTimeout(autoLayoutRepairTimer);
  autoLayoutRepairTimer = setTimeout(() => { autoLayoutRepairTimer = undefined; void repairAutomaticLayout(); }, 80);
}
const nodeSizeObserver = new ResizeObserver(entries => {
  if (autoFraming && entries.some(entry => autoFocusNodeIds.has(entry.target.closest('.vue-flow__node')?.getAttribute('data-id') || ''))) scheduleAutoFocus();
  else if (entries.some(entry => entry.target.closest('.vue-flow__node')?.getAttribute('data-id') === selectedNodeId.value)) void revealSelectedEditor();
  if (entries.some(entry => automaticallyPositioned(nodes.value.find(node => node.id === entry.target.closest('.vue-flow__node')?.getAttribute('data-id'))))) scheduleAutomaticLayoutRepair();
});
let viewportTimer: ReturnType<typeof setTimeout> | undefined;
async function restoreCanvasView() {
  if (!canvasInitialized || viewportReady) return;
  viewportReady = true;
  if (nodes.value.length) { scheduleAutoFocus(); return; }
  let stored = null;
  try { stored = parseViewport(localStorage.getItem(`langjuart.viewport.${props.projectId}`)); } catch { /* Keep a useful initial view. */ }
  if (stored) { minCanvasZoom.value = Math.min(.2, stored.zoom); await nextTick(); await setViewport(stored); }
}
function stopAutoFraming() { autoFraming = false; autoFocusPending = false; pendingContentIds.clear(); clearTimeout(autoFocusTimer); autoFocusTimer = undefined; cancelAnimationFrame(revealFrame); }
watch(() => generalSettings.focusNewOutputs, enabled => { if (!enabled) stopAutoFraming(); else autoFraming = true; });
const navigatingViewport = ref(false);
let navigationEndTimer: ReturnType<typeof setTimeout> | undefined;
function canvasMoveStarted({ event }: { event: Event | null }) {
  clearTimeout(navigationEndTimer);
  navigatingViewport.value = true;
  if (event) stopAutoFraming();
}
function canvasMoveEnded() {
  // Wheel/trackpad bursts and animated fit operations can emit multiple end
  // events. Restore expensive effects only once the gesture actually settles.
  clearTimeout(navigationEndTimer);
  navigationEndTimer = setTimeout(() => { navigatingViewport.value = false; }, 120);
}
function scheduleAutoFocus() {
  if (!autoFraming || disposed) return;
  autoFocusPending = true;
  // Coalesce arrivals without postponing focus indefinitely during text streams.
  if (autoFocusTimer) return;
  autoFocusTimer = setTimeout(async () => {
    autoFocusTimer = undefined;
    if (disposed || !canvasInitialized || !autoFraming || interactingWithNode.value || isResizingChat.value || savingEdit.value) return;
    await nextTick();
    if (disposed || !autoFraming) return;
    if (pendingContentIds.size) { autoFocusNodeIds = new Set(pendingContentIds); pendingContentIds.clear(); }
    autoFocusPending = false;
    await focusOutputs(nodes.value.filter(node => autoFocusNodeIds.has(node.id)), 280, true);
  }, 120);
}
watch([selectedNodeId, isResizingChat], stopAutoFraming);
watch([isChatMinimized, composerHeight], () => { if (autoFraming) scheduleAutoFocus(); });
async function observeCanvasNodes() {
  await nextTick();
  if (disposed) return;
  const elements = new Set(canvasArea.value?.querySelectorAll('.canvas-node-stack, .canvas-prompt-panel') || []);
  for (const element of observedNodes) if (!elements.has(element)) { nodeSizeObserver.unobserve(element); observedNodes.delete(element); }
  for (const element of elements) if (!observedNodes.has(element)) { nodeSizeObserver.observe(element); observedNodes.add(element); }
  scheduleAutomaticLayoutRepair();
}
onMounted(() => { void observeCanvasNodes(); });
watch(() => nodes.value.map(node => `${node.id}:${node.data?.autoPositioned}:${node.data?.assetId || node.data?.asset?.id || ''}:${node.data?.text?.length || node.data?.summary?.length || 0}:${node.data?.previewSize?.width || ''}`).join('|'), () => { void observeCanvasNodes(); }, { flush: 'post' });
watch(viewport, value => {
  if (!viewportReady) return;
  clearTimeout(viewportTimer);
  const key = `langjuart.viewport.${props.projectId}`, saved = JSON.stringify({ x: value.x, y: value.y, zoom: value.zoom });
  viewportTimer = setTimeout(() => { try { localStorage.setItem(key, saved); } catch { /* Pan/zoom still works without persistence. */ } }, 150);
}, { deep: true });
onUnmounted(() => {
  disposed = true; clearTimeout(autoFocusTimer); nodeSizeObserver.disconnect();
  clearTimeout(autoLayoutRepairTimer);
  clearTimeout(navigationEndTimer);
  clearTimeout(viewportTimer);
  if (viewportReady) { try { localStorage.setItem(`langjuart.viewport.${props.projectId}`, JSON.stringify(viewport.value)); } catch { /* Storage unavailable. */ } }
});
watch([lockedNodeIds, selectedNodesLocked, savingEdit, spacePanning, () => getSelectedNodes.value.map(node => node.id).join('|')], () => {
  nodes.value.forEach(node => { node.draggable = !spacePanning.value && !nodeLocked(node.id) && !savingEdit.value && !(node.selected && selectedNodesLocked.value); });
});
watch(lockedNodeIds, (current, previous) => {
  if ([...previous].some(id => !current.has(id))) scheduleAutomaticLayoutRepair();
}, { flush: 'post' });

const smartSnap = ref(true);
const gridSnap = ref(false);
const alignmentGuides = ref<Guide[]>([]);
let dragBefore: Board | null = null;
const interactingWithNode = ref(false);
watch(interactingWithNode, active => { if (!active && autoFocusPending) scheduleAutoFocus(); });
let resizeBefore: Board | null = null;
function startNodeDrag() { stopAutoFraming(); dragBefore = snapshot(); interactingWithNode.value = true; }
function startNodeResize() { stopAutoFraming(); resizeBefore = snapshot(); interactingWithNode.value = true; }
function resizeNode(id: string, size: NodePreviewSize) {
  const node = nodes.value.find(node => node.id === id);
  if (node && resizeBefore) node.data = { ...node.data, previewSize: nodePreviewSize({ ...node.data, previewSize: size }) };
}
function finishNodeResize() {
  const before = resizeBefore; resizeBefore = null; interactingWithNode.value = false;
  if (before) {
    const after = snapshot();
    for (const node of after.nodes) {
      const original = before.nodes.find(item => item.id === node.id);
      if (original && JSON.stringify(original.data?.previewSize) !== JSON.stringify(node.data?.previewSize)) node.data = { ...node.data, autoPositioned: false };
    }
    void persistEdit(before, after);
  }
}
// iframe documents do not bubble mouseup to Vue Flow's window listeners.
// Disable their hit-testing during gestures and recover a release outside the app.
function releaseLostDrag(event: Event) {
  if (marquee && ['blur', 'pointercancel'].includes(event.type)) cancelMarquee();
  if (dragBefore && (['blur', 'pointercancel'].includes(event.type) || event instanceof MouseEvent && event.buttons === 0)) {
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }));
    if (dragBefore) finishDrag();
  }
  if (!dragBefore && !resizeBefore && !selectingNodes.value) interactingWithNode.value = false;
}
function releaseArmedInteraction() { if (!dragBefore && !resizeBefore && !selectingNodes.value) interactingWithNode.value = false; }
onMounted(() => { window.addEventListener('blur', releaseLostDrag); window.addEventListener('pointercancel', releaseLostDrag); window.addEventListener('mouseup', releaseArmedInteraction, true); });
onUnmounted(() => { window.removeEventListener('blur', releaseLostDrag); window.removeEventListener('pointercancel', releaseLostDrag); window.removeEventListener('mouseup', releaseArmedInteraction, true); });
const avatarState = (message?: ConversationMessage) => props.demoMode ? props.busy ? 'generating' : message?.status === 'succeeded' ? 'completed' : 'idle' : xiaojuState(message);
const progressLabel = computed(() => publicAssistantMessage(props.progress || '正在分析你的设计需求…'));
const kindLabels: Record<CanvasCreationKind, string> = { drawing: '画板', image: '图像', video: '视频', audio: '音频', text: '文本', html: '网页 HTML', cad: 'CAD 模型', upload: '上传图像' };
const stepStatusLabels = { running: '进行中', completed: '已完成', failed: '失败', cancelled: '已停止', adjusted: '调整' };
const executionTitles: Record<string, string> = { succeeded: '执行完成', failed: '执行中断', cancelled: '已停止' };
const visibleMessages = computed(() => props.messages.map((message) => {
  const outputs = message.taskId ? nodes.value.filter((node) => (node as any).meta?.taskId === message.taskId || node.data?.asset?.metadata?.taskId === message.taskId) : [];
  return { ...message, sources: (message.sources || []).filter((source) => { try { const url = new URL(source.url); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password; } catch { return false; } }), outputs, displayContent: message.role === 'assistant' ? canvasReply(message.content, outputs.length > 0) : message.content };
}));
function assistantCopyContent(message: (typeof visibleMessages.value)[number]) {
  if (message.role !== 'assistant') return '';
  if (message.clarification?.questions.length && message.status !== 'failed' && message.status !== 'cancelled') {
    return message.clarification.intro || '在开始设计前，先补充几个关键信息。';
  }
  return message.displayContent ? publicAssistantMessage(message.displayContent) : '';
}
const feedbackRecords = ref<Record<string, TaskFeedback>>({});
const feedbackLoaded = ref(false);
const latestAssistantTask = computed(() => [...props.messages].reverse().find(message => message.role === 'assistant')?.taskId);
watch(() => props.projectId, async (projectId, _, onCleanup) => {
  feedbackLoaded.value = false; feedbackRecords.value = {};
  if (props.demoMode) return;
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/testing/projects/${encodeURIComponent(projectId)}/feedback`, { signal: controller.signal });
    if (!response.ok) return;
    const records = await response.json() as TaskFeedback[];
    if (!controller.signal.aborted) {
      feedbackRecords.value = Object.fromEntries(records.map(record => [record.taskId, record]));
      feedbackLoaded.value = true;
    }
  } catch { /* Feedback is optional; task rendering must remain available. */ }
}, { immediate: true });
function viewTaskOutputs(taskId: string | undefined, outputs: Node[]) {
  recordBetaUsage('artifact_view', { projectId: props.projectId, taskId });
  void focusOutputs(outputs);
}

function inspectDeliveryNode(nodeId: string) {
  const node = nodes.value.find(item => item.id === nodeId);
  if (node) void focusOutputs([node]);
}

async function focusOutputs(outputs: Node[], duration = 420, automatic = false, maxZoom = 1) {
  if (!automatic) stopAutoFraming();
  if (!outputs.length || !canvasArea.value) return;
  if (canvasArea.value.clientWidth <= 700) isChatMinimized.value = true;
  await nextTick();
  const bounds = canvasArea.value.getBoundingClientRect();
  const panel = (isChatMinimized.value ? compactDock : chatPanel).value;
  // Layout dimensions stay stable while the chat's visual transform eases.
  const left = Math.max(24, panel ? panel.offsetLeft + panel.offsetWidth + 28 : 28);
  const region: FocusRect = { x: left, y: 80, width: bounds.width - left - 28, height: bounds.height - 164 };
  const controls: CanvasControlsRect[] = [];
  const rects = outputs.flatMap(node => {
    const element = canvasArea.value?.querySelector<HTMLElement>(`.vue-flow__node[data-id="${CSS.escape(node.id)}"]`);
    const origin = element?.getBoundingClientRect();
    const card = element?.querySelector<HTMLElement>('.design-asset-node')?.getBoundingClientRect();
    const editor = element?.querySelector<HTMLElement>('.canvas-prompt-panel')?.getBoundingClientRect();
    if (origin && card && editor?.width && editor.height) controls.push({
      x: node.position.x + (card.left + card.width / 2 - origin.left) / viewport.value.zoom,
      y: node.position.y + (card.bottom - origin.top) / viewport.value.zoom,
      width: editor.width, height: editor.height,
    });
    const boxes = [...(element?.querySelectorAll<HTMLElement>('.design-asset-node, .design-asset-node > header, .design-text-tools') || [])]
      .map(item => item.getBoundingClientRect()).filter(box => box.width && box.height);
    if (origin && boxes.length) return boxes.map(box => ({ x: node.position.x + (box.left - origin.left) / viewport.value.zoom,
      y: node.position.y + (box.top - origin.top) / viewport.value.zoom, width: box.width / viewport.value.zoom, height: box.height / viewport.value.zoom }));
    const size = previewSizeFor(node.data);
    return [{ ...node.position, width: size.width, height: size.height + 80 }];
  });
  const target = fitCanvasContents(rects, region, controls, maxZoom);
  if (!target || disposed) return;
  if (Math.abs(target.x - viewport.value.x) < .5 && Math.abs(target.y - viewport.value.y) < .5 && Math.abs(target.zoom - viewport.value.zoom) < .001) return;
  minCanvasZoom.value = Math.min(.2, target.zoom);
  await nextTick();
  if (!disposed) await setViewport(target, { duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : duration });
}
onInit(() => { canvasInitialized = true; void restoreCanvasView(); });

// Poll responses frequently contain the same board in fresh objects. Do not
// replace all Vue Flow nodes for identical content, or during a pan/zoom.
const canvasSyncKey = computed(() => JSON.stringify([props.projectId, props.canvasDocument, props.modelOptions, props.videoModelOptions]));
let appliedCanvasSyncKey = '', appliedCanvasProject = '';
watch([canvasSyncKey, interactingWithNode, savingEdit, navigatingViewport], () => {
  if (interactingWithNode.value || dragBefore || resizeBefore || savingEdit.value || navigatingViewport.value) return;
  if (canvasSyncKey.value === appliedCanvasSyncKey) return;
  const sameProject = appliedCanvasProject === props.projectId;
  if (!sameProject) { stopAutoFraming(); contentRevisions.clear(); autoFocusNodeIds.clear(); viewportReady = false; autoFraming = true; }
  const selectedIds = new Set(sameProject ? getSelectedNodes.value.map(node => node.id) : []);
  const selectedEdgeIds = new Set(sameProject ? getSelectedEdges.value.map(edge => edge.id) : []);
  const persistedIds = new Set((props.canvasDocument?.nodes || []).map(node => node.id));
  const drafts = sameProject ? nodes.value.filter((node) => node.data?.draft && !node.data?.generating && !persistedIds.has(node.id)) : [];
  const persisted = (props.canvasDocument?.nodes || []).map((node) => ({ ...node, type: 'creative', selected: selectedIds.has(node.id), data: { ...node.data, modelOptions: props.modelOptions, videoModelOptions: props.videoModelOptions, apiBaseUrl: props.apiBaseUrl, projectId: props.projectId } })) as unknown as CanvasNode[];
  nodes.value = [...persisted, ...drafts];
  edges.value = (props.canvasDocument?.edges || []).map((edge) => ({ ...edge, type: 'canvas-bezier', selected: selectedEdgeIds.has(edge.id), animated: edge.animated !== false })) as unknown as CanvasEdge[];
  const nextRevisions = new Map(persisted.map(node => [node.id, canvasContentRevision(node)]));
  const changedIds = persisted.filter(node => node.data.editor !== 'drawing' && contentRevisions.get(node.id) !== nextRevisions.get(node.id)).map(node => node.id);
  contentRevisions = nextRevisions;
  if (changedIds.length && (!sameProject || generalSettings.focusNewOutputs && autoFraming)) { changedIds.forEach(id => pendingContentIds.add(id)); showCanvas.value = true; scheduleAutoFocus(); }
  nodes.value.forEach(node => { node.draggable = !spacePanning.value && !nodeLocked(node.id) && !savingEdit.value && !(node.selected && selectedNodesLocked.value); });
  appliedCanvasSyncKey = canvasSyncKey.value; appliedCanvasProject = props.projectId;
  void restoreCanvasView();
}, { immediate: true });
// A demo closes on the full solution, after focusing individual arrivals.
watch(() => props.demoMode && props.messages.at(-1)?.status === 'succeeded', async complete => {
  if (!complete) return;
  await nextTick();
  if (!autoFraming) return;
  pendingContentIds.clear();
  nodes.value.forEach(node => pendingContentIds.add(node.id));
  scheduleAutoFocus();
});
let appliedTaskFocus: typeof props.taskFocus;
watch(() => [props.messages, props.progress, props.error], async () => {
  const element = scrollArea.value;
  const focusPending = props.taskFocus && props.taskFocus !== appliedTaskFocus;
  const follow = !focusPending && (!element || element.scrollHeight - element.scrollTop - element.clientHeight < 160);
  await nextTick();
  if (follow && scrollArea.value) scrollArea.value.scrollTop = scrollArea.value.scrollHeight;
  updateChatScroll();
}, { deep: true });
watch([() => props.taskFocus, () => props.messages.map(message => `${message.taskId}:${message.role}`).join('|'), () => nodes.value.map(node => node.id).join('|')], async () => {
  const target = props.taskFocus;
  if (!target || target === appliedTaskFocus) return;
  isChatMinimized.value = false;
  await nextTick();
  if (props.taskFocus !== target) return;
  if (target.nodeId) {
    const node = nodes.value.find(item => item.id === target.nodeId);
    if (!node) return;
    await focusOutputs([node]); appliedTaskFocus = target; return;
  }
  const area = scrollArea.value;
  const message = area?.querySelector<HTMLElement>(`.design-message.assistant[data-task-id="${CSS.escape(target.taskId)}"]`);
  // Project history may arrive after the page has mounted. Keep the request
  // pending until its actual message is rendered, including completed tasks.
  if (!area || !message) return;
  appliedTaskFocus = target;
  area.scrollTo({ top: area.scrollTop + message.getBoundingClientRect().top - area.getBoundingClientRect().top - 12, behavior: 'instant' });
  message.focus({ preventScroll: true });
  updateChatScroll();
}, { immediate: true, flush: 'post' });
function followReplyTyping() {
  const element = scrollArea.value;
  // Keep following the last line, but never pull readers away from history.
  if (element && element.scrollHeight - element.scrollTop - element.clientHeight < 160) element.scrollTop = element.scrollHeight;
  updateChatScroll();
}
function referenceNode(node: Pick<Node, 'id' | 'data'>, tentative = false) {
  if (dirtyDrawings.value.has(node.id)) { emit('canvas-error', '画板笔迹尚未保存，请保存后再引用'); return; }
  const assetId = node.data?.assetId || node.data?.asset?.id;
  if (!assetId && !node.data?.text && !node.data?.summary && !node.data?.html) return;
  emit('reference', assetId ? `@asset:${assetId}` : `@node:${node.id}`, tentative);
}
function submitClarification(taskId: string, submission: Omit<ClarificationSubmission, 'taskId'>) {
  if (props.busy || activeClarification.value?.taskId !== taskId) return;
  emit('clarify', { taskId, ...submission });
}
function closeMenus() { createMenu.value = null; contextMenu.value = null; }
function clickCanvasPane(event: MouseEvent) {
  closeMenus();
  if (event.button === 0 && !spacePanning.value && canvasTool.value === 'select') emit('cancel-canvas-reference');
}
function canvasPoint(event: MouseEvent): MenuPosition {
  return screenToFlowCoordinate({ x: event.clientX, y: event.clientY });
}
function openCreateMenu(event: MouseEvent) {
  if ((event.target as Element).closest('.vue-flow__node, .vue-flow__edge, .vue-flow__nodesselection-rect, .canvas-edge-delete, .canvas-selection-toolbar, .canvas-toolbar-actions, .canvas-overview, .canvas-shortcuts, .canvas-action-menu, .canvas-context-menu')) return;
  event.preventDefault(); event.stopPropagation(); closeMenus(); createPosition.value = canvasPoint(event); createMenu.value = menuPosition(event.clientX, event.clientY);
}
function openContextMenu(event: MouseEvent) {
  event.preventDefault();
  const target = event.target instanceof Element ? event.target : null;
  const nodeId = target?.closest('.vue-flow__node')?.getAttribute('data-id');
  const edgeId = target?.closest('.vue-flow__edge')?.getAttribute('data-id') || target?.closest('.canvas-edge-delete')?.getAttribute('data-edge-id');
  showContextMenu({ x: event.clientX, y: event.clientY }, nodeId || undefined, edgeId || undefined);
}
function showContextMenu(position: MenuPosition, nodeId?: string, edgeId?: string) {
  if (nodeId && !getSelectedNodes.value.some(node => node.id === nodeId)) {
    nodes.value.forEach(node => { node.selected = node.id === nodeId; });
    edges.value.forEach(edge => { edge.selected = false; });
  } else if (edgeId && !getSelectedEdges.value.some(edge => edge.id === edgeId)) {
    nodes.value.forEach(node => { node.selected = false; });
    edges.value.forEach(edge => { edge.selected = edge.id === edgeId; });
  }
  createMenu.value = null; createPosition.value = screenToFlowCoordinate(position);
  contextMenu.value = { ...position, nodeId };
}
async function saveNode(nodeId: string, format: NodeExportFormat) {
  const node = nodes.value.find(node => node.id === nodeId);
  if (!node || exportingNodes.value.has(nodeId) || uploadingNodes.value.has(nodeId)) return;
  const projectId = props.projectId;
  closeMenus();
  exportingNodes.value.add(nodeId);
  try { await exportNode({ ...node.data }, format); recordBetaUsage('artifact_export', { projectId, taskId: (node as any).meta?.taskId }); }
  catch (error) { if (props.projectId === projectId) emit('canvas-error', error instanceof Error ? error.message : '素材保存失败，请重试。'); }
  finally { exportingNodes.value.delete(nodeId); }
}
function menuPosition(x: number, y: number) { return { x: Math.max(10, Math.min(x, window.innerWidth - 190)), y: Math.max(10, Math.min(y, window.innerHeight - 290)) }; }
function createAtCenter() { const bounds = canvasArea.value?.getBoundingClientRect(); if (!bounds) return; const x = bounds.left + bounds.width * .65, y = bounds.top + bounds.height * .4; createPosition.value = screenToFlowCoordinate({ x, y }); createMenu.value = menuPosition(x, y); showShortcuts.value = false; }
function createFromDock(event: MouseEvent) {
  if (createMenu.value) { closeMenus(); return; }
  createAtCenter();
  const button = (event.currentTarget as HTMLElement).getBoundingClientRect();
  createMenu.value = menuPosition(button.right + 16, button.top);
}
function selectNode(node: Node, event: MouseEvent | TouchEvent) {
  closeMenus();
  if (event.shiftKey || event.metaKey || event.ctrlKey) {
    const ids = new Set(selectionBeforeClick);
    if (ids.has(node.id)) ids.delete(node.id); else ids.add(node.id);
    nodes.value.forEach(item => { item.selected = ids.has(item.id); });
    return;
  }
  isChatMinimized.value = false; referenceNode(node, true);
}
function selectEdge(edge: Edge, event: MouseEvent | TouchEvent) {
  closeMenus();
  if (!event.shiftKey && !event.metaKey && !event.ctrlKey) {
    if (edgeSelectionBeforeClick.has(edge.id)) {
      edgeSelectionBeforeClick.clear();
      void deleteEdge(edge.id);
      return;
    }
    nodes.value.forEach(node => { node.selected = false; });
    edges.value.forEach(item => { item.selected = item.id === edge.id; });
  }
  canvasArea.value?.focus({ preventScroll: true });
}
async function refreshCadBoard() {
  const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/canvas`);
  if (response.ok) emit('canvas-change', await response.json());
}
async function chooseNode(kind: CanvasCreationKind) {
  if (savingEdit.value) return;
  const before = snapshot();
  const projectId = props.projectId;
  const position = { ...createPosition.value }; closeMenus();
  if (kind === 'upload') { uploadInput.value?.click(); return; }
  savingEdit.value = true;
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/agent-tools/canvas_create_node`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, title: `新建${kindLabels[kind]}节点`, x: position.x, y: position.y }) });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    if (props.projectId !== projectId) return;
    const node = result.node;
    nodes.value.forEach(item => { item.selected = false; });
    node.selected = true;
    nodes.value = [...nodes.value.filter(item => item.id !== node.id), { ...node, type: 'creative', data: { ...node.data, modelOptions: props.modelOptions, videoModelOptions: props.videoModelOptions, apiBaseUrl: props.apiBaseUrl, projectId: props.projectId } } as Node];
    const after = cleanBoard({ nodes: [...before.nodes.filter(item => item.id !== node.id), node], edges: before.edges });
    remember(before, savedBoardEdit(before, after, result.canvas || after));
    if (result.canvas) emit('canvas-change', result.canvas);
  } catch (error) { emit('canvas-error', error instanceof Error ? error.message : '新增节点失败，请检查本地服务'); }
  finally { savingEdit.value = false; }
}
const submittingGenerations = new Set<string>();
async function generateFromNode(nodeId: string, prompt: string, kind: CanvasKind, params: Record<string, any> = {}) {
  const projectId = props.projectId;
  if (props.demoMode) { emit('canvas-error', '当前方案正在按阶段整理，请完成后再发起新的画布请求。'); return; }
  const node = nodes.value.find((item) => item.id === nodeId);
  if (!node || !prompt.trim() || node.data.generating || savingEdit.value || nodeLocked(nodeId) || submittingGenerations.has(nodeId)) return;
  if (nodeHasContent(node.data)) { emit('canvas-error', '已有内容的节点不能作为输出目标。请新建空白节点，将当前节点连线到新节点后生成。'); return; }
  if (kind === 'upload') kind = 'image';
  const references = nodeReferences.value[nodeId] || [];
  if (dirtyDrawings.value.has(nodeId) || references.some(ref => dirtyDrawings.value.has(ref.nodeId))) { emit('canvas-error', '请等待画板保存完成后再生成'); return; }
  const inputText = references.filter(ref => ref.text).map(ref => `【${ref.title}】\n${ref.text}`).join('\n\n');
  let effectiveParams: Record<string, any>;
  try { effectiveParams = canvasReferenceParams(references, params, nodeId, kind); }
  catch (error) { emit('canvas-error', error instanceof Error ? error.message : '参考素材未就绪'); return; }
  const generationData = { params, prompt: prompt.trim(), generating: true, draft: false, error: '', taskId: '' };
  node.data = { ...node.data, ...generationData };
  submittingGenerations.add(nodeId);
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/agent-tools/canvas_update_node`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ node_id: nodeId, patch: { data: generationData } }) });
    if (!response.ok) throw new Error(await response.text());
    const context = [inputText && `上游节点内容：\n${inputText}`].filter(Boolean).join('\n');
    emit('generate-node', kind, context ? `${prompt.trim()}\n${context}` : prompt.trim(), node.position, { ...effectiveParams, canvasProjectId: projectId });
  } catch (error) { node.data.generating = false; node.data.error = error instanceof Error ? error.message : '生成未能开始'; emit('canvas-error', node.data.error); }
  finally { await nextTick(); submittingGenerations.delete(nodeId); }
}
async function updateNodeData(nodeId: string, patch: Record<string, any>) {
  if (nodeLocked(nodeId)) return;
  const before = snapshot(), after = cleanBoard(before);
  const node = after.nodes.find(item => item.id === nodeId);
  if (!node) return;
  node.data = { ...node.data, ...patch };
  await persistEdit(before, after);
}
async function changeNodeAspect(nodeId: string, aspect: string) {
  const live = nodes.value.find(node => node.id === nodeId);
  if (!live || savingEdit.value || nodeLocked(nodeId) || nodeHasContent(live.data)) return;
  const patch = nodeAspectPatch(live.data, aspect);
  if (!patch) return;
  const before = snapshot(), after = cleanBoard(before);
  after.nodes.find(node => node.id === nodeId)!.data = { ...live.data, ...patch };
  live.data = { ...live.data, ...patch };
  await persistEdit(before, cleanBoard(after));
}
async function uploadIntoNode(nodeId: string, file: File) {
  const node = nodes.value.find(item => item.id === nodeId);
  if (!node || nodeLocked(nodeId) || uploadingNodes.value.has(nodeId)) return;
  const projectId = props.projectId;
  uploadingNodes.value.add(nodeId);
  try {
    if (['text', 'html'].includes(node.data.kind)) {
      const text = await file.text();
      if (props.projectId === projectId) await updateNodeData(nodeId, { [node.data.kind === 'html' ? 'html' : 'text']: text, summary: '', title: file.name, draft: false, error: '', assetId: null, asset: null, localFile: '' });
    } else {
      const form = new FormData(); form.append('file', file, file.name); form.append('kind', node.data.kind === 'image' ? 'image' : 'original');
      const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/assets/upload`, { method: 'POST', body: form });
      if (!response.ok) throw new Error(await response.text());
      const asset = await response.json();
      if (props.projectId === projectId) await updateNodeData(nodeId, { title: file.name, assetId: asset.id, asset, draft: false, error: '', localFile: '', text: '', summary: '', ...(asset.mime?.startsWith('image/') ? { params: { ...node.data.params, source_asset_id: asset.id }, referencePreviewUrl: `${props.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(asset.id)}/content` } : {}) });
    }
  } catch (error) { emit('canvas-error', error instanceof Error ? error.message : '上传失败，请重试'); }
  finally { uploadingNodes.value.delete(nodeId); }
}
function connectionPoint(event?: MouseEvent | TouchEvent) {
  if (!event) return null;
  const point = 'changedTouches' in event ? event.changedTouches[0] : event;
  return point ? { x: point.clientX, y: point.clientY } : null;
}
function startDisconnectGesture({ event, nodeId, handleType, handleId }: {
  event?: MouseEvent | TouchEvent; nodeId?: string; handleType?: string; handleId: string | null;
}) {
  disconnectGesture = null;
  if (handleType !== 'target' || savingEdit.value) return;
  const incoming = edges.value.filter(edge => edge.target === nodeId && (edge.targetHandle || 'input') === (handleId || 'input'));
  const selected = incoming.filter(edge => edge.selected);
  const edge = selected.length === 1 ? selected[0] : incoming.length === 1 ? incoming[0] : null;
  const point = connectionPoint(event);
  if (edge && point && !edgeLocked(edge.id)) disconnectGesture = { edgeId: edge.id, projectId: props.projectId, ...point };
}
function finishDisconnectGesture(event?: MouseEvent | TouchEvent) {
  const gesture = disconnectGesture;
  disconnectGesture = null;
  const point = connectionPoint(event);
  if (!gesture || !point || gesture.projectId !== props.projectId || event?.type === 'touchcancel') return;
  if (Math.hypot(point.x - gesture.x, point.y - gesture.y) < 8) return;
  const target = document.elementFromPoint(point.x, point.y);
  if (target?.closest('.vue-flow__pane') && canvasArea.value?.contains(target)) void deleteEdge(gesture.edgeId);
}
async function connectNodes(connection: Connection) {
  disconnectGesture = null;
  if (!connection.source || !connection.target || connection.source === connection.target || nodeLocked(connection.source) || nodeLocked(connection.target)) return;
  if (edges.value.some((edge) => edge.source === connection.source && edge.target === connection.target)) return;
  const before = snapshot();
  const edge: Edge = { id: `edge-${Date.now()}`, source: connection.source, target: connection.target, sourceHandle: connection.sourceHandle || 'output', targetHandle: connection.targetHandle || 'input', type: 'canvas-bezier', animated: true };
  edges.value = [...edges.value, edge];
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/agent-tools/canvas_link_nodes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_node_id: edge.source, target_node_id: edge.target, source_handle: edge.sourceHandle, target_handle: edge.targetHandle, label: '工作流连接' }) });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    if (result.edge) edges.value = edges.value.map(item => item.id === edge.id ? { ...result.edge, type: 'canvas-bezier' } : item);
    remember(before, snapshot());
    if (result.canvas) emit('canvas-change', result.canvas);
  } catch (error) {
    edges.value = edges.value.filter((item) => item.id !== edge.id);
    emit('canvas-error', error instanceof Error ? error.message : '节点连接保存失败');
  }
}
async function reconnectEdge({ edge, connection }: { edge: Edge; connection: Connection }) {
  if (savingEdit.value || edgeLocked(edge.id) || !connection.source || !connection.target || connection.source === connection.target || nodeLocked(connection.source) || nodeLocked(connection.target)) return;
  if (edges.value.some(item => item.id !== edge.id && item.source === connection.source && item.target === connection.target)) return;
  const before = snapshot(), after = cleanBoard(before);
  const updated = after.edges.find(item => item.id === edge.id);
  if (updated) { Object.assign(updated, connection); await persistEdit(before, after); }
}
async function handleUpload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
  const before = snapshot();
  const position = { ...createPosition.value };
  try {
    const form = new FormData(); form.append('file', file, file.name); form.append('kind', 'image');
    const upload = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/assets/upload`, { method: 'POST', body: form });
    if (!upload.ok) throw new Error(await upload.text());
    const asset = await upload.json();
    const nodeResponse = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/agent-tools/canvas_create_media`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ asset_id: asset.id, kind: 'image', title: file.name, x: position.x, y: position.y }) });
    if (!nodeResponse.ok) throw new Error(await nodeResponse.text());
    const result = await nodeResponse.json();
    const node = result.node || { id: `upload-${Date.now()}`, type: 'creative', position, data: { kind: 'image', previewSizingVersion: 2, title: file.name, assetId: asset.id, asset, apiBaseUrl: props.apiBaseUrl, projectId: props.projectId } };
    nodes.value = [...nodes.value.filter(item => item.id !== node.id), { ...node, type: 'creative', data: { ...node.data, asset, assetId: asset.id, apiBaseUrl: props.apiBaseUrl, projectId: props.projectId } } as Node];
    const after = cleanBoard({ nodes: [...before.nodes.filter(item => item.id !== node.id), node], edges: before.edges });
    remember(before, savedBoardEdit(before, after, result.canvas || after));
    if (result.canvas) emit('canvas-change', result.canvas);
  } catch {
    nodes.value = [...nodes.value, { id: `upload-${Date.now()}`, type: 'creative', position, data: { kind: 'image', previewSizingVersion: 2, title: file.name, text: '图片上传后可继续生成或引用', draft: true, localFile: URL.createObjectURL(file), apiBaseUrl: props.apiBaseUrl, projectId: props.projectId } } as Node];
  }
  if (uploadInput.value) uploadInput.value.value = ''; closeMenus();
}

function snapshot(): Board { return cleanBoard({ nodes: nodes.value, edges: edges.value }); }
function remember(before: Board, after: Board) {
  if (JSON.stringify(before) === JSON.stringify(after)) return;
  undoHistory.value = [...undoHistory.value.slice(-39), { before, after }]; redoHistory.value = [];
}
const comparingVersions = ref(false);
const comparisonInitialIds = ref<string[]>([]);
const comparableNodes = computed(() => nodes.value.filter(node => nodeHasContent(node.data)).map(node => ({ id: node.id, data: node.data || {} })));
function openVersionCompare() {
  comparisonInitialIds.value = getSelectedNodes.value.filter(node => nodeHasContent(node.data)).map(node => node.id).slice(0, 4);
  comparingVersions.value = true; closeMenus();
}
async function adoptVersion(id: string, comparedIds: string[]) {
  if (savingEdit.value || comparedIds.some(nodeLocked)) return;
  const before = snapshot(), after = snapshot();
  after.nodes.forEach(node => { if (comparedIds.includes(node.id)) node.data = { ...node.data, adopted: node.id === id, adoptedAt: node.id === id ? new Date().toISOString() : null }; });
  await persistEdit(before, after);
}
async function continueVersion(id: string) {
  const node = nodes.value.find(item => item.id === id);
  if (!node || nodeLocked(id)) return;
  referenceNode(node); comparingVersions.value = false; isChatMinimized.value = false;
  await nextTick(); document.querySelector<HTMLElement>('.intake-composer-editor')?.focus();
}

async function persistEdit(before: Board, after: Board, record = true, automatic = false) {
  if (savingEdit.value) return false;
  if (JSON.stringify(before) === JSON.stringify(after)) return true;
  savingEdit.value = true;
  const projectId = props.projectId;
  let deferredConflict = false;
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/canvas`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(boardChanges(before, after)) });
    if (!response.ok) {
      deferredConflict = automatic && response.status === 409;
      const message = await response.text();
      let detail = message;
      try { detail = JSON.parse(message).detail || message; } catch { /* Plain HTTP errors are already readable. */ }
      throw new Error(detail);
    }
    const doc = await response.json();
    if (props.projectId !== projectId) return false;
    const selected = new Set(getSelectedNodes.value.map(node => node.id));
    const selectedEdges = new Set(getSelectedEdges.value.map(edge => edge.id));
    nodes.value = doc.nodes.map((node: Node) => ({ ...node, selected: selected.has(node.id), data: { ...node.data, apiBaseUrl: props.apiBaseUrl, projectId } }));
    edges.value = doc.edges.map((edge: Edge) => ({ ...edge, type: 'canvas-bezier', selected: selectedEdges.has(edge.id) }));
    if (record) remember(before, savedBoardEdit(before, after, doc));
    emit('canvas-change', doc);
    return true;
  } catch (error) {
    if (!deferredConflict) emit('canvas-error', error instanceof Error ? error.message : '画布保存失败');
    try {
      const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/canvas`);
      if (response.ok && props.projectId === projectId) { const latest = await response.json(); nodes.value = latest.nodes; edges.value = latest.edges.map((edge: Edge) => ({ ...edge, type: 'canvas-bezier' })); emit('canvas-change', latest); }
    } catch { /* The next canvas snapshot will reconcile the edit. */ }
    return false;
  }
  finally { savingEdit.value = false; }
}
function selectedDeleteTarget(): DeleteTarget {
  const selected = getSelectedNodes.value;
  return { projectId: props.projectId, nodeIds: selected.map(node => node.id), edgeIds: getSelectedEdges.value.map(edge => edge.id),
    label: selected.length === 1 ? `「${selected[0].data.title || selected[0].data.label || '未命名节点'}」` : selected.length ? `${selected.length} 个节点` : `${getSelectedEdges.value.length} 条连线` };
}
async function deleteTargets(target: DeleteTarget) {
  if (savingEdit.value || target.projectId !== props.projectId || target.nodeIds.some(nodeLocked) || target.edgeIds.some(edgeLocked)) return false;
  const ids = new Set(target.nodeIds), edgeIds = new Set(target.edgeIds);
  if (!ids.size && !edgeIds.size) return false;
  const before = snapshot();
  const after = { nodes: before.nodes.filter(node => !ids.has(node.id)), edges: before.edges.filter(edge => !edgeIds.has(edge.id) && !ids.has(edge.source) && !ids.has(edge.target)) };
  return persistEdit(before, after);
}
async function deleteDrawing(id: string) {
  closeMenus();
  if (generalSettings.confirmNodeDelete && !window.confirm('删除这个画板？删除后可使用画布撤销。')) return false;
  const removed = await deleteTargets({ projectId: props.projectId, nodeIds: [id], edgeIds: [], label: '画板' });
  if (removed) canvasArea.value?.focus({ preventScroll: true });
  return removed;
}
async function deleteSelection() {
  const target = selectedDeleteTarget(); closeMenus();
  if (await deleteTargets(target)) canvasArea.value?.focus({ preventScroll: true });
}
async function deleteEdge(id: string) {
  closeMenus();
  if (await deleteTargets({ projectId: props.projectId, nodeIds: [], edgeIds: [id], label: '1 条连线' })) canvasArea.value?.focus({ preventScroll: true });
}
function requestDeleteSelection() {
  if (selectionLocked.value || savingEdit.value || pendingDelete.value) return;
  if (!generalSettings.confirmNodeDelete || !getSelectedNodes.value.length) { void deleteSelection(); return; }
  const target = selectedDeleteTarget();
  if (!target.nodeIds.length && !target.edgeIds.length) return;
  closeMenus(); deleteError.value = ''; pendingDelete.value = target;
}
function cancelDeletion() { if (!savingEdit.value) pendingDelete.value = null; }
async function confirmDeletion() {
  const target = pendingDelete.value;
  if (!target || savingEdit.value) return;
  deleteError.value = '';
  if (await deleteTargets(target)) {
    deleteDialog.value?.close();
    pendingDelete.value = null;
    await nextTick(); canvasArea.value?.focus({ preventScroll: true });
  } else if (pendingDelete.value === target) deleteError.value = '删除失败，请重试。';
}
async function duplicateSelection() {
  if (selectionLocked.value || savingEdit.value) return;
  const selected = getSelectedNodes.value;
  if (!selected.length) return;
  const before = snapshot(), after = cleanBoard(before);
  const ids = new Map(selected.map(node => [node.id, crypto.randomUUID()]));
  for (const node of before.nodes.filter(node => ids.has(node.id))) after.nodes.push({ ...node, id: ids.get(node.id), position: { x: node.position.x + 50, y: node.position.y + 50 }, data: { ...node.data, generating: false } });
  for (const edge of before.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target))) after.edges.push({ ...edge, id: crypto.randomUUID(), source: ids.get(edge.source), target: ids.get(edge.target) });
  await persistEdit(before, after); closeMenus();
}
async function undoEdit(redo = false) {
  if (savingEdit.value) return;
  const source = redo ? redoHistory : undoHistory, target = redo ? undoHistory : redoHistory;
  const entry = source.value.at(-1); if (!entry) return;
  const before = redo ? entry.before : entry.after, after = redo ? entry.after : entry.before;
  if (await persistEdit(before, after, false)) {
    const applied = savedBoardEdit(before, after, snapshot());
    source.value.pop();
    target.value.push(redo ? { before: entry.before, after: applied } : { before: applied, after: entry.after });
  }
}
function finishDrag() {
  interactingWithNode.value = false;
  alignmentGuides.value = [];
  if (dragBefore) {
    const before = dragBefore, after = snapshot();
    for (const node of after.nodes) {
      const original = before.nodes.find(item => item.id === node.id);
      if (original && (original.position.x !== node.position.x || original.position.y !== node.position.y)) node.data = { ...node.data, autoPositioned: false };
    }
    void persistEdit(before, after);
    dragBefore = null;
  }
}

function layoutRects(surfaceOnly = true): LayoutRect[] {
  return nodes.value.map(node => {
    const root = canvasArea.value?.querySelector<HTMLElement>(`.vue-flow__node[data-id="${CSS.escape(node.id)}"]`);
    const element = root?.querySelector<HTMLElement>(surfaceOnly ? '.design-node-surface' : '.design-asset-node');
    const box = element?.getBoundingClientRect(), origin = root?.getBoundingClientRect();
    const fallback = previewSizeFor(node.data);
    const zoom = viewport.value.zoom;
    // Measure the content frame, excluding the title, warnings and composer.
    // Use only the DOM's local offset: the dragged node position may already
    // be newer than the last rendered transform in this pointer event.
    const offsetX = surfaceOnly && box && origin ? (box.left - origin.left) / zoom : 0;
    const offsetY = surfaceOnly ? box && origin ? (box.top - origin.top) / zoom : 26 : 0;
    return { id: node.id, x: node.position.x + offsetX, y: node.position.y + offsetY,
      width: box?.width ? box.width / zoom : fallback.width,
      height: box?.height ? box.height / zoom : fallback.height + (surfaceOnly ? 0 : 40) };
  });
}
async function repairAutomaticLayout() {
  if (disposed || props.demoMode || savingEdit.value || repairingAutomaticLayout || interactingWithNode.value) return;
  await nextTick();
  const before = snapshot();
  const measured = layoutRects(false);
  if (measured.length !== before.nodes.length) return;
  const rectById = new Map(measured.map(rect => [rect.id, rect]));
  const automatic = before.nodes.filter(node => node.data?.autoPositioned && !nodeLocked(node.id) && rectById.has(node.id)).sort((left, right) =>
    Number(left.data?.autoLayoutOrder ?? Number.MAX_SAFE_INTEGER) - Number(right.data?.autoLayoutOrder ?? Number.MAX_SAFE_INTEGER)
    || left.id.localeCompare(right.id),
  );
  if (!automatic.length) return;
  const automaticIds = new Set(automatic.map(node => node.id));
  const occupied = measured.filter(rect => !automaticIds.has(rect.id));
  const after = cleanBoard(before);
  let changed = false;
  for (const source of automatic) {
    const rect = rectById.get(source.id)!;
    const position = nearestOpenPosition(rect, occupied);
    const target = after.nodes.find(node => node.id === source.id)!;
    // Rect coordinates include the rendered card's local offset. Apply the
    // delta rather than assuming every node begins at its Vue Flow origin.
    const nextPosition = {
      x: source.position.x + position.x - rect.x,
      y: source.position.y + position.y - rect.y,
    };
    if (Math.abs(nextPosition.x - source.position.x) > .1 || Math.abs(nextPosition.y - source.position.y) > .1) {
      target.position = nextPosition;
      changed = true;
    }
    occupied.push({ ...rect, ...position });
  }
  if (!changed) return;
  repairingAutomaticLayout = true;
  try { await persistEdit(before, after, false, true); }
  finally { repairingAutomaticLayout = false; }
}
function dragWithSnap({ node, nodes: movingNodes, event }: { node: Node; nodes: Node[]; event: MouseEvent | TouchEvent }) {
  alignmentGuides.value = [];
  if ('altKey' in event && event.altKey) return;
  const rects = layoutRects(), rect = rects.find(item => item.id === node.id);
  if (!rect) return;
  const moving = movingNodes?.length ? movingNodes : [node];
  const ids = new Set(moving.map(item => item.id));
  const snapped = smartSnap.value ? snapRect(rect, rects.filter(item => !ids.has(item.id)), 8 / viewport.value.zoom) : { x: rect.x, y: rect.y, guides: [] };
  if (gridSnap.value) {
    if (!snapped.guides.some(guide => guide.axis === 'x')) snapped.x = rect.x + Math.round(node.position.x / 20) * 20 - node.position.x;
    if (!snapped.guides.some(guide => guide.axis === 'y')) snapped.y = rect.y + Math.round(node.position.y / 20) * 20 - node.position.y;
  }
  const dx = snapped.x - rect.x, dy = snapped.y - rect.y;
  for (const item of moving) item.position = { x: item.position.x + dx, y: item.position.y + dy };
  alignmentGuides.value = snapped.guides;
}
async function arrangeNodes() {
  if (savingEdit.value) return;
  const before = snapshot(), after = cleanBoard(before);
  const selected = new Set(getSelectedNodes.value.map(node => node.id));
  const rects = layoutRects(false).filter(rect => !nodeLocked(rect.id) && (selected.size < 2 || selected.has(rect.id)));
  const available = (canvasArea.value?.clientWidth || 1280) - (isChatMinimized.value ? 80 : chatWidth.value + 80);
  const columns = Math.max(1, Math.min(3, Math.floor((available + 48) / 348)));
  const nextOrder = Math.max(0, ...after.nodes.map(node => Number(node.data?.autoLayoutOrder) || 0)) + 1;
  for (const [index, position] of arrangeRects(rects, columns).entries()) {
    const node = after.nodes.find(item => item.id === position.id);
    node.position = { x: position.x, y: position.y };
    node.data = { ...node.data, autoPositioned: true, autoLayoutOrder: nextOrder + index };
  }
  if (await persistEdit(before, after)) { nodes.value.forEach(node => { node.selected = false; }); await nextTick(); void focusOutputs(nodes.value.filter(node => rects.some(rect => rect.id === node.id))); }
}
async function alignSelection(mode: Alignment) {
  if (selectedNodesLocked.value || savingEdit.value || getSelectedNodes.value.length < (mode.startsWith('distribute') ? 3 : 2)) return;
  stopAutoFraming(); closeMenus();
  const before = snapshot(), selected = new Set(getSelectedNodes.value.map(node => node.id));
  const rects = layoutRects().filter(rect => selected.has(rect.id));
  await persistEdit(before, alignBoardNodes(before, rects, mode));
}

function canvasKeydown(event: KeyboardEvent) {
  if (event.defaultPrevented || event.isComposing || pendingDelete.value) return;
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], .canvas-markdown, .canvas-drawing-pad, .canvas-overview, .design-chat-panel, dialog, [role="dialog"], [role="alertdialog"]')) return;
  if (target && target !== document.body && target !== document.documentElement && !canvasArea.value?.contains(target) && !compactDock.value?.contains(target)) return;
  const mod = event.metaKey || event.ctrlKey;
  if (mod && event.key.toLowerCase() === 'z') { event.preventDefault(); void undoEdit(event.shiftKey); }
  else if (mod && event.key.toLowerCase() === 'y') { event.preventDefault(); void undoEdit(true); }
  else if (mod && event.key.toLowerCase() === 'd') { event.preventDefault(); void duplicateSelection(); }
  else if (mod && event.key === '0') { event.preventDefault(); void focusOutputs(nodes.value); }
  else if (mod && event.key.toLowerCase() === 'a') { event.preventDefault(); nodes.value.forEach(node => { node.selected = true; }); }
  else if (!mod && !event.altKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key) && getSelectedNodes.value.length) {
    // Handle before Vue Flow's selection-box keyboard handler so group nudges
    // are persisted once and undo as one operation.
    event.preventDefault(); event.stopPropagation();
    if (selectedNodesLocked.value || savingEdit.value) return;
    const before = snapshot(), after = cleanBoard(before), ids = new Set(getSelectedNodes.value.map(node => node.id));
    const step = event.shiftKey ? 10 : 1;
    after.nodes.filter(node => ids.has(node.id)).forEach(node => { node.position.x += event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0; node.position.y += event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0; node.data = { ...node.data, autoPositioned: false }; });
    void persistEdit(before, after);
  }
  else if ((event.key === 'Delete' || event.key === 'Backspace') && !mod && !event.altKey) {
    if (!getSelectedNodes.value.length && !getSelectedEdges.value.length) return;
    event.preventDefault();
    if (!event.repeat) requestDeleteSelection();
  }
  else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenus(); showShortcuts.value = false; clearSelection(); }
}
onMounted(() => window.addEventListener('keydown', canvasKeydown));
onUnmounted(() => window.removeEventListener('keydown', canvasKeydown));
</script>

<template>
  <CanvasVersionCompare v-if="comparingVersions" :nodes="comparableNodes" :initial-ids="comparisonInitialIds" :busy="savingEdit" :locked-ids="nodes.filter(node => nodeLocked(node.id)).map(node => node.id)" @close="comparingVersions = false" @adopt="adoptVersion" @continue="continueVersion" />
  <section class="design-workspace" :class="{ 'chat-minimized': isChatMinimized, 'canvas-pan-tool': canvasTool === 'pan', 'is-interacting-with-node': interactingWithNode, 'is-navigating-viewport': navigatingViewport, 'has-multiple-selection': getSelectedNodes.length > 1 }" :style="{ '--design-chat-width': `${chatWidth}px`, '--design-chat-min-width': `${minChatWidth}px`, '--design-composer-height': `${composerHeight}px` }" aria-label="设计 Agent 工作区" @click="closeMenus">
    <div ref="canvasArea" class="design-canvas-area" aria-label="无限画布" tabindex="-1" @contextmenu="openContextMenu" @keydown.capture="canvasKeydown" @pointerdown.capture="rememberSelection" @mousedown.capture="rememberSelection" @dblclick.capture="openCreateMenu">
      <VueFlow id="design-canvas" v-model:nodes="nodes" v-model:edges="edges" class="design-flow" :nodes-connectable="true" :elements-selectable="true" :select-nodes-on-drag="false" :node-drag-threshold="5" :selection-key-code="canvasTool === 'select'" :selection-mode="SelectionMode.Partial" :multi-selection-key-code="['Shift', 'Meta', 'Control']" :pan-activation-key-code="'Space'" :delete-key-code="null" :edges-updatable="true" :connection-line-type="ConnectionLineType.Bezier" :zoom-on-double-click="false" :pan-on-drag="spacePanning || canvasTool === 'pan' ? true : [1]" :min-zoom="minCanvasZoom" @move-start="canvasMoveStarted" @move-end="canvasMoveEnded" :max-zoom="MAX_CANVAS_ZOOM" :default-viewport="{ x: 24, y: 68, zoom: 0.85 }" @connect="connectNodes" @connect-start="startDisconnectGesture" @connect-end="finishDisconnectGesture" @edge-update="reconnectEdge" @node-click="({ node, event }) => selectNode(node, event)" @edge-click="({ edge, event }) => selectEdge(edge, event)" @pane-click="clickCanvasPane" @selection-start="startSelection" @selection-end="finishSelection" @node-drag-start="startNodeDrag" @node-drag="dragWithSnap" @node-drag-stop="finishDrag">
        <Background :variant="BackgroundVariant.Lines" pattern-color="var(--workspace-grid-color)" :gap="28" :line-width="1" />
        <template #edge-canvas-bezier="edgeProps">
          <GeneralCanvasEdge v-bind="edgeProps" :disabled="edgeLocked(edgeProps.id) || savingEdit" @delete="deleteEdge" />
        </template>
        <template #node-creative="nodeProps">
          <div class="canvas-node-stack" :class="{ 'has-html': nodeProps.data.kind === 'html' }" :style="{ '--canvas-node-width': `${previewSizeFor(nodeProps.data).width}px` }">
            <GeneralCanvasNode :node-id="nodeProps.id" :delete-drawing="() => deleteDrawing(nodeProps.id)" @drawing-saved="drawingSaved" @drawing-dirty="drawingDirty(nodeProps.id, $event)" @reference="referenceNode(nodeProps)" @cad-updated="refreshCadBoard" :data="nodeProps.data" :selected="nodeProps.selected" :exporting="exportingNodes.has(nodeProps.id)" :uploading="uploadingNodes.has(nodeProps.id)" :busy="nodeLocked(nodeProps.id) || savingEdit || uploadingNodes.has(nodeProps.id)" @export="saveNode(nodeProps.id, $event)" @cancel="emit('cancel-node-task', nodeProps.id, $event)" @context-menu="showContextMenu($event, nodeProps.id)" @dismiss-menu="closeMenus" @resize-start="startNodeResize" @resize="resizeNode(nodeProps.id, $event)" @resize-end="finishNodeResize" @upload="uploadIntoNode(nodeProps.id, $event)" @update="updateNodeData(nodeProps.id, $event)" @media-ratio="mediaRatios[$event.url] = $event.ratio" />
            <CanvasPromptPanel v-if="!nodeHasContent(nodeProps.data)" v-show="!selectingNodes && getSelectedNodes.length === 1 && selectedNodeId === nodeProps.id && nodeProps.data.editor !== 'drawing'"
              :kind="canvasNodeKind(nodeProps.data)"
              :api-base-url="apiBaseUrl" :project-id="projectId" :node-id="nodeProps.id"
              :model-options="modelOptions" :video-model-options="videoModelOptions" :text-model-options="textModelOptions" :audio-model-options="audioModelOptions"
              :generating="savingEdit || nodeProps.data.generating || uploadingNodes.has(nodeProps.id) || dirtyDrawings.has(nodeProps.id) || (nodeReferences[nodeProps.id] || []).some(ref => dirtyDrawings.has(ref.nodeId))" :params="nodeProps.data.params" :initial-prompt="nodeProps.data.prompt"
              :reference-preview-url="nodeProps.data.referencePreviewUrl"
              :connected-references="nodeReferences[nodeProps.id] || []"
              @aspect-change="changeNodeAspect(nodeProps.id, $event)"
              @submit="generateFromNode(nodeProps.id, $event.prompt, canvasNodeKind(nodeProps.data) as CanvasKind, $event.params)" />
            <p v-else-if="!selectingNodes && getSelectedNodes.length === 1 && selectedNodeId === nodeProps.id" class="canvas-filled-node-hint nodrag nowheel">已有内容节点仅作为来源。请新建空白节点并连线后生成。</p>
          </div>
        </template>
      </VueFlow>
      <svg v-if="alignmentGuides.length" class="canvas-alignment-guides" aria-hidden="true"><g :transform="`translate(${viewport.x}, ${viewport.y}) scale(${viewport.zoom})`"><line v-for="(guide, index) in alignmentGuides" :key="index" :x1="guide.axis === 'x' ? guide.value : guide.from" :x2="guide.axis === 'x' ? guide.value : guide.to" :y1="guide.axis === 'y' ? guide.value : guide.from" :y2="guide.axis === 'y' ? guide.value : guide.to" /></g></svg>
      <div v-if="!nodes.length" class="design-canvas-empty-region">
        <div class="design-canvas-empty"><Images :size="32" :stroke-width="1.3" /><h3>让设计在这里呈现</h3><p>右键或双击画布新增画板、图像、视频、文本等节点。</p><small>中键拖动 · 右键操作</small></div>
      </div>
      <div v-if="createMenu" class="canvas-action-menu" :style="{ left: `${createMenu.x}px`, top: `${createMenu.y}px` }" @click.stop>
        <strong>新增节点</strong>
        <button type="button" @click="chooseNode('drawing')"><Pencil :size="15" />画板</button>
        <button type="button" @click="chooseNode('cad')"><Plus :size="15" />CAD 模型</button><button type="button" @click="chooseNode('image')"><FileImage :size="15" />图像</button><button type="button" @click="chooseNode('video')"><Video :size="15" />视频</button><button type="button" @click="chooseNode('audio')"><Music2 :size="15" />音频</button><button type="button" @click="chooseNode('text')"><FileText :size="15" />文本</button><button type="button" @click="chooseNode('html')"><FileText :size="15" />网页 HTML</button><button type="button" @click="chooseNode('upload')"><Upload :size="15" />上传图像</button>
      </div>
      <div v-if="contextMenu" ref="contextMenuElement" class="canvas-context-menu" :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }" @click.stop>
        <template v-if="contextNode"><button type="button" :disabled="!nodeHasContent(contextNode.data)" @click="openVersionCompare">作品版本对比</button><button type="button" :disabled="nodeLocked(contextNode.id) || !nodeHasContent(contextNode.data)" @click="continueVersion(contextNode.id); closeMenus()">从此版继续修改</button>
          <template v-if="canvasNodeKind(contextNode.data) === 'html'">
            <button type="button" :disabled="contextExportDisabled" @click="saveNode(contextNode.id, 'html')"><Download :size="15" />导出 HTML</button>
            <button type="button" :disabled="contextExportDisabled" @click="saveNode(contextNode.id, 'pdf')"><Download :size="15" />导出 PDF</button>
          </template>
          <button v-else type="button" :disabled="contextExportDisabled" @click="saveNode(contextNode.id, 'original')"><Download :size="15" />{{ nodeSaveLabel(contextNode.data) }}</button>
          <div class="canvas-context-divider" role="separator" />
        </template>
        <button type="button" @click="createMenu = contextMenu; contextMenu = null"><Plus :size="15" />新增节点</button><button type="button" :disabled="selectionLocked || savingEdit || !selectedNodeId" @click="duplicateSelection"><Copy :size="15" />复制选中节点</button><button type="button" class="canvas-delete-action" :disabled="selectionLocked || savingEdit || (!selectedNodeId && !getSelectedEdges.length)" @click="deleteSelection"><Trash2 :size="15" />{{ deleteActionLabel }}</button><button type="button" @click="focusOutputs(nodes); closeMenus()"><Maximize2 :size="15" />适应画布</button><button type="button" @click="showShortcuts = true; canvasToolTab = 'shortcuts'; closeMenus()"><Circle :size="15" />画布快捷键</button><button type="button" @click="closeMenus"><X :size="15" />关闭菜单</button>
      </div>
      <div v-if="getSelectedNodes.length > 1 && !selectingNodes" class="canvas-selection-toolbar nodrag nopan" :style="selectionToolbarPosition" role="toolbar" aria-label="选中节点的移动与对齐" @pointerdown.stop @mousedown.stop @click.stop @contextmenu.stop>
        <button type="button" class="canvas-compare-button" aria-label="对比版本" title="对比版本" :disabled="getSelectedNodes.filter(node => nodeHasContent(node.data)).length < 2" @click="openVersionCompare"><Columns2 :size="17" /></button><span class="canvas-selection-count" role="status" :aria-label="`已选 ${getSelectedNodes.length} 个节点`" :title="`已选 ${getSelectedNodes.length} 个节点`"><Layers :size="15" aria-hidden="true" />{{ getSelectedNodes.length }}</span>
        <div class="canvas-selection-align" role="group" aria-label="对齐与分布">
          <button v-for="action in alignmentActions" :key="action.mode" type="button" :aria-label="action.label" :title="action.label" :disabled="selectedNodesLocked || savingEdit || getSelectedNodes.length < action.minimum" @click="alignSelection(action.mode)"><component :is="action.icon" :size="17" /></button>
        </div>
        <button type="button" class="canvas-selection-close" aria-label="取消选择" title="取消选择（Esc）" @click="clearSelection"><X :size="16" /></button>
      </div>
      <CanvasOverview v-if="overviewVisible" @navigate="navigateOverview" @close="hideOverview" />
      <div class="canvas-toolbar-actions" @click.stop @contextmenu.stop>
        <CanvasZoomControls @fit="focusOutputs(nodes)" />
        <button type="button" aria-label="画布操作与快捷键" :aria-expanded="showShortcuts" @click="showShortcuts = !showShortcuts"><Keyboard :size="17" /></button>
        <button ref="overviewToggle" type="button" class="canvas-overview-toggle" :class="{ active: overviewVisible }" :aria-label="overviewVisible ? '隐藏画布观察视图' : '显示画布观察视图'" :title="overviewVisible ? '隐藏画布观察视图' : '显示画布观察视图'" aria-controls="canvas-overview" :aria-expanded="overviewVisible" @click="overviewVisible = !overviewVisible"><MapIcon :size="17" /></button>
      </div>
      <div v-if="showShortcuts" class="canvas-shortcuts" @click.stop @contextmenu.stop>
        <header><button :class="{ active: canvasToolTab === 'actions' }" @click="canvasToolTab = 'actions'">操作</button><button :class="{ active: canvasToolTab === 'shortcuts' }" @click="canvasToolTab = 'shortcuts'">快捷键</button><button aria-label="关闭画布工具" @click="showShortcuts = false"><X :size="14" /></button></header>
        <div v-if="canvasToolTab === 'actions'" class="canvas-tool-options"><button :disabled="comparableNodes.length < 2" @click="openVersionCompare">作品版本对比</button><button @click="createAtCenter"><Plus :size="14" />新增节点</button><button @click="focusOutputs(nodes)"><Maximize2 :size="14" />适应全部节点</button><button :disabled="selectionLocked || savingEdit || !selectedNodeId" @click="duplicateSelection"><Copy :size="14" />复制节点</button><button :disabled="selectionLocked || savingEdit || (!selectedNodeId && !getSelectedEdges.length)" @click="deleteSelection"><Trash2 :size="14" />删除选中内容</button><button :disabled="savingEdit || !undoHistory.length" @click="undoEdit()"><Undo2 :size="14" />撤销</button><button :disabled="savingEdit || !redoHistory.length" @click="undoEdit(true)"><Redo2 :size="14" />重做</button><button :disabled="savingEdit || !nodes.length" @click="arrangeNodes"><Images :size="14" />{{ getSelectedNodes.length > 1 ? '整理选中节点' : '自动整理全部节点' }}</button><div class="canvas-snap-options"><label><input v-model="smartSnap" type="checkbox" />智能吸附</label><label><input v-model="gridSnap" type="checkbox" />网格吸附</label></div><div class="canvas-align-options"><button v-for="action in alignmentActions" :key="action.mode" :disabled="selectedNodesLocked || savingEdit || getSelectedNodes.length < action.minimum" @click="alignSelection(action.mode)">{{ action.label }}</button></div></div>
        <template v-else><p><kbd>双击</kbd> 新增节点</p><p><kbd>中键 / 空格</kbd> 按住拖动画布</p><p><kbd>左键拖动空白处</kbd> 框选多个节点</p><p><kbd>Shift + 框选</kbd> 追加到当前选择</p><p><kbd>Shift / ⌘ / Ctrl + 点击</kbd> 添加或取消单个节点</p><p><kbd>拖动选中节点 / 选区</kbd> 整体移动</p><p><kbd>Esc</kbd> 取消选择</p><p><kbd>拖动连接点</kbd> 连接上下游节点</p><p><kbd>Alt + 拖动</kbd> 暂时关闭吸附</p><p><kbd>⌘ / Ctrl + A</kbd> 全选节点</p><p><kbd>方向键</kbd> 微调位置，Shift 加速</p><p><kbd>拖动连线端点</kbd> 更换连接的节点；从左侧连接点拖至空白处断开</p><p><kbd>滚轮</kbd> 缩放画布</p><p><kbd>⌘ / Ctrl + 0</kbd> 适应全部节点</p><p><kbd>⌘ / Ctrl + D</kbd> 复制选中节点</p><p><kbd>Backspace / Delete</kbd> 删除选中连线；节点需确认</p><p><kbd>⌘ / Ctrl + Z</kbd> 撤销，加 Shift 重做</p></template>
      </div>
      <input ref="uploadInput" class="visually-hidden" type="file" accept="image/*" @change="handleUpload" />
    </div>
    <Transition name="canvas-dock" :css="motionEnabled">
    <div v-show="isChatMinimized" ref="compactDock" class="canvas-compact-dock" :inert="!isChatMinimized" :aria-hidden="!isChatMinimized" @click.stop @pointerdown.stop @contextmenu.prevent.stop @keydown="canvasKeydown">
      <button type="button" class="canvas-home-button" aria-label="返回首页" title="返回首页" @click="emit('return-home')"><House :size="18" :stroke-width="1.7" /></button>
      <div class="canvas-compact-tools" role="group" aria-label="画布基本操作">
        <button type="button" class="canvas-add-tool" aria-label="新增节点" title="新增节点" :aria-expanded="Boolean(createMenu)" @click="createFromDock"><Plus :size="22" /></button>
        <button type="button" :class="{ active: canvasTool === 'select' }" :aria-pressed="canvasTool === 'select'" aria-label="选择工具" title="选择 · 拖动空白处框选" @click="canvasTool = 'select'; closeMenus()"><MousePointer2 :size="19" /></button>
        <button type="button" :class="{ active: canvasTool === 'pan' }" :aria-pressed="canvasTool === 'pan'" aria-label="拖动画布" title="拖动画布 · 按住空格也可拖动" @click="canvasTool = 'pan'; closeMenus()"><Hand :size="19" /></button>
        <span class="canvas-tool-divider" role="separator" />
        <button type="button" :disabled="savingEdit || !nodes.length" aria-label="整理画布" :title="getSelectedNodes.length > 1 ? '整理选中节点' : '自动整理全部节点'" @click="arrangeNodes"><Images :size="19" /></button>
        <button type="button" :disabled="savingEdit || !undoHistory.length" aria-label="撤销" :title="savingEdit ? '正在保存画布' : undoHistory.length ? '撤销 · Ctrl / ⌘ + Z' : '暂无可撤销的画布编辑'" @click="undoEdit()"><Undo2 :size="19" /></button>
        <button type="button" :disabled="savingEdit || !redoHistory.length" aria-label="重做" :title="savingEdit ? '正在保存画布' : redoHistory.length ? '重做 · Ctrl + Y / ⌘ + Shift + Z' : '暂无可重做的画布编辑'" @click="undoEdit(true)"><Redo2 :size="19" /></button>
      </div>
      <button ref="agentToggle" type="button" class="canvas-agent-toggle" aria-label="展开对话" :title="`展开${agentName}对话`" aria-controls="design-chat-panel" :aria-expanded="!isChatMinimized" @click="toggleChat">
        <XiaojuAvatar :state="busy ? 'generating' : 'idle'" />
        <span v-if="busy" class="canvas-agent-busy" aria-label="正在生成" />
      </button>
    </div>
    </Transition>
    <Transition name="canvas-chat" :css="motionEnabled">
    <aside v-show="!isChatMinimized" id="design-chat-panel" ref="chatPanel" class="design-chat-panel" :class="{ resizing: isResizingChat }" :inert="isChatMinimized" :aria-hidden="isChatMinimized" :aria-label="`${agentName}对话面板`">
      <div v-if="!isChatMinimized" class="design-chat-resize-handle" role="separator" tabindex="0" aria-label="调整左侧对话栏宽度" aria-orientation="vertical" aria-controls="design-chat-panel" :aria-valuemin="minChatWidth" :aria-valuemax="maxChatWidth" :aria-valuenow="chatWidth" :aria-valuetext="`${chatWidth} 像素`" title="拖动调整宽度，也可使用左右方向键" @pointerdown.stop="startChatResize" @pointermove.stop="moveChatResize" @pointerup.stop="stopChatResize" @pointercancel.stop="stopChatResize" @lostpointercapture="stopChatResize" @keydown="resizeChatWithKeyboard" @click.stop />
      <header class="design-chat-header"><button type="button" class="canvas-home-button" aria-label="返回首页" title="返回首页" @click.stop="emit('return-home')"><House :size="18" :stroke-width="1.7" /></button><span class="design-chat-title"><strong>{{ agentName }}</strong></span><button ref="chatToggle" class="icon-button" type="button" aria-label="收起对话" title="收起对话" aria-controls="design-chat-panel" :aria-expanded="!isChatMinimized" @click.stop="toggleChat"><Minimize2 :size="17" /></button></header>
      <div id="design-chat-messages" ref="scrollArea" class="design-chat-scroll" :class="{ 'is-scrolling': isChatScrolling }" @scroll.passive="handleChatScroll">
          <div v-if="!messages.length" class="design-chat-welcome"><XiaojuAvatar /><h3>从一个设计目标开始</h3><p>描述你的设计想法，也可以上传参考图、品牌资料或项目需求。</p></div>
          <div class="design-messages" role="log" aria-label="对话记录" aria-live="polite">
            <article v-for="(message, index) in visibleMessages" :key="`${message.conversationTurnId || message.taskId || index}-${message.role}`" :data-task-id="message.taskId" tabindex="-1" class="design-message" :class="[message.role, { 'has-error': message.error }]">
              <span v-if="message.role === 'assistant'" class="design-message-agent"><XiaojuAvatar :state="avatarState(message)" /><strong>{{ agentName }}</strong><button v-if="message.taskId && message.execution" type="button" class="design-message-inspect" aria-label="查看产物与用量" title="查看产物与用量" @click.stop="emit('task-action', message.taskId, 'inspect')"><FileText :size="16" aria-hidden="true" /></button><AssistantMessageCopy v-if="assistantCopyContent(message)" :content="assistantCopyContent(message)" :task-id="message.taskId" /></span>
              <TaskProgress v-if="message.execution" :info="message.execution" :has-reply="Boolean(message.displayContent)" :status="message.status || 'running'" :clarification="Boolean(message.clarification)" :reference-selection="!!message.referenceSelection?.items.length && message.referenceSelection.status === 'pending'" @inspect="inspectDeliveryNode" @action="emit('task-action', message.taskId!, $event)" />
              <details v-if="message.steps?.length" class="design-execution" aria-label="执行过程" :open="!['succeeded', 'failed', 'cancelled'].includes(message.status || '')">
                <summary>{{ demoMode ? message.status === 'succeeded' ? '方案已完成' : busy ? '正在制作' : '方案已暂停' : executionTitles[message.status || ''] || '执行中' }}</summary>
                <TransitionGroup name="design-step" tag="ol" class="design-step-list">
                  <li v-for="step in message.steps" :key="step.id" :class="[step.status, { 'execution-summary': step.kind === 'summary' }]">
                    <DesignStepIcon :step="step" />
                    <AgentMarkdown v-if="step.kind === 'summary'" class="design-step-description" :content="step.label" compact /><span v-else>{{ step.label }}</span><small><LoaderCircle v-if="step.status === 'running'" :size="11" class="spin-icon" aria-hidden="true" /><CircleX v-else-if="step.status === 'failed'" :size="11" aria-hidden="true" />{{ step.kind === 'summary' ? '说明' : stepStatusLabels[step.status] }}</small>
                  </li>
                </TransitionGroup>
              </details>
              <AgentMarkdown v-if="message.role === 'assistant' && message.clarification?.questions.length && message.status !== 'failed' && message.status !== 'cancelled'" :content="message.clarification.intro || '在开始设计前，先补充几个关键信息。'" />
              <AgentMarkdown v-else-if="message.role === 'assistant' && message.displayContent" :content="publicAssistantMessage(message.displayContent)" :animate="message.animateReply" @reveal="followReplyTyping" />
              <UserMessageBubble v-else-if="message.role === 'user'" :message="message" :busy="busy" :resend="resubmitMessage" :edit-request="messageEditRequest && messageEditRequest.taskId === message.taskId ? messageEditRequest.requestId : undefined" />
              <button v-if="message.issue && message.taskId" class="design-canvas-result" :disabled="busy && message.issue.action !== 'settings'" @click="emit('task-action', message.taskId, message.issue.action)">{{ message.issue.actionLabel }}</button>
              <div v-if="message.verification && (message.verification.technical !== '产物已保存' || message.verification.content)" class="message-verification"><span v-if="message.verification.technical !== '产物已保存'">{{ message.verification.technical }}</span><span v-if="message.verification.content">{{ message.verification.content }}</span></div>
              <ReferenceSelectionCard v-if="message.referenceSelection?.items.length" :selection="message.referenceSelection" :api-base-url="apiBaseUrl" :project-id="projectId" :disabled="busy || pendingReferenceSelection(messages)?.id !== message.referenceSelection.id" @submit="emit('select-reference', $event)" />
              <div v-if="message.sources?.length" class="design-search-sources"><small>联网参考来源</small><a v-for="source in message.sources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }} <ArrowUpRight :size="12" /></a></div>
              <button v-if="message.role === 'assistant' && message.outputs.length" class="design-canvas-result" type="button" @click.stop="viewTaskOutputs(message.taskId, message.outputs)"><Images :size="15" />查看画布产物 · {{ message.outputs.length }}<ArrowUpRight :size="14" /></button>
              <TaskFeedbackPrompt v-if="message.role === 'assistant' && message.taskId && message.outputs.length" :key="`${projectId}:${message.taskId}`" :api-base-url="apiBaseUrl" :project-id="projectId" :task-id="message.taskId" :record="feedbackRecords[message.taskId]" :loaded="feedbackLoaded" :active="message.taskId === latestAssistantTask && !message.clarification?.questions.length" :ready="readyForFeedback(message.outputs)" :running="message.status === 'running' || message.status === 'queued'" @saved="feedbackRecords[message.taskId!] = $event" />
            </article>
          </div>
          <p v-if="busy" class="design-run-progress" role="status"><LoaderCircle :size="15" class="spin-icon" />{{ progressLabel }}</p><p v-if="error" class="design-run-error" role="alert">{{ publicAssistantMessage(error) }}</p>
        </div>
      <div v-if="activeClarification" class="design-clarification-dock">
        <DesignClarificationCard :key="`${projectId}:${activeClarification.taskId}:${JSON.stringify(activeClarification.clarification.questions)}`" :project-id="projectId" :task-id="activeClarification.taskId" :clarification="activeClarification.clarification" :busy="busy" @submit="submitClarification(activeClarification.taskId, $event)" />
      </div>
      <button v-if="showReturnToBottom && !activeClarification" class="design-return-bottom" type="button" :aria-label="busy ? '正在生成，返回底部' : '返回底部'" aria-controls="design-chat-messages" @click.stop="returnToBottom"><LoaderCircle v-if="busy" :size="14" class="spin-icon" aria-hidden="true" /><ArrowDown v-else :size="14" aria-hidden="true" />返回底部</button>
      <div id="design-composer-host" />
    </aside>
    </Transition>
    <Teleport to="body">
      <dialog ref="deleteDialog" class="canvas-delete-dialog" aria-labelledby="canvas-delete-title" aria-describedby="canvas-delete-description" @cancel.prevent="cancelDeletion" @keydown.stop @keydown.backspace.prevent>
        <span class="canvas-delete-icon"><Trash2 :size="21" /></span>
        <h2 id="canvas-delete-title">确认删除{{ pendingDelete?.nodeIds.length ? '节点' : '连线' }}？</h2>
        <p id="canvas-delete-description">将删除 <strong>{{ pendingDelete?.label }}</strong>{{ pendingDelete?.nodeIds.length ? '及相连的连线' : '' }}。</p>
        <small>删除后可按 ⌘ / Ctrl + Z 撤销。</small>
        <p v-if="deleteError" class="canvas-delete-error" role="alert">{{ deleteError }}</p>
        <footer><button ref="cancelDeleteButton" type="button" :disabled="savingEdit" @click="cancelDeletion">取消</button><button type="button" class="canvas-delete-confirm" :disabled="savingEdit" @click="confirmDeletion">{{ savingEdit ? '正在删除…' : '确认删除' }}</button></footer>
      </dialog>
    </Teleport>
  </section>
</template>

<style scoped>
.canvas-filled-node-hint { box-sizing:border-box; width:var(--canvas-node-width); margin:8px 0 0; padding:9px 11px; border:1px solid var(--theme-border); border-radius:10px; background:var(--theme-surface-raised); color:var(--theme-text-muted); font-size:11px; line-height:1.55; }
.design-return-bottom { position:absolute; z-index:3; bottom:calc(var(--design-composer-height, 220px) + 12px); left:50%; transform:translateX(-50%); display:inline-flex; align-items:center; gap:5px; min-height:32px; padding:6px 12px; border:1px solid var(--theme-border); border-radius:999px; background:var(--theme-surface-raised); color:var(--theme-text); box-shadow:0 3px 12px #0002; font-size:12px; line-height:18px; white-space:nowrap; cursor:pointer; }
.design-return-bottom:hover { border-color:var(--theme-accent-strong); }
.design-return-bottom:focus-visible { outline:2px solid var(--theme-accent-strong); outline-offset:3px; }
.design-step-description { flex: 1; min-width: 0; }
.design-message.has-error > .agent-markdown { color: var(--theme-danger); }
.design-clarification-dock { position:absolute; z-index:4; left:12px; right:12px; bottom:calc(var(--design-composer-height, 220px) + 10px); display:flex; min-height:0; max-height:min(480px, calc(100% - var(--design-composer-height, 220px) - 86px)); filter:drop-shadow(0 8px 18px #0002); }
.design-search-sources { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; font-size: 12px; }
.design-search-sources a { color: inherit; text-decoration: underline; overflow-wrap: anywhere; }
.design-search-sources small { opacity: .65; }
.design-canvas-area:focus { outline: none; }
.canvas-context-menu .canvas-delete-action { color: var(--theme-danger); }
.canvas-context-menu .canvas-delete-action:hover:not(:disabled) { background: var(--theme-danger-soft); }
.canvas-context-menu button:disabled { opacity: .4; }
.canvas-delete-dialog { width: min(400px, calc(100vw - 40px)); padding: 24px; border: 1px solid var(--theme-border); border-radius: 20px; background: var(--theme-surface); color: var(--theme-text); box-shadow: var(--theme-shadow); }
.canvas-delete-dialog::backdrop { background: var(--theme-overlay); backdrop-filter: blur(5px); }
.canvas-delete-icon { display: inline-grid; place-items: center; width: 42px; height: 42px; border-radius: 13px; color: var(--theme-danger); background: var(--theme-danger-soft); }
.canvas-delete-dialog h2 { margin: 16px 0 10px; font-size: 19px; font-weight: 600; }
.canvas-delete-dialog p { margin: 0 0 10px; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; color: var(--theme-text-muted); }
.canvas-delete-dialog strong { color: var(--theme-text); }
.canvas-delete-dialog small { color: var(--theme-text-subtle); font-size: 11px; }
.canvas-delete-dialog footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
.canvas-delete-dialog button { border: 1px solid var(--theme-border); border-radius: 10px; padding: 9px 16px; color: var(--theme-text); background: var(--theme-surface-raised); font-size: 12px; }
.canvas-delete-dialog button:focus-visible { outline: 2px solid var(--theme-accent-strong); outline-offset: 3px; }
.canvas-delete-dialog .canvas-delete-confirm { color: var(--theme-surface); background: var(--theme-danger); border-color: var(--theme-danger); }
.canvas-delete-dialog button:disabled { opacity: .5; }
.canvas-delete-dialog .canvas-delete-error { color: var(--theme-danger); margin-top: 12px; }
</style>

<style>
@import '@vue-flow/core/dist/style.css';
@import '@vue-flow/core/dist/theme-default.css';
</style>

<style scoped>
.message-verification{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0;font-size:11px;color:var(--theme-text-muted,#acacac)}.message-verification span{border:1px solid var(--theme-border);border-radius:8px;padding:5px 8px}
</style>
