"""Install shipped, portable skills once per workspace; preserve user decisions."""
import json
import re
from pathlib import Path

from .skill_packages import package_definition, package_path
from .skills import SkillConflict, SkillError, digest, encoded

BUNDLE_ROOT = Path(__file__).with_name('builtin_skills')


def read_bundles(root=BUNDLE_ROOT):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schemaVersion') != 1:
        raise SkillError('内置技能清单版本不支持')
    bundles, names = [], set()
    for entry in manifest['skills']:
        name = entry['name']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or name in names:
            raise SkillError('内置技能标识无效或重复')
        names.add(name)
        directory = root / name
        files = {}
        for filename, expected in entry['files'].items():
            path = directory / package_path(filename)
            if any(p.is_symlink() for p in [path, *path.parents]) or not path.resolve().is_relative_to(directory.resolve()):
                raise SkillError('内置技能资源路径无效')
            content = path.read_bytes()
            if digest(content) != expected:
                raise SkillError('内置技能资源校验失败：' + name + '/' + filename)
            files[filename] = content
        definition, _ = package_definition(files)
        if definition['name'] != name:
            raise SkillError('内置技能名称与清单不一致')
        definition['builtin'] = {'name': name, 'revision': entry['revision'], 'modifiedLocally': False}
        bundles.append((definition, files, digest(encoded(definition).encode())))
    return bundles


def install_bundled_skills(service, root=BUNDLE_ROOT):
    # Validate all packages before making any changes. No network/model/tool run.
    bundles = read_bundles(root)
    for definition, _, _ in bundles:
        missing = set(definition['requiredTools']) - set(service.tool_names())
        if missing:
            raise SkillError('内置技能缺少工具：' + '、'.join(sorted(missing)))
    with service.store._connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS bundled_skill_installs (
            name TEXT PRIMARY KEY, skill_id TEXT, installed_hash TEXT NOT NULL)''')
    results = []
    for definition, files, content_hash in bundles:
        name = definition['name']
        with service.store._connect() as db:
            installed = db.execute('SELECT * FROM bundled_skill_installs WHERE name=?', (name,)).fetchone()
        previous = None
        if installed:
            if not installed['skill_id']:
                continue  # An existing user skill owned this name on first boot.
            previous = service.get(installed['skill_id'], allow_deleted=True)
            if (previous['deleted'] or previous['contentHash'] != installed['installed_hash']
                    or content_hash == installed['installed_hash']):
                continue
        operation = 'builtin:' + name + ':' + content_hash
        try:
            result = service._commit_package(definition, files, content_hash,
                previous['enabled'] if previous else True, previous, operation, content_hash)
        except SkillConflict:
            # A user/concurrent process won the name/version. Never overwrite it.
            with service.store._connect() as db:
                db.execute('INSERT OR IGNORE INTO bundled_skill_installs VALUES (?,NULL,?)', (name, content_hash))
            continue
        # Receipts also recover a crash between package commit and this marker.
        with service.store._connect() as db:
            db.execute('''INSERT INTO bundled_skill_installs VALUES (?,?,?)
                ON CONFLICT(name) DO UPDATE SET skill_id=excluded.skill_id, installed_hash=excluded.installed_hash''',
                (name, result['id'], result['contentHash']))
        results.append(result)
    return results
