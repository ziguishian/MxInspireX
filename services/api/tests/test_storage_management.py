from types import SimpleNamespace
from app.storage_management import workspace_usage, clear_preview_cache


def test_usage_counts_files_without_modifying_them(tmp_path):
    (tmp_path / 'project').mkdir()
    image = tmp_path / 'project' / 'image.png'
    image.write_bytes(b'12345')
    (tmp_path / 'catalog.sqlite').write_bytes(b'123')
    assert workspace_usage(tmp_path) == {'path': str(tmp_path), 'bytes': 8, 'partial': False}
    assert image.read_bytes() == b'12345'


def test_cache_cleanup_keeps_user_data(tmp_path):
    original = tmp_path / 'original.png'
    original.write_bytes(b'original')
    previews = SimpleNamespace(cache={'a': 1}, html_cache={'a': 2})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(project_previews=previews)))
    assert clear_preview_cache(request) == {'cleared': True}
    assert not previews.cache and not previews.html_cache
    assert original.read_bytes() == b'original'
