import { describe, expect, it, vi } from 'vitest';
import { CREATOR_ENCOURAGEMENT, CREATOR_POEM, printConsoleEasterEgg } from './consoleEasterEgg';

describe('console easter egg', () => {
  it('prints the poem before a separate encouragement message', () => {
    const write = vi.fn();
    printConsoleEasterEgg(write);

    expect(write).toHaveBeenCalledTimes(3);
    expect(write.mock.calls[1]?.[0]).toBe(`%c${CREATOR_POEM}`);
    expect(CREATOR_POEM.split('\n')).toHaveLength(4);
    expect(write.mock.calls[2]?.[0]).toContain(CREATOR_ENCOURAGEMENT);
    expect(write.mock.calls.every(call => String(call[0]).startsWith('%c') && String(call[1]).length > 20)).toBe(true);
  });
});
