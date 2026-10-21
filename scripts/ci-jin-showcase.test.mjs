import { test, expect } from 'vitest';
import { existsSync } from 'node:fs';
import { buildBoard, preflight, validateBoard, manifest } from './import-ci-jin-showcases.mjs';

test('supplied porcelain and brocade artwork retains photo/concept sources and complete portfolio assets', () => {
  for (const entry of manifest.cases) {
    const assets = entry.images.map((image, i) => ({ id: `${entry.key}-${i}`, metadata: {} }));
    // Private originals belong to the separate media-integrity test.
    const layoutEntry = { ...entry, images: entry.images.map(image => ({ ...image, bytes: Buffer.from('layout-test-only') })) };
    const board = buildBoard(layoutEntry, assets);
    expect(() => validateBoard(entry, board)).not.toThrow();
    const images = board.nodes.filter(n => n.data.kind === 'image');
    expect(images.filter(n => n.data.showcaseProvenance.role === 'photo')).toHaveLength(2);
    expect(images.every(n => n.data.showcaseProvenance.sha256 && n.data.showcaseProvenance.sourceFile && n.data.imageFit === 'contain')).toBe(true);
    expect(images.filter(n => n.data.showcaseProvenance.role === 'concept').every(n => n.data.productionNotes.includes('未经过实物'))).toBe(true);
    const html = board.nodes.find(n => n.data.kind === 'html').data;
    expect(html.imageAssetIds).toEqual(assets.map(a => a.id));
    expect(Object.keys(html.htmlAssets)).toHaveLength(entry.images.length);
    for (const asset of assets) expect(html.html).toContain(`asset://${asset.id}`);
    expect(html.html).toContain('原始实拍');
    expect(html.html).toContain('概念设计方案');
    if (entry.key === 'jin') expect(html.html).toContain('CITONG STUDIO');
    // Real failure modes: accidentally dropping a supplied image or stacking two images.
    const missing = { ...board, nodes: board.nodes.filter(n => n.id !== images[0].id) };
    expect(() => validateBoard(entry, missing)).toThrow();
    images[1].position = images[0].position;
    expect(() => validateBoard(entry, board)).toThrow(/重叠/);
  }
});

const assetsRoot = new URL('./showcase-assets/ci-jin-v1/', import.meta.url);
test.skipIf(!manifest.cases.some(entry => entry.images.some(image => existsSync(new URL(image.file, assetsRoot)))))(
  'porcelain and brocade source media hashes match the manifest (requires private assets)',
  async () => { await preflight(); },
);
