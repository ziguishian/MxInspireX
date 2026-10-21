"""Small catalogue records and cached previews; never ship full task history."""
import json
import re
from pathlib import Path


def canvas_revision(project):
    try:
        stat = Path(project['rootPath'], 'canvas', 'board.json').stat()
        return f'{stat.st_mtime_ns}-{stat.st_size}', stat.st_mtime
    except OSError:
        return 'empty', 0


def project_overviews(store, projects):
    from datetime import datetime, timezone
    with store._connect() as db:
        rows = db.execute("""SELECT p.id, t.id AS task_id, t.status, t.updated_at,
            json_extract(CASE WHEN json_valid(t.input_json) THEN t.input_json ELSE '{}' END,'$.userMessage') AS message,
            json_extract(CASE WHEN json_valid(t.output_json) THEN t.output_json ELSE '{}' END,'$.structured_data.answer') AS answer,
            json_extract(CASE WHEN json_valid(t.output_json) THEN t.output_json ELSE '{}' END,'$.structured_data.clarification.questions') AS clarification
            FROM projects p LEFT JOIN tasks t ON t.id=(SELECT id FROM tasks
                WHERE project_id=p.id AND agent_key='design' AND superseded_by IS NULL
                  AND COALESCE(json_extract(CASE WHEN json_valid(input_json) THEN input_json ELSE '{}' END,'$.taskSurface'),'conversation')!='canvas_node'
                ORDER BY updated_at DESC, COALESCE(turn_order,rowid) DESC LIMIT 1)""").fetchall()
    latest = {row['id']: row for row in rows}
    output = []
    for project in projects:
        task = latest.get(project['id'])
        state = task['status'] if task and task['task_id'] else 'empty'
        if state == 'succeeded' and task['clarification'] and json.loads(task['clarification']):
            state = 'awaiting_input'
        summary = str((task['answer'] if state in {'succeeded', 'awaiting_input'} else task['message']) or task['message'] or '') if task and task['task_id'] else project['brief']
        summary = re.sub(r'@(?:asset|node):[\w-]+', '引用内容', summary)
        summary = re.sub(r'[*#`]|\s+', ' ', summary).strip()[:140]
        revision, modified = canvas_revision(project)
        activity = max(project['updatedAt'], task['updated_at'] if task and task['task_id'] else project['updatedAt'], datetime.fromtimestamp(modified, timezone.utc).isoformat() if modified else '')
        output.append({**project, 'latestTaskId': task['task_id'] if task else None, 'latestTaskStatus': state,
                       'summary': summary, 'activityAt': activity, 'previewRevision': revision})
    return sorted(output, key=lambda item: item['activityAt'], reverse=True)


