import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMascotSettings, mascotSpriteStyle, mascotPresets, mascotPresetImageUrl, type MascotGeneration } from './mascot';

const item: MascotGeneration = { id: 'aa', prompt: '一只猫咪', status: 'succeeded', model: 'image', imageUrl: '/api/mascot/generations/aa/image', error: '' };
const response = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('shared Agent mascot', () => {
  it('selects bundled artwork without POSTing a generation and preserves the latest custom preview', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ active:null, activePreset:'robot', latest:item }))
      .mockResolvedValueOnce(response({ active:null, activePreset:'cloud', latest:item }))
      .mockResolvedValueOnce(response({ active:item, activePreset:null, latest:item }));
    vi.stubGlobal('fetch', fetch);
    const controller = createMascotSettings('http://localhost:8765');
    await controller.load();
    await controller.applyPreset('cloud');
    expect(controller.activePreset.value).toBe('cloud');
    expect(controller.activeName.value).toBe('云朵');
    expect(controller.latest.value?.id).toBe(item.id);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ presetId:'cloud' });
    expect(mascotSpriteStyle(controller.apiBaseUrl, null, 'cloud')['--xiaoju-image']).toContain('/assets/mascots/cloud.png');
    await controller.apply(item.id);
    expect(controller.activePreset.value).toBeNull();
    expect(controller.activeName.value).toBe('自定义形象');
    expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(0);
    controller.dispose();
  });

  it('keeps the current preset when saving fails and ignores unknown preset assets', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ active:null, activePreset:'sprout', latest:null }))
      .mockRejectedValueOnce(new Error('连接中断'));
    vi.stubGlobal('fetch', fetch);
    const controller = createMascotSettings('http://localhost:8765');
    await controller.load(); await controller.applyPreset('cloud');
    expect(controller.activePreset.value).toBe('sprout');
    expect(controller.error.value).toContain('连接中断');
    expect(mascotPresetImageUrl('unknown' as 'robot')).toBe('');
    expect(mascotPresets.map(preset => preset.id)).toEqual(['robot','cream-cat','cloud','sprout','moon-bunny','amber-fox','sea-otter','star-penguin']);
    controller.dispose();
  });
  it('keeps a new result in preview until explicitly applied; reset restores bundled artwork', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ active: null, latest: item }))
      .mockResolvedValueOnce(response({ active: item, latest: item }))
      .mockResolvedValueOnce(response({ active: null, latest: item }));
    vi.stubGlobal('fetch', fetch);
    const controller = createMascotSettings('http://localhost:8765');
    await controller.load();
    expect(controller.active.value).toBeNull();
    await controller.apply(item.id);
    expect(mascotSpriteStyle(controller.apiBaseUrl, controller.active.value)['--xiaoju-image']).toContain('/api/mascot/generations/aa/image');
    await controller.apply(null);
    expect(mascotSpriteStyle(controller.apiBaseUrl, controller.active.value)['--xiaoju-image']).toContain('assets/mascots/robot-soft.png');
    expect(controller.activeName.value).toBe('点阵机器人');
    controller.dispose();
  });

  it('uses the explicitly chosen model and does not submit again during generation', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValueOnce(response({ active: item, latest: item }))
      .mockResolvedValueOnce(response({ ...item, status: 'running', imageUrl: null }));
    vi.stubGlobal('fetch', fetch);
    const controller = createMascotSettings('http://localhost:8765');
    await controller.load();
    await controller.generate('新猫咪', { key: 'openai-compatible', model: 'global', manual: true }, 'selected');
    await controller.generate('新猫咪', { key: 'openai-compatible' }, 'selected');
    expect(fetch).toHaveBeenCalledTimes(2);
    const body = JSON.parse(fetch.mock.calls[1][1].body);
    expect(body.model).toBe('selected');
    expect(body.requestId).toBeTruthy();
    expect(controller.active.value?.id).toBe(item.id);
    controller.dispose();
    await vi.runOnlyPendingTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('reconciles uncertain submission without automatically issuing another POST', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValueOnce(response({ active: null, latest: null }))
      .mockRejectedValueOnce(new Error('network disconnected'))
      .mockResolvedValueOnce(response({ active: null, latest: item }));
    vi.stubGlobal('fetch', fetch);
    const controller = createMascotSettings('http://localhost:8765');
    await controller.load();
    await controller.generate('新的猫咪', { key: 'openai-compatible' }, '');
    expect(controller.uncertain.value).toBe(true);
    await controller.generate('新的猫咪', { key: 'openai-compatible' }, '');
    await vi.advanceTimersByTimeAsync(2500);
    expect(controller.latest.value?.status).toBe('succeeded');
    expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1);
    controller.dispose();
  });
});
