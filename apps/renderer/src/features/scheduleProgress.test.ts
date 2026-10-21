import { afterEach, describe, expect, it, vi } from 'vitest';
import { arrangeSchedule, scheduleCountdown } from './scheduleProgress';

afterEach(() => vi.unstubAllGlobals());

describe('schedule planning progress', () => {
  it('decodes split Chinese text, heartbeat and stage updates before returning the plan', async () => {
    const frames = ': heartbeat\r\n\r\nevent: progress\r\ndata: {"id":"planning","status":"running","label":"正在解析时间","at":"now"}\r\n\r\nevent: progress\ndata: {"id":"planning","status":"completed","label":"已解析","at":"now"}\n\nevent: result\ndata: {"schedules":[{"id":"one"}],"questions":[]}\n\n';
    const bytes = new TextEncoder().encode(frames);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(controller) {
      for (let i = 0; i < bytes.length; i += 2) controller.enqueue(bytes.slice(i, i + 2));
      controller.close();
    } }))));
    const progress = vi.fn();
    const result = await arrangeSchedule('/arrange', { requestId: 'original' }, new AbortController().signal, progress);
    expect(progress.mock.calls.map(([event]) => event.label)).toEqual(['正在解析时间', '已解析']);
    expect(result).toEqual({ schedules: [{ id: 'one' }], questions: [] });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('shows server failures and does not resubmit after an interrupted stream', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('event: error\ndata: {"message":"模型暂不可用"}\n\n'))
      .mockResolvedValueOnce(new Response(': heartbeat\n\n'));
    vi.stubGlobal('fetch', fetcher);
    await expect(arrangeSchedule('/arrange', {}, new AbortController().signal, () => {})).rejects.toThrow('模型暂不可用');
    await expect(arrangeSchedule('/arrange', {}, new AbortController().signal, () => {})).rejects.toThrow('进度连接已中断');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe('next schedule countdown', () => {
  const now = Date.parse('2030-01-01T00:00:00Z');
  it('uses absolute time, rounds up the last second and handles days', () => {
    expect(scheduleCountdown({ status: 'active', nextRunAt: '2030-01-01T08:10:00+08:00' }, now)).toBe('00:10:00');
    expect(scheduleCountdown({ status: 'active', nextRunAt: '2030-01-01T00:00:01Z' }, now + 950)).toBe('00:00:01');
    expect(scheduleCountdown({ status: 'active', nextRunAt: '2030-01-03T01:02:03Z' }, now)).toBe('2 天 01:02:03');
  });
  it('does not show negative time or stale countdowns for inactive schedules', () => {
    const job = { status: 'active', nextRunAt: '2030-01-01T00:00:00Z' };
    expect(scheduleCountdown(job, now + 1000)).toBe('等待执行');
    expect(scheduleCountdown({ ...job, status: 'paused' }, now)).toBe('已暂停');
    expect(scheduleCountdown({ ...job, status: 'completed' }, now)).toBe('已到期');
    expect(scheduleCountdown({ status: 'active' }, now)).toBe('未安排');
    expect(scheduleCountdown({ ...job, nextRunAt: 'invalid' }, now)).toBe('时间待确认');
  });
});
