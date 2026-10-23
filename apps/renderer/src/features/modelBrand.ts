// Match model families before gateway metadata: a reseller is not the model maker.
const brands = [
  ['openai', 'OpenAI', /openai|gpt[- ]|chatgpt|dall-e|sora|^o[134](?:-|$)/i],
  ['anthropic', 'Anthropic', /anthropic|claude/i],
  ['google', 'Google', /google|gemini|imagen|veo|nano[- ]?banana/i],
  ['deepseek', 'DeepSeek', /deepseek/i],
  ['alibaba', '阿里通义', /alibaba|qwen|通义|wan(?:x|[-_\d])|wan\//i],
  ['bytedance', '字节跳动', /bytedance|doubao|seedance|seedream|豆包/i],
  ['kuaishou', '快手', /kuaishou|kling|可灵/i],
  ['xai', 'xAI', /xai|x-ai|grok/i],
  ['meta', 'Meta', /meta|llama/i],
  ['mistral', 'Mistral', /mistral|mixtral|codestral/i],
  ['bfl', 'Black Forest Labs', /black.?forest|bfl|flux/i],
  ['moonshot', 'Moonshot', /moonshot|kimi/i],
  ['minimax', 'MiniMax', /minimax|hailuo|海螺/i],
  ['zhipu', '智谱', /zhipu|z-ai|glm|cogview|cogvideo/i],
] as const;
export function modelBrand(model: string, vendor = '') {
  const match = brands.find(([, , pattern]) => pattern.test(model)) || brands.find(([, , pattern]) => pattern.test(vendor));
  return match ? { id: match[0], label: match[1] } : { id: 'generic', label: '模型' };
}
