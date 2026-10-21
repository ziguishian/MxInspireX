import { createTextVNode, h, type VNode } from 'vue';
import { renderAgentMarkdown } from './agentMarkdown';
import { replyCharacters } from './replyTypewriter';

type MarkdownPart = { key: string; start: number; end: number } & (
  { type: 'text'; value: string; characters: string[] } |
  { type: 'element'; tag: string; attributes: Record<string, string>; children: MarkdownPart[] }
);

/** Parse only when a server snapshot changes, never on each animation frame. */
export function typedMarkdown(content: string, inline = false) {
  const template = document.createElement('template');
  // The shared renderer escapes raw HTML and rejects executable/local URLs.
  template.innerHTML = renderAgentMarkdown(content, inline);
  const characters: string[] = [];
  function walk(node: Node, key: string): MarkdownPart | null {
    const start = characters.length;
    if (node.nodeType === Node.TEXT_NODE) {
      const value = node.textContent || '', units = replyCharacters(value);
      // Markdown's serialized block separators are not visible reply letters.
      if (node.parentNode === template.content && !value.trim()) return null;
      for (const unit of units) characters.push(unit);
      return { type: 'text', key, start, end: characters.length, value, characters: units };
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    const children = Array.from(element.childNodes).map((child, index) => walk(child, `${key}.${index}`)).filter((part): part is MarkdownPart => Boolean(part));
    // Give empty structural elements (br/hr) a position in the reveal order.
    if (characters.length === start) characters.push('\n');
    return { type: 'element', key, tag, start, end: characters.length,
      attributes: Object.fromEntries(Array.from(element.attributes).map(attr => [attr.name, attr.value])), children };
  }
  const parts = Array.from(template.content.childNodes).map((node, index) => walk(node, String(index))).filter((part): part is MarkdownPart => Boolean(part));
  return { parts, characters };
}

/** Stable VNode keys preserve completed paragraphs and update only their text. */
export function revealMarkdown(parts: MarkdownPart[], position: number): VNode[] {
  const visible: VNode[] = [];
  for (const part of parts) {
    if (part.start >= position) break;
    if (part.type === 'text') {
      const value = position >= part.end ? part.value : part.characters.slice(0, position - part.start).join('');
      const node = createTextVNode(value);
      node.key = part.key;
      visible.push(node);
    } else {
      visible.push(h(part.tag, { ...part.attributes, key: part.key }, revealMarkdown(part.children, position)));
    }
  }
  return visible;
}
