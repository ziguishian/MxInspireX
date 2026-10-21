import { afterEach, describe, expect, it, vi } from 'vitest';
import { followTask } from './designTaskStream';

afterEach(() => vi.unstubAllGlobals());
describe('durable Agent event stream', () => {
  it('reassembles split UTF-8 and multiple SSE events without losing the reply', async () => {
    const payload = 'event: task\ndata: {"status":"running","text":"船舶"}\n\nevent: task\ndata: {"status":"succeeded","text":"已完成"}\n\n';
    const bytes = new TextEncoder().encode(payload);
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(controller) {
      for (let i = 0; i < bytes.length; i += 2) controller.enqueue(bytes.slice(i, i + 2));
      controller.close();
    } })));
    vi.stubGlobal('fetch', fetcher);
    const receive = vi.fn();
    const result = await followTask('/task/1', { status: 'queued', text: '' }, new AbortController().signal, receive);
    expect(result).toEqual({ status: 'succeeded', text: '已完成' });
    expect(receive.mock.calls.map(([task]) => task.status)).toEqual(['queued', 'running', 'succeeded']);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('falls back to the same task after SSE fails, without resubmitting it', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('disconnected')).mockResolvedValueOnce(Response.json({ status: 'failed', error: { message: '模型不可用' } }));
    vi.stubGlobal('fetch', fetcher);
    const result = await followTask('/task/1', { status: 'running' }, new AbortController().signal, () => undefined);
    expect(result.status).toBe('failed');
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/task/1/events', '/task/1']);
  });
  it('does not reconnect after cancellation', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => { controller.abort(); throw new DOMException('Cancelled', 'AbortError'); }));
    await expect(followTask('/task/1', { status: 'running' }, controller.signal, () => undefined)).rejects.toThrow('Cancelled');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
