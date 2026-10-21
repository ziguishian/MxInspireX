import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from test_delivery_contract import workspace, task
from app.design_tools import DesignToolRegistry
from app.delivery import DeliveryService
from app.html_assets import resolve_html_assets
from app.task_focus import node_view


def image_asset(workspace):
    stream = io.BytesIO()
    Image.new('RGBA', (32, 24), (40, 180, 90, 80)).save(stream, format='PNG')
    return workspace[2].add_bytes(project_id=workspace[1], kind='image', filename='illustration.png', content=stream.getvalue())


def test_css_syntax_rejected_before_saving_and_original_remains_intact(workspace):
    store, project, assets, canvas = workspace
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    original = tools.canvas_create_html(project_id=project, html='<h1>原网页</h1>')['node']
    broken = '<style>.bar{padding:0 max(24px,calc((100% - 1120px)/2);display:flex}.hero{display:grid}</style><h1>新网页</h1>'
    with pytest.raises(ValueError, match='CSS 括号'):
        tools.canvas_create_html(project_id=project, canvas_node_id=original['id'], html=broken)
    assert canvas.load(project)['nodes'] == [original]
    fixed = broken.replace('/2);', '/2));')
    tools.canvas_create_html(project_id=project, canvas_node_id=original['id'], html=fixed)
    assert len(canvas.load(project)['nodes']) == 1
    assert canvas.load(project)['nodes'][0]['data']['html'] == fixed


def test_referenced_image_embeds_for_preview_export_and_recovery_without_model_base64(workspace):
    store, project, assets, canvas = workspace
    image = image_asset(workspace)
    task(store, project, context={'referencedAssets': [{'id': image['id']}], 'deliveryVerification': True})
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    source = f'<h1>网页</h1><img src="asset://{image["id"]}" alt="插图"><style>.hero{{background-image:url(asset://{image["id"]})}}</style>'
    args = {'html': source, 'output_mode': 'create'}
    result = tools.execute(project_id=project, task_id='task', name='canvas_create_html', arguments=args)
    assert 'base64' not in json.dumps(result)
    assert result['node']['data']['imageAssetIds'] == [image['id']]
    node = canvas.load(project)['nodes'][0]
    embedded = resolve_html_assets(node['data'])
    assert embedded.count('data:image/png;base64,') == 2 and 'asset://' not in embedded
    image_data = node['data']['htmlAssets'][image['id']].split(',', 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(image_data))) as png:
        assert png.getextrema()[3] == (80, 80)
    assert 'htmlAssets' not in node_view(node)['data']
    assert tools.execute(project_id=project, task_id='task', name='canvas_create_html', arguments=args) == result
    assert len(canvas.load(project)['nodes']) == 1
    delivery = DeliveryService(store)
    assert delivery.claim_previews()[0]['html'] == embedded
    original_hash = delivery.fingerprint(node)
    node['data']['htmlAssets'][image['id']] = 'data:image/png;base64,YQ=='
    assert delivery.fingerprint(node) != original_hash
    for format in ('html', 'zip'):
        exported = tools.execute(project_id=project, task_id='task', name='export_deliverable', arguments={'format': format, 'node_ids': [result['node']['id']]})
        path = Path(assets.get_asset(project_id=project, asset_id=exported['assetId'])['absolutePath'])
        if format == 'html': assert path.read_text() == embedded
        else:
            with zipfile.ZipFile(path) as archive: assert archive.read('nodes/1.html').decode() == embedded


def test_html_asset_scope_rejects_unrelated_missing_and_svg_assets(workspace):
    store, project, assets, canvas = workspace
    allowed, unrelated = image_asset(workspace), image_asset(workspace)
    task(store, project, context={'referencedAssets': [{'id': allowed['id']}]})
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    with pytest.raises(ValueError, match='无关'):
        tools.execute(project_id=project, task_id='task', name='canvas_create_html', arguments={'html':f'<img src="asset://{unrelated["id"]}">','output_mode':'create'})
    with pytest.raises(ValueError, match='不存在'):
        tools.canvas_create_html(project_id=project, html='<img src="asset://missing">')
    svg = assets.add_bytes(project_id=project, kind='image', filename='image.svg', content=b'<svg/>')
    with pytest.raises(ValueError, match='SVG'):
        tools.canvas_create_html(project_id=project, html=f'<img src="asset://{svg["id"]}">')
    assert canvas.load(project)['nodes'] == []


def test_editing_webpage_keeps_image_scope_and_removes_unused_embeds(workspace):
    store, project, assets, canvas = workspace
    image = image_asset(workspace)
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    node = tools.canvas_create_html(project_id=project, html=f'<img src="asset://{image["id"]}">')['node']
    task(store, project, context={'referencedNodes': [{'id': node['id']}], 'userMessage': '修改网页，保留原插图'})
    updated = tools.execute(project_id=project, task_id='task', name='canvas_update_node', arguments={'node_id':node['id'],'patch':{'data':{'html':f'<h1>新版</h1><img src="asset://{image["id"]}">'}}})
    assert updated['node']['data']['imageAssetIds'] == [image['id']]
    assert len(canvas.load(project)['nodes']) == 1
    tools.execute(project_id=project, task_id='task', name='canvas_create_html', arguments={'canvas_node_id':node['id'], 'html':'<h1>纯文字</h1>'})
    assert canvas.load(project)['nodes'][0]['data']['htmlAssets'] == {}


def test_new_nodes_do_not_overlap_wide_or_resized_webpages(workspace):
    _, project, _, canvas = workspace
    page = canvas.create_node(project, kind='html', title='桌面网页', data={'html':'<h1>网页</h1>'})
    following = canvas.create_node(project, kind='image', title='图片')
    # Compact placement may wrap below a wide webpage instead of extending
    # the row. Both directions must leave the actual preview unobstructed.
    assert (following['position']['x'] >= page['position']['x'] + 960 + 48
            or following['position']['y'] >= page['position']['y'] + 640 + 40 + 48)
    following = canvas.update_node(project, following['id'], {'data': {'kind':'html','htmlPreviewSize': {'width':1500,'height':900}}})
    last = canvas.create_node(project, kind='text', title='文案')
    assert (last['position']['x'] >= following['position']['x'] + 1500 + 48
            or last['position']['y'] >= following['position']['y'] + 900 + 40 + 48)
