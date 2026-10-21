export type TaskIssue = { code: string; title: string; message: string; action: 'settings' | 'resume' | 'edit' | 'inspect' | 'repair'; actionLabel: string };

export const serviceNetworkHint = '当前网络暂时无法连接服务，请切换到可访问海外服务的网络后重试。';
export const localServiceHint = '暂时无法连接本地服务，请重新打开应用后重试。已有对话和资料会保留。';

function errorText(value: unknown): string {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  if (value && typeof value === 'object') {
    const data = value as Record<string, unknown>;
    return ['code', 'errorCode', 'message', 'detail', 'error'].map(key => errorText(data[key])).filter(Boolean).join(' ');
  }
  const raw = String(value || '').trim();
  try { const data = JSON.parse(raw); if (data && typeof data === 'object') return errorText(data); } catch { /* Plain provider message. */ }
  return raw;
}

export function taskIssue(value: unknown): TaskIssue {
  const raw = errorText(value);
  if (/请先设置已支持的 Meshy|请先配置语音服务的 API Key/.test(raw)) return { code:'media_configuration', title:'媒体服务尚未配置', message:raw, action:'settings', actionLabel:'配置媒体服务' };
  if (/created under a different OpenAI resource/i.test(raw)) return { code:'response_resource', title:'历史会话的服务端资源不匹配', message:'上游无法读取旧响应的资源编号。历史和产物已保留，本轮没有自动重发。请核对原请求与费用。', action:'inspect', actionLabel:'查看请求与计费' };
  if (/EvoLink 结果下载失败|在产物记录中取回原结果/.test(raw)) return { code:'image_download', title:'图片已生成，等待取回', message:'服务商已生成图片，但下载未完成。可在产物记录中查询并取回原结果，不会重新生成。', action:'inspect', actionLabel:'取回原结果' };
  if (/请先选择支持语音生成的音频模型/.test(raw)) return { code: 'audio_model', title: '尚未配置语音模型', message: '当前服务没有可用的语音生成模型，本次音频生成未提交。请在设置中配置支持语音合成的服务和模型。', action: 'settings', actionLabel: '配置语音模型' };
  if (/video 模型.*不在本地目录/.test(raw)) return { code: 'video_model', title: '视频模型不可用', message: '默认视频模型不在当前服务的本地目录中，本次视频生成未提交。请在模型菜单中选择目录内的视频模型，或在设置中更新默认模型。', action: 'settings', actionLabel: '检查视频模型设置' };
  if (/model_stream_interrupted|other side closed|UND_ERR_SOCKET|terminated.*(?:socket|connection)/i.test(raw)) return { code: 'model_stream_interrupted', title: '模型服务连接中断', message: '文本模型未返回完整结果，本轮已停止。原请求的费用尚未确认，请先查看请求与计费记录，再决定是否继续；已有对话和资料会保留。', action: 'inspect', actionLabel: '查看请求与计费' };
  if (/model_output_limit|max_output_tokens|模型输出达到.*长度上限/.test(raw)) return { code: 'model_output_limit', title: '模型输出达到长度上限', message: '本轮文本或工具参数被截断，未执行不完整的工具。已有会话和产物已保留；请求可能已计费，已停止自动重发，请先核对本轮请求。', action: 'inspect', actionLabel: '查看请求、产物与计费' };
  if (/model_response_incomplete|unsuccessful terminal state|response\.incomplete/.test(raw)) return { code: 'model_response_incomplete', title: '文本响应未完成', message: '文本服务未返回完整成功结果，已有会话和产物已保留。请求可能已计费，已停止自动重发，请先核对本轮请求。', action: 'inspect', actionLabel: '查看请求、产物与计费' };
  if (/工具参数校验未通过|工具参数需修正/.test(raw)) return { code: 'tool_arguments', title: '执行参数未能正确衔接', message: '内部工具参数未通过校验，已停止重复纠错。已有计划、会话和产物已保留；无需改写设计要求，请先查看本轮执行详情。', action: 'inspect', actionLabel: '查看本轮执行详情' };
  if (/image_response_timeout|等待图像响应超时/.test(raw)) return { code: 'image_response_timeout', title: '图像响应超时，结果待确认', message: '等待图像服务响应超时，生成结果尚未确认。请求可能已计费，已停止自动重试；请先核对原请求，已保存的图片会保留。', action: 'inspect', actionLabel: '查看请求、产物与计费' };
  if (/image_result_unconfirmed|生成结果待确认|生成请求的结果尚未确认|generate_image 上次调用尚未确认/.test(raw)) return { code: 'image_result_unconfirmed', title: '生成结果待确认', message: '图像请求未取得完整结果，可能已计费。已停止自动重试，请先核对原请求；已保存的图片会保留。', action: 'inspect', actionLabel: '查看请求、产物与计费' };
  if (/image_response_invalid|图像响应内容异常/.test(raw)) return { code: 'image_response_invalid', title: '图像响应内容异常', message: '图像服务返回的内容无法保存为图片，请求可能已计费。已停止自动重试，请先核对原请求。', action: 'inspect', actionLabel: '查看请求、产物与计费' };
  if (/目标不在本轮引用、对话相关内容或本轮产物中/.test(raw)) return { code: 'scope', title: '素材关联未通过', message: '本轮引用了未关联到当前任务的素材，流程已停止。已生成的文件仍保留在画布中，可查看和下载。', action: 'edit', actionLabel: '回到对话' };
  const networkIssue: TaskIssue = { code: 'network', title: '请切换网络后重试', message: `${serviceNetworkHint}已有对话和已完成的产物会保留，网络恢复后可继续原任务。`, action: 'resume', actionLabel: '已切换网络，继续任务' };
  if (/对话信息保存校验|记忆来源引文|memory_invalid|memory_conflict|source\.quote/.test(raw)) return { code: 'memory', title: '对话信息未保存', message: '整理对话信息时，来源或版本校验未通过，已停止重复提交。原始消息和资料仍保留；可在当前对话继续，并说明需要采用的资料。', action: 'edit', actionLabel: '回到对话继续' };
  if (/图像服务返回了 SVG|image_output_format/.test(raw)) return { code: 'image_output_format', title: '图像返回格式不符合要求', message: '图像服务返回了已禁用的 SVG，未保存为产物。请求已返回，可能已计费，已停止自动重试；请检查图像服务的输出格式。', action: 'settings', actionLabel: '检查图像模型设置' };
  if (/找不到 Node\.js|Agent 本地运行时|OpenAI Agents SDK worker 不存在/.test(raw)) return { code: 'runtime', title: '本地执行环境需要恢复', message: '本地执行进程未能启动。请先重启应用，再继续原任务；已生成的产物会保留，不会重复提交已完成的生成请求。', action: 'resume', actionLabel: '继续原任务' };
  if (/local_service_unavailable|无法连接本地服务/.test(raw)) return { code: 'local_service', title: '本地服务暂未连接', message: localServiceHint, action: 'resume', actionLabel: '重新连接' };
  if (/媒体.*(预览|解码)|(?:视频|音频|播放).*检查/.test(raw)) return { code: 'media_preview', title: '媒体预览检查未通过', message: '生成文件已保留在画布中。未通过的是播放预览检查，可以重新检查已有文件，无需重新生成。', action: 'resume', actionLabel: '重新检查已有媒体' };
  if (/spending.limit|monthly.limit|insufficient.quota|quota.exceeded|credit.balance|余额不足|额度不足|消费限额|积分预算|budget.*exceed/i.test(raw)) {
    return { code: 'quota', title: '可用额度不足', message: '服务商的消费限额、余额或任务预算不足。请检查额度和预算设置，调整后再发送；重复重试不会解决这个问题。', action: 'settings', actionLabel: '检查模型与预算设置' };
  }
  // Geographic restrictions often arrive as 403 or "unsupported"; they are
  // network access problems, not evidence of a bad key or incompatible model.
  if (/(?:unsupported|blocked|restricted|not[\s_-]+available|unavailable|not[\s_-]+supported)[\w\s-]*(?:country|region|territory)|(?:country|region|territory|location|geographic)[^\n]{0,80}(?:not.supported|unsupported|blocked|restricted|not.available|unavailable)|(?:地区|地域|国家|区域).{0,20}(?:不支持|不可用|限制|无法访问)|(?:仅限|只允许).{0,10}海外/i.test(raw)) return networkIssue;
  if (/401|authentication|unauthorized/i.test(raw)) return { code: 'auth', title: '模型认证失败', message: '请检查当前服务的 API Key 是否已保存、有效，并与所选服务地址匹配。', action: 'settings', actionLabel: '检查模型设置' };
  if (/403|forbidden|permission.denied|无权限/i.test(raw)) return { code: 'permission', title: '服务拒绝访问', message: '当前账号或 API Key 没有使用该模型的权限，请检查服务权限或更换已授权的模型。', action: 'settings', actionLabel: '检查模型设置' };
  if (/429|rate.limit|too.many.requests|请求过于频繁/i.test(raw)) return { code: 'rate', title: '服务暂时限流', message: '请求频率超过服务限制，请稍后继续原任务。已保存的产物会保留。', action: 'resume', actionLabel: '继续原任务' };
  if (/timeout|timed.out|超时|network|连接|fetch.failed|failed.to.fetch|load.failed|econn|enotfound|eai_again|enetunreach|ehostunreach|socket|connection[\s_-]*(?:error|failed|refused|reset|closed|aborted)|connecterror|apiconnectionerror|getaddrinfo|nodename.nor.servname|name.or.service.not.known|temporary.failure.in.name.resolution|remote.end.closed|tls.*(?:handshake|disconnected)|\b50[0234]\b|可访问海外服务的网络/i.test(raw)) return networkIssue;
  if (/api.?key|凭据|鉴权/i.test(raw)) return { code: 'auth', title: '模型认证失败', message: '请检查当前服务的 API Key 是否已保存、有效，并与所选服务地址匹配。', action: 'settings', actionLabel: '检查模型设置' };
  if (/没有可用且兼容的自动图像模型|image 模型.*不在本地目录/i.test(raw)) return { code: 'image_model', title: '自动图像模型不可用', message: '文本 Agent 已正常运行，但当前图像模型目录或图像服务地址不可用。请同步图像模型目录并检查图像模型设置。', action: 'settings', actionLabel: '检查图像模型设置' };
  if (/unsupported|not.support|模型.*不|不支持|模型.*目录|模型配置|reasoning_effort|model.*not.found|协议/i.test(raw)) return { code: 'model', title: '模型配置不兼容', message: '所选模型的能力、协议或参数与本次任务不匹配。请同步模型目录，并选择支持本次输入和工具的模型。', action: 'settings', actionLabel: '检查模型设置' };
  if (/验收|审查|交付/.test(raw)) return { code: 'delivery', title: '本轮交付未完成', message: '本轮仍有文件、数量或预览未就绪。已保存的产物会保留，请查看执行详情与缺项。', action: 'inspect', actionLabel: '查看交付记录' };
  return { code: 'unknown', title: '本轮未完成', message: '执行未能完成，已有对话和产物已保留。可以调整要求后继续。', action: 'edit', actionLabel: '修改后重发' };
}

export const taskErrorMessage = (value: unknown) => { const issue = taskIssue(value); return `${issue.title}：${issue.message}`; };
