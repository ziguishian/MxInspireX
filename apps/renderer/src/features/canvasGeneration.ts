export function canvasTextModel(kind: string, model: string | undefined, fallback: string) {
  return ['text', 'html', 'cad'].includes(kind) && model ? model : fallback;
}

export function canvasTaskTerminalPatch(task: { id: string; status: string; error?: { message?: string } | null }, data: Record<string, any>) {
  // A delayed observer must never reset a newer run or overwrite a saved result.
  if (data.taskId && data.taskId !== task.id || !data.generating) return null;
  if (!['succeeded', 'failed', 'cancelled'].includes(task.status)) return null;
  if (data.assetId || data.asset?.id || data.localFile || data.html || data.text || data.cad || data.job) return null;
  return { generating: false, status: task.status === 'cancelled' ? '已停止' : '生成失败',
    error: task.status === 'cancelled' ? '已停止生成' : task.error?.message || '本轮未产生可用内容，请检查任务详情后再继续' };
}

/** Lock by project and node before provider checks or HTTP requests start. */
export function createCanvasSubmissionGate() {
  const pending = new Set<string>();
  return async function run<T>(projectId: string, nodeId: string, action: () => Promise<T>): Promise<T | false> {
    const key = JSON.stringify([projectId, nodeId]);
    if (pending.has(key)) return false;
    pending.add(key);
    try { return await action(); } finally { pending.delete(key); }
  };
}