class ProjectPreviews:
    def __init__(self, store, canvas):
        self.store, self.canvas, self.cache = store, canvas, {}
        self.html_cache = {}

    def html_assets(self):
        """Index existing canvas pages without copying or exporting user files."""
        from datetime import datetime, timezone
        from hashlib import sha256
        from .html_assets import resolve_html_assets
        output = []
        projects = self.store.list_projects()
        existing = {project['id'] for project in projects}
        self.html_cache = {key: value for key, value in self.html_cache.items() if key in existing}
        for project in projects:
            revision, modified = canvas_revision(project)
            cached = self.html_cache.get(project['id'])
            if not cached or cached[0] != revision:
                records = []
                for node in self.canvas.load(project['id'])['nodes']:
                    data = node.get('data') or {}
                    html = data.get('html')
                    if data.get('kind') != 'html' or not isinstance(html, str) or not html.strip():
                        continue
                    filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(data.get('title') or '网页'))[:120]
                    if not filename.lower().endswith(('.html', '.htm')): filename += '.html'
                    content_key = json.dumps([html, data.get('htmlAssets') or {}], ensure_ascii=False, sort_keys=True)
                    records.append({'id': f"canvas-html-{node['id']}", 'htmlNodeId': node['id'], 'kind': 'html',
                        'pathRelative': filename, 'mime': 'text/html', 'byteSize': len(resolve_html_assets(data).encode()),
                        'revision': sha256(content_key.encode()).hexdigest(),
                        'updatedAt': datetime.fromtimestamp(modified, timezone.utc).isoformat() if modified else project['updatedAt']})
                if len(self.html_cache) >= 128: self.html_cache.pop(next(iter(self.html_cache)))
                self.html_cache[project['id']] = (revision, records)
                cached = self.html_cache[project['id']]
            output.extend({**record, 'projectId': project['id'], 'projectName': project['name']} for record in cached[1])
        return sorted(output, key=lambda record: record['updatedAt'], reverse=True)

    def html_document(self, project_id, node_id):
        from .html_assets import resolve_html_assets
        if not self.store.get_project(project_id): raise ValueError('项目不存在')
        node = next((node for node in self.canvas.load(project_id)['nodes'] if node['id'] == node_id), None)
        data = node.get('data', {}) if node else {}
        if data.get('kind') != 'html' or not isinstance(data.get('html'), str) or not data['html'].strip():
            raise ValueError('HTML 产物不存在或已被删除')
        return {'html': resolve_html_assets(data), 'title': data.get('title') or '网页'}

    def get(self, project_id):
        from .canvas_layout import node_preview_size
        project = self.store.get_project(project_id)
        if not project:
            raise ValueError('项目不存在')
        revision, _ = canvas_revision(project)
        cached = self.cache.get(project_id)
        if cached and cached[0] == revision:
            return cached[1]
        board = self.canvas.load(project_id)
        # Project cards are a way back into a project, not miniature copies of
        # its entire canvas.  Prefer the first finished visual deliverable in
        # canvas creation order so cards keep a stable, recognisable cover as
        # later iterations are added.  HTML counts as a visual deliverable
        # even though it is stored on the node rather than in AssetStore.
        def visual_output(node):
            data = node.get('data') or {}
            asset = data.get('asset') or {}
            kind = str(data.get('kind') or asset.get('kind') or '')
            mime = str(asset.get('mime') or '')
            path = str(asset.get('pathRelative') or '').lower()
            has_asset = bool(data.get('assetId') or asset.get('id'))
            is_visual_media = kind in {'image', 'video', '3d', 'cad'} or mime.startswith(('image/', 'video/')) or path.endswith(('.glb', '.gltf', '.obj', '.fbx', '.stl'))
            return (is_visual_media and has_asset) or (
                kind == 'html' and str(data.get('html') or '').strip()
            )

        chosen = next((node for node in board['nodes'] if visual_output(node)), None)
        # Older projects can legitimately contain only text or a pending
        # node. Keep the previous lightweight fallback for those projects,
        # while never returning an entire canvas as a card preview.
        if chosen is None:
            chosen = next((node for node in board['nodes'] if any(
                node.get('data', {}).get(key) for key in ('assetId', 'text', 'html', 'summary')
            ) or (node.get('data', {}).get('asset') or {}).get('id')), None)
        chosen = [chosen] if chosen else []
        nodes = []
        for node in chosen:
            data = node.get('data') or {}
            asset = data.get('asset') or {}
            nodes.append({'id': node['id'], 'position': node.get('position', {'x': 0, 'y': 0}), 'data': {
                'kind': data.get('kind'), 'title': str(data.get('title') or '')[:80],
                'assetId': data.get('assetId') or asset.get('id'),
                'asset': {key: asset[key] for key in ('id', 'projectId', 'mime', 'pathRelative') if key in asset},
                'previewSize': node_preview_size(data),
                'htmlNodeId': node['id'] if data.get('kind') == 'html' and str(data.get('html') or '').strip() else None,
                'text': str(data.get('text') or data.get('summary') or '')[:140],
                'generating': bool(data.get('generating')), 'error': bool(data.get('error')),
            }})
        value = {'nodes': nodes, 'edges': [], 'revision': revision}
        # Bounded process cache; no HTML, prompts or image bytes in previews.
        if len(self.cache) >= 128:
            self.cache.pop(next(iter(self.cache)))
        self.cache[project_id] = (revision, value)
        return value


def library_assets(store):
    with store._connect() as db:
        rows = db.execute("""SELECT a.id,a.project_id,p.name,a.kind,a.path_relative,a.mime,a.byte_size,a.created_at
            FROM assets a JOIN projects p ON p.id=a.project_id
            WHERE COALESCE(json_extract(a.metadata_json,'$.cadRole'),'model')='model'
            AND COALESCE(json_extract(a.metadata_json,'$.cadHidden'),0)=0
            AND COALESCE(json_extract(a.metadata_json,'$.systemHidden'),0)=0 ORDER BY a.created_at DESC""").fetchall()
    return [{'id': row['id'], 'projectId': row['project_id'], 'projectName': row['name'], 'kind': row['kind'],
             'pathRelative': row['path_relative'], 'mime': row['mime'], 'byteSize': row['byte_size'], 'createdAt': row['created_at']} for row in rows]
