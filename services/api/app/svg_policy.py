"""Server-owned permission for newly authored SVG, independent of Skill text."""
import html
import json
import re
from urllib.parse import unquote

ERROR = 'SVG 绘图已全局禁用。静态视觉产物请使用 generate_image，文案与制作说明按需以文字交付；不得通过批量生成、内嵌 SVG、文本文件或旧 SVG 资产复用来绕过。当前不提供 SVG 制作稿，不要要求用户开启 SVG 或承诺矢量交付。'


def configured_mode(store, db=None):
    return 'off'


def derive_policy(mode=None, message=None, inherited=None):
    # A product-wide prohibition: legacy settings, explicit requests and
    # previously pinned permissions cannot turn SVG authoring back on.
    return {'mode': 'off', 'allowed': False, 'reason': 'globally_disabled'}


def task_policy(store, inputs, db=None):
    return derive_policy()


def ensure_task_policy(store, task_id):
    """Replace old permissions when tasks execute or recover."""
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT input_json FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('SVG 策略需要关联真实任务')
        from .task_policy import normalize_delivery_context
        original = json.loads(row[0] or '{}')
        inputs = normalize_delivery_context(original)
        policy = task_policy(store, inputs, db)
        inputs['svgPolicy'] = policy
        if inputs != original:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(inputs, ensure_ascii=False), task_id))
        return policy


def contains_svg(value):
    """Preflight SVG markup, data URLs and common dynamic SVG constructors.

    This is an output policy check, not a JavaScript security sandbox.
    Existing asset:// references and ordinary text discussing SVG are allowed.
    """
    if isinstance(value, dict):
        return any(contains_svg(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_svg(item) for item in value)
    if not isinstance(value, str):
        return False
    from .web_framework import strip_web_framework
    value = strip_web_framework(value)
    for _ in range(3):
        decoded = html.unescape(unquote(value))
        decoded = re.sub(r'\\(?:u00|x)([0-9a-f]{2})', lambda m: chr(int(m[1], 16)), decoded, flags=re.I)
        if decoded == value:
            break
        value = decoded
    return bool(re.search(r'<\s*(?:[\w-]+:)?svg\b|image/svg\+xml|www\.w3\.org/2000/svg|createElement\s*\(\s*[\x27\"]svg[\x27\"]', value, re.I))


def validate_tool(policy, name, arguments):
    if name == 'canvas_create_svg':
        raise ValueError(ERROR)
    if name in {'generate_image', 'image_edit'}:
        params = arguments.get('params')
        params = params if isinstance(params, dict) else {}
        fmt = params.get('output_format' if name == 'generate_image' else 'format')
        if fmt is not None and str(fmt).strip().lower() not in {'', 'png', 'jpeg', 'jpg', 'webp'}:
            raise ValueError('图像输出格式只允许 PNG、JPEG 或 WebP；SVG 绘图已全局禁用。')
    # Text/HTML and generic node writes must not become an alternative SVG
    # authoring channel. Existing SVG asset IDs remain readable.
    if name in {'canvas_create_html', 'canvas_create_text', 'canvas_update_node', 'canvas_create_node'} and contains_svg(arguments):
        raise ValueError(ERROR)


def validate_asset_references(registry, project_id, task_id, name, args):
    """Run before receipt replay too: old successes do not grant permission."""
    if not task_id or not registry.asset_store:
        return
    ids = []
    if name == 'canvas_create_media':
        ids = [args.get('asset_id')]
    elif name == 'canvas_update_node':
        patch = args.get('patch')
        data = patch.get('data') if isinstance(patch, dict) else None
        ids = [data.get('assetId')] if isinstance(data, dict) else []
    elif name == 'export_deliverable':
        selected = set(args.get('node_ids') or [])
        slides = args.get('slides') if isinstance(args.get('slides'), list) else []
        nodes = [] if slides and not selected else [n for n in registry.canvas_store.load(project_id)['nodes']
            if (n['id'] in selected if selected else not n['data'].get('downloadable'))]
        if any(contains_svg(n['data'].get('html') or n['data'].get('text', '')) for n in nodes):
            raise ValueError(ERROR)
        ids = [n['data'].get('assetId') for n in nodes]
        ids += [asset_id for slide in slides if isinstance(slide, dict) and isinstance(slide.get('imageAssetIds'), list) for asset_id in slide['imageAssetIds']]
    for asset_id in filter(None, ids):
        asset = registry.asset_store.get_asset(project_id=project_id, asset_id=str(asset_id))
        if asset and (asset.get('mime') == 'image/svg+xml' or str(asset.get('absolutePath', '')).lower().endswith('.svg')):
            raise ValueError(ERROR)
