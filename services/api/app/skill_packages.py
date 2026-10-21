"""Portable Agent Skills packages and bounded GitHub downloads. No code execution."""
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit, unquote, quote
from zipfile import ZipFile, BadZipFile, ZIP_DEFLATED
import json
import mimetypes
import re
import stat

import httpx
import yaml

from .skills import SkillError, SkillCreate, MAX_FILE_BYTES, MAX_PACKAGE_BYTES, digest, encoded

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_FILES = 256


def package_path(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or '\\' in value or ':' in value
            or any(ord(c) < 32 for c in value) or PurePosixPath(value).is_absolute()
            or any(p in {'', '.', '..', '.git'} for p in value.split('/'))):
        raise SkillError('Skill 包含不安全的相对路径')
    return value


def yaml_map(text):
    # Metadata is small and passive. Reject aliases/tags to avoid recursive or
    # expanded YAML graphs, and reject duplicate keys instead of silently losing metadata.
    if len(text) > 32768:
        raise SkillError('Skill 元数据过长')
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        value = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in value:
                raise SkillError('Skill YAML 字段重复或键不是文本')
            value[key] = loader.construct_object(value_node)
        return value
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        depth = 0
        for token in yaml.scan(text):
            if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken)):
                raise SkillError('Skill YAML 不支持锚点、别名或自定义类型')
            if isinstance(token, (yaml.tokens.BlockMappingStartToken, yaml.tokens.BlockSequenceStartToken, yaml.tokens.FlowMappingStartToken, yaml.tokens.FlowSequenceStartToken)):
                depth += 1
            elif isinstance(token, (yaml.tokens.BlockEndToken, yaml.tokens.FlowMappingEndToken, yaml.tokens.FlowSequenceEndToken)):
                depth -= 1
            if depth > 24:
                raise SkillError('Skill YAML 嵌套过深')
        result = yaml.load(text, Loader=UniqueLoader)
    except yaml.YAMLError as error:
        raise SkillError('Skill YAML 格式无效') from error
    if not isinstance(result, dict):
        raise SkillError('Skill 元数据必须为 YAML 对象')
    return result


def parse_markdown(content):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise SkillError('SKILL.md 必须采用 UTF-8 编码') from error
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)\Z', text, re.S)
    if not match:
        raise SkillError('SKILL.md 需要包含 name 和 description 的 YAML frontmatter')
    metadata, instructions = yaml_map(match[1]), match[2].strip()
    if not isinstance(metadata.get('name'), str) or not isinstance(metadata.get('description'), str):
        raise SkillError('SKILL.md 的 name 和 description 必须为文本')
    return metadata, instructions


def package_definition(files, source=None):
    if 'SKILL.md' not in files or len(files) > MAX_FILES:
        raise SkillError('请选择包含 SKILL.md 的技能目录，最多 256 个文件')
    for name, content in files.items():
        package_path(name)
        if len(content) > MAX_FILE_BYTES:
            raise SkillError('单个资源不能超过 8 MB')
    if sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
        raise SkillError('Skill 包不能超过 24 MB')
    metadata, instructions = parse_markdown(files['SKILL.md'])
    try:
        config = yaml_map(files['agents/openai.yaml'].decode('utf-8')) if 'agents/openai.yaml' in files else {}
    except UnicodeDecodeError as error:
        raise SkillError('agents/openai.yaml 必须采用 UTF-8 编码') from error
    interface = config.get('interface') or {}
    if not isinstance(interface, dict):
        raise SkillError('agents/openai.yaml 的 interface 必须为对象')
    local = {}
    if 'langju.json' in files:
        try:
            local = json.loads(files['langju.json'])
        except (ValueError, UnicodeDecodeError) as error:
            raise SkillError('langju.json 格式无效') from error
        if not isinstance(local, dict):
            raise SkillError('langju.json 必须为对象')
    try:
        spec = SkillCreate.model_validate({'name': metadata['name'], 'description': metadata['description'], 'instructions': instructions,
                                           'title': interface.get('display_name') or local.get('title') or metadata['name'],
                                           'required_tools': local.get('requiredTools', [])})
    except ValueError as error:
        raise SkillError(str(error)) from error
    warnings = []
    if any(p.startswith('scripts/') or PurePosixPath(p).suffix in {'.py', '.sh', '.js', '.mjs', '.ps1'} for p in files):
        warnings.append('包含脚本：原文件已保留，本应用不执行 Skill 自带脚本。')
    if config.get('dependencies'):
        warnings.append('包含外部工具依赖：原声明已保留，本应用不会自动安装 MCP 或授予权限。')
    compatibility = metadata.get('compatibility')
    if isinstance(compatibility, str):
        warnings.append('运行环境要求：' + compatibility[:500])
    if metadata.get('allowed-tools'):
        warnings.append('allowed-tools 声明已保留，实际可用能力仍由当前 Agent 工具权限决定。')
    resources = [{'path': path, 'byteSize': len(content), 'sha256': digest(content), 'mime': mimetypes.guess_type(path)[0] or 'application/octet-stream'}
                 for path, content in sorted(files.items()) if path != 'SKILL.md']
    policy = config.get('policy') or {}
    definition = {'name': spec.name, 'title': spec.title, 'description': spec.description, 'instructions': spec.instructions,
                  'requiredTools': spec.required_tools, 'resources': resources, 'source': source,
                  'compatibilityWarnings': warnings, 'explicitOnly': isinstance(policy, dict) and policy.get('allow_implicit_invocation') is False,
                  'files': {path: digest(content) for path, content in sorted(files.items())}}
    return definition, digest(encoded(definition).encode())


