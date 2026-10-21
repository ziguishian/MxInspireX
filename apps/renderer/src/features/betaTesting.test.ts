import { describe, expect, it } from 'vitest';
import { feedbackCooldown, readyForFeedback, shouldPromptFeedback } from './betaTesting';

describe('lightweight result feedback', () => {
  it('waits for a real generated artifact, including partial results during a run', () => {
    expect(readyForFeedback([{ data: { kind: 'image', generating: true } }])).toBe(false);
    expect(readyForFeedback([{ data: { kind: 'image' } }])).toBe(false);
    expect(readyForFeedback([{ data: { kind: 'upload', assetId: 'reference' } }])).toBe(false);
    expect(readyForFeedback([{ data: { kind: 'html', html: '<p>done</p>', error: 'failed' } }])).toBe(false);
    expect(readyForFeedback([{ data: { kind: 'image', assetId: 'result' } }, { data: { kind: 'video', generating: true } }])).toBe(true);
  });
  it('does not repeat prompts after rating, dismissal, a previous prompt or during cooldown', () => {
    const now = 10000000;
    expect(shouldPromptFeedback(undefined, 0, now)).toBe(true);
    expect(shouldPromptFeedback(undefined, now - 1, now)).toBe(false);
    expect(shouldPromptFeedback(undefined, now - feedbackCooldown, now)).toBe(true);
    expect(shouldPromptFeedback({ taskId: 'task', rating: 5 }, 0, now)).toBe(false);
    expect(shouldPromptFeedback({ taskId: 'task', rating: null, dismissedAt: 'date' }, 0, now)).toBe(false);
    expect(shouldPromptFeedback({ taskId: 'task', rating: null, shownAt: 'date' }, 0, now)).toBe(false);
  });
});
