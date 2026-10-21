import { describe, expect, it } from 'vitest';
import { messageReferences } from './messageReferences';
import { replaceConversationTurn, resubmissionReferences } from './messageResubmission';
import type { ConversationMessage } from '../pageServices';

describe('editing a conversation turn', () => {
  it('replaces the same user/reply pair and clears all old completion and failure details', () => {
    const messages: ConversationMessage[] = [
      { role: 'user', content: '前文', taskId: 'before' },
      { role: 'user', content: '原文', taskId: 'old' },
      { role: 'assistant', content: '旧回复', taskId: 'old', status: 'failed', error: true,
        steps: [], sources: [{ url: 'https://example.test', title: '旧来源' }], verification: { technical: '已完成', content: '' }, clarification: { questions: [] } },
      { role: 'user', content: '后续消息', taskId: 'after' },
    ];
    const task = { id: 'edited', replacesTaskId: 'old', conversationTurnId: 'old', userMessage: '修改后', status: 'queued', references: { referencedFiles: [{ documentId: 'doc' }] } };
    const edited = replaceConversationTurn(messages, task);
    expect(edited).toHaveLength(messages.length);
    expect(edited[1]).toEqual({ role: 'user', content: '修改后', taskId: 'edited', conversationTurnId: 'old', status: 'queued', referenceSnapshot: task.references });
    expect(edited[2]).toEqual({ role: 'assistant', content: '', taskId: 'edited', conversationTurnId: 'old', status: 'queued' });
    expect(edited[0]).toBe(messages[0]); expect(edited[3]).toBe(messages[3]);
    expect(replaceConversationTurn(edited, task)).toEqual(edited);
    expect(messages[1].content).toBe('原文');
  });
});

describe('edited message references', () => {
  it('preserves ordered frame images and file IDs while dropping legacy manual modes', () => {
    const original = { referencedAssets: [{ id: 'first', projectId: 'other', referenceMode: 'identity' as const }, { id: 'last', projectId: 'p', referenceMode: 'layout' as const }], referencedFiles: [{ documentId: 'uploaded', projectId: 'p', index: 1, filename: '参考.png', referenceMode: 'edit' as const }] };
    expect(resubmissionReferences('这两张图做首尾帧', '改成十秒的首尾帧视频', original, [], {})).toEqual({
      referencedAssets: [{ id: 'first', projectId: 'other' }, { id: 'last', projectId: 'p' }],
      referencedFiles: [{ documentId: 'uploaded', projectId: 'p', index: 1, filename: '参考.png' }],
      referencedNodes: [],
    });
  });
  it('removes a deleted explicit reference and preserves metadata of references still used', () => {
    const original = { referencedAssets: [{ id: 'first', projectId: 'p', nodeId: 'node-a' }, { id: 'last', projectId: 'other' }], referencedNodes: [{ id: 'node-a', projectId: 'p' }] };
    const before = '@asset:first @asset:last 制作视频', after = '@asset:last 制作图像';
    const references = messageReferences({ text: before, projectId: 'p', apiBaseUrl: '', snapshot: original, assets: [], documents: [], nodes: [] });
    const result = resubmissionReferences(before, after, original, references, { referencedAssets: [{ id: 'last', projectId: 'p' }, { id: 'new', projectId: 'p' }] });
    expect(result.referencedAssets).toEqual([{ id: 'last', projectId: 'other' }, { id: 'new', projectId: 'p' }]);
    expect(result.referencedNodes).toEqual([]);
  });
  it('keeps the historical @1 bound to its own document when edited', () => {
    const original = { referencedFiles: [{ documentId: 'old-upload', projectId: 'p', index: 1, filename: '包装图.png' }] };
    const references = messageReferences({ text: '@1 制作视频', projectId: 'p', apiBaseUrl: '', snapshot: original, assets: [], documents: [], nodes: [] });
    expect(resubmissionReferences('@1 制作视频', '@1 制作海报', original, references, {}).referencedFiles).toEqual(original.referencedFiles);
    expect(resubmissionReferences('@1 制作视频', '制作海报', original, references, {}).referencedFiles).toEqual([]);
  });
});
