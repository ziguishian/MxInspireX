import type { SkillBinding } from '../../../../packages/contracts/skills';
import type { ConversationMemorySnapshot } from '../../../../packages/contracts/conversationMemory';
import type { DesignBatch, DeliveryProgress } from '../../../../packages/contracts/designBatches';
import type { DesignBrief } from '../../../../packages/contracts/designBrief';
import { findingSummary, deliverableLabel, type DeliveryFinding } from './deliveryFindings';
export type { DesignBatch, DeliveryProgress } from '../../../../packages/contracts/designBatches';
export type ProgressTrace = { at?: string; phase?: string; message?: string; data?: Record<string, string | number | boolean> };
export type ExecutionInfo = { failureReason?: string; updates?: Array<{ id: string; text: string; createdAt?: string; appliedAt?: string | null }>; findings?: DeliveryFinding[]; brief?: DesignBrief; batch?: DesignBatch; memory?: ConversationMemorySnapshot; assetBaseUrl?: string; skills?: SkillBinding[]; trace?: ProgressTrace[]; createdAt?: string; updatedAt?: string; reconnecting?: boolean; deliveryStatus?: string; reviewStatus?: string; deliverables?: DeliveryProgress[]; plan?: Array<{ id: string; title: string; kind: string }>; decisions?: Array<{ label: string; value: string; status: string }> };
export function deliveryProgress(info: ExecutionInfo) {
  const saved = new Map((info.deliverables || []).map(item => [item.id, item]));
  const fields: Record<string, string> = { quantity: '数量', budget: '预算', budget_scope: '预算范围', audience: '赠送对象', official_identity: '官方视觉规范', dimensions: '尺寸' };
  const items: DeliveryProgress[] = info.plan?.length ? info.plan.map(item => saved.get(item.id) || { ...item, status: 'pending' }) : info.deliverables || [];
  const cumulativeRows = items.map(item => ({ ...item, blockingFields: item.blockingFields?.map(field => fields[field] || field) }));
  const current = new Map((info.batch?.currentProgress || []).map(item => [item.id, item]));
  const finalDelivery = ['passed', 'needs_review', 'failed'].includes(info.deliveryStatus || '');
  const rows = info.batch ? cumulativeRows.filter(item => info.batch!.itemIds.includes(item.id))
    .map(item => finalDelivery ? {...current.get(item.id),...item} : {...item,...current.get(item.id)}) : cumulativeRows;
  const ready = rows.filter(item => ['ready', 'passed', 'needs_review'].includes(item.status)).length;
  const cumulativeReady = cumulativeRows.filter(item => ['ready', 'passed', 'needs_review'].includes(item.status)).length;
  return { rows, ready, total: rows.length, cumulativeRows, cumulativeReady, cumulativeTotal: cumulativeRows.length, label: deliverableLabel };
}
const labels = { understand: '理解需求', create: '制作内容', check: '保存产物', done: '本轮完成' };
type Stage = keyof typeof labels;
const timestamp = (value?: string) => value ? Date.parse(value) : NaN;
export function taskProgress(info: ExecutionInfo, status: string, now = Date.now(), clarification = false) {
  const trace = info.trace || [];
  // Edited turns keep their original position/date; elapsed time belongs to
  // the current execution, whose queued event is recorded when resubmitted.
  const start = timestamp(trace.find(event => event.phase === 'queued')?.at) || timestamp(info.createdAt) || timestamp(trace[0]?.at) || now;
  const terminal = ['succeeded', 'failed', 'cancelled'].includes(status);
  const end = terminal ? timestamp(info.updatedAt) || timestamp(trace.at(-1)?.at) || start : now;
  let stage: Stage = 'understand', stageStart = start;
  let waiting = '', activity = start;
  const durations: Partial<Record<Stage, number>> = {};
  for (const event of trace) {
    if (event.phase === 'review' || /审查 Agent|delivery_snapshot/.test(event.message || '')) continue;
    const at = timestamp(event.at);
    if (!Number.isFinite(at)) continue;
    if (event.phase !== 'heartbeat') activity = at;
    const text = event.message || '';
    let next: Stage = stage;
    if (event.phase === 'generation') next = 'create';
    if (event.phase === 'agent' && /开始处理|开始运行/.test(text)) next = /研究|research/i.test(text) ? 'understand' : 'create';
    if (event.phase === 'tool' && /delivery_verify|preview/.test(text)) next = 'check';
    if (event.phase === 'tool' && /调用工具.*(?:generate_|canvas_create|canvas_update)/.test(text)) next = 'create';
    if (next !== stage) { durations[stage] = (durations[stage] || 0) + Math.max(0, at - stageStart); stage = next; stageStart = at; }
    if (event.phase === 'retry') waiting = '服务暂时异常，正在重试';
    else if (event.phase === 'recovery_attempt') waiting = '正在主动修正错误';
    else if (event.phase === 'context_compaction') waiting = event.data?.status === 'started' ? '正在压缩上下文' : '';
    else if (event.phase === 'generation') waiting = '正在生成网页';
    else if (event.phase === 'paused') waiting = '服务重启中，等待恢复';
    else if (event.phase === 'media') waiting = '等待媒体生成或预览检查';
    else if (['agent', 'text', 'tool', 'recovered'].includes(event.phase || '')) waiting = '';
  }
  durations[stage] = (durations[stage] || 0) + Math.max(0, end - stageStart);
  const stalled = !terminal && end - activity >= 60000;
  const rows = deliveryProgress(info).rows;
  const findingLabel = findingSummary(info.findings || []);
  const deliveryLabel = findingLabel || (info.batch?.status === 'needs_plan' ? '正在整理本批计划' : rows.some(item => item.status === 'generating') ? '产物仍在生成' : rows.some(item => ['pending', 'blocked'].includes(item.status)) ? '仍有待交付项' : info.deliveryStatus === 'needs_review' ? '生成未完成' : labels.done);
  const label = info.reconnecting && !terminal ? '正在恢复连接' : status === 'failed' ? findingLabel || '本轮未完成' : status === 'cancelled' ? '已停止' : status === 'succeeded' ? clarification ? '等待补充需求' : deliveryLabel : waiting || labels[stage];
  const modelEvents = trace.filter(event => event.phase === 'model_call');
  const completedCompactionCalls = modelEvents.filter(event => event.data?.stage === 'compaction').length;
  const nativeCompactionAttempted = trace.some(event => event.phase === 'context_compaction' && event.data?.mode === 'native' && event.data?.attempted !== false && !['skipped','not_needed'].includes(String(event.data?.status)));
  const compactionCalls = Math.max(completedCompactionCalls, nativeCompactionAttempted ? 1 : 0);
  const totals = [...modelEvents].reverse().find(event => typeof event.data?.totalModelCalls === 'number')?.data;
  const calls = Math.max(modelEvents.length, Number(totals?.totalModelCalls || 0)) + Math.max(0, compactionCalls - completedCompactionCalls);
  const recoveryEvents = trace.filter(event => event.phase === 'recovery_attempt' || event.phase === 'retry');
  const latestRecovery = recoveryEvents.at(-1)?.data;
  const latestContext = [...trace].reverse().find(event => event.phase === 'context_compaction' && event.data)?.data;
  const contextFor = (mode: string) => [...trace].reverse().find(event => event.phase === 'context_compaction' && event.data?.mode === mode)?.data;
  const observed = modelEvents.filter(event => event.data?.cacheReported === true);
  const writeObserved = modelEvents.filter(event => event.data?.cacheWriteReported === true);
  const sum = (events: ProgressTrace[], field: string) => events.reduce((n,event) => n+Number(event.data?.[field] || 0),0);
  const reportedCalls = Number(totals?.cacheReportedCalls ?? observed.length);
  const inputTokens = Number(totals?.cacheObservedInputTokens ?? sum(observed,'inputTokens'));
  const cachedTokens = Number(totals?.totalCachedTokens ?? sum(observed,'cachedTokens'));
  const writtenTokens = Number(totals?.totalCacheWriteTokens ?? sum(writeObserved,'cacheWriteTokens'));
  const writeReported = Number(totals?.cacheWriteReportedCalls ?? writeObserved.length) > 0;
  const partial = reportedCalls > 0 && reportedCalls < Number(totals?.totalModelCalls || modelEvents.length);
  const rate = inputTokens > 0 ? Math.min(100, cachedTokens/inputTokens*100) : 0;
  const cacheLabel = reportedCalls
    ? `${cachedTokens > 0 ? `缓存命中 ${rate.toFixed(1)}%` : '缓存未命中'} · ${cachedTokens.toLocaleString()} / ${inputTokens.toLocaleString()} tokens${partial ? '（部分调用未返回统计）' : ''}`
    : '缓存命中统计：入口未返回';
  return { label, stage, stageMs: durations[stage], totalMs: Math.max(0, end - start), idleMs: Math.max(0, end - activity),
    lastActivity: activity, stalled, terminal, durations, stages: labels,
    modelProgress: {
      calls,
      agentRounds: Math.max(modelEvents.length, Number(totals?.totalModelCalls || 0)) - completedCompactionCalls,
      compactionCalls,
      recoveryCount: recoveryEvents.length,
      recoveryStageTotal: Number(latestRecovery?.stageTotal || recoveryEvents.length),
      recoveryStageLimit: Number(latestRecovery?.stageLimit || 6),
      correctionAttempt: Number(latestRecovery?.attempt || 0),
      correctionLimit: Number(latestRecovery?.limit || 0),
      safetyWarning: modelEvents.filter(event => event.data?.stage !== 'compaction').length >= 55 ? '接近 60 轮技术保护' : '',
      context: latestContext,
      localContext: contextFor('local'), nativeContext: contextFor('native'),
      cache: modelEvents.length ? { label:cacheLabel, reportedCalls, partial, cachedTokens, inputTokens, writtenTokens,
        writeLabel:writeReported ? `缓存写入 ${writtenTokens.toLocaleString()} tokens` : '缓存写入统计：入口未返回' } : undefined,
    },
  };
}
export function durationLabel(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
