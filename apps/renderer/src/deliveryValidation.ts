import { htmlPreviewDocument, HTML_PREVIEW_SANDBOX } from './htmlPreview';

export const DELIVERY_PROBE_VERSION = 2;

type Check = { passed: boolean; errors: string[]; frames?: string[]; duration?: number; buttonsTested?: number; code?: string };
const queued = new Set<string>();
const jobs: (() => Promise<void>)[] = [];
let running = 0;
function pump() {
  while (running < 2 && jobs.length) {
    running++;
    void jobs.shift()!().finally(() => { running--; pump(); });
  }
}

export function probeHtml(source: string, assets?: Record<string, string>): Promise<Check> {
  return new Promise(resolve => {
    const token = Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-'), iframe = document.createElement('iframe');
    iframe.setAttribute('sandbox', HTML_PREVIEW_SANDBOX);
    iframe.style.cssText = 'position:fixed;left:-20000px;top:0;width:1440px;height:960px;border:0;pointer-events:none';
    const finish = (result: Check) => { clearTimeout(timer); window.removeEventListener('message', receive); iframe.remove(); resolve(result); };
    const receive = (event: MessageEvent) => {
      if (event.source === iframe.contentWindow && event.data?.deliveryToken === token) finish(event.data.result);
    };
    const timer = window.setTimeout(() => finish({ passed: false, errors: ['网页预览检查超时'] }), 15000);
    window.addEventListener('message', receive);
    // Run in a separate, opaque-origin iframe. The generated page never gains
    // access to the application, its requests, or this parent verification code.
    const harness = `<script>(()=>{const errors=[];let buttonsTested=0;addEventListener('error',e=>errors.push(e.message||'资源加载失败'),true);addEventListener('unhandledrejection',()=>errors.push('未处理的脚本异常'));addEventListener('securitypolicyviolation',e=>errors.push('预览不允许外部资源：'+e.violatedDirective));addEventListener('submit',e=>e.preventDefault(),true);addEventListener('load',async()=>{await new Promise(r=>setTimeout(r,250));for(const button of [...document.querySelectorAll('button,[role=button]')].filter(b=>!b.disabled).slice(0,6)){try{button.click();buttonsTested++;await new Promise(r=>setTimeout(r,50));}catch(e){errors.push(String(e));}}const visible=Boolean(document.body?.innerText.trim()||document.querySelector('img,svg,canvas,video,input'));if(!visible)errors.push('网页没有可见内容');parent.postMessage({deliveryToken:${JSON.stringify(token)},result:{passed:errors.length===0,errors:errors.slice(0,12),buttonsTested}},'*');});})();<\/script>`;
    iframe.srcdoc = htmlPreviewDocument(harness + source, assets);
    document.body.append(iframe);
  });
}

class MediaCheckError extends Error {
  constructor(message: string, readonly code: string) { super(message); }
}

// Each stage gets its own deadline: downloading must not consume the seek budget.
function mediaStage<T>(run: (signal: AbortSignal) => Promise<T>, label: string, timeout: number): Promise<T> {
  const controller = new AbortController();
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new MediaCheckError(`媒体预览检查超时：${label}，已保存的文件会保留`, 'media_timeout'));
      controller.abort();
    }, timeout);
    void run(controller.signal).then(resolve, reject).finally(() => clearTimeout(timer));
  });
}

