import { describe, expect, it } from 'vitest';
import { canDispatchQueue, createQueueMessage, moveQueueItem, shouldAdvanceQueue, queueTaskResult, queuePauseReason } from './messageQueue';

describe('composer message queue', () => {
  it('keeps restored tasks paused for the same reasons as streamed tasks', () => {
    const restored = { status: 'succeeded', output: { structured_data: { deliveryStatus: 'needs_review', review: { status: 'timed_out' } } } };
    expect(shouldAdvanceQueue(queueTaskResult(restored))).toBe(false);
    expect(queuePauseReason(queueTaskResult(restored))).toContain('待处理');
    expect(shouldAdvanceQueue(queueTaskResult({ status: 'succeeded', updates: [{ appliedAt: null }] }))).toBe(false);
    expect(shouldAdvanceQueue(queueTaskResult({ status: 'succeeded', output: { structured_data: { deliveryStatus: 'passed', review: { status: 'failed' } } } }))).toBe(true);
  });
  it('moves a queued message without mutating the saved order', () => {
    const original = [{ id: 'one' }, { id: 'two' }, { id: 'three' }];
    expect(moveQueueItem(original, 2, 0).map(item => item.id)).toEqual(['three', 'one', 'two']);
    expect(original.map(item => item.id)).toEqual(['one', 'two', 'three']);
  });

  it('ignores invalid moves and snapshots message metadata', () => {
    const original = [{ id: 'one' }, { id: 'two' }];
    expect(moveQueueItem(original, -1, 1)).toEqual(original);
    const message = createQueueMessage('继续完善', { files: [new Blob(['reference'])] });
    expect(message.text).toBe('继续完善');
    expect(message.id).toBeTruthy();
    expect(message.draft.files[0].size).toBeGreaterThan(0);
    expect(Number.isNaN(Date.parse(message.createdAt))).toBe(false);
  });

  it('only dispatches while idle and advances after successful tasks', () => {
    const ready = { activeProject: true, running: false, awaitingInput: false, dispatching: false, hasMessages: true };
    expect(canDispatchQueue(ready)).toBe(true);
    expect(canDispatchQueue({ ...ready, running: true })).toBe(false);
    expect(canDispatchQueue({ ...ready, awaitingInput: true })).toBe(false);
    expect(canDispatchQueue({ ...ready, dispatching: true })).toBe(false);
    expect(canDispatchQueue({ ...ready, activeProject: false })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'succeeded' })).toBe(true);
    expect(shouldAdvanceQueue({ status: 'succeeded', deliveryStatus: 'passed', reviewStatus: 'passed' })).toBe(true);
    expect(shouldAdvanceQueue({ status: 'failed' })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'cancelled' })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'succeeded', deliveryStatus: 'pending' })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'succeeded', deliveryStatus: 'needs_review' })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'succeeded', awaitingClarification: true })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'succeeded', awaitingReferenceSelection: true })).toBe(false);
    expect(shouldAdvanceQueue({ status: 'succeeded', deliveryStatus: 'passed', reviewStatus: 'timed_out' })).toBe(true);
    expect(shouldAdvanceQueue({ status: 'succeeded', deliveryStatus: 'passed', unverifiedNodeIds: ['node-28'] })).toBe(true);
  });
});
