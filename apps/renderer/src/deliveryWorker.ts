import { probeHtml, probeMedia, DELIVERY_PROBE_VERSION } from './deliveryValidation';

export function startDeliveryWorker(api: string) {
  let stopped = false;
  const request = async (path: string, body?: unknown) => {
    const response = await fetch(`${api}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}), signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error(`验收队列请求失败：${response.status}`);
    return response.json();
  };
  const poll = async () => {
    if (stopped) return;
    try {
      const jobs = await request('/api/delivery/claim', { probeVersion: DELIVERY_PROBE_VERSION }) as Array<{ projectId: string; nodeId: string; fingerprint: string; kind: string; html: string; assetId?: string }>;
      await Promise.allSettled(jobs.map(async job => {
        const result = job.kind === 'cad' ? await (await import('./features/cadViewer')).probeCad(`${api}/api/projects/${encodeURIComponent(job.projectId)}/assets/${encodeURIComponent(job.assetId!)}/content`) : job.kind === 'html' ? await probeHtml(job.html) : await probeMedia(`${api}/api/projects/${encodeURIComponent(job.projectId)}/assets/${encodeURIComponent(job.assetId!)}/content`, job.kind);
        if (!stopped) await request(`/api/projects/${job.projectId}/canvas/${job.nodeId}/delivery-check`, { fingerprint: job.fingerprint, probeVersion: DELIVERY_PROBE_VERSION, result });
      }));
    } catch { /* Startup/reconnect: expired leases allow another worker to resume. */ }
    finally { if (!stopped) setTimeout(poll, 2500); }
  };
  void poll();
  return () => { stopped = true; };
}
