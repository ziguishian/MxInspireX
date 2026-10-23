export type QueuedComposerMessage<Draft> = {
  id: string;
  text: string;
  draft: Draft;
  createdAt: string;
  supplementTaskId?: string;
};

export function supplementUnavailableReason(draft: { files: readonly unknown[]; assets: readonly unknown[]; skills?: readonly unknown[] }) {
  return draft.files.length || draft.assets.length || draft.skills?.length
    ? '补充当前任务仅支持文字；附件、引用和技能请在队列中作为下一项发送。' : '';
}

export function queueItemCanStart(message: { id: string; supplementTaskId?: string }, editingId: string | null, sendingSupplement: boolean) {
  return message.id !== editingId && !message.supplementTaskId && !sendingSupplement;
}

export function canDispatchQueue(input: { activeProject: boolean; running: boolean; awaitingInput: boolean; dispatching: boolean; hasMessages: boolean }) {
  return input.activeProject && input.hasMessages && !input.running && !input.awaitingInput && !input.dispatching;
}

export type QueueTaskResult = {
  status: string;
  deliveryStatus?: string;
  awaitingTaskUpdate?: boolean;
  awaitingClarification?: boolean;
  awaitingReferenceSelection?: boolean;
  reviewStatus?: string;
  unverifiedNodeIds?: readonly string[];
};

export function shouldAdvanceQueue(task: QueueTaskResult) {
  return !queuePauseReason(task);
}

export function queuePauseReason(task?: QueueTaskResult | null): string {
  if (!task) return '';
  if (task.awaitingTaskUpdate && !['queued','pending','running'].includes(task.status)) return '任务结束前有补充尚未应用，请先查看并处理这条补充。';
  if (task.awaitingClarification) return '请先回答当前任务的补充问题。';
  if (task.awaitingReferenceSelection) return '请先完成当前任务的参考选择。';
  if (['queued', 'pending', 'running'].includes(task.status)) return '当前任务完成后继续。';
  if (task.status === 'cancelled') return '当前任务已停止，请先核对已提交请求和已保存产物。';
  if (task.status === 'failed') return '当前任务遇到问题，请先查看请求和产物。';
  if (task.status !== 'succeeded') return '当前任务尚未完成。';
  if (task.deliveryStatus === 'needs_review') return '当前交付有待处理事项，请先查看交付清单。';
  if (task.deliveryStatus && task.deliveryStatus !== 'passed') return '当前交付尚未通过，队列已暂停。';
  return '';
}

/** The same persisted task is used after streaming, reopening, and manual dispatch. */
export function queueTaskResult(task: { status: string; updates?: Array<{ appliedAt?: string | null }>; output?: { structured_data?: Record<string, any> } | null }): QueueTaskResult {
  const data = task.output?.structured_data || {};
  return {
    status: task.status, deliveryStatus: data.deliveryStatus,
    awaitingTaskUpdate: task.updates?.some(item => !item.appliedAt),
    awaitingClarification: Boolean(data.clarification?.questions?.length),
    awaitingReferenceSelection: Boolean(data.referenceSelection?.items?.length && data.referenceSelection.status === 'pending' && !data.referenceSelection.submittedAction),
  };
}

/** Return a reordered copy and keep the original array untouched. */
export function moveQueueItem<T>(items: readonly T[], fromIndex: number, toIndex: number): T[] {
  if (fromIndex < 0 || fromIndex >= items.length || toIndex < 0 || toIndex >= items.length || fromIndex === toIndex) {
    return [...items];
  }
  const next = [...items];
  const [item] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, item);
  return next;
}

export function createQueueMessage<Draft>(text: string, draft: Draft): QueuedComposerMessage<Draft> {
  const randomId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return { id: randomId, text, draft, createdAt: new Date().toISOString() };
}
