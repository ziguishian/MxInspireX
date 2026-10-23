import { reactive } from 'vue';
export type CanvasBackground = { pattern: 'grid' | 'dots' | 'none'; image: string };
export function parseCanvasBackground(raw: string | null): CanvasBackground {
  try { const value = JSON.parse(raw || '{}'); return { pattern: ['grid','dots','none'].includes(value.pattern) ? value.pattern : 'grid', image: typeof value.image === 'string' && /^data:image\/(png|jpeg|webp);base64,/.test(value.image) ? value.image : '' }; }
  catch { return { pattern:'grid', image:'' }; }
}
function read() { try { return parseCanvasBackground(localStorage.getItem('aics.canvasBackground')); } catch { return parseCanvasBackground(null); } }
export const canvasBackground = reactive(read());
export function saveCanvasBackground(next: CanvasBackground) {
  localStorage.setItem('aics.canvasBackground', JSON.stringify(next));
  Object.assign(canvasBackground, next);
}
