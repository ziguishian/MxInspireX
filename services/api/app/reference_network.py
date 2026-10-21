"""Bounded public-page extraction. Only verified image bytes become candidates."""
import json
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .reference_library import ReferenceError
from .research import safe_source_uri, ResearchImportError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def image_source_key(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname and parsed.hostname.endswith('.behance.net') and '/project_modules/' in parsed.path:
        return parsed.hostname + '/' + parsed.path.rsplit('/', 1)[-1]
    if parsed.hostname and parsed.hostname.endswith('.imgix.net'):
        return parsed.hostname + parsed.path
    return url


def fetch_public(url, *, limit=25 * 1024 * 1024, cancelled=lambda: False):
    deadline = time.monotonic() + 30
    opener = urllib.request.build_opener(NoRedirect())
    for _ in range(5):
        if cancelled() or time.monotonic() > deadline:
            raise ReferenceError('参考采集已取消')
        try:
            url = safe_source_uri(url)
        except ResearchImportError as error:
            raise ReferenceError(str(error)) from error
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 LangjuReferenceLibrary/1.0', 'Accept': 'image/*,text/html,application/json;q=0.8'})
        try:
            response = opener.open(request, timeout=12)
        except urllib.error.HTTPError as error:
            if error.code in {301, 302, 303, 307, 308} and error.headers.get('Location'):
                url = urllib.parse.urljoin(url, error.headers['Location'])
                error.close()
                continue
            raise ReferenceError(f'来源无法读取（HTTP {error.code}）') from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ReferenceError('来源连接失败，请更换公开作品页或上传图片') from error
        with response:
            data = bytearray()
            while True:
                if cancelled() or time.monotonic() > deadline:
                    raise ReferenceError('参考采集已取消')
                chunk = response.read(min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise ReferenceError('来源文件过大')
            return bytes(data), response.headers.get('Content-Type', '').split(';')[0], url
    raise ReferenceError('来源重定向次数过多')


class PageImages(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.images, self.title, self.author = url, [], '', ''
        self.in_title = False
        self.in_json = False
        self.json_text = ''

    def add(self, url):
        if isinstance(url, dict):
            url = url.get('url') or url.get('contentUrl')
        if isinstance(url, str) and url.strip():
            absolute = urllib.parse.urljoin(self.url, url.strip())
            if absolute.startswith(('http://', 'https://')) and absolute not in self.images:
                self.images.append(absolute)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.in_title = self.in_title or tag == 'title'
        if tag == 'meta':
            key = values.get('property') or values.get('name')
            if key in {'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'}:
                self.add(values.get('content'))
            if key == 'og:title':
                self.title = values.get('content') or self.title
            if key in {'author', 'article:author'}:
                self.author = values.get('content') or ''
        if tag == 'img':
            self.add(values.get('data-src') or values.get('src'))
        if tag == 'script' and values.get('type') == 'application/ld+json':
            self.in_json, self.json_text = True, ''

    def handle_data(self, data):
        if self.in_title and not self.title:
            self.title += data.strip()
        if self.in_json:
            self.json_text += data

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'script' and self.in_json:
            self.in_json = False
            try:
                self._json(json.loads(self.json_text))
            except (ValueError, RecursionError):
                pass

    def _json(self, value):
        if isinstance(value, list):
            for item in value:
                self._json(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {'image', 'thumbnailUrl', 'contentUrl'}:
                    for image in item if isinstance(item, list) else [item]:
                        self.add(image)
                elif isinstance(item, (dict, list)):
                    self._json(item)


def import_page(library, url, *, saved=True, metadata=None, limit=6, cancelled=lambda: False):
    deadline = time.monotonic() + 75
    parent_cancelled = cancelled
    cancelled = lambda: parent_cancelled() or time.monotonic() > deadline
    body, mime, source = fetch_public(url, cancelled=cancelled)
    metadata = dict(metadata or {})
    metadata.update(sourceType='web', sourceUrl=source, sourceGroup=source)
    if mime.startswith('image/'):
        item = library.add(body, urllib.parse.urlsplit(source).path.rsplit('/', 1)[-1] or '网络参考', metadata={**metadata, 'imageUrl': source}, saved=saved)
        return {'items': [item], 'errors': []}
    if 'html' not in mime and not body.lstrip().startswith((b'<', b'<!')):
        raise ReferenceError('来源不是可解析的作品页面或图片')
    page = PageImages(source)
    page.feed(body.decode('utf-8', errors='replace'))
    # Behance cover crops duplicate the artwork. Prefer its full project images.
    if urllib.parse.urlsplit(source).hostname in {'www.behance.net', 'behance.net'}:
        modules = [image for image in page.images if '/project_modules/' in image]
        if modules:
            page.images = modules
    metadata.setdefault('title', page.title[:300] or '网络视觉参考')
    metadata.setdefault('author', page.author)
    items, errors, seen, image_sources = [], [], set(), set()
    for image in page.images[:18]:
        if len(items) >= min(12, limit) or cancelled():
            break
        key = image_source_key(image)
        if key in image_sources:
            continue
        try:
            content, image_mime, final_url = fetch_public(image, cancelled=cancelled)
            if not image_mime.startswith('image/'):
                raise ReferenceError('地址没有返回图片')
            # Validate dimensions before persistence; icons never enter the library.
            import io
            from PIL import Image
            with Image.open(io.BytesIO(content)) as preview:
                if min(preview.size) < 160:
                    continue
            item = library.add(content, metadata['title'], metadata={**metadata, 'imageUrl': final_url}, saved=saved)
            image_sources.add(key)
            if item['id'] not in seen:
                items.append(item)
                seen.add(item['id'])
        except Exception as error:
            errors.append({'url': source, 'message': str(error)[:240]})
    if not items:
        errors.append({'url': source, 'message': '页面没有可读取的参考图片，可上传图片或更换公开来源'})
    return {'items': items, 'errors': errors[:8]}
