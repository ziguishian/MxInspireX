const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
export const replyCharacters = (text: string) => Array.from(segmenter.segment(text), item => item.segment);

/** Buffer provider snapshots; rendering follows its own clock, not packet timing. */
export class ReplyTypewriter {
  characters: string[] = [];
  position = 0;
  private credit = 0;
  private deliveryAt?: number;
  private incomingRate = 48;
  get pending() { return this.position < this.characters.length; }

  update(characters: string[], immediate = false, now = performance.now()) {
    const wasPending = this.pending;
    let shared = 0;
    while (shared < this.position && shared < characters.length && this.characters[shared] === characters[shared]) shared++;
    const added = characters.length - this.characters.length;
    const appended = added > 0 && this.characters.every((character, index) => character === characters[index]);
    if (immediate || !appended && shared < this.position) {
      this.deliveryAt = undefined; this.incomingRate = 48;
    } else if (appended) {
      const elapsed = this.deliveryAt === undefined ? 0 : now - this.deliveryAt;
      // Match slower upstream output so small packets do not repeatedly drain
      // at a fast rate and then pause while waiting for the next packet.
      if (elapsed >= 80 && elapsed <= 2000) this.incomingRate = Math.max(12, Math.min(60, added * 1000 / elapsed));
      else if (elapsed > 2000) this.incomingRate = 48;
      this.deliveryAt = now;
    }
    if (shared < this.position || !wasPending) this.credit = 0;
    this.characters = characters;
    this.position = immediate ? characters.length : shared;
  }

  advance(elapsedMs: number) {
    if (!this.pending) return;
    // Small chunks print one character at a time. Large backlogs catch up
    // gradually instead of adding a long artificial wait after completion.
    const perSecond = Math.max(this.incomingRate, Math.min(240, (this.characters.length - this.position) / 2));
    this.credit += Math.max(0, Math.min(50, elapsedMs)) * perSecond / 1000;
    const count = Math.floor(this.credit);
    this.credit -= count;
    this.position = Math.min(this.characters.length, this.position + count);
    if (!this.pending) this.credit = 0;
  }

  finish() { this.position = this.characters.length; this.credit = 0; }
}
