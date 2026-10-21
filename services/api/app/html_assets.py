"""Embed explicitly chosen local raster assets without granting iframe API access."""
import base64
import re
from pathlib import Path

ASSET_REFERENCE = re.compile(r'asset://([A-Za-z0-9_-]+)')
RASTER_DATA = re.compile(r'data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+\Z')


def referenced_image_ids(source):
    return list(dict.fromkeys(ASSET_REFERENCE.findall(str(source or ''))))


def prepare_html_assets(source, assets, project_id):
    ids = referenced_image_ids(source)
    if len(ids) > 12:
        raise ValueError('单个网页最多引用 12 张本地图片')
    embedded, total = {}, 0
    for asset_id in ids:
        asset = assets.get_asset(project_id=project_id, asset_id=asset_id) if assets else None
        if not asset:
            raise ValueError(f'网页引用图片不存在或不属于当前项目：{asset_id}')
        if asset.get('mime') not in {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}:
            raise ValueError('网页插图必须引用 PNG、JPEG、WebP 或 GIF 图片；不要用 SVG 替代生成插图')
        path = Path(asset['absolutePath'])
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('网页引用图片不可读取或超过 8 MB，请先缩小图片')
        content = path.read_bytes()
        total += len(content)
        if total > 16 * 1024 * 1024:
            raise ValueError('网页嵌入图片总大小不能超过 16 MB')
        embedded[asset_id] = f"data:{asset['mime']};base64,{base64.b64encode(content).decode()}"
    return {'htmlAssets': embedded, 'imageAssetIds': ids}


def resolve_html_assets(data):
    assets = data.get('htmlAssets') or {}
    def replace(match):
        url = assets.get(match[1], '')
        return url if isinstance(url, str) and RASTER_DATA.fullmatch(url) else match[0]
    return ASSET_REFERENCE.sub(replace, data.get('html', ''))
