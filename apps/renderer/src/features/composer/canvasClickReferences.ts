/** Canvas clicks remain reversible until the user starts using the composer. */
export function createCanvasClickReferences() {
  let before: string | undefined;
  let after: string | undefined;
  function confirm() { before = after = undefined; }
  return {
    record(previous: string, next: string) {
      if (previous === next) return;
      if (after !== previous) before = previous;
      after = next;
    },
    confirm,
    cancel(current: string) {
      // Never roll back edits made since the canvas inserted its references.
      const restored = current === after && before !== undefined ? before : current;
      confirm();
      return restored;
    },
  };
}
