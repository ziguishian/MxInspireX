import base64
import io
from pathlib import Path

from PIL import Image

from app.assets import AssetStore
from app.models import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime
from app.vision_preview import MAX_EDGE, MAX_ITEM_BYTES, make_vision_preview


def test_visual_preview_is_bounded_jpeg_and_keeps_original_bytes():
    original = io.BytesIO()
    Image.new('RGBA', (3200, 1800), (35, 107, 120, 170)).save(original, format='PNG')
    content = original.getvalue()
    preview = make_vision_preview(content)
    assert preview is not None
    assert preview['mime'] == 'image/jpeg'
    assert max(preview['width'], preview['height']) <= MAX_EDGE
    assert preview['byteSize'] <= MAX_ITEM_BYTES
    assert preview['originalByteSize'] == len(content)
    assert content == original.getvalue()


def test_agent_attachment_budget_keeps_only_eight_previews_and_never_rewrites_sources(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(
        name='预览预算', slug='previews', brief='', budget_minor=None,
        currency='CNY', root_path=str(tmp_path / 'previews'),
    ))
    assets = AssetStore(store)
    originals = []
    refs = []
    for index in range(9):
        content = f'original-{index}'.encode()
        asset = assets.add_bytes(project_id=project['id'], kind='image', filename=f'{index}.png', content=content)
        originals.append((asset, content))
        refs.append({'assetId': asset['id'], 'projectId': project['id']})

    preview_bytes = 2 * 1024 * 1024
    monkeypatch.setattr('app.vision_preview.make_vision_preview', lambda content: {
        'content': b'p' * preview_bytes, 'mime': 'image/jpeg',
        'width': 1600, 'height': 900, 'originalWidth': 3200, 'originalHeight': 1800,
        'byteSize': preview_bytes, 'originalByteSize': len(content),
    })
    resolved = TaskRuntime(store, asset_store=assets)._resolve_attachments(project['id'], refs)
    assert len(resolved) == 8
    assert len([item for item in resolved if item.get('data')]) == 4
    assert all(len(base64.b64decode(item['data'])) <= MAX_ITEM_BYTES for item in resolved if item.get('data'))
    assert all(item.get('data') or '8 MB' in item.get('text', '') for item in resolved)
    for asset, content in originals:
        stored = assets.get_asset(project_id=project['id'], asset_id=asset['id'])
        assert stored is not None
        assert Path(stored['absolutePath']).read_bytes() == content
