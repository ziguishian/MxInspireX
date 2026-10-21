// Recover only the original local receipt. This path never submits generation.
export const unconfirmedImageResult = () => ({tool:'generate_image', status:'generation_unconfirmed',
  errorCode:'image_result_unconfirmed', retryable:false, billingCertainty:'unknown',
  message:'图像连接中断，原请求结果尚未确认。',
  instruction:'保留已保存图像；本项可能已计费，不得重发或改参数重试。'});

export async function waitForImageResult({baseUrl,projectId,taskId,args,fetchResult = fetch,toolName = 'generate_image',
  now = Date.now, sleep = ms => new Promise(resolve=>setTimeout(resolve,ms)), timeoutMs = 15*60*1000, intervalMs = 2000, operationId, returnEnvelope = false}) {
  const terminal = (output,httpStatus=200) => returnEnvelope ? {output,httpStatus} : output;
  const unconfirmed = () => ({...unconfirmedImageResult(),tool:toolName,
    ...(toolName === 'generate_audio' ? {message:'语音连接中断，原请求结果尚未确认。',instruction:'保留原请求；本项可能已计费，不得重发或改参数重试。'} : {})});
  if (!taskId) return terminal(unconfirmed());
  const deadline = now()+timeoutMs;
  while (now()<deadline) {
    try {
      const prefix = `${baseUrl}/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}`;
      const response = await fetchResult(operationId ? `${prefix}/${toolName === 'generate_audio' ? 'audio' : 'image'}-operations/${encodeURIComponent(operationId)}` : `${prefix}/tool-result`, {
        ...(operationId ? {method:'GET'} : {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:toolName,arguments:args})}),
        signal:AbortSignal.timeout(5000),
      });
      if ([404,422].includes(response.status)) return terminal(unconfirmed());
      if (response.ok) {
        const result = await response.json();
        if (result.state==='completed' && result.output) return terminal(result.output,result.httpStatus || 200);
        if (result.state==='cancelled') return terminal({tool:toolName,status:'cancelled',retryable:false});
        if (['unconfirmed','rejected','missing'].includes(result.state)) return terminal(unconfirmed());
      }
    } catch { /* A failed lookup cannot prove that the original call failed. */ }
    await sleep(Math.min(intervalMs,Math.max(0,deadline-now())));
  }
  return terminal(unconfirmed());
}
