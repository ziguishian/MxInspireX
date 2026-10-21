import { describe, expect, it } from 'vitest';
import { ReplyTypewriter, replyCharacters } from './replyTypewriter';

describe('buffered reply typing', () => {
  const shown = (buffer: ReplyTypewriter) => buffer.characters.slice(0, buffer.position).join('');
  it('reveals a burst on its own clock and keeps typing through later snapshots', () => {
    const buffer = new ReplyTypewriter();
    buffer.update(replyCharacters('你好，这是分批返回的回复。'));
    expect(shown(buffer)).toBe('');
    buffer.advance(22); expect(shown(buffer)).toBe('你');
    buffer.advance(22); expect(shown(buffer)).toBe('你好');
    buffer.update(replyCharacters('你好，这是分批返回的回复。现在继续。'));
    expect(shown(buffer)).toBe('你好');
    for (let i = 0; i < 100; i++) buffer.advance(22);
    expect(shown(buffer)).toBe('你好，这是分批返回的回复。现在继续。');
    expect(buffer.pending).toBe(false);
  });
  it('never splits emoji, surrogate pairs or combining accents', () => {
    const units = replyCharacters('你👩🏽‍💻🇨🇳e\u0301好');
    expect(units).toEqual(['你', '👩🏽‍💻', '🇨🇳', 'e\u0301', '好']);
    const buffer = new ReplyTypewriter(); buffer.update(units);
    for (let i = 1; i <= units.length; i++) { buffer.advance(21); expect(shown(buffer)).toBe(units.slice(0, i).join('')); }
  });
  it('paces slow upstream packets instead of repeatedly printing fast then pausing', () => {
    const buffer = new ReplyTypewriter();
    buffer.update(replyCharacters('一二三四五六'), false, 0);
    buffer.finish();
    buffer.update(replyCharacters('一二三四五六七八九十十一'), false, 300);
    buffer.advance(25); expect(shown(buffer)).toBe('一二三四五六');
    buffer.advance(25); expect(shown(buffer)).toBe('一二三四五六七');
    buffer.advance(50); expect(shown(buffer)).toBe('一二三四五六七八');
  });
  it('keeps historical text visible and animates only new content on reconnection', () => {
    const buffer = new ReplyTypewriter();
    buffer.update(replyCharacters('已有内容'), true);
    buffer.update(replyCharacters('已有内容'));
    expect(shown(buffer)).toBe('已有内容');
    buffer.update(replyCharacters('已有内容，继续'));
    expect(shown(buffer)).toBe('已有内容');
    buffer.advance(22); expect(shown(buffer)).toBe('已有内容，');
  });
  it('reconciles a corrected final answer and immediately displays stop/error messages', () => {
    const buffer = new ReplyTypewriter();
    buffer.update(replyCharacters('初稿内容'), true);
    buffer.update(replyCharacters('初稿已修正'));
    expect(shown(buffer)).toBe('初稿');
    buffer.advance(22); expect(shown(buffer)).toBe('初稿已');
    buffer.update(replyCharacters('已停止生成。'), true);
    expect(shown(buffer)).toBe('已停止生成。'); expect(buffer.pending).toBe(false);
  });
  it('catches up with large batches gradually and does not jump after a stalled frame', () => {
    const buffer = new ReplyTypewriter(); buffer.update(replyCharacters('长'.repeat(2000)));
    buffer.advance(10000); expect(buffer.position).toBeLessThanOrEqual(12);
    for (let i = 0; i < 1500; i++) buffer.advance(16);
    expect(buffer.pending).toBe(false);
    buffer.update(replyCharacters('长'.repeat(2000) + '下一句'));
    buffer.finish(); expect(buffer.pending).toBe(false);
  });
});
