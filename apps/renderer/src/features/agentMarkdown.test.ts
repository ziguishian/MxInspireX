import { describe, expect, it } from 'vitest';
import { renderAgentMarkdown } from './agentMarkdown';
import { canvasReply } from '../designPresentation';

describe('Agent Markdown replies', () => {
  it('renders headings, emphasis, rules, nested lists, quotes and tables', () => {
    const html = renderAgentMarkdown('## 设计方案\n\n**重点**、*说明*、~~旧版~~\n\n---\n\n1. 主体\n   - 配色\n\n> 引用说明\n\n| 项目 | 内容 |\n| --- | --- |\n| 风格 | 简洁 |');
    for (const tag of ['h2', 'strong', 'em', 's', 'hr', 'ol', 'ul', 'blockquote', 'table', 'th', 'td']) {
      expect(html).toMatch(new RegExp(`<${tag}(?:>|\\s)`));
    }
    expect(html).toContain('class="agent-markdown-table"');
    expect(html).not.toContain('## 设计方案');
  });

  it('preserves code and line breaks instead of stripping Markdown-like characters', () => {
    const html = renderAgentMarkdown('第一行\n第二行\n\n`**原样**`\n\n```html\n<div>## 标题</div>\n```');
    expect(html).toContain('第一行<br>\n第二行');
    expect(html).toContain('<code>**原样**</code>');
    expect(html).toContain('<pre><code class="language-html">&lt;div&gt;## 标题&lt;/div&gt;');
  });

  it('reparses growing snapshots and incomplete fenced code without losing text', () => {
    expect(renderAgentMarkdown('## 方案\n\n**完成')).toContain('完成');
    expect(renderAgentMarkdown('## 方案\n\n**完成**')).toContain('<strong>完成</strong>');
    expect(renderAgentMarkdown('```js\nconst n = 1;')).toContain('const n = 1;</code></pre>');
    expect(renderAgentMarkdown('```js\nconst n = 1;\n```\n\n已完成')).toContain('</pre>\n<p>已完成</p>');
  });

  it('escapes raw HTML and rejects executable, local and data URLs', () => {
    const html = renderAgentMarkdown('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[脚本](javascript:alert%281%29) [实体](javascript&#x3a;alert%281%29) [文件](file:///tmp/private) [数据](data:text/html,test) ![图片](data:image/png;base64,AAAA)');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toMatch(/<(?:script|img)\b/);
    expect(html).not.toContain('<a ');
  });

  it('creates safe reference links and does not automatically load media URLs', () => {
    const html = renderAgentMarkdown('[参考](https://example.com)\n\nhttps://example.org\n\n![预览](https://example.com/image.png)');
    expect(html).toContain('target="_blank" rel="noopener noreferrer"');
    expect(html).toContain('href="https://example.org"');
    expect(html).toContain('>预览</a>');
    expect(html).not.toContain('<img');
  });

  it('keeps generated media on the canvas and research citations in the reply', () => {
    const html = renderAgentMarkdown(canvasReply('## 完成\n\n![产物](https://example.com/output.png)\n\n参考 [来源](https://example.org/research)', true));
    expect(html).toContain('<h2>完成</h2>');
    expect(html).toContain('href="https://example.org/research"');
    expect(html).not.toContain('output.png');
  });

  it('renders formatting inside option labels without adding paragraph blocks', () => {
    expect(renderAgentMarkdown('**保留**构图', true)).toBe('<strong>保留</strong>构图');
  });
});