export async function probeMedia(url: string, kind: string): Promise<Check> {
  let objectUrl = '', media: HTMLVideoElement | undefined;
  try {
    const { bytes, mime } = await mediaStage(async signal => {
      const response = await fetch(url, { signal });
      if (!response.ok) throw new MediaCheckError(`媒体预览无法读取已保存文件（HTTP ${response.status}）`, response.status >= 500 ? 'media_transport' : 'media_unavailable');
      return { bytes: await response.arrayBuffer(), mime: response.headers.get('content-type') };
    }, '读取文件', 20000);
    if (kind === 'audio') {
      const audio = new AudioContext();
      try {
        const decoded = await mediaStage(() => audio.decodeAudioData(bytes), '解码音频', 15000);
        if (decoded.duration <= 0) throw new MediaCheckError('媒体预览检查失败：音频时长为空', 'media_invalid');
        return { passed: true, errors: [], duration: decoded.duration };
      } finally { await audio.close(); }
    }
    objectUrl = URL.createObjectURL(new Blob([bytes], { type: mime || 'video/mp4' }));
    const video = document.createElement('video'); media = video;
    video.muted = true; video.preload = 'auto'; video.playsInline = true;
    video.style.cssText = 'position:fixed;left:-20000px;top:0;width:640px;height:360px;pointer-events:none';
    document.body.append(video);
    const event = (name: string, trigger: () => void, label: string, ready: () => boolean = () => false) => mediaStage(signal => new Promise<void>((resolve, reject) => {
      const clean = () => { video.removeEventListener(name, done); video.removeEventListener('error', fail); signal.removeEventListener('abort', aborted); };
      const done = () => { clean(); resolve(); };
      const fail = () => { clean(); reject(new MediaCheckError(`媒体预览无法解码视频（解码器代码 ${video.error?.code || 0}）`, 'media_decode')); };
      const aborted = () => { clean(); reject(new MediaCheckError(`媒体预览检查超时：${label}`, 'media_timeout')); };
      video.addEventListener(name, done); video.addEventListener('error', fail); signal.addEventListener('abort', aborted, { once: true });
      try { trigger(); if (video.error) fail(); else if (ready()) done(); }
      catch (error) { clean(); reject(error); }
    }), label, 15000);
    await event('loadeddata', () => { video.src = objectUrl; video.load(); }, '读取首帧', () => video.readyState >= 2);
    if (video.duration === Infinity) {
      // Streamed WebM containers may omit duration until Chromium reaches EOF.
      await event('durationchange', () => { video.currentTime = 1e10; }, '读取时长', () => Number.isFinite(video.duration));
    }
    if (!Number.isFinite(video.duration) || video.duration <= 0 || !video.videoWidth) throw new MediaCheckError('媒体预览检查失败：视频时长或画面无效', 'media_invalid');
    const canvas = document.createElement('canvas');
    canvas.width = Math.min(640, video.videoWidth); canvas.height = Math.round(canvas.width * video.videoHeight / video.videoWidth);
    const frames: string[] = [];
    for (const time of [0, video.duration * .5, Math.max(0, video.duration - .15)]) {
      if (Math.abs(time - video.currentTime) > .01 || video.seeking) {
        await event('seeked', () => { video.currentTime = time; }, `读取第 ${frames.length + 1} 帧`, () => !video.seeking && video.readyState >= 2 && Math.abs(video.currentTime - time) <= .01);
      }
      canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height);
      frames.push(canvas.toDataURL('image/jpeg', .65));
    }
    return { passed: true, errors: [], duration: video.duration, frames };
  } catch (error) {
    const code = error instanceof MediaCheckError ? error.code : error instanceof TypeError ? 'media_transport' : 'media_decode';
    return { passed: false, code, errors: [error instanceof MediaCheckError ? error.message : `媒体预览检查失败：${error instanceof Error ? error.message : '无法读取媒体'}`] };
  } finally {
    if (media) { media.pause(); media.removeAttribute('src'); media.load(); media.remove(); }
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

export function validateDeliveries(api: string, projectId: string, nodes: any[], save: (path: string, result: unknown) => Promise<unknown>) {
  for (const node of nodes) {
    const probe = node.deliveryProbe, kind = node.data?.kind;
    if (!probe?.required || probe.result || !['html', 'video', 'audio'].includes(kind) || node.data.generating || (kind !== 'html' && !node.data.assetId)) continue;
    const key = `${projectId}:${node.id}:${probe.fingerprint}`;
    if (queued.has(key)) continue;
    queued.add(key);
    jobs.push(async () => {
      try {
        const result = kind === 'html' ? await probeHtml(node.data.html || '', node.data.htmlAssets) : await probeMedia(`${api}/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(node.data.assetId)}/content`, kind);
        await save(`/api/projects/${projectId}/canvas/${node.id}/delivery-check`, { fingerprint: probe.fingerprint, probeVersion: DELIVERY_PROBE_VERSION, result });
      } catch { /* A later canvas refresh retries transport failures. */ }
      finally { queued.delete(key); }
    });
  }
  pump();
}
