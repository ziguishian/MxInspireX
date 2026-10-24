// The generated document runs only in an opaque-origin sandbox. No API,
// parent document, remote script, frame, or network access is granted.
// Local form validation/submit events work; CSP still blocks form navigation.
export const HTML_PREVIEW_SANDBOX = 'allow-scripts allow-forms';
export const HTML_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
export const HTML_PREVIEW_SCALE = 2 / 3;
export type HtmlPreviewSize = { width: number; height: number };
export function htmlPreviewSize(value?: Partial<HtmlPreviewSize>): HtmlPreviewSize {
  const clamp = (n: unknown, fallback: number, min: number, max: number) => Math.round(Math.min(max, Math.max(min, typeof n === 'number' && Number.isFinite(n) ? n : fallback)));
  return { width: clamp(value?.width, 960, 320, 1920), height: clamp(value?.height, 640, 240, 1440) };
}
export function resolveHtmlAssets(source: string, assets: Record<string, string> = {}): string {
  return source.replace(/asset:\/\/([A-Za-z0-9_-]+)/g, (reference, id) => {
    const url = assets[id];
    return /^data:(?:image\/(?:png|jpeg|webp|gif)|video\/(?:mp4|webm)|audio\/(?:mpeg|mp3|wav|x-wav|ogg|webm|mp4|aac|flac));base64,[A-Za-z0-9+/=]+$/.test(url || '') ? url : reference;
  });
}
export function htmlPreviewDocument(source: string, assets: Record<string, string> = {}, contextMenu = false): string {
  // srcdoc inherits the host URL as its base. A native #fragment link would
  // otherwise replace the preview with the application route inside itself.
  const anchors = `<script>addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0) return;
    const link = event.target.closest?.('a[href]');
    const href = link?.getAttribute('href');
    if (!href?.startsWith('#')) return;
    event.preventDefault();
    let id; try { id = decodeURIComponent(href.slice(1)); } catch { return; }
    const target = id ? document.getElementById(id) || document.getElementsByName(id)[0] : document.documentElement;
    target?.scrollIntoView({block:'start'});
  });<\/script>`;
  const bridge = contextMenu ? `<script>addEventListener('contextmenu', event => {
    event.preventDefault();
    parent.postMessage({type:'aics:html-context-menu', x:event.clientX, y:event.clientY}, '*');
  }, true);
  addEventListener('pointerdown', event => {
    if (event.button === 0) parent.postMessage({type:'aics:html-dismiss-menu'}, '*');
  }, true);
  addEventListener('keydown', event => {
    if (event.key === 'Escape') parent.postMessage({type:'aics:html-dismiss-menu'}, '*');
  }, true);<\/script>` : '';
  return `<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${HTML_PREVIEW_CSP}"><meta name="referrer" content="no-referrer">${anchors}${bridge}${resolveHtmlAssets(source, assets)}`;
}
