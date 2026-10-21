"""Workspace skills: immutable packages, shared catalogue and task-local activation.

Skills contain instructions and passive resources. They never install tools or run
scripts. Both the UI and the Agent gateway use this service.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


SKILL_TOOLS = ('skill_create', 'skill_update', 'skill_delete', 'skill_list', 'skill_read', 'skill_load', 'skill_unload')
SKILL_WRITES = {'skill_create', 'skill_update', 'skill_delete'}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PACKAGE_BYTES = 24 * 1024 * 1024
RESOURCE_EXTENSIONS = {'.md', '.txt', '.json', '.csv', '.tsv', '.html', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.pdf', '.docx', '.pptx', '.xlsx'}


class SkillError(ValueError):
    status_code = 422


class SkillNotFound(SkillError):
    status_code = 404


class SkillConflict(SkillError):
    status_code = 409


class SkillResourceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str
    text: str | None = None
    dataBase64: str | None = None
    sourceAssetId: str | None = None
    sourceDocumentId: str | None = None
    # Reuse a resource from the version being edited, never a filesystem path.
    existingPath: str | None = None


class SkillCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=64)
    title: str = Field(default='', max_length=100)
    description: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(min_length=1, max_length=24000)
    required_tools: list[str] = Field(default_factory=list, max_length=64)
    resources: list[SkillResourceInput] = Field(default_factory=list, max_length=256)
    enabled: bool = True


class SkillUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=64)
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=1024)
    instructions: str | None = Field(default=None, min_length=1, max_length=24000)
    required_tools: list[str] | None = Field(default=None, max_length=64)
    resources: list[SkillResourceInput] | None = Field(default=None, max_length=64)
    enabled: bool | None = None


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(content):
    return hashlib.sha256(content).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def resource_name(value):
    value = str(value)
    path = PurePosixPath(value)
    if (not value or len(value) > 220 or '\\' in value or '\x00' in value or ':' in value
            or path.is_absolute() or any(p in {'', '.', '..'} for p in value.split('/'))
            or len(path.parts) < 2 or path.parts[0] not in {'references', 'assets'}
            or path.suffix.lower() not in RESOURCE_EXTENSIONS):
        raise SkillError('资源必须位于 references/ 或 assets/，使用安全的相对路径及支持的资料格式')
    return value


class SkillService:
    def __init__(self, store):
        self.store = store
        self.root = store.workspace_root / 'skills'
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.resolve().parent != store.workspace_root.resolve():
            raise SkillError('技能库目录必须位于当前工作区内')
        with store._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS skills (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, current_version INTEGER NOT NULL,
                  enabled INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS skills_active_name ON skills(name) WHERE deleted=0;
                CREATE TABLE IF NOT EXISTS skill_versions (
                  skill_id TEXT NOT NULL REFERENCES skills(id), version INTEGER NOT NULL,
                  definition_json TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
                  PRIMARY KEY(skill_id,version));
                CREATE TABLE IF NOT EXISTS task_skill_bindings (
                  task_id TEXT NOT NULL, skill_id TEXT NOT NULL, version INTEGER NOT NULL,
                  active INTEGER NOT NULL, updated_at TEXT NOT NULL,
                  PRIMARY KEY(task_id,skill_id), FOREIGN KEY(skill_id,version) REFERENCES skill_versions(skill_id,version));
                CREATE TABLE IF NOT EXISTS skill_operations (
                  operation_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL);
            ''')

    def tool_names(self):
        from .design_tools import DesignToolRegistry
        internal = {'budget_check', 'repair_control', 'delivery_verify', 'canvas_create_node', 'canvas_create_svg', 'generation_reference_check'}
        return sorted((set(DesignToolRegistry.TOOL_NAMES) - internal) | {'generate_batch'})

    def _row(self, db, skill_id, allow_deleted=False):
        row = db.execute('SELECT * FROM skills WHERE id=?', (skill_id,)).fetchone()
        if not row or row['deleted'] and not allow_deleted:
            raise SkillNotFound('Skill 不存在或已删除')
        return row

    def _version(self, db, row, version=None):
        version = row['current_version'] if version is None else int(version)
        item = db.execute('SELECT * FROM skill_versions WHERE skill_id=? AND version=?', (row['id'], version)).fetchone()
        if not item:
            raise SkillNotFound('Skill 版本不存在')
        return item, json.loads(item['definition_json'])

    def _detail(self, db, row, version=None):
        item, definition = self._version(db, row, version)
        return {**{k: v for k, v in definition.items() if k != 'files'}, 'id': row['id'],
                'version': item['version'], 'currentVersion': row['current_version'],
                'enabled': bool(row['enabled']), 'deleted': bool(row['deleted']),
                'contentHash': item['content_hash'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
                'missingTools': sorted(set(definition['requiredTools']) - set(self.tool_names()))}

    def get(self, skill_id, version=None, *, allow_deleted=False):
        with self.store._connect() as db:
            return self._detail(db, self._row(db, skill_id, allow_deleted), version)

    def list(self, query='', offset=0, limit=20, include_disabled=False):
        offset, limit = max(0, int(offset)), max(1, min(50, int(limit)))
        with self.store._connect() as db:
            rows = db.execute('SELECT * FROM skills WHERE deleted=0 ORDER BY updated_at DESC,id').fetchall()
            values = [self._detail(db, r) for r in rows if include_disabled or r['enabled']]
        tokens = str(query).lower().split()
        values = [v for v in values if all(token in ' '.join([v['name'], v['title'], v['description']]).lower() for token in tokens)]
        summaries = [{k: v for k, v in item.items() if k not in {'instructions', 'resources'}} for item in values]
        return {'skills': summaries[offset:offset+limit], 'total': len(values),
                'nextOffset': offset+limit if offset+limit < len(values) else None}

    def versions(self, skill_id):
        with self.store._connect() as db:
            self._row(db, skill_id)
            return [{'version': r['version'], 'contentHash': r['content_hash'], 'createdAt': r['created_at']}
                    for r in db.execute('SELECT * FROM skill_versions WHERE skill_id=? ORDER BY version DESC', (skill_id,))]

    def _path(self, skill_id, version, filename):
        # IDs/versions come only from catalogue rows, and files from the manifest.
        path = self.root / skill_id / 'versions' / str(version) / filename
        current = path
        while current != self.root:
            if current.is_symlink():
                raise SkillError('Skill 资源不能通过符号链接访问其他文件')
            current = current.parent
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise SkillError('Skill 资源不在当前工作区内')
        return path

    def _bytes(self, row, item, definition, filename):
        expected = definition['files'].get(filename)
        if not expected:
            raise SkillNotFound('Skill 资源不存在')
        path = self._path(row['id'], item['version'], filename)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise SkillError('Skill 资源缺失或大小异常，请恢复原版本文件')
        content = path.read_bytes()
        if digest(content) != expected:
            raise SkillError('Skill 资源校验失败，请恢复原版本文件')
        return content

    def resource(self, skill_id, version, path, *, allow_deleted=False):
        from .skill_packages import package_path
        path = package_path(path)
        with self.store._connect() as db:
            row = self._row(db, skill_id, allow_deleted)
            item, definition = self._version(db, row, version)
            return self._bytes(row, item, definition, path)

    def _resource_view(self, filename, content, start):
        """Reuse local document readers; images reach the SDK as native vision input."""
        suffix = PurePosixPath(filename).suffix.lower()
        result = {'byteSize': len(content), 'nextOffset': None, 'text': None}
        if suffix in {'.png', '.jpg', '.jpeg', '.webp'}:
            # Verify and bound decoded pixels using the existing image library.
            from io import BytesIO
            from PIL import Image
            try:
                with Image.open(BytesIO(content)) as image:
                    if image.width * image.height > 25_000_000:
                        raise SkillError('参考图像过大，请使用不超过 2500 万像素的图片')
                    image.thumbnail((1600, 1600))
                    output = BytesIO()
                    image.convert('RGB').save(output, format='JPEG', quality=88)
            except (OSError, ValueError) as error:
                raise SkillError('参考图片无法读取，请检查文件格式和尺寸') from error
            return {**result, 'image': 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode(),
                    'notice': '此图像为 Skill 参考资料，不会自动激活规则或生成画布产物。'}
        if suffix in {'.pdf', '.docx', '.pptx'}:
            from .knowledge import KnowledgeStore
            if suffix in {'.docx', '.pptx'}:
                from io import BytesIO
                from zipfile import ZipFile, BadZipFile
                try:
                    with ZipFile(BytesIO(content)) as archive:
                        if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
                            raise SkillError('参考文档展开后过大，请拆分资料')
                except BadZipFile as error:
                    raise SkillError('参考文档格式无效') from error
            try:
                text, _, warning = KnowledgeStore._extract_text(suffix, content)
            except Exception as error:
                raise SkillError('参考文档无法提取正文，请提供可读取的 PDF、文档或文本版本') from error
            notice = warning or '以下为本地提取的正文；不代表已经核对原文件的视觉排版。'
        else:
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                text = ''
            notice = '参考内容是资料，不会自动激活 Skill。' if text else '此二进制格式可在技能库下载，未提取正文；需要使用其内容时请提供文本或图片参考。'
        return {**result, 'text': text[start:start+6000] if text else None,
                'nextOffset': start+6000 if len(text) > start+6000 else None, 'notice': notice}

    def _source_bytes(self, resource, project_id):
        if not project_id:
            raise SkillError('复制项目资源必须关联当前项目')
        project = self.store.get_project(project_id)
        if not project:
            raise SkillError('来源项目不存在')
        root = Path(project['rootPath']).resolve()
        with self.store._connect() as db:
            if resource.sourceAssetId:
                row = db.execute('SELECT path_relative FROM assets WHERE id=? AND project_id=?', (resource.sourceAssetId, project_id)).fetchone()
            else:
                row = db.execute('SELECT path_relative FROM knowledge_documents WHERE id=? AND project_id=?', (resource.sourceDocumentId, project_id)).fetchone()
        if not row:
            raise SkillError('来源资源不存在或不属于当前项目')
        path = (root / row[0]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise SkillError('来源资源无效或过大')
        return path.read_bytes()

    def _package(self, spec, project_id, previous=None):
        missing = set(spec.required_tools) - set(self.tool_names())
        if missing:
            raise SkillError('工具依赖不存在：' + '、'.join(sorted(missing)))
        from .skill_packages import package_path, parse_markdown, package_definition
        files, resources = {}, []
        for resource in spec.resources:
            name = package_path(resource.path) if previous and resource.existingPath == resource.path else resource_name(resource.path)
            if name in files:
                raise SkillError('资源路径重复：' + name)
            sources = [resource.text, resource.dataBase64, resource.sourceAssetId, resource.sourceDocumentId, resource.existingPath]
            if sum(value is not None for value in sources) != 1:
                raise SkillError('每个资源必须且只能指定一种内容来源')
            if resource.text is not None:
                content = resource.text.encode('utf-8')
            elif resource.dataBase64 is not None:
                if len(resource.dataBase64) > MAX_FILE_BYTES * 4 // 3 + 4:
                    raise SkillError('单个资源不能超过 8 MB')
                try:
                    content = base64.b64decode(resource.dataBase64, validate=True)
                except ValueError as error:
                    raise SkillError('资源编码无效') from error
            elif resource.existingPath is not None:
                if not previous:
                    raise SkillError('只能复用正在编辑的 Skill 版本中的资源')
                content = self.resource(previous['id'], previous['version'], resource.existingPath)
            else:
                content = self._source_bytes(resource, project_id)
            if len(content) > MAX_FILE_BYTES:
                raise SkillError('单个资源不能超过 8 MB')
            files[name] = content
            resources.append({'path': name, 'byteSize': len(content), 'sha256': digest(content),
                              'mime': mimetypes.guess_type(name)[0] or 'application/octet-stream'})
        definition = {'name': spec.name, 'title': spec.title or spec.name, 'description': spec.description,
                      'instructions': spec.instructions, 'requiredTools': sorted(set(spec.required_tools)),
                      'resources': resources}
        files['SKILL.md'] = ('---\nname: ' + json.dumps(spec.name) + '\ndescription: '
                             + json.dumps(spec.description, ensure_ascii=False) + '\n---\n\n' + spec.instructions + '\n').encode()
        local = {}
        if previous:
            with self.store._connect() as db:
                row = self._row(db, previous['id'])
                item, old = self._version(db, row, previous['version'])
                original = self._bytes(row, item, old, 'SKILL.md')
                if all(previous[k] == definition[k] for k in ('name', 'description', 'instructions')):
                    files['SKILL.md'] = original
                elif previous.get('source') or previous.get('builtin'):
                    import yaml
                    metadata, _ = parse_markdown(original)
                    metadata.update(name=spec.name, description=spec.description)
                    files['SKILL.md'] = ('---\n' + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + '---\n\n' + spec.instructions + '\n').encode()
                if 'langju.json' in old['files']:
                    local = json.loads(self._bytes(row, item, old, 'langju.json'))
        local.update(schemaVersion=1, title=definition['title'], requiredTools=definition['requiredTools'])
        files['langju.json'] = encoded(local).encode()
        if previous and (previous.get('source') or previous.get('builtin')):
            source = {**previous['source'], 'modifiedLocally': True} if previous.get('source') else None
            definition, _ = package_definition(files, source)
            definition['title'] = spec.title or spec.name
            if previous.get('builtin'):
                definition['builtin'] = {**previous['builtin'], 'modifiedLocally': True}
        if sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
            raise SkillError('Skill 包不能超过 24 MB')
        # Local Markdown references must resolve within the package. Web links
        # remain references; creation never fetches them or executes anything.
        for link in re.findall(r'\]\(([^\s)]+)', spec.instructions):
            link = link.split('#', 1)[0]
            if link and not re.match(r'^https?://|^mailto:', link) and link.removeprefix('./') not in files:
                raise SkillError('正文引用了不存在的资源：' + link)
        definition['files'] = {name: digest(content) for name, content in sorted(files.items())}
        return definition, files, digest(encoded(definition).encode())

    def _operation(self, db, operation_id, fingerprint):
        if not operation_id:
            return None
        row = db.execute('SELECT * FROM skill_operations WHERE operation_id=?', (operation_id,)).fetchone()
        if row and row['fingerprint'] != fingerprint:
            raise SkillConflict('同一操作标识不能用于不同的 Skill 操作')
        return json.loads(row['result_json']) if row else None

    def _finish(self, db, operation_id, fingerprint, result):
        if operation_id:
            db.execute('INSERT INTO skill_operations VALUES (?,?,?)', (operation_id, fingerprint, encoded(result)))
        return result

    def write(self, payload, *, skill_id=None, project_id=None, operation_id=None):
        fingerprint = digest(encoded([skill_id, payload, project_id]).encode())
        # Check a committed receipt before copying sources: the original source
        # may have been deleted after the first successful operation.
        with self.store._connect() as db:
            previous_result = self._operation(db, operation_id, fingerprint)
            if previous_result is not None:
                return previous_result
        previous = self.get(skill_id) if skill_id else None
        if previous:
            patch = SkillUpdate.model_validate(payload).model_dump(exclude_none=True)
            if patch.pop('expected_version') != previous['version']:
                raise SkillConflict('Skill 已被修改，请读取最新版本后再保存')
            raw = {k: previous[k] for k in ('name', 'title', 'description', 'instructions', 'enabled')}
            if set(patch) <= {'enabled'}:
                with self.store._connect() as db:
                    row = self._row(db, skill_id)
                    item, definition = self._version(db, row, previous['version'])
                    files = {name: self._bytes(row, item, definition, name) for name in definition['files']}
                return self._commit_package(definition, files, previous['contentHash'], patch.get('enabled', previous['enabled']), previous, operation_id, fingerprint)
            raw.update(required_tools=previous['requiredTools'], resources=[{'path': r['path'], 'existingPath': r['path']} for r in previous['resources'] if r['path'] != 'langju.json'])
            raw.update(patch)
        else:
            raw = payload
        spec = SkillCreate.model_validate(raw)
        if not previous and len(spec.resources) > 64:
            raise SkillError('创建 Skill 最多支持 64 个资源')
        definition, files, content_hash = self._package(spec, project_id, previous)
        return self._commit_package(definition, files, content_hash, spec.enabled, previous, operation_id, fingerprint)

    def _commit_package(self, definition, files, content_hash, enabled, previous, operation_id, fingerprint):
        skill_id = previous['id'] if previous else None
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            replay = self._operation(db, operation_id, fingerprint)
            if replay is not None:
                return replay
            if previous:
                row = self._row(db, skill_id)
                if row['current_version'] != previous['version']:
                    raise SkillConflict('Skill 已被修改，请读取最新版本后再保存')
                if previous['contentHash'] == content_hash and previous['enabled'] == enabled:
                    return self._finish(db, operation_id, fingerprint, self._detail(db, row))
            duplicate = db.execute('SELECT id FROM skills WHERE name=? AND deleted=0', (definition['name'],)).fetchone()
            if duplicate and duplicate[0] != skill_id:
                raise SkillConflict('该 Skill 标识已存在，请更新已有 Skill 或使用新的标识')
            identity, timestamp = skill_id or str(uuid4()), now()
            version = previous['version'] + 1 if previous else 1
            directory = self._path(identity, version, 'SKILL.md').parent
            if directory.exists():
                # An uncommitted directory can remain after a process crash.
                shutil.rmtree(directory)
            directory.mkdir(parents=True)
            try:
                for name, content in files.items():
                    path = self._path(identity, version, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                if previous:
                    db.execute('UPDATE skills SET name=?,current_version=?,enabled=?,updated_at=? WHERE id=?', (definition['name'], version, int(enabled), timestamp, identity))
                else:
                    db.execute('INSERT INTO skills VALUES (?,?,?,?,0,?,?)', (identity, definition['name'], version, int(enabled), timestamp, timestamp))
                db.execute('INSERT INTO skill_versions VALUES (?,?,?,?,?)', (identity, version, encoded(definition), content_hash, timestamp))
                result = self._detail(db, self._row(db, identity))
                self._finish(db, operation_id, fingerprint, result)
                db.commit()
            except Exception:
                shutil.rmtree(directory)
                raise
        return result

    def delete(self, skill_id, expected_version, *, operation_id=None):
        fingerprint = digest(encoded(['delete', skill_id, expected_version]).encode())
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            replay = self._operation(db, operation_id, fingerprint)
            if replay is not None:
                return replay
            row = self._row(db, skill_id, True)
            if row['current_version'] != expected_version:
                raise SkillConflict('Skill 已被修改，请读取最新版本后再删除')
            db.execute('UPDATE skills SET deleted=1,enabled=0,updated_at=? WHERE id=?', (now(), skill_id))
            return self._finish(db, operation_id, fingerprint, {'id': skill_id, 'version': expected_version, 'deleted': True})

    def _task(self, db, project_id, task_id):
        row = db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if not row or row['status'] == 'cancelled':
            raise SkillError('Skill 操作需要当前项目中有效的任务')
        return json.loads(row['input_json'])

    def bind(self, project_id, task_id, skill_id, *, active, version=None, operation_id=None):
        if not operation_id:
            raise SkillError('加载和卸载需要真实的工具调用标识')
        fingerprint = digest(encoded(['bind', project_id, task_id, skill_id, active, version]).encode())
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            inputs = self._task(db, project_id, task_id)
            replay = self._operation(db, operation_id, fingerprint)
            if replay is not None:
                return replay
            binding = db.execute('SELECT * FROM task_skill_bindings WHERE task_id=? AND skill_id=?', (task_id, skill_id)).fetchone()
            row = self._row(db, skill_id, bool(binding))
            if active:
                # Repeated activation keeps the pinned version until explicitly
                # unloaded; a retired package remains usable only by old tasks.
                selected = binding['version'] if binding and binding['active'] and version is None else version
                if binding and binding['active'] and version is not None and version != binding['version']:
                    raise SkillConflict('请先卸载当前版本，再加载另一个版本')
                if (row['deleted'] or not row['enabled']) and not (binding and binding['active']):
                    raise SkillError('Skill 已停用或删除，不能在新任务中加载')
                item, definition = self._version(db, row, selected)
                missing = set(definition['requiredTools']) - set(self.tool_names())
                if missing:
                    raise SkillError('缺少工具依赖：' + '、'.join(sorted(missing)))
                from .svg_policy import task_policy, ERROR as SVG_ERROR
                if 'canvas_create_svg' in definition['requiredTools'] and not task_policy(self.store, inputs, db)['allowed']:
                    raise SkillError('该 Skill 的必需工具 canvas_create_svg 在当前任务不可用。' + SVG_ERROR)
                if not inputs.get('allowExternalNetwork') and set(definition['requiredTools']) & {'web_search', 'web_read'}:
                    raise SkillError('该 Skill 需要联网工具，但当前任务未允许联网')
                self._bytes(row, item, definition, 'SKILL.md')
                selected = item['version']
                db.execute('INSERT INTO task_skill_bindings VALUES (?,?,?,?,?) ON CONFLICT(task_id,skill_id) DO UPDATE SET version=excluded.version,active=1,updated_at=excluded.updated_at', (task_id, skill_id, selected, 1, now()))
            else:
                selected = binding['version'] if binding else row['current_version']
                db.execute('UPDATE task_skill_bindings SET active=0,updated_at=? WHERE task_id=? AND skill_id=?', (now(), task_id, skill_id))
            self._persist_bindings(db, task_id)
            return self._finish(db, operation_id, fingerprint, {'skillId': skill_id, 'version': selected, 'active': active})

    def _persist_bindings(self, db, task_id):
        rows = db.execute('SELECT b.*,v.definition_json,v.content_hash FROM task_skill_bindings b JOIN skill_versions v ON v.skill_id=b.skill_id AND v.version=b.version WHERE b.task_id=? ORDER BY b.updated_at,b.skill_id', (task_id,)).fetchall()
        values = []
        for row in rows:
            definition = json.loads(row['definition_json'])
            values.append({'skillId': row['skill_id'], 'name': definition['name'], 'title': definition['title'],
                           'version': row['version'], 'contentHash': row['content_hash'], 'active': bool(row['active']),
                           'resources': definition['resources']})
        task = db.execute('SELECT input_json FROM tasks WHERE id=?', (task_id,)).fetchone()
        inputs = json.loads(task[0])
        inputs['skillBindings'] = values
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (encoded(inputs), task_id))

    def bindings(self, task_id, *, active_only=False, full=False):
        with self.store._connect() as db:
            rows = db.execute('SELECT * FROM task_skill_bindings WHERE task_id=? ORDER BY updated_at,skill_id', (task_id,)).fetchall()
            values = []
            for binding in rows:
                if active_only and not binding['active']:
                    continue
                row = self._row(db, binding['skill_id'], True)
                item, definition = self._version(db, row, binding['version'])
                value = {'skillId': row['id'], 'name': definition['name'], 'title': definition['title'],
                         'version': item['version'], 'contentHash': item['content_hash'], 'active': bool(binding['active']),
                         'resources': definition['resources']}
                if full and binding['active']:
                    self._bytes(row, item, definition, 'SKILL.md')
                    if 'langju.json' in definition['files']:
                        self._bytes(row, item, definition, 'langju.json')
                    value.update(instructions=definition['instructions'], requiredTools=definition['requiredTools'], resources=definition['resources'], compatibilityWarnings=definition.get('compatibilityWarnings', []))
                values.append(value)
            return values

    def inherit(self, project_id, task_id, source_task_id):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._task(db, project_id, task_id)
            # A stopped turn is a valid immutable source for a new continuation;
            # only the destination must still accept Skill operations.
            if not db.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?', (source_task_id, project_id)).fetchone():
                raise SkillError('Skill 续接来源不属于当前项目')
            db.execute('INSERT OR IGNORE INTO task_skill_bindings SELECT ?,skill_id,version,active,updated_at FROM task_skill_bindings WHERE task_id=? AND active=1', (task_id, source_task_id))
            self._persist_bindings(db, task_id)

    def runtime(self, task_id, *, simple=False):
        if simple:
            return {'catalog': [], 'bindings': [], 'active': []}
        catalogue, size = [], 0
        available = self.list(limit=50)
        for skill in available['skills']:
            if skill.get('explicitOnly'):
                continue
            summary = {k: skill[k] for k in ('id', 'name', 'title', 'version')}
            summary['description'] = skill['description'][:200]
            cost = len(encoded(summary))
            if size + cost > 6000:
                break
            catalogue.append(summary)
            size += cost
        with self.store._connect() as db:
            task = db.execute('SELECT input_json FROM tasks WHERE id=?', (task_id,)).fetchone()
        requested = json.loads(task['input_json']).get('referencedSkills', []) if task else []
        return {'catalog': catalogue, 'catalogTotal': available['total'], 'requested': requested, 'bindings': self.bindings(task_id),
                'active': self.bindings(task_id, active_only=True, full=True)}

    def resolve_mentions(self, text, *, allow_network=False):
        """Only canonical # tokens in this user message select skills.

        Resolve metadata server-side; browser labels/versions/instructions are
        never authority. The pinned version is retained by task retries.
        """
        identities = list(dict.fromkeys(re.findall(r'(?:^|[\s（(，,：；。！？\u3400-\u9fff])#skill:([a-zA-Z0-9_-]+)(?=$|[\s，。！？、；：!?;,)）])', str(text))))
        if len(identities) > 8:
            raise SkillError('单条消息最多选择 8 个技能，请减少 # 技能标签后重试')
        result = []
        for identity in identities:
            try:
                skill = self.get(identity)
            except SkillNotFound as error:
                raise SkillError('引用的技能已卸载或不在当前工作区，请删除该 # 标签并重新选择') from error
            if not skill['enabled']:
                raise SkillError(f'技能「{skill["title"]}」已停用，请启用后重试或删除 # 标签')
            if skill['missingTools']:
                raise SkillError(f'技能「{skill["title"]}」缺少工具：' + '、'.join(skill['missingTools']))
            if not allow_network and set(skill['requiredTools']) & {'web_search', 'web_read'}:
                raise SkillError(f'技能「{skill["title"]}」需要联网，请开启联网或删除该 # 标签')
            result.append({key: skill[key] for key in ('id', 'name', 'title', 'version')})
        return result

    def execute(self, name, project_id, task_id, args, *, role='design', operation_id=None):
        with self.store._connect() as db:
            inputs = self._task(db, project_id, task_id)
        if name in SKILL_WRITES and (role != 'design' or inputs.get('deliveryReviewOnly') or inputs.get('deliveryRepairOnly')):
            raise SkillError('研究、审查和修复阶段不能修改共享 Skill')
        if name == 'skill_create':
            result = self.write(args, project_id=project_id, operation_id=operation_id)
        elif name == 'skill_update':
            identity = args.pop('skill_id')
            result = self.write(args, skill_id=identity, project_id=project_id, operation_id=operation_id)
        elif name == 'skill_delete':
            result = self.delete(args['skill_id'], args['expected_version'], operation_id=operation_id)
        elif name == 'skill_list':
            page = self.list(**{**args, 'limit': min(10, int(args.get('limit', 10)))})
            summaries = [{k: v for k, v in skill.items() if k in {'id', 'name', 'title', 'description', 'version', 'enabled', 'missingTools', 'explicitOnly', 'compatibilityWarnings'}} for skill in page['skills']]
            for summary in summaries:
                summary['description'] = summary['description'][:200]
            result = {'total': page['total'], 'nextOffset': page['nextOffset'], 'availableTools': self.tool_names(), 'skills': summaries}
        elif name in {'skill_load', 'skill_unload'}:
            result = self.bind(project_id, task_id, args['skill_id'], active=name == 'skill_load',
                               version=args.get('version'), operation_id=operation_id)
        elif name == 'skill_read':
            identity, version = args['skill_id'], args.get('version')
            binding = next((b for b in self.bindings(task_id, active_only=True) if b['skillId'] == identity), None)
            if version is None and binding:
                version = binding['version']
            allow_deleted = bool(binding and version == binding['version'])
            detail = self.get(identity, version, allow_deleted=allow_deleted)
            filename = args.get('resource')
            start = max(0, int(args.get('offset', 0)))
            if filename:
                content = self.resource(identity, detail['version'], filename, allow_deleted=allow_deleted)
                result = {'id': identity, 'version': detail['version'], 'resource': filename,
                          **self._resource_view(filename, content, start)}
            else:
                text = detail['instructions']
                resource_start = max(0, int(args.get('resource_offset', 0)))
                result = {**detail, 'instructions': text[start:start+6000], 'nextOffset': start+6000 if len(text) > start+6000 else None,
                          'resources': detail['resources'][resource_start:resource_start+8],
                          'nextResourceOffset': resource_start+8 if len(detail['resources']) > resource_start+8 else None}
        else:
            raise SkillError('未知 Skill 工具')
        # Full packages stay in canonical storage; a separate live context block
        # owns activation. Creation must not accidentally activate its content.
        if name in SKILL_WRITES:
            result = {k: v for k, v in result.items() if k not in {'instructions', 'resources'}}
        return {'tool': name, 'status': 'succeeded', **result,
                **({'skillContext': self.runtime(task_id)} if name in SKILL_WRITES | {'skill_load', 'skill_unload'} else {})}
