import { createHash } from 'node:crypto';

const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const count = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
export function cacheUsage(usage = {}) {
  const raw = usage.inputTokensDetails ?? usage.input_tokens_details ?? usage.prompt_tokens_details ?? {};
  const details = Array.isArray(raw) ? raw : [raw];
  const metric = name => {
    if (Object.hasOwn(usage, name)) return count(usage[name]);
    const values = details.filter(d => d && Object.hasOwn(d, name)).map(d => count(d[name]));
    return values.length && values.every(v => v !== undefined) ? values.reduce((a,b) => a+b,0) : undefined;
  };
  const input = count(usage.inputTokens ?? usage.input_tokens ?? usage.prompt_tokens);
  const cached = metric('cached_tokens'), written = metric('cache_write_tokens');
  const present = name => Object.hasOwn(usage,name) || details.some(d => d && Object.hasOwn(d,name));
  const invalid = present('cached_tokens') && cached === undefined || present('cache_write_tokens') && written === undefined;
  const valid = !invalid && input !== undefined && (cached ?? 0)+(written ?? 0) <= input;
  return { cached_tokens: valid ? cached ?? 0 : 0, cache_write_tokens: valid ? written ?? 0 : 0,
    cache_reported_requests: valid && cached !== undefined ? 1 : 0,
    cache_observed_input_tokens: valid && cached !== undefined ? input : 0,
    cache_write_reported_requests: valid && written !== undefined ? 1 : 0 };
}

// Apply documented controls only at confirmed endpoints. Unknown compatible
// gateways still benefit from the same stable prefix, without new parameters
// that could reject a paid request. No probing, prewarming or retry is needed.
export function cachedModelRequest(request, endpoint, scope) {
  const official = /^https:\/\/api\.openai\.com\/v1\/?$/.test(endpoint.baseUrl);
  const router = /^https:\/\/openrouter\.ai\/api\/v1\/?$/.test(endpoint.baseUrl);
  if (!official && !router) return request;
  const key = `langju-v1-${hash([scope, endpoint.model, request.systemInstructions]).slice(0,48)}`;
  const settings = { ...request.modelSettings, providerData: { ...request.modelSettings?.providerData,
    prompt_cache_key: key, ...(router ? { session_id: key } : {}) } };
  const family = endpoint.model.replace(/^openai\//,'');
  const version = /^gpt-(\d+)(?:\.(\d+))?(?:-|$)/.exec(family);
  const explicit = version && (Number(version[1]) >= 6 || Number(version[1]) === 5 && Number(version[2]) >= 6);
  if (!explicit || !request.systemInstructions) return { ...request, modelSettings: settings };
  // Explicit-only caching writes the reusable rules and tools; changing
  // project state and one-off tool results remain outside this breakpoint.
  settings.promptCacheOptions = { mode: 'explicit', ttl: '30m' };
  return { ...request, systemInstructions: undefined, modelSettings: settings, input: [
    // SDK 0.17 models developer messages through provider passthrough items.
    // This exists only in the outbound view, never in canonical Session data.
    { type:'unknown', providerData:{role:'developer', content:[{
      type:endpoint.api === 'chat_completions' ? 'text' : 'input_text', text:request.systemInstructions,
      prompt_cache_breakpoint:{ mode:'explicit' } }]} }, ...request.input,
  ] };
}
