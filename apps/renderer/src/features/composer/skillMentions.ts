import type { SkillSummary } from '@contracts/skills';
import { referencedKeys, type InlineReference } from './references';

export type SkillMention = Pick<SkillSummary, 'id' | 'name' | 'title' | 'version'>;
export const skillToken = (id: string) => `#skill:${id}`;

// A standalone # opens the picker; URLs, C#, headings and existing tokens do not.
export function skillMentionQuery(text: string, caret: number) {
  const match = text.slice(0, caret).match(/(?:^|[\s（(，,：；。！？\u3400-\u9fff])#([^\s#:`]*)$/u);
  return match ? { query: match[1], start: caret - match[1].length - 1, caret } : null;
}

export function skillReferences(skills: SkillMention[]): InlineReference[] {
  return skills.map(skill => ({ key: `skill:${skill.id}`, token: skillToken(skill.id), label: skill.title,
    kind: `Skill · v${skill.version}`, badge: '#', textContent: `${skill.title}\n${skill.name} · v${skill.version}` }));
}

export function selectedSkillMentions(text: string, skills: SkillMention[]): SkillMention[] {
  const keys = referencedKeys(text, skillReferences(skills));
  return skills.filter((skill, index) => keys.has(`skill:${skill.id}`) && skills.findIndex(s => s.id === skill.id) === index)
    .map(({ id, name, title, version }) => ({ id, name, title, version }));
}
