import { describe, expect, it } from 'vitest';
import { generalDefaults, readGeneralSettings, shouldSendMessage } from './generalSettings';

describe('general preferences', () => {
  it('defaults to Enter sending while preserving an existing shortcut preference', () => {
    expect(readGeneralSettings({ getItem: () => null }).sendWithEnter).toBe(true);
    expect(readGeneralSettings({ getItem: () => '{"sendWithEnter":false}' }).sendWithEnter).toBe(false);
  });
  it('restores only known boolean preferences and tolerates damaged storage', () => {
    expect(readGeneralSettings({ getItem: () => '{' })).toEqual(generalDefaults);
    expect(readGeneralSettings({ getItem: () => { throw Error('denied'); } })).toEqual(generalDefaults);
    expect(readGeneralSettings({ getItem: () => JSON.stringify({ notifications: false, sendWithEnter: true, restoreProject: 'false', unknown: true }) }))
      .toEqual({ ...generalDefaults, notifications: false, sendWithEnter: true });
  });
  const enter = { key: 'Enter', ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, isComposing: false };
  it('supports both platforms and keeps composition and newline shortcuts safe', () => {
    expect(shouldSendMessage(enter, false)).toBe(false);
    expect(shouldSendMessage(enter, true)).toBe(true);
    expect(shouldSendMessage({ ...enter, ctrlKey: true }, false)).toBe(true);
    expect(shouldSendMessage({ ...enter, metaKey: true }, false)).toBe(true);
    for (const mode of [true, false]) for (const modifier of ['shiftKey', 'altKey', 'isComposing']) {
      expect(shouldSendMessage({ ...enter, ctrlKey: true, [modifier]: true }, mode)).toBe(false);
    }
  });
});
