import { computed, onScopeDispose, ref, watch, type Ref } from 'vue';
import type { Project } from '../../../../../packages/contracts/project';
import type { Board } from '../../canvasEditing';
import type { DesignStep } from '../../designPresentation';
import type { ConversationMessage } from '../pageServices';
import { showcaseNarrativeForSlug, type ShowcaseNarrative } from './showcaseNarratives';

type ShowcaseItem = { id: string; kind: string; title: string; delayMs: number; node: Record<string, any> };
type Session = { projectId: string; showcase: ShowcaseNarrative };

type Options = {
  projects: Ref<Project[]>;
  projectId: Ref<string | null>;
  visible: () => boolean;
  board: Ref<Board>;
  selectProject: (id: string) => void;
};

const cleanTitle = (title: string) => title.replace(/^\d+｜/, '');
const showcaseRole = (node: Record<string, any>) => String(node.data?.showcaseRole || '');
const isDeliveryText = (node: Record<string, any>) => showcaseRole(node) === 'handoff' || /交付|打样|说明/.test(String(node.data?.title || node.data?.text || ''));
const isIntroText = (node: Record<string, any>) => showcaseRole(node) === 'intro' || (!showcaseRole(node) && !isDeliveryText(node));
const curatedOrder = (node: Record<string, any>) => {
  const order = Number(node.data?.showcaseOrder);
  return Number.isFinite(order) ? order : Number.MAX_SAFE_INTEGER;
};

type ConversationSnapshot = {
  script: ShowcaseNarrative;
  items: ShowcaseItem[];
  completedIds: Set<string>;
  pending: ShowcaseItem | null;
  done: boolean;
  progress: string;
};

/** One narrative for staged home playback and the saved project's conversation. */
function showcaseMessages({ script, items, completedIds, pending, done, progress }: ConversationSnapshot): ConversationMessage[] {
  const plan = items.find(item => item.kind === 'text' && isIntroText(item.node));
  const images = items.filter(item => item.kind === 'image');
  const engineering = items.find(item => showcaseRole(item.node) === 'engineering');
  const html = items.find(item => item.kind === 'html' && showcaseRole(item.node) !== 'engineering');
  const handoff = items.find(item => item.kind === 'text' && isDeliveryText(item.node));
  const marketing = items.find(item => showcaseRole(item.node) === 'marketing');
  const isComplete = (item?: ShowcaseItem) => Boolean(item && completedIds.has(item.id));
  const messages: ConversationMessage[] = [
    { conversationTurnId: 'showcase-request', role: 'user', content: script.request },
    { conversationTurnId: 'showcase-clarification', role: 'assistant', status: 'succeeded', content: script.clarification },
    { conversationTurnId: 'showcase-answer', role: 'user', content: script.answer },
    { conversationTurnId: 'showcase-intake', role: 'assistant', status: isComplete(plan) ? 'succeeded' : 'running', animateReply: true, content: isComplete(plan) ? `项目信息已整理：\n\n${script.summary}` : `正在汇总「${script.name}」的项目背景、已确认条件和待核实信息，并建立画布中的设计计划。图片将逐张加载，每张 15 秒。` },
  ];
  if (!isComplete(plan)) return messages;
  messages.push(
    { conversationTurnId: 'showcase-plan', role: 'assistant', status: 'succeeded', content: script.requirements, steps: [{ id: plan!.id, label: cleanTitle(plan!.title), status: 'completed' }] },
    { conversationTurnId: 'showcase-production-request', role: 'user', content: script.productionRequest },
  );
  const visualSteps: DesignStep[] = images
    .filter(item => isComplete(item) || pending?.id === item.id)
    .map(item => ({ id: item.id, label: cleanTitle(item.title), status: isComplete(item) ? 'completed' : 'running' }));
  if (visualSteps.length) {
    const visualsDone = images.length > 0 && images.every(isComplete);
    messages.push({
      conversationTurnId: 'showcase-production', role: 'assistant', status: visualsDone ? 'succeeded' : 'running',
      content: visualsDone ? '系列视觉已按设计任务顺序呈现。接下来整理营销文案、可浏览的作品集和打样边界。' : `正在按设计任务逐张呈现关键视觉；每张图片固定展示 15 秒的加载过程。${progress}`,
      steps: visualSteps,
    });
  }
  if (!images.length || !images.every(isComplete)) return messages;
  messages.push({ conversationTurnId: 'showcase-copy-request', role: 'user', content: '视觉顺序清楚了。请补上适合这套产品的营销文字，最后整理成作品集，并明确哪些工程内容还需要实物确认。' });
  if (!marketing || isComplete(marketing)) messages.push({ conversationTurnId: 'showcase-marketing', role: 'assistant', status: 'succeeded', content: script.marketing });
  const deliverySteps: DesignStep[] = [engineering, marketing, html, handoff]
    .filter((item): item is ShowcaseItem => Boolean(item && (isComplete(item) || pending?.id === item.id)))
    .map(item => ({ id: item.id, label: cleanTitle(item.title), status: isComplete(item) ? 'completed' : 'running' }));
  if (deliverySteps.length) messages.push({
    conversationTurnId: 'showcase-delivery', role: 'assistant', status: done ? 'succeeded' : 'running',
    content: done ? `展示页面与交付说明已呈现完成。${script.handoff}` : `正在整理系列展示页面与交付说明。${progress}`,
    steps: deliverySteps,
  });
  return messages;
}

