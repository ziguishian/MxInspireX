import { describe, expect, it } from 'vitest';
import { referenceSegments, referencedKeys, readableReferences, type InlineReference } from './references';
const refs: InlineReference[] = [
  { key: 'file:0', token: '@1', label: '附件.png', kind: '图像', badge: '@1' },
  { key: 'asset:one', token: '@asset:one', aliases: ['@封面 图.png'], label: '封面 图.png', kind: '图像', badge: '@' },
  { key: 'asset:two', token: '@asset:two', label: '封面 图.png', kind: '图像', badge: '@' },
  { key: 'knowledge:doc', token: '@knowledge:doc', label: '工艺报价.pdf', kind: '知识文档', badge: '@' },
];
describe('inline composer references', () => {
  it('does not mistake @12 or a filename for attachment @1', () => {
    expect(referencedKeys('@12 @1.png @1', refs)).toEqual(new Set(['file:0']));
    expect(referenceSegments('@12', refs)).toEqual([{ text: '@12' }]);
  });
  it('preserves surrounding text, whitespace and tokens for submission', () => {
    const input = '参考 @asset:one\n结合 @1 ，设计新封面';
    expect(referenceSegments(input, refs).map(item => item.text).join('')).toBe(input);
    expect(referencedKeys(input, refs)).toEqual(new Set(['asset:one', 'file:0']));
  });
  it('supports filenames with spaces without confusing equal filenames', () => {
    expect(referencedKeys('@封面 图.png ', refs)).toEqual(new Set(['asset:one']));
    expect(referencedKeys('@asset:two ', refs)).toEqual(new Set(['asset:two']));
  });
  it('keeps only references still present after deletion and includes knowledge', () => {
    expect(referencedKeys('查看 @knowledge:doc', refs)).toEqual(new Set(['knowledge:doc']));
    expect(readableReferences('查看 @knowledge:doc', refs)).toBe('查看 @工艺报价.pdf');
  });
});
