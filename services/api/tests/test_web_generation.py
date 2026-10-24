import io
import wave

import pytest

from test_delivery_contract import workspace, task
from app.design_tools import DesignToolRegistry
from app.generation_inputs import bind_generation_inputs
from app.html_assets import resolve_html_assets
from app.svg_policy import contains_svg
from app.task_focus import node_view
from app.web_framework import apply_web_framework, strip_web_framework


def audio_asset(assets, project):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 800)
    return assets.add_bytes(project_id=project, kind='audio', filename='sample.wav', content=stream.getvalue())


def test_media_embeds_and_survives_edit_export_and_scope(workspace):
    store, project, assets, canvas = workspace
    audio = audio_asset(assets, project)
    video = assets.add_bytes(project_id=project, kind='video', filename='sample.mp4', content=b'mock video')
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas)
    source = f'<audio controls src="asset://{audio["id"]}"></audio><video controls><source src="asset://{video["id"]}"></video>'
    page = tools.canvas_create_html(project_id=project, html=source, style_framework='bootstrap')['node']
    assert page['data']['imageAssetIds'] == []
    assert page['data']['audioAssetIds'] == [audio['id']]
    assert page['data']['videoAssetIds'] == [video['id']]
    embedded = resolve_html_assets(page['data'])
    assert 'data:audio/' in embedded and 'data:video/mp4;base64,' in embedded
    assert 'asset://' not in embedded
    assert node_view(page)['data']['html'] == source
    assert not contains_svg(page['data'])  # Trusted framework icons are not authored illustrations.
    task(store, project, context={'referencedNodes': [{'id': page['id']}]})
    edited = tools.execute(project_id=project, task_id='task', name='canvas_update_node', arguments={
        'node_id': page['id'], 'patch': {'data': {'html': '<h1>新版</h1>' + source}}})['node']
    assert edited['data']['html'].count('mx-web-framework:start') == 1
    assert edited['data']['audioAssetIds'] == [audio['id']]
    exported = tools.execute(project_id=project, task_id='task', name='export_deliverable', arguments={'format': 'html', 'node_ids': [page['id']]})
    from pathlib import Path
    path = assets.get_asset(project_id=project, asset_id=exported['assetId'])['absolutePath']
    persisted = next(n for n in canvas.load(project)['nodes'] if n['id'] == page['id'])
    assert Path(path).read_text(encoding='utf-8') == resolve_html_assets(persisted['data'])


def test_framework_is_idempotent_and_does_not_whitelist_authored_svg():
    html = '<!doctype html><html><head><style>body{color:red}</style></head><body>页面</body></html>'
    embedded = apply_web_framework(html, 'bootstrap')
    assert apply_web_framework(embedded, 'bootstrap') == embedded
    assert strip_web_framework(embedded) == html
    assert embedded.index('bootstrap-5.3.8') < embedded.index('body{color:red}')
    assert contains_svg(embedded + '<svg/>')
    assert contains_svg('<!-- mx-web-framework:start --><svg/><!-- mx-web-framework:end -->')
    with pytest.raises(ValueError): apply_web_framework(html, 'unknown')


def web_plan():
    return {'goal': '制作交互网页', 'preserve': [], 'deliverables': [
        {'id': 'sound', 'title': '网页试听音频', 'kind': 'audio', 'supporting': True, 'acceptance': '可播放'},
        {'id': 'page', 'title': '网页', 'kind': 'html', 'acceptance': '试听按钮可用', 'dependsOn': ['sound'],
         'inputs': [{'source': 'deliverable', 'id': 'sound', 'role': 'content', 'purpose': '试听'}]}],
        'coverage': [], 'deferred': [], 'openQuestions': [], 'research': '无需外部研究'}


@pytest.mark.parametrize('invalid', ['', 'unused', 'node', 'excluded'])
def test_page_supporting_media_preserves_final_scope_and_prohibitions(workspace, invalid):
    store, project, assets, canvas = workspace
    context = {'userMessage': '生成一个网页', 'designPlanning': {'profile': 'deliverables'},
               'deliveryContract': [{'kind': 'html', 'count': 1}]}
    if invalid == 'node': context.update(taskSurface='canvas_node', canvasParams={'kind': 'html'})
    if invalid == 'excluded': context['userMessage'] += '，不要生成音频'
    task(store, project, context=context)
    proposal = web_plan()
    if invalid == 'unused': proposal['deliverables'][1].update(dependsOn=[], inputs=[])
    result = DesignToolRegistry(store).design_plan(project_id=project, task_id='task', plan=proposal)
    assert result['status'] == ('invalid' if invalid else 'ready'), result


def test_html_content_dependencies_accept_audio_without_relaxing_image_inputs(workspace):
    store, project, assets, canvas = workspace
    audio = audio_asset(assets, project)
    context = {'designPlan': {'scopeId': 's', 'deliverables': [{'id': 'page', 'inputs': [
        {'source': 'asset', 'id': audio['id'], 'role': 'content', 'purpose': '试听'}]}]}}
    bound = bind_generation_inputs(context, {'itemIds': ['page']}, {'html': f'<audio src="asset://{audio["id"]}"></audio>'}, [], assets, project)
    assert bound['source_asset_ids'] == [audio['id']]
    with pytest.raises(ValueError, match='必须嵌入'):
        bind_generation_inputs(context, {'itemIds': ['page']}, {'html': '<h1>遗漏音频</h1>'}, [], assets, project)
    with pytest.raises(ValueError):
        bind_generation_inputs(context, {'itemIds': ['page']}, {'prompt': '图片'}, [], assets, project)
