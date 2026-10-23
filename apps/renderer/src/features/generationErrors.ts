import { localServiceHint, serviceNetworkHint, taskIssue } from './taskErrors';

/** Public descriptions only. Keep the original exception in task/backend logs. */
export function generationFailureText(value: unknown): string {
  if (/only supports background|background.*(?:unsupported|not supported)|不支持.*透明|未声明透明输出/i.test(String(value || ''))) {
    return '所选模型不支持当前背景参数，请调整节点的背景设置后再生成。';
  }
  const issue = taskIssue(value);
  if (['image_response_timeout', 'image_result_unconfirmed', 'image_response_invalid', 'model_stream_interrupted', 'model_output_limit', 'model_response_incomplete', 'media_configuration', 'audio_model', 'video_model'].includes(issue.code)) return issue.message;
  const messages: Record<string, string> = {
    scope: '素材关联未通过，已生成的文件仍保留在画布中，可查看和下载。',
    image_output_format: '图像服务返回了已禁用的 SVG，未保存。请求可能已计费，已停止自动重试，请检查图像模型设置。',
    quota: '可用额度不足，请检查余额或任务预算。',
    auth: '生成服务未能验证账号，请检查模型设置。',
    permission: '当前账号无法使用所选模型，请检查服务权限。',
    model: '当前模型不支持这次请求，请调整模型设置。',
    rate: '生成服务暂时繁忙，请稍后继续。',
    network: serviceNetworkHint,
    local_service: localServiceHint,
    runtime: '本地生成服务未能启动，请重启应用后继续。',
    media_preview: '文件已保留，但暂时无法预览，请重新检查已有文件。',
    delivery: '已有内容已保留，本轮结果还需要调整。',
  };
  return messages[issue.code] || '本轮执行未完成，已保存的内容会保留。';
}

const technicalFailure = /\bHTTP\s*[:：]?\s*[45]\d{2}\b|Traceback\s*\(|\b(?:TypeError|ReferenceError|SyntaxError|RuntimeError|ProviderError|ZodError|APIConnectionError|APITimeoutError|ConnectError|ConnectTimeout|ReadTimeout)\b|\b(?:ECONNRESET|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ENETUNREACH|EHOSTUNREACH)\b|connection[\s_-]*(?:error|failed|refused|reset|closed|aborted)|fetch.failed|failed.to.fetch|network.error|unsupported_country_region_territory|could not generate an image|"(?:error|stack)"\s*:|\b(?:Error|Exception):/i;

/** Clean runtime diagnostics echoed in progress/replies, preserving normal prose/code. */
export function publicAssistantMessage(value: string): string {
  const text = value.replace(/```[^\n]*\n[\s\S]*?```/g, block => technicalFailure.test(block) ? generationFailureText(block) : block);
  return text.split(/\n\s*\n/).map(paragraph => technicalFailure.test(paragraph) ? generationFailureText(paragraph) : paragraph).join('\n\n');
}
