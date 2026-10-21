import { deliveryProgress, type ExecutionInfo } from './taskProgress';
import { taskIssue } from './taskErrors';
export function taskOutcome(info: ExecutionInfo, status: string) {
  const delivery = deliveryProgress(info);
  const unknown = info.findings?.some(f => f.kind === 'generation_unconfirmed');
  const issue = info.failureReason ? taskIssue(info.failureReason) : undefined;
  const saved = delivery.total ? `已保存 ${delivery.ready}/${delivery.total} 项` : '本轮已结束';
  const incomplete = delivery.total > delivery.ready;
  const problem = info.findings?.find(f => f.kind === 'problem');
  const plainCompleted = status === 'succeeded' && !delivery.total && (!info.deliveryStatus || info.deliveryStatus === 'passed') && !info.findings?.length;
  const passed = status === 'succeeded' && info.deliveryStatus === 'passed' && !incomplete && !plainCompleted;
  const title = unknown ? '生成结果待确认' : passed ? '本轮交付完成' : plainCompleted ? '本轮已完成' : status === 'cancelled' ? `${delivery.ready ? saved + ' · ' : ''}已停止` : delivery.total ? saved : status === 'failed' ? '本轮未完成' : '本轮已结束';
  const detail = unknown ? '原请求可能仍有结果或费用，请先核对记录。' : issue && issue.code !== 'unknown' ? issue.message : incomplete ? '已保存的产物会保留，剩余项目尚未交付。' : problem ? problem.message : passed ? '作品已保存到画布。' : status === 'failed' ? '本轮执行未完成。已有对话和资料已保留，可查看执行详情了解原因。' : status === 'cancelled' && !delivery.ready ? '本轮已停止，已有对话和资料已保留。' : '可在画布中查看作品。';
  return {title, detail: plainCompleted ? '本轮结果已保存。' : detail, tone: passed || plainCompleted ? 'green' : status === 'failed' && !delivery.ready ? 'red' : 'yellow',
    action: unknown || issue?.action === 'inspect' ? 'inspect' : issue?.action === 'settings' ? 'settings' : undefined,
    canCompleteMissing: incomplete && !unknown && issue?.action !== 'inspect' && !!info.plan?.length && !['running','queued','cancelled'].includes(status)};
}
