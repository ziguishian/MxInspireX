export type TaskFeedback = { taskId: string; rating: number | null; shownAt?: string | null; dismissedAt?: string | null; ratedAt?: string | null };
export const feedbackCooldown = 10 * 60 * 1000;
export const feedbackCooldownKey = 'langjuart.feedbackLastPrompt';

export function readyForFeedback(outputs: Array<{ data?: Record<string, any> }>): boolean {
  return outputs.some(({ data }) => data && data.kind !== 'upload' && !data.generating && !data.draft && !data.error && Boolean(data.assetId || data.asset?.id || data.text?.trim() || data.html?.trim() || data.src));
}
export function shouldPromptFeedback(record: TaskFeedback | undefined, lastPrompt: number, now: number) {
  return !record?.rating && !record?.dismissedAt && !record?.shownAt && (!lastPrompt || now - lastPrompt >= feedbackCooldown);
}
export function betaActor() {
  try { return (localStorage.getItem('langjuart.userNickname') || '').slice(0, 80); } catch { return ''; }
}
export function recordBetaUsage(event: 'app_open' | 'page_view' | 'artifact_view' | 'artifact_export' | 'message_copy' | 'message_edit', details: { page?: string; projectId?: string; taskId?: string } = {}) {
  const api = window.studio?.apiBaseUrl ?? import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765';
  void fetch(`${api}/api/testing/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, actor: betaActor(), ...details }) }).catch(() => undefined);
}
