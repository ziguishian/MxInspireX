import { reactive, watch } from 'vue';

export type ThemeColors = { background: string; foreground: string; accent: string };
export type Appearance = { preset: string; custom: Record<'dark' | 'light', ThemeColors>; font: 'system' | 'serif' | 'mono' };
export const themePalettes = [
  { id: 'neutral', name: '中性灰', dark: { background: '#181818', foreground: '#dddddd', accent: '#dddddd' }, light: { background: '#f3f2ef', foreground: '#282828', accent: '#353535' } },
  { id: 'ocean', name: '雾海蓝', dark: { background: '#171d27', foreground: '#e0e8f4', accent: '#8db7ff' }, light: { background: '#edf3fa', foreground: '#243348', accent: '#285da9' } },
  { id: 'forest', name: '苔原绿', dark: { background: '#18211e', foreground: '#dceae1', accent: '#9bc7ab' }, light: { background: '#eef4ed', foreground: '#283c30', accent: '#35704b' } },
  { id: 'sand', name: '暖沙', dark: { background: '#25201b', foreground: '#eee2d3', accent: '#d6b48b' }, light: { background: '#f8f1e7', foreground: '#463829', accent: '#8b5a2e' } },
  { id: 'violet', name: '暮光紫', dark: { background: '#201b2a', foreground: '#e9e0f4', accent: '#bda0e7' }, light: { background: '#f4eff9', foreground: '#3d2e50', accent: '#784ca4' } },
  { id: 'rose', name: '蔷薇', dark: { background: '#281c21', foreground: '#f2e0e5', accent: '#dfa0b6' }, light: { background: '#fbf0f3', foreground: '#4c2e39', accent: '#a34365' } },
] as const;
export const validHex = (value: unknown): value is string => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
export function parseAppearance(raw: string | null): Appearance {
  const result: Appearance = { preset: 'neutral', custom: { dark: { ...themePalettes[0].dark }, light: { ...themePalettes[0].light } }, font: 'system' };
  try {
    const data = JSON.parse(raw || '{}');
    if (data.preset === 'custom' || themePalettes.some(p => p.id === data.preset)) result.preset = data.preset;
    if (['system', 'serif', 'mono'].includes(data.font)) result.font = data.font;
    for (const mode of ['dark', 'light'] as const) for (const key of ['background', 'foreground', 'accent'] as const) {
      if (validHex(data.custom?.[mode]?.[key])) result.custom[mode][key] = data.custom[mode][key];
    }
  } catch { /* Keep defaults if local preferences are damaged. */ }
  return result;
}
function loadAppearance() { try { return parseAppearance(localStorage.getItem('aics.appearance')); } catch { return parseAppearance(null); } }
export const appearance = reactive(loadAppearance());
export function colorsFor(mode: 'dark' | 'light'): ThemeColors {
  return appearance.preset === 'custom' ? appearance.custom[mode] : (themePalettes.find(p => p.id === appearance.preset) || themePalettes[0])[mode];
}
export function mixColor(a: string, b: string, ratio: number) {
  return '#' + [1, 3, 5].map(i => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - ratio) + parseInt(b.slice(i, i + 2), 16) * ratio).toString(16).padStart(2, '0')).join('');
}
export function contrastRatio(a: string, b: string) {
  const luminance = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
}
export function paletteVariables(colors: ThemeColors) {
  const { background: bg, foreground: fg, accent } = colors;
  const mix = (ratio: number) => mixColor(bg, fg, ratio);
  return {
    '--theme-bg': bg, '--theme-shell-bg': bg, '--theme-sidebar': mix(.02),
    '--theme-surface': mix(.05), '--theme-surface-raised': mix(.07), '--theme-surface-floating': mix(.08),
    '--theme-surface-subtle': mix(.03), '--theme-surface-hover': mix(.11),
    '--theme-input': mix(.10), '--theme-input-border': mix(.19), '--theme-border': mix(.14), '--theme-border-strong': mix(.26),
    '--theme-text': fg, '--theme-text-muted': mix(.72), '--theme-text-subtle': mix(.57),
    '--theme-accent': accent, '--theme-accent-strong': accent, '--theme-accent-soft': mixColor(bg, accent, .15),
    '--theme-accent-foreground': contrastRatio(accent, '#ffffff') > contrastRatio(accent, '#181818') ? '#ffffff' : '#181818',
  };
}
export function applyAppearance(mode: 'dark' | 'light') {
  const root = document.documentElement;
  root.style.setProperty('--desktop-titlebar-height', window.studio?.isDesktop ? '34px' : '0px');
  const variables = paletteVariables(colorsFor(mode));
  for (const [key, value] of Object.entries(variables)) {
    if (appearance.preset === 'neutral') root.style.removeProperty(key);
    else root.style.setProperty(key, value);
  }
  root.style.setProperty('--app-font', appearance.font === 'serif' ? 'Georgia, "Noto Serif SC", "Songti SC", SimSun, serif' : appearance.font === 'mono' ? 'Consolas, "SFMono-Regular", "Microsoft YaHei", monospace' : 'Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', colorsFor(mode).background);
  const { background, foreground } = colorsFor(mode);
  void window.studio?.setTitleBarTheme?.({ background, foreground });
}
watch(appearance, () => {
  try { localStorage.setItem('aics.appearance', JSON.stringify(appearance)); } catch { /* Keep current session settings. */ }
  if (typeof document !== 'undefined') applyAppearance(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
}, { flush: 'sync' });
