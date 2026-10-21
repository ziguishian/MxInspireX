import { describe, expect, it } from 'vitest';
import { clarificationAnswered, clarificationReply, emptyClarificationAnswer, pendingClarification, restoreClarificationDraft, type Clarification } from './clarification';
import type { ConversationMessage } from './pageServices';

const clarification: Clarification = { questions: [
  { id: 'q1', question: '主要面向谁？', options: ['亲子家庭', '年轻游客'] },
  { id: 'q1', question: '需要哪些产物？', options: ['海报', '标志'], multi: true },
  { id: 'name', question: '品牌名是什么？', options: [] },
] };

describe('design clarification', () => {
  it('only opens the latest unanswered request, never historical or failed forms', () => {
    const assistant: ConversationMessage = { role: 'assistant', taskId: 'first', status: 'succeeded', content: '', clarification };
    expect(pendingClarification([assistant])?.taskId).toBe('first');
    expect(pendingClarification([assistant, { role: 'user', content: '改做另一件事' }])).toBeNull();
    expect(pendingClarification([assistant, { role: 'assistant', taskId: 'new', status: 'running', content: '' }])).toBeNull();
    expect(pendingClarification([{ ...assistant, status: 'failed' }])).toBeNull();
    expect(pendingClarification([assistant, { ...assistant, taskId: 'second' }])?.taskId).toBe('second');
  });
  it('does not preselect answers and sends custom text, multiple choices and explicit skips together', () => {
    expect(clarificationAnswered(emptyClarificationAnswer())).toBe(false);
    expect(clarificationAnswered({ ...emptyClarificationAnswer(), useCustom: true, custom: '  ' })).toBe(false);
    const answers = [
      { ...emptyClarificationAnswer(), useCustom: true, custom: '银发游客，保留舒适感' },
      { ...emptyClarificationAnswer(), selected: ['海报', '标志'], useCustom: true, custom: '再加门票' },
      { ...emptyClarificationAnswer(), skipped: true },
    ];
    expect(clarificationReply(clarification, answers)).toBe('主要面向谁？\n银发游客，保留舒适感\n\n需要哪些产物？\n海报；标志；再加门票\n\n品牌名是什么？\n暂时跳过，尚未确定。');
  });
  it('restores matching drafts by question position, including legacy duplicate IDs, and rejects stale content', () => {
    const raw = JSON.stringify({ signature: JSON.stringify(clarification.questions), step: 2, answers: [
      { selected: ['年轻游客', '亲子家庭', '不存在的选项'], custom: '', useCustom: false },
      { selected: ['标志', '海报'], custom: '包装', useCustom: true },
      { custom: '白鹭号', useCustom: true },
    ] });
    const restored = restoreClarificationDraft(clarification, raw);
    expect(restored.step).toBe(2);
    expect(restored.answers[0].selected).toEqual(['年轻游客']);
    expect(restored.answers[1].selected).toEqual(['标志', '海报']);
    expect(restored.answers[2].custom).toBe('白鹭号');
    expect(restoreClarificationDraft({ questions: [{ ...clarification.questions[0], question: '新的问题？' }] }, raw).answers).toEqual([emptyClarificationAnswer()]);
    expect(restoreClarificationDraft(clarification, 'broken').step).toBe(0);
  });
});
