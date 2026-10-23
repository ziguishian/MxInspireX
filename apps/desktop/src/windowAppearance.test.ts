import { describe, expect, it } from 'vitest';
import { titleBarColors } from './windowAppearance.js';

describe('native title bar colors', () => {
  it.each([
    ['#181818', '#dddddd'], ['#f3f2ef', '#282828'], ['#171d27', '#e0e8f4'],
  ])('uses the actual page background %s and foreground %s', (background, foreground) => {
    expect(titleBarColors({ background, foreground })).toEqual({ color: background, symbolColor: foreground, height: 34 });
  });
  it.each([null, 'dark', {}, { background: 'red', foreground: '#dddddd' }, { background: '#181818', foreground: null }])('rejects invalid IPC payload %j', value => {
    expect(titleBarColors(value)).toBeUndefined();
  });
});
