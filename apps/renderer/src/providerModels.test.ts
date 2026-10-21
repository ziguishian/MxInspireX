import { describe, expect, it, vi } from 'vitest';
import { createProviderModelCatalog, normalizeModelResponse, selectAvailableModel, type ModelCatalogResponse } from './providerModels';

const source = { provider: 'openai-compatible', baseUrl: 'https://relay.test/v1' };

describe('API model catalog', () => {
  it('keeps only returned IDs and respects empty capability lists', () => {
    const catalog = normalizeModelResponse({
      models: ['relay-chat', 'relay-image', 'relay-chat', 'relay-video', 'relay-3d', 'future-kind'],
      textModels: [], imageModels: ['relay-image', 'not-returned'],
      videoModels: ['relay-video'], threeDModels: ['relay-3d'], unknownModels: ['future-kind'],
      modelCatalog: [{ id: 'stale-model', kind: 'text' }, { id: 'future-kind', kind: 'unknown', classificationSource: 'unknown-provider-category' }],
    });
    expect(catalog.models).toEqual(['relay-chat', 'relay-image', 'relay-video', 'relay-3d', 'future-kind']);
    expect(catalog.text).toEqual([]);
    expect(catalog.image).toEqual(['relay-image']);
    expect(catalog.video).toEqual(['relay-video']);
    expect(catalog.threeD).toEqual(['relay-3d']);
    expect(catalog.unknown).toEqual(['future-kind']);
    expect(catalog.catalog.map((item) => item.id)).toEqual(catalog.models);
  });

  it('preserves catalog coverage and warnings from provider-specific discovery', () => {
    const catalog = normalizeModelResponse({
      models: ['chat', 'image'], textModels: ['chat'], imageModels: ['image'],
      catalogCoverage: 'complete', catalogSources: ['openai-compatible', 'closeai-management'],
      catalogWarnings: ['fixture warning'],
    });
    expect(catalog.coverage).toBe('complete');
    expect(catalog.sources).toEqual(['openai-compatible', 'closeai-management']);
    expect(catalog.warnings).toEqual(['fixture warning']);
  });

  it('restores a selection only when the API still returns it', () => {
    expect(selectAvailableModel('removed-model', ['relay-a', 'relay-b'])).toBe('relay-a');
    expect(selectAvailableModel('relay-b', ['relay-a', 'relay-b'])).toBe('relay-b');
    expect(selectAvailableModel('old-default', [])).toBe('');
  });

  it('starts empty, reads the requested gateway and replaces the catalog on refresh', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ models: ['relay-a'], textModels: ['relay-a'] })
      .mockResolvedValueOnce({ models: ['relay-b'], textModels: ['relay-b'] });
    const catalog = createProviderModelCatalog(fetcher);
    expect(catalog.data.value.models).toEqual([]);
    await catalog.refresh(source);
    expect(fetcher).toHaveBeenCalledWith(source, expect.any(AbortSignal));
    expect(catalog.data.value.text).toEqual(['relay-a']);
    await catalog.refresh(source);
    expect(catalog.data.value.text).toEqual(['relay-b']);
  });

  it('shows no fallback models after an empty response, error, or malformed response', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ models: ['relay-a'] })
      .mockRejectedValueOnce(new Error('HTTP 401'))
      .mockResolvedValueOnce({ models: [] })
      .mockResolvedValueOnce({ error: 'not a catalog' });
    const catalog = createProviderModelCatalog(fetcher);
    await catalog.refresh(source);
    expect(await catalog.refresh(source)).toBe(false);
    expect(catalog.data.value.models).toEqual([]);
    expect(catalog.error.value).toContain('API Key');
    expect(catalog.error.value).not.toContain('切换');
    expect(await catalog.refresh(source)).toBe(true);
    expect(catalog.data.value.text).toEqual([]);
    expect(catalog.status.value).toBe('ready');
    expect(catalog.error.value).toBe('');
    expect(await catalog.refresh(source)).toBe(false);
    expect(catalog.status.value).toBe('error');
    expect(catalog.data.value.models).toEqual([]);
  });

  it('ignores late responses after changing URL, provider or credentials', async () => {
    let finishOld!: (value: ModelCatalogResponse) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<ModelCatalogResponse>((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce({ models: ['new-gateway-model'] });
    const catalog = createProviderModelCatalog(fetcher);
    const oldRequest = catalog.refresh(source);
    catalog.reset();
    expect(fetcher.mock.calls[0][1].aborted).toBe(true);
    expect(catalog.data.value.models).toEqual([]);
    await catalog.refresh({ provider: 'openrouter', baseUrl: 'https://other.test/v1', secret: 'test-only' });
    finishOld({ models: ['old-gateway-model'] });
    expect(await oldRequest).toBe(false);
    expect(catalog.data.value.models).toEqual(['new-gateway-model']);
    expect(catalog.status.value).toBe('ready');
  });

  it('ignores late failures from an invalidated request', async () => {
    let failOld!: (error: Error) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise((_resolve, reject) => { failOld = reject; }))
      .mockResolvedValueOnce({ models: ['new-model'] });
    const catalog = createProviderModelCatalog(fetcher);
    const oldRequest = catalog.refresh(source);
    await catalog.refresh(source);
    failOld(new Error('old gateway failed'));
    await oldRequest;
    expect(catalog.data.value.models).toEqual(['new-model']);
    expect(catalog.error.value).toBe('');
  });

  it('keeps the saved catalog on network failure and clears the hint after recovery', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('模型探测失败：<urlopen error [Errno 8] nodename nor servname provided, or not known>'))
      .mockResolvedValueOnce({ models: ['recovered-model'] });
    const catalog = createProviderModelCatalog(fetcher);
    catalog.hydrate({ models: ['saved-model'], savedAt: '2026-09-15' }, source);
    expect(await catalog.refresh(source)).toBe(false);
    expect(catalog.error.value).toContain('切换到可访问海外服务的网络');
    expect(catalog.error.value).not.toMatch(/API Key|模型配置|urlopen|Errno/);
    expect(catalog.status.value).toBe('error');
    expect(catalog.data.value.models).toEqual(['saved-model']);
    expect(catalog.savedAt.value).toBe('2026-09-15');
    expect(await catalog.refresh(source)).toBe(true);
    expect(catalog.error.value).toBe('');
    expect(catalog.data.value.models).toEqual(['recovered-model']);
  });

  it('never uses a different gateway catalog when the new gateway is unreachable', async () => {
    const catalog = createProviderModelCatalog(vi.fn().mockRejectedValue(new Error('Connection error.')));
    catalog.hydrate({ models: ['old-model'] }, source);
    await catalog.refresh({ ...source, baseUrl: 'https://other.test/v1' });
    expect(catalog.data.value.models).toEqual([]);
    expect(catalog.error.value).toContain('切换到可访问海外服务的网络');
  });

  it('distinguishes a stopped local API from an unreachable upstream', async () => {
    const catalog = createProviderModelCatalog(vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await catalog.refresh(source);
    expect(catalog.error.value).toContain('重新打开应用');
    expect(catalog.error.value).not.toMatch(/海外|API Key/);
  });

  it('offers network recovery when the upstream catalog request times out', async () => {
    vi.useFakeTimers();
    try {
      const catalog = createProviderModelCatalog((_source, signal) => new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      }));
      const refresh = catalog.refresh(source);
      await vi.advanceTimersByTimeAsync(45_000);
      expect(await refresh).toBe(false);
      expect(catalog.error.value).toContain('切换到可访问海外服务的网络');
    } finally { vi.useRealTimers(); }
  });
});
