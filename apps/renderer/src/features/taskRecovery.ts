type Inspection = {
  task?: { status?: string };
  recoverableImages?: { id: string; saved: boolean }[];
};

// Only accepted, persisted provider jobs can be retrieved. Never infer that a
// failed task was unsubmitted or that retrying it would be free.
export function canRecoverOriginal(data: Inspection | undefined, id: string): boolean {
  return ['failed', 'succeeded'].includes(data?.task?.status || '')
    && !!data?.recoverableImages?.some(item => item.id === id && !item.saved);
}

export function recoveryHint(data: Inspection): string {
  const status = data.task?.status;
  if (status === 'running' || status === 'queued') return '任务仍在进行，可刷新记录查看进度。';
  if (status === 'cancelled') return '任务已停止，已保存的内容保留。';
  if (data.recoverableImages?.some(item => !item.saved)) return '可查询原任务并取回结果，不重新生成。';
  if (status === 'failed') return '先核对产物与计费记录，再决定下一步；失败不代表未收费。';
  return '';
}

export function receiptState(receipt: { status?: string; submitted?: boolean | null }): string {
  if (receipt.submitted === false) return '本工具请求未提交';
  if (receipt.status === 'running') return '结果尚未确认';
  if (receipt.status === 'rejected') return '调用被拒绝，请核对回执';
  return '已有回执';
}
