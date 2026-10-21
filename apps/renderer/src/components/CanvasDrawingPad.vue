<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { Pencil, Eraser, Undo2, Redo2, Trash2, ArrowUpRight } from 'lucide-vue-next';
import { copyDrawing, drawingPoint, paintDrawing, type DrawingContent, type DrawingDocument, type DrawingStroke } from '../features/drawing';

const props = defineProps<{ drawing: DrawingDocument; apiBaseUrl: string; projectId: string; nodeId: string; disabled?: boolean; deleteNode?: () => Promise<boolean> }>();
const emit = defineEmits<{ saved: [result: { projectId: string; node: Record<string, any> }]; dirty: [value: boolean]; reference: [] }>();
const surface = ref<HTMLCanvasElement | null>(null);
const paper = ref<HTMLElement | null>(null);
const paperSize = ref({ width: 1, height: 1 });
let observer: ResizeObserver | undefined;
const drawing = ref<DrawingContent>(copyDrawing(props.drawing));
const tool = ref<'pen' | 'eraser'>('pen');
const color = ref('#202020'), width = ref(6);
const undo = ref<DrawingContent[]>([]), redo = ref<DrawingContent[]>([]);
const saving = ref(false), error = ref(''), conflict = ref(false);
const deleting = ref(false);
const blocked = computed(() => props.disabled || deleting.value);
let activeSave: Promise<void> | undefined;
const editVersion = ref(0), savedVersion = ref(0);
const dirty = computed(() => editVersion.value !== savedVersion.value);
let revision = props.drawing.revision, mounted = true;
let timer: ReturnType<typeof setTimeout> | undefined;
let pointer: number | null = null, stroke: DrawingStroke | null = null;
let remainingPoints = 20000;
const draftKey = `langju.drawing.${props.projectId}.${props.nodeId}`;
function stash() {
  try {
    if (dirty.value) localStorage.setItem(draftKey, JSON.stringify({ baseRevision: revision, drawing: drawing.value }));
    else localStorage.removeItem(draftKey);
  } catch { /* A failed save stays visible; never claim persistence on quota failure. */ }
}
function repaint() { if (surface.value) paintDrawing(surface.value, drawing.value); }
function fitPaper() {
  if (!paper.value) return;
  const availableWidth = Math.max(1, paper.value.clientWidth - 16), availableHeight = Math.max(1, paper.value.clientHeight - 16);
  const scale = Math.min(availableWidth / drawing.value.width, availableHeight / drawing.value.height);
  paperSize.value = { width: drawing.value.width * scale, height: drawing.value.height * scale };
}
function remember() { undo.value.push(copyDrawing(drawing.value)); if (undo.value.length > 40) undo.value.shift(); redo.value = []; }
function changed() { editVersion.value++; error.value = ''; stash(); repaint(); schedule(); }
function schedule() { clearTimeout(timer); if (mounted && !conflict.value && !deleting.value) timer = setTimeout(() => void save(), 650); }
watch([dirty, saving], () => emit('dirty', dirty.value || saving.value), { immediate: true });
watch(() => props.drawing.revision, value => {
  if (value === revision || dirty.value || saving.value || pointer !== null) return;
  revision = value; drawing.value = copyDrawing(props.drawing); undo.value = []; redo.value = []; repaint();
});
function save(): Promise<void> {
  if (activeSave) return activeSave;
  if (deleting.value) return Promise.resolve();
  activeSave = persistDrawing().finally(() => {
    activeSave = undefined;
    if (!mounted && dirty.value && !error.value && !deleting.value) void save();
  });
  return activeSave;
}
async function persistDrawing() {
  clearTimeout(timer);
  if (!dirty.value || saving.value || conflict.value || pointer !== null) return;
  const version = editVersion.value, body = { baseRevision: revision, drawing: copyDrawing(drawing.value) };
  saving.value = true;
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/canvas/${encodeURIComponent(props.nodeId)}/drawing`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
    });
    const result = await response.json();
    if (!response.ok) { conflict.value = response.status === 409; throw new Error(typeof result.detail === 'string' ? result.detail : '画板保存失败，请重试'); }
    revision = result.node.data.drawing.revision;
    savedVersion.value = version;
    error.value = '';
    emit('saved', result);
    stash();
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '画板保存失败，请重试'; stash(); }
  finally { saving.value = false; if (mounted && dirty.value && !error.value) schedule(); }
}
async function deleteDrawing() {
  if (blocked.value || !props.deleteNode) return;
  finish(); deleting.value = true; clearTimeout(timer);
  try {
    // Finish an already submitted write before taking the deletion snapshot.
    await activeSave;
    if (!mounted) { deleting.value = false; stash(); void save(); return; }
    if (!await props.deleteNode()) throw new Error('画板删除失败，请重试');
    try { localStorage.removeItem(draftKey); } catch { /* Storage may be unavailable. */ }
  } catch (reason) {
    deleting.value = false;
    error.value = reason instanceof Error ? reason.message : '画板删除失败，请重试';
    stash();
    if (!mounted) void save();
  }
}
function start(event: PointerEvent) {
  if (blocked.value || event.button !== 0 || pointer !== null || conflict.value) return;
  if (drawing.value.strokes.length >= 2000 || drawing.value.strokes.reduce((n, s) => n + s.points.length, 0) >= 95000) { error.value = '笔迹较多，请新建另一张画板继续'; return; }
  event.preventDefault(); surface.value?.focus({ preventScroll: true });
  remember(); pointer = event.pointerId; surface.value?.setPointerCapture(pointer);
  remainingPoints = Math.min(20000, 100000 - drawing.value.strokes.reduce((n, s) => n + s.points.length, 0));
  stroke = { tool: tool.value, color: color.value, width: tool.value === 'eraser' ? Math.max(16, width.value * 2) : width.value,
    points: [drawingPoint(event.clientX, event.clientY, surface.value!.getBoundingClientRect(), drawing.value)] };
  drawing.value.strokes.push(stroke); repaint();
}
function move(event: PointerEvent) {
  if (event.pointerId !== pointer || !stroke || !surface.value || stroke.points.length >= remainingPoints) return;
  const point = drawingPoint(event.clientX, event.clientY, surface.value.getBoundingClientRect(), drawing.value);
  const previous = stroke.points.at(-1)!;
  if (Math.hypot(point[0] - previous[0], point[1] - previous[1]) < 1) return;
  stroke.points.push(point); repaint();
}
function finish() {
  if (pointer === null) return;
  const id = pointer; pointer = null; stroke = null;
  if (surface.value?.hasPointerCapture(id)) surface.value.releasePointerCapture(id);
  changed();
}
function history(forward = false) {
  if (blocked.value || conflict.value || pointer !== null) return;
  const source = forward ? redo.value : undo.value, target = forward ? undo.value : redo.value;
  const next = source.pop(); if (!next) return;
  target.push(copyDrawing(drawing.value)); drawing.value = next; changed();
}
function clear() { if (blocked.value || conflict.value || pointer !== null || !drawing.value.strokes.length) return; remember(); drawing.value.strokes = []; changed(); }
function keyboard(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); history(event.shiftKey); }
}
async function reload() {
  try {
    const response = await fetch(`${props.apiBaseUrl}/api/projects/${encodeURIComponent(props.projectId)}/canvas`);
    if (!response.ok) throw new Error('读取画板失败');
    const board = await response.json(), node = board.nodes.find((n: any) => n.id === props.nodeId);
    if (!node?.data.drawing) throw new Error('画板已被删除');
    revision = node.data.drawing.revision; drawing.value = copyDrawing(node.data.drawing);
    savedVersion.value = editVersion.value; undo.value = []; redo.value = []; conflict.value = false; error.value = '';
    stash(); repaint(); emit('saved', { projectId: props.projectId, node });
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '读取失败'; }
}
onMounted(async () => {
  try {
    const cached = JSON.parse(localStorage.getItem(draftKey) || 'null');
    if (cached?.drawing && cached.drawing.strokes?.length >= 0) {
      if (JSON.stringify(copyDrawing(props.drawing)) === JSON.stringify(cached.drawing)) localStorage.removeItem(draftKey);
      else {
        drawing.value = cached.drawing; editVersion.value++;
        if (cached.baseRevision !== revision) { conflict.value = true; error.value = '本地草稿与当前画板版本不同；可保留此页笔迹，或放弃本地改动载入最新版本。'; }
        else schedule();
      }
    }
  } catch { /* Invalid local draft: use the persisted project node. */ }
  await nextTick(); repaint(); fitPaper();
  observer = new ResizeObserver(fitPaper); if (paper.value) observer.observe(paper.value);
});
onUnmounted(() => { mounted = false; observer?.disconnect(); finish(); clearTimeout(timer); if (!deleting.value) { stash(); void save(); } emit('dirty', false); });
</script>

<template>
  <div class="canvas-drawing-pad nodrag nopan nowheel" @pointerdown.stop @mousedown.stop @click.stop @dblclick.stop @contextmenu.stop.prevent @keydown.stop="keyboard">
    <div class="drawing-tools" role="toolbar" aria-label="画板工具">
      <button type="button" :class="{ active: tool === 'pen' }" aria-label="画笔" :aria-pressed="tool === 'pen'" @click="tool = 'pen'"><Pencil :size="15" /></button>
      <button type="button" :class="{ active: tool === 'eraser' }" aria-label="橡皮" :aria-pressed="tool === 'eraser'" @click="tool = 'eraser'"><Eraser :size="15" /></button>
      <input v-model="color" type="color" aria-label="画笔颜色" title="画笔颜色" @input="tool = 'pen'" />
      <label class="drawing-width">粗细<input v-model.number="width" type="range" min="1" max="32" aria-label="画笔粗细" /></label>
      <button type="button" aria-label="撤销笔迹" :disabled="blocked || conflict || !undo.length" @click="history()"><Undo2 :size="15" /></button>
      <button type="button" aria-label="重做笔迹" :disabled="blocked || conflict || !redo.length" @click="history(true)"><Redo2 :size="15" /></button>
      <button type="button" aria-label="清空画板" title="清空画板内容（可撤销）" :disabled="blocked || conflict || !drawing.strokes.length" @click="clear"><Eraser :size="15" />清空</button>
      <button type="button" aria-label="删除画板节点" title="删除此画板节点及相连连线" :disabled="blocked || !deleteNode" @click="deleteDrawing"><Trash2 :size="15" />删除</button>
      <button class="drawing-reference" type="button" :disabled="blocked || dirty || saving || !drawing.strokes.length || !props.drawing.hasContent" @click="emit('reference')"><ArrowUpRight :size="15" />引用布局</button>
    </div>
    <div ref="paper" class="drawing-paper">
      <canvas ref="surface" tabindex="0" aria-label="布局画板绘画区" :class="{ erasing: tool === 'eraser', locked: blocked || conflict }" :style="{ width: `${paperSize.width}px`, height: `${paperSize.height}px` }"
        @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="finish" @lostpointercapture="finish" />
      <span v-if="!drawing.strokes.length" class="drawing-hint">用鼠标画出主体位置、轮廓和布局</span>
    </div>
    <div class="drawing-status" role="status">
      <span v-if="error" class="drawing-error">{{ error }}</span>
      <span v-else>{{ deleting ? '正在删除…' : disabled ? '任务正在使用此画板' : saving ? '正在保存…' : dirty ? '笔迹待保存' : '已保存 · 结构布局参考' }}</span>
      <button v-if="error && !conflict" type="button" :disabled="saving || blocked" @click="save">重试保存</button>
      <button v-if="conflict" type="button" :disabled="blocked" @click="reload">放弃本地改动，载入最新</button>
    </div>
  </div>
</template>

<style scoped>
.canvas-drawing-pad{height:100%;display:flex;flex-direction:column;background:var(--theme-surface,#232323);color:var(--theme-text,#eee);font-size:12px}
.drawing-tools{display:flex;align-items:center;flex-wrap:wrap;gap:5px;padding:8px;border-bottom:1px solid var(--theme-border,#444)}
.drawing-tools button,.drawing-status button{display:inline-flex;align-items:center;justify-content:center;gap:4px;border:0;border-radius:5px;padding:6px;background:transparent;color:inherit;cursor:pointer;font:inherit}
.drawing-tools button.active,.drawing-tools button:hover{background:var(--theme-accent-soft,#4c4c4c)}
.drawing-tools button:disabled{opacity:.35;cursor:default}.drawing-tools input[type=color]{width:27px;height:26px;padding:1px;border:1px solid #777;border-radius:4px;background:none}
.drawing-width{display:flex;align-items:center;gap:3px;color:var(--theme-text-muted,#b4b4b4)}.drawing-width input{width:60px}.drawing-reference{margin-left:auto}
.drawing-paper{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;padding:8px;position:relative;overflow:hidden;background:#e4e6e3}
canvas{display:block;max-width:100%;max-height:100%;width:auto;height:100%;background:white;touch-action:none;cursor:crosshair;box-shadow:0 1px 5px #0002}
canvas.erasing{cursor:cell}canvas.locked{cursor:not-allowed}.drawing-hint{position:absolute;pointer-events:none;color:#9a9d99;font-size:14px}
.drawing-status{padding:5px 9px;min-height:24px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--theme-text-muted,#b4b4b4)}.drawing-error{color:#b1b1b1}.drawing-status button{text-decoration:underline;padding:2px}
button:focus-visible,canvas:focus-visible{outline:2px solid var(--theme-accent-strong,#c3c3c3);outline-offset:-2px}
</style>
