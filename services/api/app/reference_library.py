"""Workspace-wide visual references. Project assets are independent snapshots."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .agent_contracts import utc_now


class ReferenceError(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS visual_references (
 id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
 mime TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
 metadata_json TEXT NOT NULL DEFAULT '{}', saved INTEGER NOT NULL DEFAULT 1,
 analysis_status TEXT NOT NULL DEFAULT 'pending', analysis_error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_categories (
 id TEXT PRIMARY KEY, dimension TEXT NOT NULL, name TEXT NOT NULL,
 UNIQUE(dimension,name)
);
CREATE TABLE IF NOT EXISTS reference_selections (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT NOT NULL UNIQUE,
 data_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 submission_json TEXT, continuation_task_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_project_assets (
 project_id TEXT NOT NULL, reference_id TEXT NOT NULL, asset_id TEXT NOT NULL,
 PRIMARY KEY(project_id, reference_id)
);
CREATE TABLE IF NOT EXISTS reference_migrations (source_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS reference_vectors (
 reference_id TEXT PRIMARY KEY, model_key TEXT NOT NULL, vector_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS design_lessons (
 id TEXT PRIMARY KEY, media_kind TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]',
 strategy TEXT NOT NULL, avoid_json TEXT NOT NULL DEFAULT '[]', source_task_id TEXT,
 source_node_id TEXT, review_code TEXT, created_at TEXT NOT NULL,
 UNIQUE(source_task_id, source_node_id, review_code)
);
"""
DEFAULTS = {
    'industry': ['科技数码', '消费零售', '食品饮料', '生活方式', '教育服务', '工业制造', '商业服务'],
    'designType': ['品牌视觉', '平面设计', '产品设计', '包装礼盒', '数字界面', '空间设计', 'IP 插画', '导视', '海报', '多媒体'],
}
EDITABLE = {'title', 'industries', 'designTypes', 'tags', 'colors', 'description', 'notes', 'author', 'rightsStatus'}
_WRITE_LOCK = threading.RLock()


