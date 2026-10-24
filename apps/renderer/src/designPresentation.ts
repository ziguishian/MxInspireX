import { generationFailureText, publicAssistantMessage } from './features/generationErrors';
import { taskIssue } from './features/taskErrors';

export type DesignTrace = { at?: string; phase?: string; message?: string };
export type DesignStep = { id: string; label: string; phase?: string; tool?: string; kind?: 'summary'; status: 'running' | 'completed' | 'failed' | 'cancelled' | 'adjusted' };

/** Async delivery keeps the earlier submission draft in its execution history. */
export function completedDeliveryReply(status?: string, output?: { provenance?: Record<string, unknown>; structured_data?: Record<string, any> } | null): string | undefined {
  const data = output?.structured_data;
  if (status === 'succeeded' && data?.delivery) return data.answer || '作品已保存到右侧画布。';
}

const toolLabels: Record<string, string> = {
  design_plan: '明确设计范围与交付清单', generate_batch: '并行生成本组内容',
  search: '检索设计参考', web_search: '联网搜索', list_models: '读取可用模型', generate_3d: '生成 3D 模型', generate_cad: '本地 CAD 建模', knowledge_search: '检索知识库', asset_search: '查找已有素材',
  generate_text: '生成文本', asset_inspect: '查看图片细节', canvas_read: '读取相关节点', canvas_create_html: '生成网页', generate_image: '生成图像', generate_video: '生成视频', generate_audio: '生成音频',
  canvas_create_media: '展示画布素材', canvas_create_text: '整理画布文本',
  canvas_update_node: '更新画布节点', canvas_link_nodes: '关联画布节点',
};
const internalTools = new Set(['conversation_memory_read', 'conversation_memory_update']);

/** Poll snapshots may omit text; keep the current message until a new one arrives. */
export function designLiveText(trace: DesignTrace[] = [], answer?: string, previous = ''): string {
  const text = [...trace].reverse().find(event => event.phase === 'text' && event.message)?.message || answer || previous;
  const prompts = [...new Set(trace.filter(event => event.phase === 'generation_prompt').map(event => event.message).filter(Boolean))] as string[];
  return [...prompts.filter(prompt => !text.includes(prompt)), text].filter(Boolean).join('\n\n');
}

