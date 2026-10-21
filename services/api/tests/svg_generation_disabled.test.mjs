import {test} from 'vitest';
import assert from 'node:assert/strict';
import {generationTools} from '../app/tool_scheduler.mjs';
import {validateSvgOperation} from '../app/svg_policy.mjs';

test('SVG generation is removed and raster formats are checked before dispatch', () => {
  assert.ok(!generationTools.includes('canvas_create_svg'));
  for (const format of ['svg', 'SVG', 'image/svg+xml']) {
    assert.throws(()=>validateSvgOperation({}, 'generate_image', {params:{output_format:format}}), /全局禁用/);
    assert.throws(()=>validateSvgOperation({}, 'image_edit', {params:{format}}), /全局禁用/);
  }
  for (const format of ['png','jpeg','webp']) {
    assert.doesNotThrow(()=>validateSvgOperation({}, 'generate_image', {params:{output_format:format}}));
  }
});
