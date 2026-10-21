import { describe, expect, it } from 'vitest';
import { taskIssue } from './taskErrors';
import { durationLabel, taskProgress } from './taskProgress';
import { ComposerDraftStore, type DraftBackend } from './composerDrafts';
import { renderAgentMarkdown as renderMarkdown } from './agentMarkdown';
import { parseViewport } from './canvasWorkspace';
import { projectCompleted, projectStatusLabel } from './projectStatus';
import { boardChanges, cleanBoard } from '../canvasEditing';
import type { Project } from '../../../../packages/contracts/project';

describe('actionable failures', () => {
  it('reports memory validation separately from model configuration', () => {
    expect(taskIssue('对话信息保存校验反复未通过，已停止重复提交。记忆 logo 的 source.quote 未匹配用户原文。')).toMatchObject({code:'memory',action:'edit'});
    expect(taskIssue('memory_conflict: 版本已更新').title).toBe('对话信息未保存');
  });
  it('continues the original task after restoring a local runtime, without asking for regeneration', () => {
    for (const message of ['找不到 Node.js：/old/App.app/Contents/MacOS/LangjuAgent', 'Agent 本地运行时启动失败（任务工作目录不存在）']) {
      expect(taskIssue(message)).toMatchObject({ code: 'runtime', action: 'resume', actionLabel: '继续原任务' });
      expect(taskIssue(message).message).toContain('重启应用');
    }
  });
  it('never suggests retrying a spending limit as a network error', () => {
    expect(taskIssue('429 insufficient_quota monthly spending limit').action).toBe('settings');
    expect(taskIssue('403 you have reached the monthly spending limit').code).toBe('quota');
    expect(taskIssue('429 too many requests').action).toBe('resume');
    expect(taskIssue('504 gateway timeout').action).toBe('resume');
    expect(taskIssue('400 Function tools with reasoning_effort are not supported').code).toBe('model');
    expect(taskIssue('401 missing authentication header').code).toBe('auth');
  });
  it('separates a saved media preview timeout from provider network failures', () => {
    expect(taskIssue('媒体无法解码或检查超时').code).toBe('media_preview');
    expect(taskIssue('媒体预览检查超时：读取第 2 帧').actionLabel).toBe('重新检查已有媒体');
    expect(taskIssue('媒体预览检查失败：Failed to fetch').code).toBe('media_preview');
    expect(taskIssue('504 gateway timeout').code).toBe('network');
  });
});

describe('real task progress', () => {
  const at = (seconds: number) => new Date(seconds * 1000 + 1_000_000).toISOString();
  const execution = { createdAt: at(0), updatedAt: at(80), trace: [
    { at: at(0), phase: 'running', message: '开始运行' },
    { at: at(5), phase: 'agent', message: 'Langju Design Agent 开始处理' },
    { at: at(10), phase: 'tool', message: '调用工具：generate_image' },
    { at: at(40), phase: 'heartbeat', message: '连接正常' },
  ] };
  it('separates elapsed time from model reasoning and detects missing progress', () => {
    const state = taskProgress(execution, 'running', Date.parse(at(80)));
    expect(state.stage).toBe('create');
    expect(state.stageMs).toBe(75000);
    expect(state.idleMs).toBe(70000);
    expect(state.stalled).toBe(true);
    expect(durationLabel(state.totalMs)).toBe('1 分 20 秒');
  });
  it('freezes terminal durations and distinguishes clarification/reconnection', () => {
    expect(taskProgress(execution, 'succeeded', Date.parse(at(999))).totalMs).toBe(80000);
    expect(taskProgress(execution, 'succeeded', Date.parse(at(999)), true).label).toBe('等待补充需求');
    expect(taskProgress({ ...execution, reconnecting: true }, 'running').label).toBe('正在恢复连接');
    const reviewed={...execution,trace:[...execution.trace,{phase:'needs_review',at:at(60)}]};
    expect(taskProgress(reviewed,'succeeded').label).toBe('本轮完成');
    reviewed.trace.push({phase:'succeeded',at:at(80)});
    expect(taskProgress(reviewed,'succeeded').label).toBe('本轮完成');
  });
});

