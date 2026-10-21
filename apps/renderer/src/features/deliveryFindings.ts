import type { DeliveryFinding, DeliveryFindingKind } from '../../../../packages/contracts/deliveryFindings';
import { taskIssue } from './taskErrors';
import { generationFailureText } from './generationErrors';
export type { DeliveryFinding, DeliveryFindingKind } from '../../../../packages/contracts/deliveryFindings';

export const findingLabels: Record<DeliveryFindingKind, string> = {
  problem: '生成异常', unverified: '执行待处理', production_confirmation: '制作参数待确认', generation_unconfirmed: '生成结果待确认',
};
const nextActions: Record<DeliveryFindingKind, string> = {
  problem: '查看对应产物，说明需要修改的部分后继续。',
  unverified: '查看已有产物与依据，补充资料或明确要求检查具体内容。',
  production_confirmation: '制作前补充并确认尺寸、材质、工艺等参数。',
  generation_unconfirmed: '先核对图像服务的原请求、结果和计费记录；核对前不要重新提交生成。',
};
const operationalCodes = new Set(['file_missing','file_empty','asset_missing','content_empty','image_invalid','cad_invalid','cad_check_unavailable','video_generation_failed','generation_failed','generation_unconfirmed','image_output_format','image_response_invalid','image_response_timeout','image_result_unconfirmed','media_timeout','media_transport','media_decode','preview_failed','count_mismatch','artifact_missing','plan_incomplete','execution_interrupted']);
export const isOperationalFinding = (item: DeliveryFinding) => item.kind === 'generation_unconfirmed' || operationalCodes.has(item.code);
export function uniqueFindings(items: DeliveryFinding[]): DeliveryFinding[] {
  const saved = new Map<string, DeliveryFinding>();
  for (const item of items) {
    if (!item || !(item.kind in findingLabels) || !item.message || !isOperationalFinding(item)) continue;
    const key = JSON.stringify([item.kind, item.nodeId, item.planItemId, item.message]);
    saved.set(key, { ...item, nextAction: item.nextAction || nextActions[item.kind] });
  }
  return [...saved.values()];
}
export function findingGroups(items: DeliveryFinding[]) {
  const findings = uniqueFindings(items);
  return (Object.keys(findingLabels) as DeliveryFindingKind[]).map(kind => ({
    kind, label: findingLabels[kind], items: findings.filter(item => item.kind === kind),
  })).filter(group => group.items.length);
}
export function findingSummary(items: DeliveryFinding[]) {
  return findingGroups(items).map(group => `${group.label} ${group.items.length} 项`).join('；');
}

function generationFinding(error: unknown, nodeId?: string, forceUnconfirmed = false): DeliveryFinding | undefined {
  const issue = taskIssue(error);
  const unknown = forceUnconfirmed || ['image_response_timeout', 'image_result_unconfirmed'].includes(issue.code);
  if (!unknown && !['image_output_format', 'image_response_invalid'].includes(issue.code)) return undefined;
  return { kind: unknown ? 'generation_unconfirmed' : 'problem', code: issue.code, nodeId,
    message: unknown && !['image_response_timeout', 'image_result_unconfirmed'].includes(issue.code)
      ? '图像请求未取得完整结果，可能已计费，已停止自动重试。' : issue.message,
    nextAction: unknown ? nextActions.generation_unconfirmed : '检查图像模型与输出格式设置；本轮已停止自动重试。' };
}

/** API provides structured findings; the fallback supports old saved conversations. */
export function taskDeliveryFindings(data: Record<string, any> = {}, error?: unknown): DeliveryFinding[] {
  const findings: DeliveryFinding[] = Array.isArray(data.deliveryFindings) ? [...data.deliveryFindings] : [...(data.delivery?.findings || [])];
  const generation = error ? generationFinding(error) : undefined;
  if (generation && !findings.some(f => f.kind === generation.kind && f.code === generation.code)) findings.push(generation);
  return uniqueFindings(findings);
}

export function nodeDeliveryFindings(data: Record<string, any>, nodeId?: string): DeliveryFinding[] {
  const findings: DeliveryFinding[] = [];
  if (data.error && !data.generating) {
    const generation = generationFinding(data.error, nodeId, data.status === '生成结果待确认');
    if (generation) {
      if (!findings.some(f => f.kind === generation.kind && (!f.nodeId || f.nodeId === nodeId))) findings.push(generation);
    } else if (!findings.some(f => f.kind === 'problem')) findings.push({
      kind: 'problem', code: 'generation_failed', message: generationFailureText(data.error), nextAction: '按错误原因检查配置或补充要求后继续。', nodeId,
    });
  }
  return uniqueFindings(findings);
}

export function deliverableLabel(item: { status: string; findings?: DeliveryFinding[] }) {
  const findings = item.findings?.filter(isOperationalFinding) || [];
  if (findings.length) return [...new Set(findings.map(f => findingLabels[f.kind]))].join(' · ');
  return ({ pending: '待交付', generating: '生成中', blocked: '等待必要资料', ready: '已生成', passed: '已生成', needs_review: '待完成' } as Record<string, string>)[item.status] || item.status;
}