/**
 * Plays an already-saved curated project as a local, display-only sequence.
 * It never sends a task or changes the project: the complete board remains
 * intact and is only progressively revealed in this view.
 */
export function useShowcasePlayback(options: Options) {
  const session = ref<Session | null>(null);
  const items = ref<ShowcaseItem[]>([]);
  const completedIds = ref<Set<string>>(new Set());
  const pending = ref<ShowcaseItem | null>(null);
  const playing = ref(false);
  const preparing = ref(false);
  const error = ref('');
  let epoch = 0;
  let cancelDelay: (() => void) | undefined;

  const active = computed(() => Boolean(session.value && options.visible() && options.projectId.value === session.value.projectId));
  const completed = computed(() => items.value.filter(item => completedIds.value.has(item.id)));
  const done = computed(() => Boolean(items.value.length) && completed.value.length === items.value.length);
  const progress = computed(() => {
    if (error.value) return '展示过程已暂停，请从首页重新打开项目。';
    if (preparing.value) return '正在载入已保存的项目素材…';
    if (pending.value?.kind === 'image') return `正在逐张呈现「${cleanTitle(pending.value.title)}」· 本张预计 15 秒 · ${completed.value.length}/${items.value.length}`;
    if (pending.value) return `正在整理${cleanTitle(pending.value.title)} · ${completed.value.length}/${items.value.length}`;
    if (done.value) return `全部 ${items.value.length} 项内容已呈现`;
    return `已呈现 ${completed.value.length}/${items.value.length} 项内容`;
  });

  const messages = computed<ConversationMessage[]>(() => session.value ? showcaseMessages({
    script: session.value.showcase, items: items.value, completedIds: completedIds.value,
    pending: pending.value, done: done.value, progress: progress.value,
  }) : []);

  // A normal project entry has no playback session. Present the same narrative
  // against its saved, curated board without hiding nodes or starting timers.
  const savedMessages = computed<ConversationMessage[]>(() => {
    const project = options.projects.value.find(project => project.id === options.projectId.value);
    const script = project && showcaseNarrativeForSlug(project.slug);
    if (!script || !options.board.value.nodes.some(node => Number.isFinite(node.data?.showcaseOrder))) return [];
    const savedItems = makeItems(options.board.value);
    return showcaseMessages({ script, items: savedItems, completedIds: new Set(savedItems.map(item => item.id)),
      pending: null, done: true, progress: '',
    }).map(message => ({ ...message, animateReply: false }));
  });

  const canvasDocument = computed<Board>(() => {
    const source = options.board.value;
    if (!active.value) return source;
    const visibleIds = new Set(completedIds.value);
    const nextNodes = source.nodes.flatMap(node => {
      if (visibleIds.has(node.id)) return [node];
      if (pending.value?.id !== node.id) return [];
      const { asset, assetId, html, text, summary, ...rest } = node.data || {};
      return [{ ...node, data: { ...rest, kind: node.data?.kind, title: node.data?.title, generating: true, draft: true, params: { ...(node.data?.params || {}), ...(node.data?.kind === 'image' ? { aspectRatio: '16:9' } : {}) } } }];
    });
    const nextIds = new Set(nextNodes.map(node => node.id));
    return {
      ...source,
      lockedNodeIds: [...((source as any).lockedNodeIds || []), ...(pending.value ? [pending.value.id] : [])],
      nodes: nextNodes,
      edges: source.edges.filter(edge => nextIds.has(edge.source) && nextIds.has(edge.target)),
    };
  });

  function makeItems(board: Board): ShowcaseItem[] {
    const nodes = board.nodes as Record<string, any>[];
    const item = (node: Record<string, any>, delayMs: number): ShowcaseItem => ({ id: node.id, kind: String(node.data?.kind || 'content'), title: String(node.data?.title || '项目内容'), delayMs, node });
    // Curated showcase boards carry their own order, so the visual story stays
    // stable even if their JSON node storage or canvas positions change.
    const curated = nodes.filter(node => Number.isFinite(Number(node.data?.showcaseOrder)));
    if (curated.length) return curated
      .sort((left, right) => curatedOrder(left) - curatedOrder(right) || String(left.id).localeCompare(String(right.id)))
      .map(node => item(node, node.data?.kind === 'image' ? 15_000 : node.data?.kind === 'html' ? 4_500 : node.data?.kind === 'text' ? 2_400 : 3_000));
    const textNodes = nodes.filter(node => node.data?.kind === 'text');
    const plan = textNodes.find(isIntroText);
    const handoff = textNodes.find(isDeliveryText);
    const images = nodes.filter(node => node.data?.kind === 'image');
    const html = nodes.filter(node => node.data?.kind === 'html');
    const known = new Set([plan, handoff, ...images, ...html]
      .filter((node): node is Record<string, any> => Boolean(node))
      .map(node => node.id));
    const other = nodes.filter(node => !known.has(node.id));
    return [
      ...(plan ? [item(plan, 2_200)] : []),
      ...images.map(node => item(node, 15_000)),
      ...html.map(node => item(node, 4_500)),
      ...other.map(node => item(node, 3_000)),
      ...(handoff ? [item(handoff, 2_400)] : []),
    ];
  }

  const wait = (ms: number, token: number) => new Promise<boolean>(resolve => {
    const finish = (value: boolean) => { clearTimeout(timer); if (cancelDelay === cancel) cancelDelay = undefined; resolve(value); };
    const cancel = () => finish(false);
    const timer = setTimeout(() => finish(epoch === token), ms);
    cancelDelay = cancel;
  });

  function stop(clearSession = false) {
    epoch += 1;
    cancelDelay?.();
    cancelDelay = undefined;
    playing.value = false;
    preparing.value = false;
    pending.value = null;
    if (clearSession) session.value = null;
  }

  async function startWhenReady() {
    const current = session.value;
    if (!current || !preparing.value || options.projectId.value !== current.projectId || !options.visible() || !options.board.value.nodes.length) return;
    const nextItems = makeItems(options.board.value);
    if (!nextItems.length) { error.value = '该项目暂时没有可呈现的画布内容。'; preparing.value = false; return; }
    items.value = nextItems;
    preparing.value = false;
    playing.value = true;
    const token = ++epoch;
    for (const item of nextItems) {
      pending.value = item;
      if (!await wait(item.delayMs, token)) return;
      completedIds.value = new Set([...completedIds.value, item.id]);
      pending.value = null;
      if (epoch !== token) return;
    }
    if (epoch === token) { playing.value = false; pending.value = null; }
  }

  function open(slug: string) {
    const project = options.projects.value.find(item => item.slug === slug);
    const showcase = showcaseNarrativeForSlug(slug);
    if (!project || !showcase) { error.value = '这个精选项目尚未导入到当前工作区。'; return; }
    stop(true);
    session.value = { projectId: project.id, showcase };
    items.value = [];
    completedIds.value = new Set();
    error.value = '';
    preparing.value = true;
    options.selectProject(project.id);
  }

  watch([() => options.projectId.value, () => options.board.value.nodes, () => options.visible()], () => { void startWhenReady(); }, { deep: true });
  watch(() => options.projectId.value, projectId => { if (session.value && projectId !== session.value.projectId) stop(true); });
  watch(() => options.visible(), visible => { if (!visible && session.value) stop(true); });
  onScopeDispose(() => stop(true));

  return { active, playing, preparing, error, pending, completed, total: computed(() => items.value.length), done, progress, messages, savedMessages, canvasDocument, open };
}
