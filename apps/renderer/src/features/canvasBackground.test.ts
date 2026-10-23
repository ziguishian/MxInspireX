import { describe, expect, it } from 'vitest';
import { parseCanvasBackground } from './canvasBackground';
describe('canvas background preferences', () => {
  it('defaults safely for missing or corrupt settings', () => {
    for (const raw of [null, 'bad', 'null', '{}']) expect(parseCanvasBackground(raw)).toEqual({pattern:'grid',image:''});
  });
  it('retains each supported pattern and embedded image', () => {
    for (const pattern of ['grid','dots','none']) expect(parseCanvasBackground(JSON.stringify({pattern,image:'data:image/png;base64,YQ=='}))).toEqual({pattern,image:'data:image/png;base64,YQ=='});
  });
  it('rejects external URLs and SVG while retaining a valid pattern', () => {
    for (const image of ['https://example.com/private.png','file:///secret','data:image/svg+xml;base64,YQ==']) expect(parseCanvasBackground(JSON.stringify({pattern:'dots',image}))).toEqual({pattern:'dots',image:''});
  });
});
