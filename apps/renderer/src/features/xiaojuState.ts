export type XiaojuState = 'idle' | 'thinking' | 'generating' | 'waiting' | 'error' | 'completed';
export const xiaojuStateLabels: Record<XiaojuState, string> = { idle: '准备好了', thinking: '正在理解需求', generating: '正在制作', waiting: '等待你补充', error: '需要你查看', completed: '本轮已完成' };
export function xiaojuState(message?: { status?: string; clarification?: unknown; referenceSelection?: unknown; execution?: { findings?: unknown[]; trace?: Array<{ phase?: string; message?: string }> } }): XiaojuState {
  if (!message) return 'idle';
  if (message.clarification || message.referenceSelection) return 'waiting';
  if (message.status === 'failed' || message.status === 'cancelled' || message.execution?.findings?.length) return 'error';
  if (message.status === 'succeeded') return 'completed';
  const recent = message.execution?.trace?.filter(item => ['tool', 'progress', 'stage'].includes(item.phase || '')).at(-1)?.message || '';
  return /generat|制作|生成|修改|渲染|构建/.test(recent) ? 'generating' : 'thinking';
}
