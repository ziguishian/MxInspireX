import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { expect, it } from 'vitest';
import ModelBrandIcon from './ModelBrandIcon.vue';
it('renders local vector paths without external use URLs in packaged apps', async () => {
  const html = await renderToString(createSSRApp(ModelBrandIcon, { model: 'claude-sonnet' }));
  expect(html).toContain('aria-label="Anthropic"');
  expect(html).toContain('<path');
  expect(html).not.toContain('<use');
  expect(html).not.toContain('data:image');
});
