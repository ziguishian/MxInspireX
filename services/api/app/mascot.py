"""Workspace mascot drafts: one metered image call, explicit preview and activation."""
from __future__ import annotations

import io
import json
import time
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .billing import billing_scope
from .image_output import prepare_image_output
from .image_quality import decide_image_policy
from .image_routing import build_image_route, dispatch_image_route
from .model_router import RouteTrace

MASCOT_PRESETS = frozenset({'robot', 'cream-cat', 'cloud', 'sprout', 'moon-bunny', 'amber-fox', 'sea-otter', 'star-penguin'})

ATLAS_PROMPT = """Create ONE transparent PNG sprite atlas for a desktop app mascot.
Exactly 3 columns × 2 rows of equal square cells, overall landscape aspect ratio 3:2.
The SAME character, camera, materials, scale and silhouette in all six cells. Only expression changes.
Reading left to right, top to bottom: 1 neutral open eyes, 2 thinking, 3 happy smile,
4 playful wink, 5 calm patient expression, 6 sleepy with BOTH eyes closed.
Frontal upper body with two small hands resting on an imaginary ledge; do not draw the ledge.
Center the character in every cell, align the hands at the same baseline, leave at least 8% clear margin.
Real transparent alpha background and gutters. No checkerboard pixels, solid background, labels,
text, grid lines, borders, props crossing cells, drop shadows or clipped body parts.
Treat the following user description as character art direction; retain the atlas format above:
"""