/** Only public execution events are presented; model reasoning is never read. */
export function designSteps(trace: DesignTrace[], taskStatus: string): DesignStep[] {
  const steps: DesignStep[] = [];
  let lastFailure = '';
  const attemptLabel = (name?: string, reason = '') => {
    const needsUser=['quota','auth','permission','runtime','image_output_format','network','local_service'].includes(taskIssue(reason).code);
    return `${name ? toolLabels[name] || '处理步骤' : '执行流程'}：${needsUser ? generationFailureText(reason) : taskStatus==='running' ? '正在调整处理方式' : '本次尝试已结束'}`;
  };
  const finishStage = (status: DesignStep['status'] = 'completed') => steps.forEach((step) => {
    if ((!step.tool || status !== 'completed') && step.status === 'running') step.status = status;
  });
  trace.forEach((event, index) => {
    const message = event.message || '';
    if (event.phase === 'review' || /审查 Agent|delivery_snapshot|已发现问题|尚未核实|最终审查|统一审查|审查通过/.test(message)) return;
    const id = event.at ? `${event.at}-${event.phase}-${message}` : String(index);
    if (event.phase === 'generation') {
      const previous = steps.at(-1);
      if (previous?.status === 'running' && previous.label === message) return;
      finishStage();
      steps.push({ id, phase: event.phase, label: message, status: 'running' });
      return;
    }
    if (['progress','narration'].includes(event.phase || '')) {
      const label = publicAssistantMessage(message);
      if (label && steps.at(-1)?.label !== label) steps.push({id,phase:event.phase,label,kind:'summary',status:'completed'});
      return;
    }
    if (event.phase === 'route_failed') {
      lastFailure = message;
      finishStage('adjusted');
      steps.push({ id, phase: event.phase, label: attemptLabel(undefined,message), status: 'adjusted' });
      return;
    }
    const tool = message.match(/^(调用工具|工具完成|工具失败|工具连接失败)[:：]\s*([\w-]+)/);
    if (tool) {
      const [, action, name] = tool;
      if (internalTools.has(name)) return;
      finishStage();
      const status = action === '调用工具' ? 'running' : action === '工具完成' ? 'completed' : 'adjusted';
      if (status==='adjusted') lastFailure=message;
      const pending = steps.find((step) => step.tool === name && step.status === 'running');
      if (action !== '调用工具' && pending) {
        pending.status = status;
        if (status === 'adjusted') pending.label = attemptLabel(name,message);
      }
      else steps.push({ id, phase: event.phase, label: status === 'adjusted' ? attemptLabel(name,message) : toolLabels[name] || `执行工具 ${name}`, tool: name, status });
      return;
    }
    const labels: Record<string, string> = {
      queued: '任务已接收', running: 'MxinspireX开始处理', attachments: message,
      agent: message, media: message, retrieval: message, recovered: '恢复任务进度',
      model: message.includes('已完成') ? '设计结果已完成' : '整理设计结果',
      route: message, retry: message, escalation: message,
      succeeded: '本轮已完成', failed: '本轮未完成', cancelled: '本轮已停止',
    };
    const label = labels[event.phase || ''] && publicAssistantMessage(labels[event.phase || '']);
    if (!label) return;
    finishStage(event.phase === 'failed' || event.phase === 'cancelled' ? 'cancelled' : 'completed');
    steps.push({ id, phase: event.phase, label:event.phase==='failed' ? `本轮未完成：${generationFailureText(lastFailure || message)}` : label,
      status: event.phase === 'failed' ? 'failed' : event.phase === 'cancelled' ? 'cancelled'
        : ['queued', 'attachments', 'retrieval', 'succeeded', 'route', 'retry', 'escalation'].includes(event.phase || '') || message.includes('已完成') ? 'completed' : 'running' });
  });
  if (['succeeded', 'failed', 'cancelled'].includes(taskStatus)) {
    steps.forEach((step) => {
      if (step.status === 'running') step.status = taskStatus !== 'succeeded' || step.tool ? 'cancelled' : 'completed';
    });
    if (taskStatus==='failed' && !steps.some(step=>step.phase==='failed')) steps.push({id:'terminal-failure',phase:'failed',status:'failed',label:`本轮未完成：${generationFailureText(lastFailure)}`});
    const interrupted = designLiveText(trace);
    if (taskStatus !== 'succeeded' && interrupted && !steps.some(step => step.kind === 'summary' && step.label === interrupted)) {
      steps.push({ id: 'interrupted-output', kind: 'summary', status: 'completed', label: `中断前的输出：\n${publicAssistantMessage(interrupted)}` });
    }
  }
  return steps;
}

/** Media is rendered from persisted asset IDs, never model-invented URLs. */
export function canvasReply(content: string, hasCanvasOutput: boolean): string {
  if (!hasCanvasOutput) return content;
  const isMedia = (url: string) => /(?:\/assets\/|\.(?:png|jpe?g|gif|webp|svg|mp4|webm|mov|mp3|wav|ogg)(?:[?#]|$))/i.test(url);
  return content
    .replace(/!\[[^\]]*\]\([^\n]*?\)/g, '')
    .replace(/\[([^\]]*)\]\(([^\s)]+)\)/g, (match, _label, url) => isMedia(url) ? '' : match)
    .replace(/https?:\/\/[^\s<>]+/g, (url) => isMedia(url) ? '' : url)
    .replace(/在下面查看|在下方查看/g, '在右侧画布查看')
    .replace(/\n{3,}/g, '\n\n').trim();
}