def github_source(url, ref=None, path=None):
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as error:
        raise SkillError('GitHub 仓库地址无效') from error
    if parsed.scheme != 'https' or parsed.hostname != 'github.com' or port or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SkillError('请使用 https://github.com/组织/仓库 或具体 Skill 目录链接')
    parts = [unquote(p) for p in parsed.path.strip('/').split('/')]
    if len(parts) < 2 or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', p) or p in {'.', '..'} for p in parts[:2]):
        raise SkillError('GitHub 仓库地址无效')
    owner, repo = parts[:2]
    repo = repo.removesuffix('.git')
    if not repo or repo in {'.', '..'}:
        raise SkillError('GitHub 仓库地址无效')
    if len(parts) > 2:
        if parts[2] not in {'tree', 'blob'} or len(parts) < 4:
            raise SkillError('请使用仓库地址、tree 目录链接或 SKILL.md 文件链接')
        # Branch names containing slashes are unambiguous when explicitly supplied.
        tail = '/'.join(parts[3:])
        if ref:
            if not (tail == ref or tail.startswith(ref + '/')):
                raise SkillError('指定分支与链接不一致')
            linked_path = tail[len(ref):].lstrip('/')
        else:
            ref, linked_path = parts[3], '/'.join(parts[4:])
        path = path if path is not None else linked_path
        if parts[2] == 'blob' and path.endswith('SKILL.md'):
            path = path[:-len('SKILL.md')].rstrip('/')
    if ref and (len(ref) > 180 or not re.fullmatch(r'[\w./-]+', ref) or '..' in ref):
        raise SkillError('GitHub 分支或提交无效')
    if path:
        package_path(path)
    return {'owner': owner, 'repo': repo, 'ref': ref, 'path': path or ''}