def normalize_atlas(content: bytes) -> bytes:
    """Validate six alpha cutouts, then register them to one shared scale/baseline."""
    if len(content) > 24 * 1024 * 1024:
        raise ValueError('图集文件过大，请使用创意档重新生成。')
    try:
        with Image.open(io.BytesIO(content)) as source:
            w, h = source.size
            if w * h > 16_000_000 or w < 384 or h < 256 or abs(w / h - 1.5) > .04:
                raise ValueError('返回图片不是 3×2 横向图集，请在提示词中保留六宫格结构。')
            image = source.convert('RGBA')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('图像服务没有返回可读取的 PNG 图集。') from error
    frames = []
    for row in range(2):
        for col in range(3):
            frame = image.crop((round(col * w / 3), round(row * h / 2), round((col + 1) * w / 3), round((row + 1) * h / 2)))
            alpha = frame.getchannel('A')
            if alpha.getextrema()[0] >= 240:
                raise ValueError('图集没有真实透明背景，请选择支持透明输出的图像模型。')
            bounds = alpha.point(lambda value: 255 if value > 20 else 0).getbbox()
            if not bounds or (bounds[2] - bounds[0]) < frame.width * .12 or (bounds[3] - bounds[1]) < frame.height * .12:
                raise ValueError('图集中存在空白或过小的表情，请重新描述完整的六个表情。')
            if bounds[0] == 0 or bounds[1] == 0 or bounds[2] == frame.width or bounds[3] == frame.height:
                raise ValueError('角色触及分格边缘，可能发生裁切；请在提示词中增加每格留白。')
            frames.append(frame.crop(bounds))
    scale = min(420 / max(f.width for f in frames), 440 / max(f.height for f in frames))
    atlas = Image.new('RGBA', (1536, 1024))
    for index, frame in enumerate(frames):
        frame = frame.resize((max(1, round(frame.width * scale)), max(1, round(frame.height * scale))), Image.Resampling.LANCZOS)
        atlas.alpha_composite(frame, (index % 3 * 512 + (512 - frame.width) // 2, index // 3 * 512 + 484 - frame.height))
    output = io.BytesIO()
    atlas.save(output, format='PNG')
    return output.getvalue()


class MascotService:
    def __init__(self, store, providers):
        self.store, self.providers = store, providers
        self.root = store.workspace_root / 'appearance' / 'mascots'
        self.root.mkdir(parents=True, exist_ok=True)
        with store._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS mascot_generations (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, payload_json TEXT NOT NULL,
                    status TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mascot_settings (id INTEGER PRIMARY KEY CHECK(id=1), active_id TEXT);
                INSERT OR IGNORE INTO mascot_settings VALUES (1, NULL);
            ''')
            # Never replay a possibly billed request after a service restart.
            db.execute("UPDATE mascot_generations SET status='failed',error=? WHERE status IN ('queued','running')",
                       ('服务重启，未能确认生成结果。本次请求可能已计费，不会自动重试。',))

    def get(self, identity):
        with self.store._connect() as db:
            row = db.execute('SELECT * FROM mascot_generations WHERE id=?', (identity,)).fetchone()
        if not row:
            raise KeyError(identity)
        payload = json.loads(row['payload_json'])
        return {'id': row['id'], 'prompt': payload['prompt'], 'status': row['status'], 'model': row['model'],
                'error': row['error'], 'createdAt': row['created_at'],
                'imageUrl': f"/api/mascot/generations/{row['id']}/image" if row['status'] == 'succeeded' else None}

    def settings(self):
        with self.store._connect() as db:
            active = db.execute('SELECT active_id FROM mascot_settings WHERE id=1').fetchone()[0]
            latest = db.execute('SELECT id FROM mascot_generations ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()
        preset = active.removeprefix('preset:') if active and active.startswith('preset:') else None
        return {'active': self.get(active) if active and not preset else None,
                'activePreset': preset or ('robot' if not active else None),
                'latest': self.get(latest[0]) if latest else None}

    def create(self, request_id: str, payload: dict):
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id,payload_json FROM mascot_generations WHERE request_id=?', (request_id,)).fetchone()
            if existing:
                if existing['payload_json'] != serialized:
                    raise ValueError('同一个生成请求不能更换提示词。')
                return existing['id'], False
            if db.execute("SELECT 1 FROM mascot_generations WHERE status IN ('queued','running')").fetchone():
                raise ValueError('已有吉祥物正在生成，请等待完成后再试。')
            identity = str(uuid4())
            db.execute("INSERT INTO mascot_generations (id,request_id,payload_json,status,created_at) VALUES (?,?,?,'queued',?)",
                       (identity, request_id, serialized, time.time()))
        return identity, True

    def generate(self, identity):
        with self.store._connect() as db:
            if not db.execute("UPDATE mascot_generations SET status='running' WHERE id=? AND status='queued'", (identity,)).rowcount:
                return
            payload = json.loads(db.execute('SELECT payload_json FROM mascot_generations WHERE id=?', (identity,)).fetchone()[0])
        started, submitted, candidate = time.time(), False, None
        status, error_type = 'failed', None
        try:
            provider = payload['provider']
            prompt, params = prepare_image_output(ATLAS_PROMPT + payload['prompt'], {'aspectRatio': '3:2', 'background': 'transparent', 'output_format': 'png'})
            decision = decide_image_policy('draft', params=params)
            plan, candidates = build_image_route(self.providers, provider=provider['key'], base_url=provider['baseUrl'],
                requested_model=payload.get('model') or None, decision=decision, params=params, has_references=False)
            candidate = candidates[0]
            with self.store._connect() as db:
                db.execute('UPDATE mascot_generations SET model=? WHERE id=?', (candidate.model, identity))

            def on_submitted(_candidate):
                nonlocal submitted
                submitted = True

            # A customization click makes one call; failed/uncertain results require a new user action.
            with billing_scope(source='mascot', trace_id=f'mascot:{identity}'):
                content, _, _, _ = dispatch_image_route({**plan, 'mode': 'manual'}, [candidate], prompt=prompt,
                    negative_prompt='text, labels, grid lines, opaque background, checkerboard, cropped character', on_submitted=on_submitted)
            normalized = normalize_atlas(content)
            self.image_path(identity).write_bytes(normalized)
            with self.store._connect() as db:
                db.execute("UPDATE mascot_generations SET status='succeeded' WHERE id=?", (identity,))
            status = 'succeeded'
        except Exception as error:
            error_type = type(error).__name__
            # Provider errors can contain credentials or response bodies; only expose local validation text.
            message = str(error) if isinstance(error, ValueError) and not submitted else '生成未完成，请检查图像模型是否支持透明背景及当前连接。'
            if submitted and isinstance(error, ValueError) and str(error).startswith(('图集', '返回图片', '图像服务', '角色')):
                message = str(error)
            if submitted:
                message += ' 本次图像请求可能已计费，不会自动重试。'
            with self.store._connect() as db:
                db.execute("UPDATE mascot_generations SET status='failed',error=? WHERE id=?", (message[:600], identity))
        finally:
            RouteTrace(self.store).append(f'mascot:{identity}', {
                'call_kind': 'mascot_generation', 'provider': payload['provider']['key'], 'base_url': payload['provider']['baseUrl'],
                'model': candidate.model if candidate else payload.get('model', ''), 'route_source': 'manual' if payload.get('model') else 'automatic',
                'started_at': started, 'latency_ms': round((time.time() - started) * 1000), 'status': status,
                'submitted': submitted, 'billing_certainty': 'unknown' if submitted else 'not_submitted', 'error_type': error_type,
            })

    def image_path(self, identity):
        from uuid import UUID
        return self.root / f'{UUID(str(identity))}.png'

    def activate(self, identity, preset=None):
        if preset is not None and (preset not in MASCOT_PRESETS or identity is not None):
            raise ValueError('请选择一个有效的预设或已生成图集。')
        if identity and (self.get(identity)['status'] != 'succeeded' or not self.image_path(identity).is_file()):
            raise ValueError('请先完成图集生成和预览。')
        # Reuse the existing selection slot; preset changes never create generation records.
        selection = f'preset:{preset}' if preset and preset != 'robot' else identity
        with self.store._connect() as db:
            db.execute('UPDATE mascot_settings SET active_id=? WHERE id=1', (selection,))
        return self.settings()
