export type PlanningProgress = {
  id: string;
  status: 'running' | 'completed' | 'waiting' | 'failed';
  label: string;
  at: string;
};

/** Read actual backend progress. A dropped stream must never resubmit a plan. */
export async function arrangeSchedule<T>(url: string, payload: unknown, signal: AbortSignal, progress: (event: PlanningProgress) => void): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '无法连接计划组织服务');
  }
  if (!response.body) throw new Error('无法读取计划组织进度');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = frame.split(/\r?\n/);
        const kind = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!data) continue;
        const event = JSON.parse(data);
        if (kind === 'progress') progress(event as PlanningProgress);
        if (kind === 'result') return event as T;
        if (kind === 'error') throw new Error(event.message || '计划组织失败');
      }
      if (done) throw new Error('进度连接已中断，请先查看计划列表；再次提交相同需求可恢复已保存的结果。');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export function scheduleCountdown(job: { status: string; nextRunAt?: string | null }, now: number): string {
  if (job.status === 'paused') return '已暂停';
  if (job.status === 'completed') return '已到期';
  if (job.status !== 'active' || !job.nextRunAt) return '未安排';
  const due = Date.parse(job.nextRunAt);
  if (!Number.isFinite(due)) return '时间待确认';
  const seconds = Math.ceil((due - now) / 1000);
  if (seconds <= 0) return '等待执行';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const clock = [hours, minutes, seconds % 60].map(value => String(value).padStart(2, '0')).join(':');
  return `${days ? `${days} 天 ` : ''}${clock}`;
}
