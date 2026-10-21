import MarkdownIt from 'markdown-it';

// Replies are untrusted model output. Parse Markdown without enabling raw HTML.
const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });
const validateLink = markdown.validateLink.bind(markdown);
markdown.validateLink = (url) => validateLink(url) && /^(?:https?:\/\/|mailto:|#)/i.test(url);

markdown.renderer.rules.link_open = (tokens, index, options, _env, renderer) => {
  const token = tokens[index];
  if (!String(token.attrGet('href') || '').startsWith('#')) {
    token.attrSet('target', '_blank');
    token.attrSet('rel', 'noopener noreferrer');
  }
  return renderer.renderToken(tokens, index, options);
};

// Media outputs belong on the canvas. Keep image references usable without
// automatically fetching model-supplied URLs while the reply is streaming.
markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
  const token = tokens[index];
  const label = markdown.utils.escapeHtml(renderer.renderInlineAsText(token.children || [], options, env) || '查看图片');
  const url = String(token.attrGet('src') || '');
  if (!markdown.validateLink(url)) return label;
  return `<a href="${markdown.utils.escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
};

markdown.renderer.rules.table_open = () => '<div class="agent-markdown-table" role="region" aria-label="表格，可横向滚动" tabindex="0"><table>\n';
markdown.renderer.rules.table_close = () => '</table></div>\n';

/** Re-render the latest snapshot; incomplete fences close safely during streaming. */
export function renderAgentMarkdown(content: string, inline = false): string {
  return inline ? markdown.renderInline(content) : markdown.render(content);
}