class ReferenceLibraryStore:
    max_bytes = 25 * 1024 * 1024

    def __init__(self, store):
        self.store = store
        self.root = store.workspace_root / 'references'
        for folder in ('originals', 'thumbnails'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        with store._connect() as db:
            db.executescript(SCHEMA)
            # Preserve the existing category identity when widening its label.
            db.execute("UPDATE reference_categories SET name='文旅' WHERE dimension='industry' AND name='文旅景区' AND NOT EXISTS (SELECT 1 FROM reference_categories WHERE dimension='industry' AND name='文旅')")
            migration = 'taxonomy:primary-industries-v1'
            if not db.execute('SELECT 1 FROM reference_migrations WHERE source_id=?', (migration,)).fetchone():
                for row in db.execute('SELECT id,metadata_json FROM visual_references').fetchall():
                    metadata = json.loads(row['metadata_json'])
                    if '文旅景区' in metadata.get('industries', []):
                        metadata['industries'] = list(dict.fromkeys('文旅' if name == '文旅景区' else name for name in metadata['industries']))
                        db.execute('UPDATE visual_references SET metadata_json=? WHERE id=?', (json.dumps(metadata, ensure_ascii=False), row['id']))
                db.execute('INSERT INTO reference_migrations VALUES (?)', (migration,))
            db.execute("DELETE FROM reference_categories WHERE dimension='industry' AND name='文旅景区'")
            for dimension, names in DEFAULTS.items():
                for name in names:
                    db.execute('INSERT OR IGNORE INTO reference_categories VALUES (?,?,?)', (uuid4().hex, dimension, name))

    def categories(self):
        with self.store._connect() as db:
            categories = [dict(row) for row in db.execute('SELECT * FROM reference_categories ORDER BY rowid')]
        # Show the current general-purpose defaults first; retain historical and
        # user categories with their IDs and reference bindings intact.
        def order(category):
            defaults = DEFAULTS[category['dimension']]
            name = category['name']
            return (list(DEFAULTS).index(category['dimension']), defaults.index(name) if name in defaults else len(defaults))
        return sorted(categories, key=order)

    def category(self, dimension, name):
        name = str(name).strip()
        if dimension == 'industry' and name == '文旅景区':
            name = '文旅'
        if dimension not in DEFAULTS or not 1 <= len(name) <= 50:
            raise ReferenceError('请提供行业或设计类型名称（1–50 字）')
        with self.store._connect() as db:
            db.execute('INSERT OR IGNORE INTO reference_categories VALUES (?,?,?)', (uuid4().hex, dimension, name))
        return self.categories()

    @staticmethod
    def _metadata(values):
        clean = {}
        for key in EDITABLE:
            if key not in values:
                continue
            value = values[key]
            if key in {'industries', 'designTypes', 'tags', 'colors'}:
                if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                    raise ReferenceError(f'{key} 必须是文本列表')
                clean[key] = list(dict.fromkeys(v.strip()[:50 if key in {'industries', 'designTypes'} else 80] for v in value if v.strip()))[:30]
                if key == 'industries':
                    clean[key] = list(dict.fromkeys('文旅' if name == '文旅景区' else name for name in clean[key]))
            else:
                if not isinstance(value, str):
                    raise ReferenceError(f'{key} 必须是文本')
                clean[key] = value.strip()[:4000 if key in {'description', 'notes'} else 300]
        return clean

    def add(self, content, filename, *, metadata=None, saved=True):
        if not content or len(content) > self.max_bytes:
            raise ReferenceError('图片不能为空，且不能超过 25 MB')
        try:
            with Image.open(io.BytesIO(content)) as original:
                if original.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ReferenceError('仅支持 JPEG、PNG、WebP 图片')
                if original.width * original.height > 40_000_000:
                    raise ReferenceError('图片像素总数不能超过 4000 万')
                original.load()
                fmt = original.format
                preview = ImageOps.exif_transpose(original).convert('RGB')
                width, height = preview.size
                preview.thumbnail((720, 720))
                thumb = io.BytesIO()
                preview.save(thumb, 'JPEG', quality=86)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ReferenceError('图片损坏或无法读取') from error
        digest = hashlib.sha256(content).hexdigest()
        suffix = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}[fmt]
        meta = self._metadata(metadata or {})
        meta.setdefault('title', Path(filename).stem[:300] or '视觉参考')
        meta.setdefault('rightsStatus', 'unknown')
        for key in ('sourceType', 'sourceUrl', 'imageUrl', 'sourceGroup', 'legacyDocumentId'):
            if (metadata or {}).get(key):
                meta[key] = str(metadata[key])[:2048]
        meta.setdefault('sourceType', 'upload')
        now = utc_now()
        with _WRITE_LOCK, self.store._connect() as db:
            old = db.execute('SELECT id FROM visual_references WHERE sha256=?', (digest,)).fetchone()
            if old:
                if saved:
                    db.execute('UPDATE visual_references SET saved=1 WHERE id=?', (old['id'],))
                identity = old['id']
            else:
                identity = uuid4().hex
                (self.root / 'originals' / f'{digest}.{suffix}').write_bytes(content)
                (self.root / 'thumbnails' / f'{digest}.jpg').write_bytes(thumb.getvalue())
                db.execute('INSERT INTO visual_references VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (
                    identity, digest, f'{digest}.{suffix}', f'image/{"jpeg" if suffix == "jpg" else suffix}',
                    width, height, json.dumps(meta, ensure_ascii=False), int(saved), 'pending', None, now, now))
        return self.get(identity)

    def _item(self, row):
        metadata = json.loads(row['metadata_json'])
        return {**metadata, 'id': row['id'], 'sha256': row['sha256'], 'mime': row['mime'],
                'width': row['width'], 'height': row['height'], 'saved': bool(row['saved']),
                'analysisStatus': row['analysis_status'], 'analysisError': row['analysis_error'],
                'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
                'thumbnailUrl': f'/api/references/{row["id"]}/thumbnail', 'contentUrl': f'/api/references/{row["id"]}/content'}

    def get(self, identity):
        with self.store._connect() as db:
            row = db.execute('SELECT * FROM visual_references WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ReferenceError('参考图不存在或已删除')
        return self._item(row)

    def path(self, identity, thumbnail=False):
        with self.store._connect() as db:
            row = db.execute('SELECT * FROM visual_references WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ReferenceError('参考图不存在或已删除')
        path = self.root / ('thumbnails' if thumbnail else 'originals') / (f'{row["sha256"]}.jpg' if thumbnail else row['filename'])
        if not path.is_file():
            raise ReferenceError('参考图文件已缺失')
        return path

    def inspect(self, identity):
        item = self.get(identity)
        return {**item, 'image': 'data:image/jpeg;base64,' + base64.b64encode(self.path(identity, True).read_bytes()).decode()}

    def update(self, identity, values, *, analysis=False):
        changes = self._metadata(values)
        with _WRITE_LOCK, self.store._connect() as db:
            row = db.execute('SELECT metadata_json FROM visual_references WHERE id=?', (identity,)).fetchone()
            if not row:
                raise ReferenceError('参考图不存在或已删除')
            meta = json.loads(row[0])
            edited = set(meta.get('userEditedFields', []))
            if analysis:
                changes = {k: v for k, v in changes.items() if k not in edited}
            else:
                edited.update(changes)
                meta['userEditedFields'] = sorted(edited)
            meta.update(changes)
            db.execute('UPDATE visual_references SET metadata_json=?, updated_at=? WHERE id=?', (json.dumps(meta, ensure_ascii=False), utc_now(), identity))
        for key, dimension in (('industries', 'industry'), ('designTypes', 'designType')):
            for name in changes.get(key, []):
                self.category(dimension, name)
        return self.get(identity)

    def save(self, identity):
        self.get(identity)
        with self.store._connect() as db:
            db.execute('UPDATE visual_references SET saved=1 WHERE id=?', (identity,))
        return self.get(identity)

    def delete(self, identity):
        with _WRITE_LOCK:
            paths = [self.path(identity), self.path(identity, True)]
            with self.store._connect() as db:
                db.execute('DELETE FROM visual_references WHERE id=?', (identity,))
                db.execute('DELETE FROM reference_vectors WHERE reference_id=?', (identity,))
            for path in paths:
                path.unlink(missing_ok=True)

    def search(self, query='', industry='', design_type='', exclude=None, offset=0, limit=24, *, saved_only=True):
        if industry == '文旅景区':
            industry = '文旅'
        with self.store._connect() as db:
            rows = db.execute('SELECT * FROM visual_references' + (' WHERE saved=1' if saved_only else '') + ' ORDER BY created_at DESC').fetchall()
        excluded = set(exclude or [])
        terms = re.findall(r'[a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}', str(query).lower())
        # Chinese words are not separated by whitespace; use overlapping bigrams
        # in addition to exact phrases, without hash embeddings.
        tokens = set(terms)
        for term in terms:
            if re.fullmatch(r'[\u4e00-\u9fff]+', term):
                tokens.update(term[i:i + 2] for i in range(len(term) - 1))
        ranked = []
        for row in rows:
            item = self._item(row)
            if item['id'] in excluded or industry and industry not in item.get('industries', []) or design_type and design_type not in item.get('designTypes', []):
                continue
            body = ' '.join(str(item.get(key, '')) for key in ('title', 'industries', 'designTypes', 'tags', 'description', 'notes')).lower()
            score = sum((3 if token in terms else 1) for token in tokens if token in body)
            if not tokens or score:
                ranked.append({**item, 'score': score})
        ranked.sort(key=lambda item: item['score'], reverse=True)
        return {'items': ranked[max(0, offset):max(0, offset) + min(100, max(1, limit))], 'total': len(ranked)}

    def project_asset(self, project_id, identity, asset_store):
        with _WRITE_LOCK:
            with self.store._connect() as db:
                row = db.execute('SELECT asset_id FROM reference_project_assets WHERE project_id=? AND reference_id=?', (project_id, identity)).fetchone()
            if row:
                existing = asset_store.get_asset(project_id=project_id, asset_id=row[0])
                if existing and Path(existing['absolutePath']).is_file():
                    return existing
            item = self.save(identity)
            asset = asset_store.add_bytes(project_id=project_id, kind='image', filename=self.path(identity).name,
                content=self.path(identity).read_bytes(), metadata={'source': 'input-reference', 'referenceOrigin': {'type': 'reference-library', 'referenceId': identity}, 'caption': item.get('title'),
                    'referenceId': identity, 'referenceSource': {key: item.get(key) for key in ('sourceUrl', 'author', 'rightsStatus', 'sha256')}})
            with self.store._connect() as db:
                db.execute('INSERT OR REPLACE INTO reference_project_assets VALUES (?,?,?)', (project_id, identity, asset['id']))
            return asset

    @staticmethod
    def _lesson_text(value, label, maximum):
        if not isinstance(value, str) or not (text := value.strip()) or len(text) > maximum:
            raise ReferenceError(f'{label}必须是 1–{maximum} 字的文本')
        # Lessons are reusable process knowledge, not a hiding place for a
        # source prompt, asset URL or client-specific brief.
        if re.search(r'https?://|data:image|(?:asset|node)[_-]?id|原始提示词|prompt\s*[:=]', text, re.I):
            raise ReferenceError('经验库不保存链接、资产标识或原始提示词')
        return text

    @staticmethod
    def _lesson_tags(values):
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ReferenceError('经验标签必须是文本列表')
        return list(dict.fromkeys(value.strip()[:40] for value in values if value.strip()))[:8]

    def add_lesson(self, values):
        if not isinstance(values, dict):
            raise ReferenceError('经验内容无效')
        media_kind = str(values.get('mediaKind') or '').strip()
        if media_kind not in {'image', 'html', 'video', 'cad'}:
            raise ReferenceError('经验媒介无效')
        strategy = self._lesson_text(values.get('strategy'), '经验策略', 500)
        avoid = [self._lesson_text(value, '避坑提示', 240) for value in values.get('avoid') or []]
        tags = self._lesson_tags(values.get('tags') or [])
        identity, now = uuid4().hex, utc_now()
        with _WRITE_LOCK, self.store._connect() as db:
            db.execute('INSERT INTO design_lessons(id,media_kind,tags_json,strategy,avoid_json,source_task_id,source_node_id,review_code,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (identity, media_kind, json.dumps(tags, ensure_ascii=False), strategy, json.dumps(avoid[:6], ensure_ascii=False),
                        None, None, None, now))
        return self.get_lesson(identity)

    @staticmethod
    def _lesson_item(row):
        return {'id': row['id'], 'mediaKind': row['media_kind'], 'tags': json.loads(row['tags_json'] or '[]'),
                'strategy': row['strategy'], 'avoid': json.loads(row['avoid_json'] or '[]'),
                'createdAt': row['created_at']}

    def get_lesson(self, identity):
        with self.store._connect() as db:
            row = db.execute('SELECT * FROM design_lessons WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ReferenceError('工作区设计经验不存在或已删除')
        return self._lesson_item(row)

    def search_lessons(self, query='', media_kind='', limit=3):
        if media_kind and media_kind not in {'image', 'html', 'video', 'cad'}:
            raise ReferenceError('经验媒介无效')
        with self.store._connect() as db:
            rows = db.execute('SELECT * FROM design_lessons' + (' WHERE media_kind=?' if media_kind else '') + ' ORDER BY created_at DESC',
                              (media_kind,) if media_kind else ()).fetchall()
        terms = set(re.findall(r'[a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}', str(query).lower()))
        ranked = []
        for row in rows:
            item = self._lesson_item(row)
            body = ' '.join([item['strategy'], *item['avoid'], *item['tags']]).lower()
            ranked.append((sum(1 for term in terms if term in body), item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:min(100, max(1, int(limit)))]]

    def delete_lesson(self, identity):
        with _WRITE_LOCK, self.store._connect() as db:
            if not db.execute('SELECT 1 FROM design_lessons WHERE id=?', (identity,)).fetchone():
                raise ReferenceError('工作区设计经验不存在或已删除')
            db.execute('DELETE FROM design_lessons WHERE id=?', (identity,))

    def record_confirmed_revision(self, revision):
        """Persist only a de-identified lesson after an explicit user click."""
        category = str(revision.get('category') or 'content')
        strategies = {
            'ai_artifact': ('图像复核优先排查伪文字、重复纹样、错误拼接与不连续边缘。', ['避免用一套通用负面词替代可见缺陷定位。']),
            'material': ('材质表现以真实连接、厚薄、反射和使用痕迹为判断依据。', ['避免塑料化表面与不符合工艺的纹理。']),
            'structure': ('先验证主体比例、开合和连接关系，再处理装饰细节。', ['避免结构不可制造或视觉上断裂。']),
            'hierarchy': ('先建立主次信息与阅读路径，再调整局部装饰。', ['避免所有元素同权导致信息堆叠。']),
            'design_alignment': ('用已确认的设计判断检查主题、受众和核心创意是否可见。', ['避免以泛化“高级感”替代设计主题。']),
            'layout': ('构图以主体比例、留白和观看重心为具体检查项。', ['避免套用单一参考图的构图。']),
            'content': ('将明确的可见问题拆为局部修订，并保留其余有效内容。', ['避免无目标地整图重做。']),
        }
        strategy, avoid = strategies.get(category, strategies['content'])
        with _WRITE_LOCK, self.store._connect() as db:
            db.execute('INSERT OR IGNORE INTO design_lessons(id,media_kind,tags_json,strategy,avoid_json,source_task_id,source_node_id,review_code,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (uuid4().hex, 'image', json.dumps([category], ensure_ascii=False), strategy, json.dumps(avoid, ensure_ascii=False),
                        revision['sourceTaskId'], revision['nodeId'], revision['code'], utc_now()))

    def migrate(self, knowledge):
        for document in knowledge.list_global_documents():
            if Path(document['pathRelative']).suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                continue
            with self.store._connect() as db:
                if db.execute('SELECT 1 FROM reference_migrations WHERE source_id=?', (document['id'],)).fetchone():
                    continue
            path = (self.store.workspace_root / document['pathRelative']).resolve()
            if not path.is_relative_to(self.store.workspace_root.resolve()) or not path.is_file():
                continue
            try:
                self.add(path.read_bytes(), path.name, metadata={'title': document['title'], 'sourceType': 'legacy', 'legacyDocumentId': document['id']})
            except ReferenceError:
                continue
            with self.store._connect() as db:
                db.execute('INSERT OR IGNORE INTO reference_migrations VALUES (?)', (document['id'],))
