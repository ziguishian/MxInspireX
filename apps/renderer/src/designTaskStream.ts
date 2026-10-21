/** Observe a durable task. Reconnection never submits a second Agent run. */
export async function followTask<T extends { status: string }>(url: string, initial: T, signal: AbortSignal, receive: (task: T) => void, connection?: (reconnecting: boolean) => void): Promise<T> {
  let task = initial;
  const terminal = () => ['succeeded', 'failed', 'cancelled'].includes(task.status);
  const update = (value: T) => { task = value; connection?.(false); receive(value); };
  update(initial);
  if (terminal()) return task;
  const streamController = new AbortController();
  const cancelStream = () => streamController.abort();
  signal.addEventListener('abort', cancelStream, { once: true });
  if (signal.aborted) cancelStream();
  let streamTimer = setTimeout(cancelStream, 8000);
  try {
    const response = await fetch(`${url}/events`, { signal: streamController.signal });
    clearTimeout(streamTimer);
    streamTimer = setTimeout(cancelStream, 25000);
    if (!response.ok || !response.body) throw new Error('无法连接任务进度');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (!terminal()) {
        const { done, value } = await reader.read();
        clearTimeout(streamTimer);
        streamTimer = setTimeout(cancelStream, 25000);
        buffer += decoder.decode(value, { stream: !done });
        let boundary: number;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const event = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const data = event.split('\n').find((line) => line.startsWith('data: '));
          if (data) update(JSON.parse(data.slice(6)) as T);
        }
        if (done) break;
      }
    } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
  } catch (error) { if (signal.aborted) throw error; }
  finally { clearTimeout(streamTimer); signal.removeEventListener('abort', cancelStream); }
  // Older sidecars or interrupted SSE connections fall back to task snapshots.
  let failures = 0;
  while (!terminal()) {
    signal.throwIfAborted();
    try {
      const controller = new AbortController();
      const cancel = () => controller.abort();
      signal.addEventListener('abort', cancel, { once: true });
      const timeout = setTimeout(cancel, 8000);
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`任务进度连接失败 (${response.status})`);
        update(await response.json() as T);
        failures = 0;
      } finally { clearTimeout(timeout); signal.removeEventListener('abort', cancel); }
    } catch (error) {
      if (signal.aborted) throw error;
      connection?.(true);
      if (++failures >= 12) throw new Error('本地服务暂时无法连接，任务进度已保存。恢复服务后重新打开项目即可继续查看。');
    }
    if (!terminal()) await new Promise<void>((resolve, reject) => {
      const cancel = () => { clearTimeout(timer); reject(signal.reason || new Error('已停止查看')); };
      const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve(); }, Math.min(5000, 1000 * (failures + 1)));
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();
    });
  }
  return task;
}
