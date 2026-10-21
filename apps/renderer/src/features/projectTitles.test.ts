import { expect, it } from 'vitest';
import type { Project } from '../../../../packages/contracts/project';
import { mergeProjectTitles } from './projectTitles';

const original: Project = { id: 'one', name: '新对话', titleMode: 'auto', titlePending: true,
  slug: 'one', brief: '你好', budgetMinor: null, currency: 'CNY', status: 'draft',
  rootPath: '/workspace/one', createdAt: '2026-09-12', updatedAt: '2026-09-12' };
const generated: Project = { ...original, name: '宠物品牌图标设计', titlePending: false, titleGeneratedAt: '2026-09-12' };

it('updates the title without resetting current project state or order', () => {
  const current = [{ ...original, brief: '后来补充的需求' }, { ...original, id: 'two' }];
  const result = mergeProjectTitles(current, [generated], [original]);
  expect(result.map(project => project.id)).toEqual(['one', 'two']);
  expect(result[0]).toMatchObject({ name: '宠物品牌图标设计', brief: '后来补充的需求', titlePending: false });
});

it('does not undo a manual rename or recreate a deleted project from a late response', () => {
  const renamed: Project = { ...original, name: '自己取的名称', titleMode: 'manual' };
  expect(mergeProjectTitles([renamed], [generated], [original])).toEqual([renamed]);
  expect(mergeProjectTitles([], [generated], [original])).toEqual([]);
  // Explicitly keeping even the same placeholder counts as a manual rename.
  const sameName: Project = { ...original, titleMode: 'manual' };
  expect(mergeProjectTitles([sameName], [generated], [original])).toEqual([sameName]);
});