class GitHubSkillInstaller:
    def __init__(self, service, client=None):
        self.service, self.client = service, client

    def _download(self, url, maximum):
        # All callers construct fixed GitHub API/codeload URLs. Never follow
        # redirects to arbitrary hosts or send application credentials.
        client = self.client or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        try:
            with client.stream('GET', url, headers={'User-Agent': 'Langju-Skill-Installer', 'Accept': 'application/vnd.github+json'}) as response:
                if response.status_code != 200:
                    reason = '仓库、分支或路径不存在，或不是公开仓库' if response.status_code == 404 else 'GitHub 请求失败或达到访问频率限制'
                    raise SkillError(f'{reason}（HTTP {response.status_code}）')
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > maximum:
                        raise SkillError('GitHub 下载超出大小上限，请使用较小的技能仓库')
                    chunks.append(chunk)
                return b''.join(chunks)
        except httpx.HTTPError as error:
            raise SkillError('无法连接 GitHub，请检查网络后重试') from error
        finally:
            if self.client is None:
                client.close()

    def _archive(self, source):
        owner, repo = source['owner'], source['repo']
        ref = source['ref']
        try:
            if not ref:
                info = json.loads(self._download(f'https://api.github.com/repos/{owner}/{repo}', 256000))
                ref = info['default_branch']
            commit = json.loads(self._download(f'https://api.github.com/repos/{owner}/{repo}/commits/{quote(ref, safe="")}', 1024 * 1024))['sha']
            if not re.fullmatch('[0-9a-f]{40}', commit):
                raise ValueError('invalid commit')
        except SkillError:
            raise
        except (ValueError, KeyError, TypeError) as error:
            raise SkillError('GitHub 返回了无效的仓库信息') from error
        content = self._download(f'https://codeload.github.com/{owner}/{repo}/zip/{commit}', MAX_ARCHIVE_BYTES)
        try:
            archive = ZipFile(BytesIO(content))
        except BadZipFile as error:
            raise SkillError('GitHub 返回的仓库压缩包无效') from error
        entries = archive.infolist()
        if len(entries) > 20000:
            archive.close()
            raise SkillError('仓库文件数量过多，请使用专门的技能仓库')
        files = {}
        root = None
        try:
            for entry in entries:
                name = entry.filename.rstrip('/')
                prefix, separator, relative = name.partition('/')
                package_path(prefix)
                if separator:
                    package_path(relative)
                if root is None:
                    root = prefix
                if prefix != root:
                    raise SkillError('仓库压缩包结构无效')
                if not separator or entry.is_dir():
                    continue
                if relative in files:
                    raise SkillError('仓库包含重复文件路径')
                files[relative] = entry
        except Exception:
            archive.close()
            raise
        return archive, files, {**source, 'ref': ref, 'commit': commit, 'url': f'https://github.com/{owner}/{repo}'}

    @staticmethod
    def _files(archive, entries, path):
        prefix = path + '/' if path else ''
        selected = {p[len(prefix):]: e for p, e in entries.items() if p.startswith(prefix)}
        # A skill package does not implicitly absorb nested independent skills.
        if any(p != 'SKILL.md' and p.endswith('/SKILL.md') for p in selected):
            raise SkillError('所选目录包含多个 Skill，请选择具体的 Skill 子目录')
        if len(selected) > MAX_FILES or sum(e.file_size for e in selected.values()) > MAX_PACKAGE_BYTES:
            raise SkillError('Skill 包文件数量或大小超过上限')
        result = {}
        for path, entry in selected.items():
            package_path(path)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or entry.flag_bits & 1 or entry.file_size > MAX_FILE_BYTES:
                raise SkillError('Skill 不支持符号链接、加密文件或超过 8 MB 的单个资源')
            try:
                result[path] = archive.read(entry)
            except (BadZipFile, RuntimeError, OSError, NotImplementedError) as error:
                raise SkillError('Skill 资源解压失败') from error
        return result

    def inspect(self, url, ref=None, path=None):
        archive, entries, source = self._archive(github_source(url, ref, path))
        candidates = []
        try:
            prefix = source['path']
            for filename, entry in entries.items():
                folder = filename.rpartition('/')[0]
                if PurePosixPath(filename).name != 'SKILL.md' or prefix and folder != prefix and not folder.startswith(prefix + '/'):
                    continue
                if len(candidates) >= 100:
                    raise SkillError('匹配的技能过多，请指定更具体的目录')
                try:
                    definition, _ = package_definition(self._files(archive, entries, folder))
                    candidates.append({'path': folder, 'name': definition['name'], 'title': definition['title'], 'description': definition['description'],
                                       'warnings': definition['compatibilityWarnings']})
                except (SkillError, ValueError) as error:
                    candidates.append({'path': folder, 'error': str(error)})
            if not candidates:
                raise SkillError('目录中没有找到 SKILL.md')
            return {'source': source, 'candidates': candidates}
        finally:
            archive.close()

    def install(self, url, ref=None, path=None, operation_id=None):
        source = github_source(url, ref, path)
        fingerprint = digest(encoded(['github-install', source]).encode())
        with self.service.store._connect() as db:
            previous = self.service._operation(db, operation_id, fingerprint)
            if previous is not None:
                return previous
        archive, entries, source = self._archive(source)
        try:
            files = self._files(archive, entries, source['path'])
            definition, content_hash = package_definition(files, source)
            return self.service._commit_package(definition, files, content_hash, True, None, operation_id, fingerprint)
        finally:
            archive.close()


def export_package(service, skill_id, version=None):
    output = BytesIO()
    with service.store._connect() as db, ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        row = service._row(db, skill_id)
        item, definition = service._version(db, row, version)
        for filename in definition['files']:
            archive.writestr(definition['name'] + '/' + filename, service._bytes(row, item, definition, filename))
    return output.getvalue()
