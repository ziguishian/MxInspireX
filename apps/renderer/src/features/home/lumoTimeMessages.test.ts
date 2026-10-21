import { describe, expect, it } from 'vitest';
import { timedLumoMessage, timedLumoStorageKey } from './lumoTimeMessages';

function localDate(hour: number, minute: number) {
  return new Date(2026, 8, 18, hour, minute, 0);
}

describe('timed 小居 messages', () => {
  it('prioritizes the 4:42 easter egg over the generic late-night reminder', () => {
    expect(timedLumoMessage(localDate(4, 42))?.id).toBe('cosmic-0442');
  });

  it('offers a quiet reminder during the rest of the late night', () => {
    expect(timedLumoMessage(localDate(2, 10))).toMatchObject({ id: 'late-night', reaction: 'calm' });
  });

  it('only speaks at configured daytime moments', () => {
    expect(timedLumoMessage(localDate(13, 37))?.id).toBe('creative-1337');
    expect(timedLumoMessage(localDate(13, 38))).toBeNull();
  });

  it('uses a once-per-day storage key', () => {
    const date = localDate(23, 42);
    const message = timedLumoMessage(date)!;
    expect(timedLumoStorageKey(message, date)).toBe('langjuart.lumoTimedMessage.save-2342.2026-09-18');
  });
});
