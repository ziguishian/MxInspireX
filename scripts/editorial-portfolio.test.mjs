import { test, expect } from 'vitest';
import { readFile } from 'node:fs/promises';
import { createEditorialPortfolio, editorialSlugs } from './editorial-portfolio.mjs';

test('four editorial pages keep all project sources and isolate brand references', async () => {
  const read = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
  const { cases } = await read('./showcase-assets/ci-jin-v1/manifest.json');
  const { case: ceMa } = await read('./showcase-assets/ce-ma-v1/manifest.json');
  const shan = await read('./showcase-assets/shan-ming-v1/manifest.json');
  const entries = [...cases, ceMa, { ...shan, credit: shan.source, images: shan.images.filter(i => i.role === 'deliverable') }];
  const themes = new Set();
  for (const slug of editorialSlugs) {
    const entry = entries.find(e => e.slug === slug);
    const rows = entry.images.map((image, i) => ({ ...image, assetId: `${slug}-${i}` }));
    const html = createEditorialPortfolio({ slug, name: entry.name, credit: entry.credit, rows });
    const ids = [...html.matchAll(/asset:\/\/([a-zA-Z0-9._-]+)/g)].map(match => match[1]);
    expect(new Set(ids)).toEqual(new Set(rows.map(row => row.assetId)));
    expect(html).toContain('data-portfolio-edition="2"');
    expect(html).toContain('<details>');
    expect(html).toContain('<dialog');
    expect(html).toContain('prefers-reduced-motion');
    expect(html).not.toMatch(/<svg|src="https?:|href="https?:|@import/i);
    themes.add(html.match(/--ink:(#[a-z0-9]+)/)[1]);
    if (slug === 'showcase-shan-ming') expect(html).not.toMatch(/ROCK GRIND|雲天晴|山砚/);
  }
  expect(themes.size).toBe(4);
});
