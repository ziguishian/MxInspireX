import { describe, expect, it } from 'vitest';
import { selectedSkillMentions, skillMentionQuery, skillReferences } from './skillMentions';
import { referenceSegments, readableReferences } from './references';
import { messageReferences } from './messageReferences';
import { resubmissionReferences } from './messageResubmission';
import { reactive } from 'vue';

const skill = { id: 'one', name: 'logo-suite', title: 'Logo 样机与品牌延展', version: 2 };
describe('# skill mentions', () => {
  it('opens at the caret for Chinese/English searches and preserves following text', () => {
    expect(skillMentionQuery('请用 #样机 后面的要求', 6)).toEqual({ query: '样机', start: 3, caret: 6 });
    expect(skillMentionQuery('#logo', 5)?.query).toBe('logo');
    expect(skillMentionQuery('请用#文旅', 5)?.query).toBe('文旅');
    expect(skillMentionQuery('#', 1)?.query).toBe('');
    for (const text of ['# 标题', '##', 'C#', 'https://github.com/repo#logo', '#skill:one ', '`#logo'])
      expect(skillMentionQuery(text, text.length)).toBeNull();
  });
  it('keeps file references, stable skill identities and surrounding text intact', () => {
    const text = '#skill:one 参考 @1 做样机';
    const refs = [...skillReferences([skill]), { key: 'file:0', token: '@1', label: '标志.png', kind: '图像', badge: '@1' }];
    expect(referenceSegments(text, refs).map(s => s.text).join('')).toBe(text);
    expect(readableReferences(text, refs)).toBe('#Logo 样机与品牌延展 参考 @标志.png 做样机');
    expect(selectedSkillMentions('#skill:one #skill:one', [skill, skill])).toEqual([skill]);
    expect(selectedSkillMentions('#skill:one-more 已删除原标签', [skill])).toEqual([]);
    expect(selectedSkillMentions('https://example.com/#skill:one', [skill])).toEqual([]);
    expect(selectedSkillMentions('请用#skill:one 做样机', [skill])).toEqual([skill]);
    expect(structuredClone(selectedSkillMentions('#skill:one', reactive([skill])))).toEqual([skill]);
  });
  it('renders historical labels from the submitted snapshot and removes deleted selections on resend', () => {
    const snapshot = { referencedSkills: [skill] }, text = '#skill:one 做样机';
    const refs = messageReferences({ text, projectId: 'project', apiBaseUrl: '', snapshot, assets: [], documents: [], nodes: [] });
    expect(refs[0].label).toBe(skill.title);
    expect(resubmissionReferences(text, '普通问题', snapshot, refs, {}).referencedSkills).toEqual([]);
    expect(resubmissionReferences(text, '#skill:one 换个材质', snapshot, refs, {}).referencedSkills).toEqual([skill]);
  });
});
