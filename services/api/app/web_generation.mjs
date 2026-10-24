import { directSingleArtifact } from './execution_efficiency.mjs';
import { waitForImageResult } from './image_result_wait.mjs';

// Keep planning/media available as an escape hatch when a simple page actually
// needs new assets. No classifier model or extra planning round is required.
export function directWeb(constraints, skills, revision, attachments = []) {
  return constraints?.taskSurface !== 'canvas_node' && constraints?.singleDeliveryTarget?.kind === 'html'
    && directSingleArtifact({...constraints, singleDeliveryTarget:{...constraints.singleDeliveryTarget,kind:'image'}}, skills, revision, attachments);
}
export const webTools = new Set(['canvas_create_html','design_plan','generate_batch','generate_image','generate_video','generate_audio',
  'conversation_memory_update','conversation_memory_read','conversation_read','context_read','asset_inspect','asset_search',
  'canvas_read','request_clarification','skill_load','skill_read','web_search','web_read']);

export function supportingWebMedia(constraints, plan, name, args) {
  if (constraints?.taskSurface === 'canvas_node' || !plan?.ready || !['generate_image','generate_audio','generate_video'].includes(name)) return false;
  const ids = args.deliverable_ids || [];
  return ids.length > 0 && ids.every(id => plan.deliverables.some(item => item.id === id && item.supporting)
    && plan.deliverables.some(item => item.kind === 'html' && item.dependsOn?.includes(id)
      && item.inputs?.some(ref => ref.source === 'deliverable' && ref.id === id && ref.role === 'content'))
    && !plan.deliverables.some(item => item.inputs?.some(ref => ref.source === 'deliverable' && ref.id === id && ref.role !== 'content')));
}

// GET only: the existing video service owns provider polling and persistence.
export async function waitForWebMedia({record, baseUrl, projectId, taskId, fetchResult = fetch,
  now = Date.now, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), timeoutMs = 15*60*1000}) {
  if (record.name !== 'generate_video') {
    const result = await waitForImageResult({baseUrl,projectId,taskId,returnEnvelope:true,
      args:record.args,operationId:record.output.operationId,toolName:record.name,fetchResult,now,sleep,timeoutMs});
    if (result.httpStatus < 400) return result.output;
    // A persisted async rejection must retain its failure semantics; never
    // interpret an HTTP error body as a successful tool receipt.
    return {...result.output,status:'failed',stopTool:true,retryable:false,
      message:result.output?.message || result.output?.detail || '网页媒体原操作失败'};
  }
  const prefix = `${baseUrl}/api/projects/${encodeURIComponent(projectId)}`;
  const deadline = now() + timeoutMs;
  while (now() < deadline) {
    try {
      const get = async url => { const response = await fetchResult(url,{method:'GET',signal:AbortSignal.timeout(5000)}); if (!response.ok) throw new Error('lookup failed'); return response.json(); };
      const task = await get(`${prefix}/tasks/${encodeURIComponent(taskId)}`);
      if (task.status === 'cancelled') return {status:'cancelled',retryable:false,job:record.output.job};
      const jobs = await get(`${prefix}/video/jobs`);
      const job = jobs.find(item => item.id === record.output.job?.id && item.metadata?.taskId === taskId);
      if (job?.outputAssetId && job.metadata?.canvasSynced) {
        const board = await get(`${prefix}/canvas`);
        const node = board.nodes.find(item => item.data?.assetId === job.outputAssetId);
        if (node && !node.data.generating && !node.data.error) return {status:'succeeded',assetId:job.outputAssetId,node,job};
      }
      if (job && ['failed','cancelled','expired'].includes(job.status)) return {status:job.status === 'cancelled' ? 'cancelled' : 'failed',stopTool:true,retryable:false,job,message:job.error || '网页视频未完成'};
    } catch { /* A lookup failure never authorizes another generation. */ }
    await sleep(Math.min(2000,Math.max(0,deadline-now())));
  }
  return {status:'generation_unconfirmed',retryable:false,billingCertainty:'unknown',job:record.output.job,message:'网页视频结果待核对，保留原任务，不重复生成。'};
}

// Media tools are available for page composition only in the conversation entry.
// Explicit exclusions and model capabilities are still checked by toolEnabled.
export function webMediaAllowed(constraints, kinds, outputKind) {
  return constraints?.taskSurface !== 'canvas_node' && kinds.has('html')
    && ['image', 'video', 'audio', 'text'].includes(outputKind);
}

export const webDesignInstructions = [
  '网页先围绕用户用途组织信息层级、版式、色彩、字体、媒体位置与交互状态，直接实现，不另加确认或润色模型。默认1440px桌面布局并加入 viewport=device-width 和响应式断点；移动端可重排，不能因画布缩略图而写死手机布局。尊重用户指定风格及局部修改范围。',
  '网页默认通过 canvas_create_html(style_framework=bootstrap) 使用离线 Bootstrap 5.3.8 的网格、表单、按钮、折叠、标签页、弹窗等组件，再用内联 CSS 定制字体层级、留白、配色、卡片和减少动画模式。用户指定其他实现时可用 none 和自包含代码；禁止依赖外部 CDN、网络字体或未加载的组件。Bootstrap 示例：.container/.row/.col-md-6；切换按钮 data-bs-toggle="tab" data-bs-target="#pane" 与 .tab-pane；折叠按钮 data-bs-toggle="collapse" data-bs-target="#details" 与 .collapse。ID 必须真实对应且唯一。',
  '网页按内容需要组合图像、文字、视频、音频，不能机械地全部生成。文案优先由主 Agent 直接编写；只有需要独立长文等才 generate_text。先复用本轮明确相关的真实素材；确实缺少媒体时才调用对应生成工具，图像不默认透明：照片或背景图保留完整画面，抠图主体才指定透明。视频/音频只在用户要求或页面用途确实需要时生成，遵守指定参数及不生成媒体等否定要求。',
  '网页需要新素材时，先一次性保存 design_plan：HTML 为最终交付，内部素材标 supporting=true；HTML 项用 dependsOn 和 inputs(source=deliverable, role=content) 引用素材项。先用 generate_batch 提交独立媒体；收到受理回执后立即编写完整网页，无需等待媒体或调用工具轮询。网页媒体位置用 deliverable://交付项ID，保存时程序等待原操作并绑定真实 asset://ID，不再调用模型补写页面。也可将完整网页与媒体放入同一批次。已有素材直接用真实 asset ID，不重复生成。失败或未知计费保留原请求，不重发媒体；网页只能在全部依赖成功后保存。依赖首图视觉身份或布局的设计仍需看过真实像素再创作，不能提前猜测。仅已有素材的简单网页无需为流程增加计划。',
  '网页必须实现用户需要的页面交互：筛选改变实际列表并显示空状态与重置，标签页和菜单切换真实内容，表单用 label、输入校验和可见反馈，按钮绑定实际动作。没有后端时表单明确显示本地演示结果，不能宣称已发送或保存到服务器。音视频使用真实媒体及 controls、合理预加载，默认不自动播放有声内容。实现键盘操作、焦点和响应式状态；不放无行为的 # 链接、假播放器或假成功反馈。所有内容在隔离预览及离线导出后可用，不调用宿主应用接口，不虚构登录、支付或数据库服务。',
];
