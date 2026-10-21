"""Local syntax guard only; no visual review, rewriting, or model calls."""
import re
from html.parser import HTMLParser


class _Styles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_style = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'style':
            self.in_style = True
        self.parts.extend(value for key, value in attrs if key == 'style' and value)

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.parts.append(data)


def validate_html_styles(html):
    parser = _Styles()
    parser.feed(html)
    # Ignore strings, comments and escaped characters before balancing syntax.
    tokens = re.compile(r'''/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|\\[\s\S]|[{}()\[\]]''')
    pairs = {')': '(', ']': '[', '}': '{'}
    for css in parser.parts:
        stack = []
        for match in tokens.finditer(css):
            token = match.group()
            if len(token) != 1:
                continue
            if token in '{([':
                stack.append(token)
            elif not stack or stack.pop() != pairs[token]:
                raise ValueError('HTML 的 CSS 括号未正确闭合，请修正样式语法后保存；无需重新生成图片。')
        if stack:
            raise ValueError('HTML 的 CSS 括号未正确闭合，请修正样式语法后保存；无需重新生成图片。')
