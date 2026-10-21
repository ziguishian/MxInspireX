"""Compact placement of automatically generated output next to existing work."""
from typing import Any
from math import floor, isfinite
import re

NODE_WIDTH = 300
GAP = 48
MAX_ROW_WIDTH = 1200


def requested_media_ratio(params):
    def ratio(width, height):
        w, h = float(width), float(height)
        return w / h if w > 0 and h > 0 and isfinite(w / h) else None

    size = re.fullmatch(r'\s*(\d+)\s*[x×]\s*(\d+)\s*', str(params.get('size') or ''), re.I)
    if size and (value := ratio(*size.groups())):
        return value
    if all(isinstance(params.get(k), (int, float)) and not isinstance(params[k], bool) for k in ('width', 'height')):
        if value := ratio(params['width'], params['height']):
            return value
    for key in ('aspectRatio', 'aspect_ratio', 'aspect'):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*', str(params.get(key) or ''))
        if match and (value := ratio(*match.groups())):
            return value
    return None


def canvas_node_kind(data: dict[str, Any]) -> str:
    """Keep the server-side layout kind in lockstep with ``nodeSizing.ts``."""
    asset = data.get('asset') or {}
    if data.get('kind') == 'cad':
        return 'cad'
    mime = str(asset.get('mime') or '')
    for kind in ('image', 'video', 'audio'):
        if mime.startswith(kind + '/'):
            return kind
    if str(asset.get('pathRelative') or '').lower().rsplit('.', 1)[-1] in {'glb', 'gltf', 'obj', 'fbx', 'stl'}:
        return '3d'
    return str(data.get('kind') or 'text')


