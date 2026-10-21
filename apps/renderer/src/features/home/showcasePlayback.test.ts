import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { effectScope, ref } from 'vue';
import type { Project } from '../../../../../packages/contracts/project';
import type { Board } from '../../canvasEditing';
import { useShowcasePlayback } from './showcasePlayback';
import { showcaseNarratives } from './showcaseNarratives';

const scopes: ReturnType<typeof effectScope>[] = [];
beforeEach(() => vi.useFakeTimers());
afterEach(() => { scopes.forEach(scope => scope.stop()); scopes.length = 0; vi.useRealTimers(); });
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };

const board: Board = { nodes: [
  { id: 'plan', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'text', title: '完整设计方案', text: '方案内容' } },
  { id: 'image-a', type: 'creative', position: { x: 400, y: 0 }, data: { kind: 'image', title: '品牌主视觉', assetId: 'asset-a' } },
  { id: 'image-b', type: 'creative', position: { x: 1200, y: 0 }, data: { kind: 'image', title: '产品包装', assetId: 'asset-b' } },
  { id: 'html', type: 'creative', position: { x: 400, y: 700 }, data: { kind: 'html', title: '系列展示页', html: '<main>展示页</main>' } },
  { id: 'handoff', type: 'creative', position: { x: 0, y: 700 }, data: { kind: 'text', title: '交付与打样说明', text: '交付内容' } },
], edges: [{ id: 'plan-to-image', source: 'plan', target: 'image-a' }] };

function setup(document = board, slug = 'showcase-song-yun') {
  const projects = ref<Project[]>([{ id: 'song', slug, name: '已保存案例', brief: '已保存项目' } as Project]);
  const projectId = ref<string | null>(null);
  const visible = ref(true);
  const canvas = ref<Board>({ nodes: [], edges: [] });
  const selectProject = vi.fn((id: string) => { projectId.value = id; canvas.value = structuredClone(document); });
  const scope = effectScope(); scopes.push(scope);
  const playback = scope.run(() => useShowcasePlayback({ projects, projectId, visible: () => visible.value, board: canvas, selectProject }))!;
  return { playback, canvas, selectProject, visible, projects, projectId };
}

const curatedBoard: Board = { ...board, nodes: board.nodes.map((node, index) => ({ ...node, data: { ...node.data,
  showcaseOrder: index + 1, ...(node.id === 'plan' ? { showcaseRole: 'intro' } : node.id === 'handoff' ? { showcaseRole: 'handoff' } : {}),
} })) };

