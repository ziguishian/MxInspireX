import { expect, it, vi } from 'vitest';
import { createProviderModelCatalog } from './providerModels';
import { usdToCny, modelPrices, modelPriceLabel, preferMediaModel, formatCny } from './modelEconomy';
it('hydrates a persisted catalog without calling the relay', () => {
  const remote = vi.fn();
  const catalog = createProviderModelCatalog(remote);
  catalog.hydrate({ models: ['saved-model'], savedAt: '2026-09-11T01:00:00Z', textModels: ['saved-model'] });
  expect(catalog.data.value.text).toEqual(['saved-model']);
  expect(catalog.savedAt.value).toBe('2026-09-11T01:00:00Z');
  expect(catalog.status.value).toBe('ready');
  remote.mockReset();
  catalog.reset();
  expect(remote).not.toHaveBeenCalled();
});
it('formats real cost tariffs in RMB and keeps unknown prices explicit', () => {
  usdToCny.value = 7.2;
  modelPrices.value = [{ id:'image', price:{ currency:'CNY', perImage:.2 } }, {id:'video', price:{currency:'USD',perSecond:.1}}];
  expect(modelPriceLabel('image')).toBe('/ 张 ¥0.20');
  expect(modelPriceLabel('video')).toBe('/ 秒 ¥0.72');
  expect(modelPriceLabel('missing')).toBe('价格待配置');
  expect(formatCny(.001)).toBe('¥0.001');
  expect(formatCny(.0000001)).toBe('<¥0.000001');
});
it('keeps cache-write tariff editable and displays reads and writes separately', async () => {
  const {formatModelPrice,editableModelPrice}=await import('./modelEconomy');
  expect(formatModelPrice({})).toBe('价格待配置');
  expect(formatModelPrice({currency:'EUR',perImage:1})).toBe('价格币种待确认');
  const price={currency:'CNY',cachedPerMillion:2,cacheWritePerMillion:12.5};
  expect(editableModelPrice(price).cacheWritePerMillion).toBe(12.5);
  expect(formatModelPrice(price)).toContain('缓存读取');
  expect(formatModelPrice(price)).toContain('缓存写入');
});
it('resolves namespaces without silently switching model versions', () => {
  expect(preferMediaModel('', ['openai/gpt-image-2.5-flare'], 'gpt-image-2.5-flare')).toBe('openai/gpt-image-2.5-flare');
  expect(preferMediaModel('', ['GPT-Image-2.5-Flare'], 'gpt-image-2.5-flare')).toBe('GPT-Image-2.5-Flare');
  expect(preferMediaModel('', ['gpt-image-2'], 'gpt-image-2.5-flare')).toBe('');
  expect(preferMediaModel('custom', ['custom', 'gpt-image-2.5-flare'], 'gpt-image-2.5-flare')).toBe('custom');
});

it('labels default and conditional tariffs without losing their units', async () => {
  const { formatModelPrice, editableModelPrice } = await import('./modelEconomy');
  expect(formatModelPrice({ currency: 'USD', source: 'default', perImage: .04 })).toContain('默认参考价');
  expect(formatModelPrice({ currency: 'USD', videoOutputPerMillion: 6.4, referenceOnly: true })).toContain('视频输出 / 百万 Token');
  expect(formatModelPrice({ currency: 'CNY', audioInputPerMillion: 11, audioOutputPerMillion: 12 })).toContain('音频输入 / 百万 Token');
  expect(formatModelPrice({ currency: 'USD', perSecond: .08, referenceOnly: true })).toContain('起（按规格计价）');
  expect(formatModelPrice({ currency: 'USD', perImage: .04, referenceOnly: true, tariffConditional: false })).toContain('当前服务仅供参考');
  expect(editableModelPrice({ currency: 'USD', perImage: .04, source: 'default', checkedAt: '2026-09-16', sourceUrl: 'https://example.test' }))
    .toEqual({ currency: 'USD', perImage: .04 });
  expect(editableModelPrice({ currency: 'USD', perImage: .04, referenceOnly: true }))
    .toEqual({ currency: 'USD' });
});

it('shows router prices as dynamic rather than missing or free', async () => {
  const { formatModelPrice } = await import('./modelEconomy');
  expect(formatModelPrice({ pricingMode: 'dynamic', referenceOnly: true })).toBe('动态计价 · 以服务返回费用为准');
});
