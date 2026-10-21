// Inspect the whole cause chain: fetch often wraps UND_ERR_SOCKET in TypeError.
// A lost response is not proof that the provider never received/billed a request.
export function workerFailure(error, toolFailureCount = 0) {
  const causes = [], seen = new Set();
  for (let cause = error; cause && !seen.has(cause) && causes.length < 6; cause = cause.cause) {
    seen.add(cause); causes.push(cause);
  }
  const message = causes.findLast(cause => cause.message)?.message || String(error);
  const text = causes.map(cause => `${cause.name || ''} ${cause.code || ''} ${cause.message || cause}`).join(' ');
  const status = Number(error?.status);
  const transport = /other side closed|UND_ERR_|timeout|timed out|fetch failed|connection|ECONNRESET|ECONNREFUSED|socket/i.test(text);
  const runtime = !transport && /ENOBUFS|\.map is not a function|Cannot read properties|TypeError|signature|JSONL|protocol|RunState/i.test(text);
  const provider = status >= 400 || transport;
  const rejected = [409, 429].includes(status);
  const retryRaw = error?.headers?.get?.('retry-after') ?? error?.headers?.['retry-after'] ?? error?.response?.headers?.get?.('retry-after');
  const retryAfter = retryRaw == null ? NaN : Number(retryRaw);
  return {
    message: transport && /other side closed|UND_ERR_SOCKET/i.test(text) ? `model_stream_interrupted: ${message}` : message,
    kind: error?.failureKind || (runtime ? 'runtime' : status >= 400
      ? (status < 500 && ![408, 409, 429].includes(status) ? 'configuration' : 'provider')
      : transport ? 'provider' : /MaxTurns|Validation|ModelBehavior|Output|Tool/.test(error?.name || '') || toolFailureCount >= 2 ? 'capability' : 'runtime'),
    statusCode: error?.status,
    ...(error?.providerRequestId ? {providerRequestId:error.providerRequestId} : {}),
    submitted: error?.submitted ?? (error?.responseStarted ? true : provider ? !rejected : false),
    billingCertainty: error?.billingCertainty || (error?.responseStarted ? 'unknown' : provider ? (rejected ? 'not_submitted' : 'unknown') : 'not_applicable'),
    ...(Number.isFinite(retryAfter) && retryAfter >= 0 ? {retryAfter} : {}),
  };
}
