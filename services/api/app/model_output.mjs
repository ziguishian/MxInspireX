// 4096 is the legacy default allowance, not enough for a multi-item plan or
// batch of detailed image prompts. Expand that default before submission only;
// keep custom limits and ordinary requests unchanged.
export function agentOutputTokenLimit(input) {
  const configured = Number(input.maxOutputTokens || 4096);
  const constraints = input.context?.constraints || {};
  const requestedCount = (constraints.deliveryContract || []).reduce((sum, item) => sum + (Number(item.count) || 1), 0);
  const multiItem = constraints.designPlanning?.required === true
    || (constraints.designPlan?.deliverables?.length || 0) >= 2 || requestedCount >= 2;
  if (configured !== 4096 || !multiItem || constraints.simpleConversation) return configured;
  const capabilities = input.modelCapabilities || {};
  const declared = Number(capabilities.maxOutputTokens || capabilities.max_output_tokens || capabilities.top_provider?.max_completion_tokens);
  return declared > 0 ? Math.min(32768, declared) : 32768;
}

export function outputFailure(reason) {
  const length = reason === 'max_output_tokens' || reason === 'length';
  return Object.assign(new Error(length
    ? 'model_output_limit：模型输出达到单次长度上限，当前内容未完成。已保留会话和完成产物，未执行被截断的工具；请核对本轮请求后继续。'
    : 'model_response_incomplete：文本服务未返回完整成功结果。已保留会话和完成产物，未执行不完整的工具；请先核对本轮请求。'),
  {failureKind:length ? 'configuration' : 'provider', unsafeToReplay:true, responseStarted:true, submitted:true, billingCertainty:'unknown'});
}

export function responsesOutputFailure(event) {
  if (!event) return null;
  const failed = ['response.incomplete','response.failed','response.error','error'].includes(event.type)
    || event.type === 'response.completed' && (!event.response || ['incomplete','failed'].includes(event.response.status));
  return failed ? outputFailure(event.response?.incomplete_details?.reason) : null;
}
