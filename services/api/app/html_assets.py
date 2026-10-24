"""Embed selected project media without granting iframe API access."""
import base64
import re
from pathlib import Path

ASSET_REFERENCE = re.compile(r'asset://([A-Za-z0-9_-]+)')
DELIVERY_REFERENCE = re.compile(r"deliverable://([^\s\"'<>()[\]{},;]+)")
RASTER_DATA = re.compile(r'data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+\Z')
MEDIA_DATA = re.compile(r'data:(?:image/(?:png|jpeg|webp|gif)|video/(?:mp4|webm)|audio/(?:mpeg|mp3|wav|x-wav|ogg|webm|mp4|aac|flac));base64,[A-Za-z0-9+/=]+\Z')
MEDIA_MIMES = {'video/mp4', 'video/webm', 'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/ogg', 'audio/webm', 'audio/mp4', 'audio/aac', 'audio/flac'}


def referenced_image_ids(source):
    return list(dict.fromkeys(ASSET_REFERENCE.findall(str(source or ''))))


def validate_html_slots(source, context, binding):
    """Only explicit content dependencies may become media slots; never guess IDs."""
    from .generation_inputs import planned_inputs
    ids = list(dict.fromkeys(DELIVERY_REFERENCE.findall(source)))
    if not ids and 'deliverable://' not in source: return []
    if context.get('taskSurface') == 'canvas_node':
        raise ValueError('节点网页不能使用未来交付占位引用')
    refs = {r['id'] for r in planned_inputs(context, binding.get('itemIds', []))
            if r['source'] == 'deliverable' and r.get('role') == 'content'}
    plan = context.get('designPlan') or {}
    media = {item['id'] for item in plan.get('deliverables', []) if item['kind'] in {'image', 'video', 'audio'}}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', id) or id not in refs or id not in media for id in ids) or 'deliverable://' in DELIVERY_REFERENCE.sub('', source):
        raise ValueError('网页媒体占位必须引用本项已声明的 content 媒体交付 ID（字母、数字、下划线或连字符）')
    return ids


def bind_html_slots(source, context, binding, nodes):
    ids = validate_html_slots(source, context, binding)
    scope = (context.get('designPlan') or {}).get('scopeId')
    resolved = {}
    for id in ids:
        candidates = [n['data'] for n in nodes if n.get('data', {}).get('deliveryBinding', {}).get('scopeId') == scope
                      and id in n['data']['deliveryBinding'].get('itemIds', [])]
        if len(candidates) != 1 or candidates[0].get('generating') or candidates[0].get('error') or not candidates[0].get('assetId'):
            raise ValueError('网页媒体尚未完成或来源不唯一：' + id)
        resolved[id] = 'asset://' + candidates[0]['assetId']
    return DELIVERY_REFERENCE.sub(lambda match: resolved[match[1]], source)


def prepare_html_assets(source, assets, project_id):
    if 'deliverable://' in source:
        raise ValueError('网页仍有未解析的媒体占位，不能作为完成产物保存')
    ids = referenced_image_ids(source)
    if len(ids) > 12:
        raise ValueError('单个网页最多引用 12 项本地媒体')
    embedded, total, image_total = {}, 0, 0
    images, videos, audio = [], [], []
    for asset_id in ids:
        asset = assets.get_asset(project_id=project_id, asset_id=asset_id) if assets else None
        if not asset:
            raise ValueError(f'网页引用媒体不存在或不属于当前项目：{asset_id}')
        mime = asset.get('mime')
        is_image = mime in {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}
        if not is_image and mime not in MEDIA_MIMES:
            raise ValueError('网页仅支持栅格图片、MP4/WebM 视频和常见音频；不接受 SVG 或其他文件')
        path = Path(asset['absolutePath'])
        limit = 8 if is_image else 32
        if not path.is_file() or path.stat().st_size > limit * 1024 * 1024:
            raise ValueError(f'网页引用媒体不可读取或超过 {limit} MB，请先缩小素材')
        content = path.read_bytes()
        total += len(content)
        if is_image: image_total += len(content)
        if image_total > 16 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise ValueError('网页嵌入图片总大小不能超过 16 MB，全部媒体不能超过 64 MB')
        embedded[asset_id] = f"data:{asset['mime']};base64,{base64.b64encode(content).decode()}"
        (images if is_image else videos if mime.startswith('video/') else audio).append(asset_id)
    return {'htmlAssets': embedded, 'imageAssetIds': images, 'mediaAssetIds': ids, 'videoAssetIds': videos, 'audioAssetIds': audio}


def resolve_html_assets(data):
    assets = data.get('htmlAssets') or {}
    def replace(match):
        url = assets.get(match[1], '')
        return url if isinstance(url, str) and MEDIA_DATA.fullmatch(url) else match[0]
    return ASSET_REFERENCE.sub(replace, data.get('html', ''))