describe('draft persistence races', () => {
  type Draft = { text: string; attachments?: Blob[] };
  const backend = () => {
    const records = new Map<string, Draft>();
    const adapter: DraftBackend<Draft> = { read: async key => records.get(key), write: async (key, value) => { records.set(key, value); }, remove: async key => { records.delete(key); } };
    return { records, adapter };
  };
  it('preserves each project and attachment after reopening', async () => {
    const { adapter } = backend(); const drafts = new ComposerDraftStore(adapter);
    await drafts.save('one', { text: '修改颜色 @1', attachments: [new Blob(['reference image'])] });
    await drafts.save('two', { text: '另一个项目' });
    const reopened = new ComposerDraftStore(adapter);
    expect((await reopened.load('two'))?.text).toBe('另一个项目');
    expect(await (await reopened.load('one'))?.attachments?.[0].text()).toBe('reference image');
  });
  it('keeps deletion after queued saves and prevents a late load replacing edits', async () => {
    const { records, adapter } = backend(); const drafts = new ComposerDraftStore(adapter);
    const first = drafts.save('one', { text: '早先草稿' });
    const second = drafts.save('one', { text: '最后草稿' });
    const removed = drafts.remove('one');
    await Promise.all([first, second, removed]); expect(records.has('one')).toBe(false);
    let resolveRead!: (value: Draft) => void;
    const slow = new ComposerDraftStore<Draft>({ ...adapter, read: () => new Promise(resolve => { resolveRead = resolve; }) });
    const loading = slow.load('one');
    await slow.save('one', { text: '刚输入的新内容' });
    resolveRead({ text: '磁盘上的旧内容' });
    expect((await loading)?.text).toBe('刚输入的新内容');
  });
});

describe('escaped conversation formatting', () => {
  it('renders emphasis, code, lists and tables', () => {
    const html = renderMarkdown('**Langju**\n\n- 第一项\n- 第二项\n\n```html\n<script>alert(1)</script>\n```\n\n| 项目 | 内容 |\n| --- | --- |\n| 名称 | 游艇 |');
    expect(html).toContain('<strong>Langju</strong>'); expect(html).toContain('<li>第一项</li>');
    expect(html).toContain('&lt;script&gt;'); expect(html).toContain('<table>');
  });
  it('keeps injected HTML and unsafe links inert, with no remote image loads', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)> [点击](javascript:alert) ![图](https://example.com/img.png) [站点](https://example.com/?x=1&y=2)');
    expect(html).not.toContain('<img'); expect(html).not.toContain('href="javascript:'); expect(html).not.toContain('<script');
    expect(html).toContain('rel="noopener noreferrer"'); expect(html).toContain('x=1&amp;y=2');
    expect(renderMarkdown('`**保持原文**`')).toContain('<code>**保持原文**</code>');
  });
});

it('restores valid viewports including large-board overviews and ignores broken values', () => {
  expect(parseViewport('{"x":10,"y":20,"zoom":0.8}')).toEqual({ x: 10, y: 20, zoom: .8 });
  expect(parseViewport('{"x":10,"y":20,"zoom":0.05}')?.zoom).toBe(.05);
  expect(parseViewport('{"x":10,"y":20,"zoom":0}')).toBeNull();
  expect(parseViewport('invalid')).toBeNull();
});

it('filters completed rounds independently of project lifecycle', () => {
  const project = { status: 'draft', latestTaskStatus: 'succeeded' } as Project;
  expect(projectCompleted(project)).toBe(true);
  expect(projectStatusLabel(project)).toBe('本轮完成');
  expect(projectCompleted({ ...project, latestTaskStatus: 'awaiting_input' })).toBe(false);
});

it('sends optimistic expectations only for fields actually changed', () => {
  const before = cleanBoard({ nodes: [{ id: 'a', position: { x: 0, y: 0 }, data: { text: '旧' } }], edges: [] });
  const after = cleanBoard(before); after.nodes[0].position.x = 10;
  expect(boardChanges(before, after).expectedNodes).toEqual({ a: { position: { x: 0, y: 0 } } });
});
