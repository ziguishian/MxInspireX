export function titleBarColors(value: unknown) {
  if (!value || typeof value !== 'object') return;
  const { background, foreground } = value as Record<string, unknown>;
  const hex = /^#[0-9a-f]{6}$/i;
  if (typeof background !== 'string' || typeof foreground !== 'string' || !hex.test(background) || !hex.test(foreground)) return;
  return { color: background, symbolColor: foreground, height: 34 };
}
