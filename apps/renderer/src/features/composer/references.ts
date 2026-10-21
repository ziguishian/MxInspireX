import type { ImageReferenceMode } from '../imageReferenceModes';

export type InlineReference = {
  key: string; token: string; aliases?: string[]; label: string; preview?: string; textContent?: string; kind: string; badge: string;
  assetId?: string; projectId?: string; nodeId?: string; referenceMode?: ImageReferenceMode;
};
export type ReferenceSegment = { text: string; reference?: InlineReference };
// Match complete known references, longest first. In particular, @1 must not
// consume the start of @12 or a filename. Original tokens survive DOM editing.
export function referenceSegments(text: string, references: InlineReference[]): ReferenceSegment[] {
  const candidates = references.flatMap(reference => [reference.token, ...(reference.aliases || [])].map(token => ({ token, reference }))).sort((a, b) => b.token.length - a.token.length);
  const result: ReferenceSegment[] = [];
  let start = 0, cursor = 0;
  while (cursor < text.length) {
    if (text[cursor] !== '@' && text[cursor] !== '#') { cursor++; continue; }
    if (text[cursor] === '#' && cursor > 0 && !/[\s（(，,：；。！？\u3400-\u9fff]/.test(text[cursor - 1])) { cursor++; continue; }
    const found = candidates.find(({ token }) => text.startsWith(token, cursor) && (!text[cursor + token.length] || /[\s，。！？、；：!?;,)）]/.test(text[cursor + token.length])));
    if (!found) { cursor++; continue; }
    if (cursor > start) result.push({ text: text.slice(start, cursor) });
    result.push({ text: found.token, reference: found.reference });
    cursor += found.token.length; start = cursor;
  }
  if (start < text.length) result.push({ text: text.slice(start) });
  return result;
}
export function referencedKeys(text: string, references: InlineReference[]) {
  return new Set(referenceSegments(text, references).flatMap(segment => segment.reference ? [segment.reference.key] : []));
}
export function readableReferences(text: string, references: InlineReference[]) {
  return referenceSegments(text, references).map(segment => segment.reference ? `${segment.reference.key.startsWith('skill:') ? '#' : '@'}${segment.reference.label}` : segment.text).join('');
}
