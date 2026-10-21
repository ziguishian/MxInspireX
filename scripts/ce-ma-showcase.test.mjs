import { test, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { preflight } from './import-ce-ma-showcase.mjs';
import { buildBoard, validateBoard } from './showcase-board.mjs';

const assetsRoot = new URL('./showcase-assets/ce-ma-v1/', import.meta.url);
const { case: entry } = JSON.parse(readFileSync(new URL('manifest.json', assetsRoot), 'utf8'));

test('ce-ma preserves all supplied artwork and identifies generated production simulations', () => {
  const assets = entry.images.map((_, i) => ({ id: `ce-ma-${i}`, metadata: {} }));
  // Layout tests need only a deterministic payload; real bytes are checked below.
  const layoutEntry = { ...entry, images: entry.images.map(image => ({ ...image, bytes: Buffer.from('layout-test-only') })) };
  const board = buildBoard(layoutEntry, assets);
  expect(() => validateBoard(entry, board)).not.toThrow();
  expect(board.nodes).toHaveLength(20);
  const images = board.nodes.filter(n => n.data.kind === 'image');
  expect(images.filter(n => n.data.showcaseProvenance.role === 'source')).toHaveLength(2);
  expect(images.filter(n => n.data.showcaseProvenance.role === 'supplied-concept')).toHaveLength(6);
  expect(images.filter(n => n.data.showcaseProvenance.role === 'generated')).toHaveLength(4);
  const simulations = images.filter(n => /刀版模拟|制作文件模拟/.test(n.data.title));
  expect(simulations).toHaveLength(2);
  expect(simulations.every(n => n.data.productionNotes.includes('不是可编辑制作文件'))).toBe(true);
  expect(board.nodes.every(n => n.meta.createdBy === 'ce-ma-import')).toBe(true);
  const html = board.nodes.find(n => n.data.kind === 'html').data;
  expect(html.html).toContain('一路相伴');
  expect(html.html).not.toContain('把一段织纹');
  expect(Object.keys(html.htmlAssets)).toHaveLength(12);
  for (const asset of assets) expect(html.html).toContain(`asset://${asset.id}`);
  expect(html.html).toContain('图像模型生成');
  expect(() => validateBoard(entry, { ...board, nodes: board.nodes.filter(n => n.data.kind !== 'html') })).toThrow(/作品集/);
  // The source board must remain independent of generated packaging and cover assets.
  expect(new Set(images.map(n => n.data.showcaseProvenance.sha256)).size).toBe(12);
});

// Private source media is intentionally absent from the public source package.
// A partially supplied dataset must fail preflight instead of silently skipping.
test.skipIf(!entry.images.some(image => existsSync(new URL(image.file, assetsRoot))))(
  'ce-ma source media hashes and dimensions match the manifest (requires private assets)',
  async () => { await preflight(); },
);
