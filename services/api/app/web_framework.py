"""Pinned offline framework, embedded before authored styles and scripts."""
import base64
import hashlib
import re
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).with_name('web_frameworks') / 'bootstrap'
HASHES = {
    'bootstrap.min.css': 'sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB',
    'bootstrap.bundle.min.js': 'FKyoEForCGlyvwx9Hj09JcYn3nv7wiPVlz7YYwJrWVcXK/BmnVDxM+D2scQbITxI',
}

@lru_cache(maxsize=1)
def framework_block():
    resources = {}
    for name, expected in HASHES.items():
        data = (ROOT / name).read_bytes()
        if base64.b64encode(hashlib.sha384(data).digest()).decode() != expected:
            raise ValueError('网页框架资源校验失败：' + name)
        resources[name] = re.sub(r'/\*[#@] sourceMappingURL=.*?\*/|//# sourceMappingURL=.*', '', data.decode('utf-8'))
    # Preserve third-party notices in both the source bundle and exported HTML.
    license_text = '\n\n'.join((ROOT / name).read_text(encoding='utf-8') for name in ('LICENSE', 'POPPER-LICENSE.md')).replace('--', '—')
    block = '<!-- mx-web-framework:start -->\n' + f'<!-- {license_text} -->\n'
    block += '<style data-mx-framework="bootstrap-5.3.8">' + resources['bootstrap.min.css'] + '</style>\n'
    block += '<script data-mx-framework="bootstrap-5.3.8">' + resources['bootstrap.bundle.min.js'] + '</script>\n<!-- mx-web-framework:end -->'
    return block


def strip_web_framework(html):
    # Only the exact verified bundle is trusted; arbitrary marker contents
    # remain subject to normal SVG/content validation.
    return html.replace(framework_block(), '') if '<!-- mx-web-framework:start -->' in html else html


def apply_web_framework(html, framework=None):
    if framework in (None, 'none'): return html
    if framework != 'bootstrap': raise ValueError('不支持的网页样式框架')
    block = framework_block()
    html = strip_web_framework(html)
    head = re.search(r'<head(?:\s[^>]*)?>', html, re.I)
    if head: return html[:head.end()] + block + html[head.end():]
    doctype = re.match(r'\s*<!doctype[^>]*>', html, re.I)
    at = doctype.end() if doctype else 0
    return html[:at] + block + html[at:]
