import { ref } from 'vue';
import type { DetectedModel } from './providerModels';
export const DEFAULT_IMAGE_MODEL = 'openai/gpt-image-2.5-sunburst';
export const DEFAULT_DRAFT_IMAGE_MODEL = 'openai/gpt-image-2.5-flare';
export const IMAGE_ROUTE_LABEL = '图像智能路由：探索 Flare / 最终 Sunburst';
export const DEFAULT_VIDEO_MODEL = 'bytedance/seedance-2.5';
export type RoutingMode = 'auto' | 'fast' | 'standard' | 'quality' | 'manual';
export const routingChoices: { id: RoutingMode; label: string; detail: string }[] = [
  { id: 'auto', label: 'Auto · 智能选择', detail: '默认 GPT-6 Luna，输入能力不匹配时使用 GPT-6 Sol' },
  { id: 'fast', label: '快速', detail: '简单任务与快速草稿' },
  { id: 'standard', label: '标准', detail: '日常设计与常规交付' },
  { id: 'quality', label: '最高质量', detail: '优先最高等级，消费可能更高' },
];
export const modelPrices = ref<DetectedModel[]>([]);
export const usdToCny = ref(7.2);
export function modelDisplayName(id: string) {
  if (id.split('/').pop() === DEFAULT_DRAFT_IMAGE_MODEL.split('/').pop()) return 'GPT-Image-2.5 Flare';
  if (id.split('/').pop() === DEFAULT_IMAGE_MODEL.split('/').pop()) return 'GPT-Image-2.5 Sunburst';
  return modelPrices.value.find((item) => item.id === id)?.name || id;
}
export function formatTokens(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}
export function formatCny(value: number) {
  if (value > 0 && value < .000001) return '<¥0.000001';
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: value > 0 && value < .01 ? 6 : 2 })}`;
}
export function modelPriceLabel(id: string) {
  return formatModelPrice(modelPrices.value.find((item) => item.id === id)?.price);
}
export function formatModelPrice(price?: Record<string, unknown>) {
  if (!price || !Object.keys(price).length) return '价格待配置';
  if (price.pricingMode === 'dynamic') return '动态计价 · 以服务返回费用为准';
  if (price.currency !== 'USD' && price.currency !== 'CNY') return '价格币种待确认';
  const scale = price.currency === 'USD' ? usdToCny.value : 1;
  if (price.source === 'evolink_public' && Array.isArray(price.publicRates)) {
    const rates = price.publicRates as { label: string; usd: number; unit: string }[];
    return rates.length ? `EvoLink 官网参考价 · ${rates.slice(0, 2).map(rate => `${rate.label} ${formatCny(rate.usd * scale)} ${rate.unit}`).join(' · ')}` : '官网单价待确认';
  }
  const entries = [
    ['inputPerMillion', '输入 / 百万 Token'], ['outputPerMillion', '输出 / 百万 Token'],
    ['cachedPerMillion', '缓存读取 / 百万 Token'], ['cacheWritePerMillion', '缓存写入 / 百万 Token'], ['imageInputPerMillion', '图像输入 / 百万 Token'],
    ['imageOutputPerMillion', '图像输出 / 百万 Token'], ['audioInputPerMillion', '音频输入 / 百万 Token'],
    ['audioOutputPerMillion', '音频输出 / 百万 Token'], ['videoInputPerMillion', '视频输入 / 百万 Token'],
    ['videoOutputPerMillion', '视频输出 / 百万 Token'], ['perInputImage', '/ 输入图'], ['perImage', '/ 张'], ['perSecond', '/ 秒'], ['perRequest', '/ 次'], ['perSearch', '/ 次联网搜索'],
  ];
  entries.push(['perInputMegapixel', '/ 输入百万像素'], ['perOutputMegapixel', '/ 输出百万像素'],
    ['perMegapixelSecond', '/ 百万像素·秒']);
  const values = entries.flatMap(([key, label]) => typeof price[key] === 'number' ? [`${label} ${formatCny(Number(price[key]) * scale)}`] : []);
  if (!values.length) return '价格待配置';
  const source = price.source === 'default' ? '默认参考价 · ' : '';
  return `${source}${values.join(' · ')}${price.referenceOnly ? price.tariffConditional === false ? '（当前服务仅供参考）' : ' 起（按规格计价）' : ''}`;
}
export function editableModelPrice(price: Record<string, unknown> = {}): Record<string, unknown> {
  const fields = ['currency', 'inputPerMillion', 'outputPerMillion', 'cachedPerMillion', 'cacheWritePerMillion', 'imageInputPerMillion',
    'imageOutputPerMillion', 'audioInputPerMillion', 'audioOutputPerMillion', 'videoInputPerMillion',
    'videoOutputPerMillion', 'perInputImage', 'perImage', 'perSecond', 'perRequest', 'perSearch'];
  // Do not accidentally save a starting price as the user's flat contract rate.
  if (price.referenceOnly) return { currency: price.currency || 'USD' };
  return { currency: 'USD', ...Object.fromEntries(Object.entries(price).filter(([key]) => fields.includes(key))) };
}
export function preferMediaModel(saved: string, options: string[], defaultId: string) {
  const requested = saved || defaultId;
  if (options.includes(requested)) return requested;
  const comparable = (id: string) => id.split('/').pop()?.toLowerCase().replace(/[_\s]+/g, '-');
  const matches = options.filter((id) => comparable(id) === comparable(requested));
  return matches.length === 1 ? matches[0] : '';
}