describe('saved showcase playback', () => {
  it.each(['showcase-ci', 'showcase-shan-ming', 'showcase-ce-ma', 'showcase-jin'])('shows the complete %s conversation on normal project entry', async slug => {
    const s = setup(curatedBoard, slug);
    s.selectProject('song'); await flush();
    const saved = s.playback.savedMessages.value;
    expect(saved).toHaveLength(10);
    expect(saved[0]?.content).toBe(showcaseNarratives.find(item => item.slug === slug)!.request);
    expect(saved.at(-1)?.content).toContain('展示页面与交付说明已呈现完成');
    expect(saved.filter(message => message.role === 'assistant').every(message => message.status === 'succeeded')).toBe(true);
    expect(saved.every(message => message.animateReply === false && !message.taskId)).toBe(true);
    expect(saved.flatMap(message => message.steps || []).every(step => step.status === 'completed')).toBe(true);
    expect(s.playback.active.value).toBe(false);
    expect(s.playback.playing.value).toBe(false);
    expect(s.playback.canvasDocument.value).toEqual(curatedBoard);
    expect(vi.getTimerCount()).toBe(0);

    s.playback.open(slug); await flush();
    expect(s.playback.messages.value).toHaveLength(4);
    await vi.runAllTimersAsync(); await flush();
    expect(s.playback.messages.value.map(message => ({ ...message, animateReply: false }))).toEqual(saved);
    expect(s.canvas.value).toEqual(curatedBoard);
  });

  it('waits for the saved board and clears preview conversations when switching to an ordinary project', async () => {
    const s = setup(curatedBoard, 'showcase-ci');
    s.projectId.value = 'song'; await flush();
    expect(s.playback.savedMessages.value).toEqual([]);
    s.canvas.value = structuredClone(curatedBoard); await flush();
    expect(s.playback.savedMessages.value).toHaveLength(10);
    s.projects.value.push({ id: 'ordinary', slug: 'my-design', name: '普通项目' } as Project);
    s.projectId.value = 'ordinary'; await flush();
    expect(s.playback.savedMessages.value).toEqual([]);
    s.projectId.value = 'song';
    s.canvas.value = structuredClone(board); await flush();
    expect(s.playback.savedMessages.value).toEqual([]);
  });

  it('stops an old playback when another project is selected directly', async () => {
    const s = setup(curatedBoard, 'showcase-ci');
    s.playback.open('showcase-ci'); await flush();
    expect(s.playback.playing.value).toBe(true);
    s.projectId.value = 'another'; await flush();
    expect(s.playback.playing.value).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    s.projectId.value = 'song'; await flush();
    expect(s.playback.active.value).toBe(false);
    expect(s.playback.savedMessages.value).toHaveLength(10);
  });

  it('provides distinct narratives for porcelain, brocade and retained saved cases', () => {
    expect(showcaseNarratives).toHaveLength(11);
    expect(new Set(showcaseNarratives.map(item => item.slug)).size).toBe(11);
    for (const item of showcaseNarratives) {
      expect(item.clarification.length).toBeGreaterThan(30);
      expect(item.answer.length).toBeGreaterThan(20);
      expect(item.requirements).toContain('交付规划');
      expect(item.marketing.length).toBeGreaterThan(30);
      expect(item.handoff).toMatch(/实物|打样/);
    }
  });
  it('shows the saved project in sequence without changing its stored board', async () => {
    const s = setup();
    s.playback.open('showcase-song-yun');
    await flush();
    expect(s.selectProject).toHaveBeenCalledWith('song');
    expect(s.playback.playing.value).toBe(true);
    expect(s.playback.canvasDocument.value.nodes).toHaveLength(1);
    expect(s.playback.canvasDocument.value.nodes[0]!.data.generating).toBe(true);
    expect(s.playback.messages.value.at(-1)?.content).toContain('15 秒');
    expect(s.playback.messages.value.map(message => message.role)).toEqual(['user', 'assistant', 'user', 'assistant']);

    await vi.advanceTimersByTimeAsync(2_200); await flush();
    expect(s.playback.canvasDocument.value.nodes.map(node => node.id)).toEqual(['plan', 'image-a']);
    expect(s.playback.canvasDocument.value.nodes.at(-1)?.data.draft).toBe(true);

    await vi.advanceTimersByTimeAsync(14_999); await flush();
    expect(s.playback.completed.value).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1); await flush();
    expect(s.playback.completed.value).toHaveLength(2);
    expect(s.playback.canvasDocument.value.nodes.map(node => node.id)).toEqual(['plan', 'image-a', 'image-b']);
    expect(s.playback.canvasDocument.value.nodes.at(-1)?.data.assetId).toBeUndefined();
    expect(s.canvas.value).toEqual(board);
  });

  it('assigns exactly fifteen seconds to every image while text and HTML use shorter phases', async () => {
    const s = setup();
    s.playback.open('showcase-song-yun'); await flush();
    await vi.runAllTimersAsync(); await flush();
    expect(s.playback.done.value).toBe(true);
    expect(s.playback.playing.value).toBe(false);
    expect(s.playback.completed.value.map(item => item.id)).toEqual(['plan', 'image-a', 'image-b', 'html', 'handoff']);
    expect(s.playback.messages.value.some(message => message.content.includes('一器映宋意'))).toBe(true);
    expect(s.playback.messages.value.at(-1)?.content).toContain('展示页面与交付说明已呈现完成');
  });

  it('stops on leaving and replays the saved board without writing or duplicating nodes', async () => {
    const s = setup();
    s.playback.open('showcase-song-yun'); await flush();
    await vi.advanceTimersByTimeAsync(2_200); await flush();
    expect(s.playback.completed.value.map(item => item.id)).toEqual(['plan']);
    s.playback.open('showcase-song-yun'); await flush();
    expect(s.playback.completed.value).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2_200); await flush();
    s.visible.value = false; await flush();
    expect(s.playback.playing.value).toBe(false);
    s.visible.value = true; await flush();
    s.playback.open('showcase-song-yun'); await flush();
    expect(s.playback.completed.value).toHaveLength(0);
    expect(s.canvas.value).toEqual(board);
    expect(s.canvas.value.nodes.map(node => node.id)).toEqual(['plan', 'image-a', 'image-b', 'html', 'handoff']);
  });

  it('uses the persistent curation order to interleave chapter text and selected visuals', async () => {
    const curatedBoard: Board = { nodes: [
      { id: 'late-image', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'image', title: '03｜收束画面', assetId: 'late', showcaseOrder: 7 } },
      { id: 'intro', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'text', title: '00｜方案与叙事', text: '开场', showcaseOrder: 1, showcaseRole: 'intro' } },
      { id: 'first-image', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'image', title: '01｜品牌开场', assetId: 'first', showcaseOrder: 3 } },
      { id: 'chapter', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'text', title: '01｜器物开场', text: '章节', showcaseOrder: 2, showcaseRole: 'chapter' } },
      { id: 'page', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'html', title: '18｜展示页面', html: '<main/>', showcaseOrder: 8 } },
      { id: 'handoff', type: 'creative', position: { x: 0, y: 0 }, data: { kind: 'text', title: '19｜呈现与落地', text: '收束', showcaseOrder: 9, showcaseRole: 'handoff' } },
      { id: 'external-reference', type: 'creative', position: { x: 0, y: 900 }, data: { kind: 'image', title: '别家品牌参考', assetId: 'other', showcaseRole: 'reference' } },
    ], edges: [] };
    const s = setup(curatedBoard);
    s.playback.open('showcase-song-yun'); await flush();
    await vi.runAllTimersAsync(); await flush();
    expect(s.playback.completed.value.map(item => item.id)).toEqual(['intro', 'chapter', 'first-image', 'late-image', 'page', 'handoff']);
    expect(s.playback.messages.value.at(-1)?.content).toContain('展示页面与交付说明已呈现完成');
  });
});
