import { describe, expect, it } from 'vitest';
import { parseAppearance, paletteVariables, themePalettes, contrastRatio } from './appearance';
describe('appearance preferences', () => {
  it('rejects invalid persisted values while preserving each valid mode', () => {
    const value = parseAppearance(JSON.stringify({preset:'custom',font:'url(evil)',custom:{dark:{background:'#112233',accent:'red;--x:1'},light:{foreground:'#123456'}}}));
    expect(value.custom.dark.background).toBe('#112233');
    expect(value.custom.dark.accent).toBe('#dddddd');
    expect(value.custom.light.foreground).toBe('#123456');
    expect(value.font).toBe('system');
    expect(parseAppearance('{').preset).toBe('neutral');
  });
  it('keeps preset text readable in both modes and leaves signal colors alone', () => {
    for (const preset of themePalettes) for (const mode of ['dark','light'] as const) {
      const colors = preset[mode], variables = paletteVariables(colors);
      expect(contrastRatio(colors.background, colors.foreground)).toBeGreaterThan(4.5);
      expect(contrastRatio(colors.accent, variables['--theme-accent-foreground'])).toBeGreaterThan(4.5);
      expect(Object.keys(variables).some(key => /status|success|warning|danger/.test(key))).toBe(false);
      expect(variables['--theme-bg']).toBe(colors.background);
    }
  });
});