def node_preview_size(data):
    """Match renderer frame limits; source asset dimensions are not resized."""
    asset = data.get('asset') or {}
    kind = canvas_node_kind(data)
    saved = data.get('previewSize') or (data.get('htmlPreviewSize') if kind == 'html' else None) or {}
    if not isinstance(saved, dict):
        saved = {}
    if kind == 'html':
        width, height, min_width, min_height = 960, 640, 320, 240
    else:
        large_media = data.get('previewSizingVersion') == 2 and kind in {'image', 'video', 'upload'}
        width = 720 if large_media else 360 if kind == 'text' else 220 if kind == 'audio' else NODE_WIDTH
        ratio = 6 / 5 if kind == 'text' else 8 / 5 if kind == 'audio' else 1 if kind == '3d' else 16 / 9
        params = data.get('params') if isinstance(data.get('params'), dict) else (asset.get('metadata') or {}).get('params') or {}
        requested_ratio = requested_media_ratio(params)
        if requested_ratio:
            ratio = requested_ratio
        # The renderer always uses the decoded source ratio for final image and
        # video frames. Reading both imageOutput and legacy metadata keeps a
        # node from being placed using a stale, letterboxed preview height.
        metadata = asset.get('metadata') or {}
        output = metadata.get('imageOutput') or {}
        w, h = output.get('width', metadata.get('width')), output.get('height', metadata.get('height'))
        if kind in {'image', 'video'} and not (data.get('generating') and requested_ratio) and all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) and v > 0 for v in (w, h)):
            ratio = w / h
        if large_media:
            width = min(width, 1080 * ratio)
        height = min(1080 if large_media else 440, max(120, width / ratio))
        min_width, min_height = (220, 90) if kind == 'audio' else (180, 150) if kind == '3d' else (160, 120) if kind in {'image', 'video', 'upload'} else (180, 120)

    def clamp(value, fallback, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            value = fallback
        return floor(min(high, max(low, value)) + .5)

    if kind in {'image', 'video'}:
        # ``previewSize.height`` is intentionally ignored by the renderer for
        # media. Persisting it here would put the next node inside a portrait
        # image after the browser corrects the aspect ratio.
        saved_width = saved.get('width')
        has_saved_width = isinstance(saved_width, (int, float)) and not isinstance(saved_width, bool) and isfinite(saved_width)
        max_height = 1080 if large_media and not has_saved_width else 1440
        max_width = min(1920, max_height * ratio)
        min_width_for_ratio = max(min_width, min_height * ratio)
        if max_width < min_width_for_ratio:
            final_width = floor(max_width + .5)
        else:
            final_width = clamp(saved_width, width, min_width_for_ratio, max_width)
        final_height = floor(final_width / ratio + .5)
        if final_height > max_height:
            final_height = max_height
            final_width = floor(final_height * ratio + .5)
        return {'width': final_width, 'height': final_height}
    return {'width': clamp(saved.get('width'), width, min_width, 1920), 'height': clamp(saved.get('height'), height, min_height, 1440)}


def node_width(node):
    data = node.get('data') or {}
    return node_preview_size(data)['width']


def text_content_height(data: dict[str, Any]) -> float:
    """Conservatively reserve the height of a growing Markdown text node.

    Canvas text is deliberately content-sized in the renderer.  The canvas
    store cannot measure its DOM, so this mirrors the typography closely and
    leaves a small safety margin until the renderer's exact measurement can
    perform its final automatic collision repair.
    """
    if canvas_node_kind(data) != 'text':
        return 0
    content = str(data.get('text') or data.get('summary') or '').strip()
    if not content:
        return 0
    style = data.get('textStyle') if isinstance(data.get('textStyle'), dict) else {}
    raw_font_size = style.get('fontSize', 15)
    font_size = float(raw_font_size) if isinstance(raw_font_size, (int, float)) and not isinstance(raw_font_size, bool) and isfinite(raw_font_size) else 15
    font_size = min(28, max(12, font_size))
    width = node_preview_size(data)['width']
    # CanvasMarkdown uses 1.5em horizontal padding and permits a break at any
    # character. A CJK glyph is the widest normal character at this font size.
    characters_per_line = max(8, int((width - font_size * 3) / font_size))
    height = font_size * 2.8  # 1.4em top + bottom padding
    lines = content.splitlines() or ['']
    in_list = False
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            height += font_size * .85
            in_list = False
            continue
        heading = re.match(r'^(#{1,3})\s+(.*)$', line)
        bullet = re.match(r'^(?:[-*+]\s+|\d+[.)]\s+)(.*)$', line)
        if heading:
            level, body = len(heading.group(1)), heading.group(2)
            scale = 1.55 if level == 1 else 1.2 if level == 2 else 1.08
            line_count = max(1, (len(body) + max(6, int(characters_per_line / scale)) - 1) // max(6, int(characters_per_line / scale)))
            height += line_count * font_size * scale * 1.4
            height += font_size * (1.6 + (.45 if level == 2 else .45))
            in_list = False
            continue
        body = bullet.group(1) if bullet else line
        line_count = max(1, (len(body) + characters_per_line - 1) // characters_per_line)
        height += line_count * font_size * 1.8
        # Paragraphs have .85em top/bottom margins; compact list entries have
        # .35em.  This intentionally rounds upward for nested Markdown.
        height += font_size * (.7 if bullet else 1.7)
        in_list = bool(bullet)
    # Browser font metrics and Markdown tables/quotes can be modestly taller
    # than plain text. The extra margin protects the next automatic node.
    return floor(height * 1.12 + 16)


def node_height(node: dict[str, Any]) -> float:
    data = node.get('data') or {}
    notes = data.get('productionNotes') if isinstance(data.get('productionNotes'), list) else []
    # Match the visible note block closely enough that subsequent automatic
    # outputs never overlap it. Long notes wrap under the media frame.
    note_height = 0
    if notes:
        characters_per_line = max(18, int(node_preview_size(data)['width'] / 12))
        lines = sum(max(1, (len(str(note)) + characters_per_line - 1) // characters_per_line) for note in notes[:8])
        note_height = 30 + lines * 18
    preview_height = node_preview_size(data)['height']
    text_height = text_content_height(data)
    return max(preview_height, text_height) + 40 + note_height


def nodes_colliding(nodes: list[dict[str, Any]], incoming: dict[str, Any], point: dict[str, float]) -> list[dict[str, Any]]:
    """Return every node whose visible footprint violates the required gap."""
    width, height = node_width(incoming), node_height(incoming)
    return [node for node in nodes
            if isinstance(node.get('position'), dict)
            and all(isinstance(node['position'].get(axis), (int, float)) and isfinite(node['position'][axis]) for axis in ('x', 'y'))
            and point['x'] < node['position']['x'] + node_width(node) + GAP
            and point['x'] + width + GAP > node['position']['x']
            and point['y'] < node['position']['y'] + node_height(node) + GAP
            and point['y'] + height + GAP > node['position']['y']]


def nearest_open_position(nodes: list[dict[str, Any]], incoming: dict[str, Any], preferred: dict[str, float]) -> dict[str, float]:
    """Find a deterministic, collision-free position nearest to ``preferred``.

    Candidate coordinates are formed from every occupied right/bottom edge,
    which means at least the right of the furthest node is always available.
    Unlike a fixed grid, this remains safe for portrait images and long text.
    """
    valid_nodes = [node for node in nodes if isinstance(node.get('position'), dict)
                   and all(isinstance(node['position'].get(axis), (int, float)) and isfinite(node['position'][axis]) for axis in ('x', 'y'))]
    target = {'x': float(preferred.get('x', 40)), 'y': float(preferred.get('y', 40))}
    if not nodes_colliding(valid_nodes, incoming, target):
        return target
    xs = {target['x']}
    ys = {target['y']}
    for node in valid_nodes:
        xs.update({float(node['position']['x']), float(node['position']['x']) + node_width(node) + GAP})
        ys.update({float(node['position']['y']), float(node['position']['y']) + node_height(node) + GAP})
    # A final outer column gives a finite proof of availability even when every
    # intersection of existing row/column edges is occupied.
    xs.add(max(xs) + GAP)
    candidates = ({'x': x, 'y': y} for y in ys for x in xs)
    available = [candidate for candidate in candidates if not nodes_colliding(valid_nodes, incoming, candidate)]
    if available:
        return min(available, key=lambda candidate: (abs(candidate['x'] - target['x']) + abs(candidate['y'] - target['y']), candidate['y'], candidate['x']))
    # Defensive fallback for malformed external nodes. It is horizontally past
    # all valid footprints and therefore cannot intersect any of them.
    return {'x': max(float(node['position']['x']) + node_width(node) + GAP for node in valid_nodes), 'y': target['y']}


def next_output_position(nodes: list[dict[str, Any]], incoming=None) -> dict[str, float]:
    nodes = [node for node in nodes if isinstance(node.get('position'), dict)
             and all(isinstance(node['position'].get(axis), (int, float))
                     and isfinite(node['position'][axis]) for axis in ('x', 'y'))]
    if not nodes:
        return {'x': 40.0, 'y': 40.0}
    last = nodes[-1]
    x, y = float(last['position']['x']), float(last['position']['y'])
    width, height = node_width(incoming or {}), node_height(incoming or {})
    # Only neighbours form a row. An unrelated node thousands of pixels away
    # at the same y must not send the next output back to that distant column.
    row, group, right_edge = [], [], float('-inf')
    for node in sorted((n for n in nodes if abs(n['position']['y'] - y) < 1), key=lambda n: n['position']['x']):
        if group and node['position']['x'] > right_edge + GAP * 2:
            if any(n is last for n in group):
                row = group
                break
            group, right_edge = [], float('-inf')
        group.append(node)
        right_edge = max(right_edge, node['position']['x'] + node_width(node))
    row = row or group
    row_left = min(n['position']['x'] for n in row)

    def collisions(point):
        return nodes_colliding(nodes, incoming or {}, point)

    right = {'x': x + node_width(last) + GAP, 'y': y}
    row_width = 2400 if (incoming or {}).get('data', {}).get('previewSizingVersion') == 2 else MAX_ROW_WIDTH
    wrap = len(row) >= 3 or right['x'] + width - row_left > row_width
    if not wrap and not collisions(right):
        return right

    # Try directly below the previous node before pushing a blocked right-hand
    # slot all the way past a tall obstacle. Rows wrap using their real height.
    below = {'x': x, 'y': y + node_height(last) + GAP}
    below_row = {'x': row_left, 'y': max(n['position']['y'] + node_height(n) for n in row) + GAP}
    candidates = [below_row, below] if wrap else [below, below_row]
    if not collisions(candidates[0]):
        return candidates[0]
    resolved = []
    for start in candidates:
        candidate = dict(start)
        while blocked := collisions(candidate):
            candidate['y'] = max(n['position']['y'] + node_height(n) for n in blocked) + GAP
        resolved.append(candidate)
    return nearest_open_position(nodes, incoming or {}, min(resolved, key=lambda point: abs(point['x'] - x) + abs(point['y'] - y)))
