import { describe, expect, it } from 'vitest';
import { pendingReferenceSelection, referenceTextChoices, referenceUrl, selectedReferenceEntries, type ReferenceSelection } from './references';
const card = { id: 'batch', status: 'pending', items: [{id:'one'}, {id:'two'}] } as ReferenceSelection;
describe('visual references', () => {
  it('only renders local verified image endpoints', () => {
    expect(referenceUrl('http://localhost:8765', '/api/references/abc/thumbnail')).toBe('http://localhost:8765/api/references/abc/thumbnail');
    expect(referenceUrl('', 'https://unverified.example/a.png')).toBe('');
    expect(referenceUrl('', '/api/references/../credentials/content')).toBe('');
  });
  it('preserves selected aspects and discards invented ids', () => {
    expect(selectedReferenceEntries(card, ['two', 'fake'], {two:['构图/信息层级']})).toEqual([{id:'two',aspects:['构图/信息层级']}]);
    expect(selectedReferenceEntries(card, ['one'])).toEqual([{id:'one',aspects:['造型语言']}]);
  });
  it('never reopens a historical or unfinished selection', () => {
    const message = {role:'assistant',status:'succeeded',referenceSelection:card};
    expect(pendingReferenceSelection([message])).toBe(card);
    expect(pendingReferenceSelection([message,{role:'user'}])).toBeUndefined();
    expect(pendingReferenceSelection([{...message,status:'running'}])).toBeUndefined();
  });
});

it('maps only unambiguous ordinals from the displayed batch', () => {
  expect(referenceTextChoices(card, '第2张的配色，第1张的排版')).toEqual([{id:'two',aspects:['色彩关系']},{id:'one',aspects:['排版字体']}]);
  for (const text of ['想要暖一点','第12张','第0张','第2张或者第1张','不要第2张']) expect(referenceTextChoices(card, text)).toEqual([]);
});
