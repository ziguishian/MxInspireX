from types import SimpleNamespace

import pytest

from app.assets import AssetStore
from app.canvas import CanvasStore, CanvasConflict
from app.canvas_layout import GAP, next_output_position, node_height, node_preview_size, nodes_colliding
from app.design_tools import DesignToolRegistry
from app.models import new_project
from app.image_production import explicit_image_disclaimer_requested, prepare_production_image_request
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


def node(id, x, y, width=300, height=300, kind='image'):
    return {'id': id, 'position': {'x': x, 'y': y},
            'data': {'kind': kind, 'previewSize': {'width': width, 'height': height}}}


def test_obstructed_right_slot_uses_nearby_space_below_previous_output():
    # Previously the right-hand candidate was pushed past the bottom of this
    # tall unrelated node, leaving >1,000 px of unnecessary separation.
    obstacle = node('obstacle', 388, 40, height=1400, kind='html')
    previous = node('previous', 40, 40)
    assert next_output_position([obstacle, previous], node('incoming', 0, 0)) == {'x': 40, 'y': 297}


def test_distant_nodes_at_same_height_do_not_control_local_row_wrapping():
    far = [node('far-a', -9000, 40), node('far-b', -5000, 40)]
    previous = node('previous', 1200, 40)
    assert next_output_position([*far, previous]) == {'x': 1548, 'y': 40}


def test_clear_right_slot_does_not_reserve_an_invisible_480px_height():
    below = node('lower-row', 388, 400)
    previous = node('previous', 40, 40)
    assert next_output_position([below, previous], node('new', 0, 0, height=150)) == {'x': 388, 'y': 40}


def test_large_web_outputs_wrap_nearby_and_rows_use_tallest_node():
    page = {'id': 'page', 'position': {'x': 100, 'y': 200}, 'data': {'kind': 'html'}}
    assert next_output_position([page], page) == {'x': 100, 'y': 928}
    row = [node('a', 40, 40, height=440, kind='html'), node('b', 388, 40), node('c', 736, 40)]
    assert next_output_position(row) == {'x': 40, 'y': 568}


def test_portrait_asset_height_matches_loaded_preview_when_wrapping():
    portrait = {'id': 'portrait', 'position': {'x': 40, 'y': 40}, 'data': {'kind': 'image',
        'asset': {'mime': 'image/png', 'metadata': {'imageOutput': {'width': 600, 'height': 1200}}}}}
    assert node_height(portrait) == 640
    assert next_output_position([portrait, node('b', 388, 40), node('c', 736, 40)]) == {'x': 40, 'y': 728}


def test_blocked_lower_slots_stay_collision_free():
    obstacles = [node('right', 388, 40, height=1400, kind='html'), node('below', 40, 428, kind='html')]
    previous = node('previous', 40, 40)
    position = next_output_position([*obstacles, previous], node('incoming', 0, 0))
    assert position == {'x': 40, 'y': 816}
    assert position['y'] >= obstacles[1]['position']['y'] + node_height(obstacles[1]) + GAP


def test_production_notes_extend_node_footprint_below_image():
    image = node('image', 40, 40)
    noted = {**image, 'data': {**image['data'], 'productionNotes': ['成品尺寸待确认', '材质与表面工艺待确认']}}
    assert node_height(noted) > node_height(image)


def test_only_explicit_user_request_allows_concept_notice_inside_image():
    assert not explicit_image_disclaimer_requested('先做一张概念示意图')
    assert not explicit_image_disclaimer_requested('尺寸还没确定')
    assert explicit_image_disclaimer_requested('请在图片右下角标注“概念示意”')
    prompt, negative = prepare_production_image_request('先做概念方向', allow_disclaimer=False)
    assert prompt == '先做概念方向' and negative == '额外说明角标、水印、占位文字'
    permitted, negative = prepare_production_image_request('右下角标注概念示意', allow_disclaimer=True)
    assert permitted == '右下角标注概念示意' and negative == ''


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    TaskRuntime(store)
    project = store.create_project(new_project(name='紧凑布局回归', slug='placement', brief='',
        budget_minor=None, currency='CNY', root_path=str(tmp_path / 'placement')))
    canvas, assets = CanvasStore(store), AssetStore(store)
    return project['id'], canvas, assets, DesignToolRegistry(store, canvas_store=canvas, asset_store=assets)


@pytest.mark.parametrize('stored_label', [None, ''])
def test_unlabeled_edge_delete_reload_and_restore(workspace, stored_label):
    project_id, canvas, _, _ = workspace
    source = canvas.create_node(project_id, kind='text', title='source', data={'text': 'preserved source'})
    target = canvas.create_node(project_id, kind='image', title='target')
    edge = canvas.link_nodes(project_id, source_node_id=source['id'], target_node_id=target['id'])
    if stored_label is not None:
        canvas.apply_changes(project_id, {'upsertEdges': [{'id': edge['id'], 'label': stored_label}]})
    before = canvas.load(project_id)
    expected = {**edge, 'label': '', 'animated': False}
    canvas.apply_changes(project_id, {'removeEdgeIds': [edge['id']], 'expectedEdges': {edge['id']: expected}})
    reopened = CanvasStore(canvas.store)
    assert reopened.load(project_id)['edges'] == []
    assert reopened.load(project_id)['nodes'] == before['nodes']
    reopened.apply_changes(project_id, {'upsertEdges': [edge], 'expectedEdges': {edge['id']: None}})
    assert CanvasStore(canvas.store).load(project_id)['edges'] == [edge]


def test_unlabeled_edge_conflict_guard_keeps_real_concurrent_edits(workspace):
    project_id, canvas, _, _ = workspace
    source = canvas.create_node(project_id, kind='text', title='source')
    target = canvas.create_node(project_id, kind='image', title='target')
    edge = canvas.link_nodes(project_id, source_node_id=source['id'], target_node_id=target['id'])
    canvas.apply_changes(project_id, {'upsertEdges': [{'id': edge['id'], 'label': 'new label'}]})
    with pytest.raises(CanvasConflict):
        canvas.apply_changes(project_id, {'removeEdgeIds': [edge['id']], 'expectedEdges': {edge['id']: {**edge, 'label': ''}}})
    assert canvas.load(project_id)['edges'][0]['label'] == 'new label'


@pytest.mark.parametrize('tool,args', [
    ('canvas_create_node', {'kind': 'image', 'title': '待生成'}),
    ('canvas_create_text', {'title': '交付文案', 'text': '内容'}),
    ('canvas_create_html', {'title': '网页', 'html': '<main>网页</main>'}),
    ('canvas_create_media', {}),
])
def test_all_agent_creation_paths_ignore_speculative_coordinates_but_ui_keeps_them(workspace, tool, args):
    project, canvas, assets, tools = workspace
    previous = canvas.create_node(project, kind='image', title='上一张', position={'x': 1200, 'y': 800})
    if tool == 'canvas_create_media':
        asset = assets.add_bytes(project_id=project, kind='image', filename='sample.png', content=b'fixture')
        args = {'asset_id': asset['id']}
    result = tools.execute(project_id=project, task_id='agent-task', name=tool, arguments={**args, 'x': 9000, 'y': -6000})
    expected = {'x': 1968, 'y': 800}
    assert result['node']['position'] == expected
    assert canvas.load(project)['nodes'][0]['position'] == previous['position']
    manual = tools.execute(project_id=project, task_id=None, name=tool, arguments={**args, 'x': 2500, 'y': 2500})
    assert manual['node']['position'] == {'x': 2500, 'y': 2500}


def test_two_generations_keep_loading_placeholders_and_finished_outputs_adjacent(workspace):
    project, canvas, assets, tools = workspace
    from app.task_runtime import TaskRuntime
    from test_conversation_context import add_turn
    TaskRuntime(tools.store)
    for identity in ('first','second'):add_turn(tools.store,identity,'',project=project,status='running')
    observed = []

    def generate(**kwargs):
        board = canvas.load(project)['nodes']
        observed.append(board[-1])
        assert board[-1]['data']['generating'] is True
        return b'test-image'

    tools.provider_registry = SimpleNamespace(image=lambda *a, **kw: SimpleNamespace(generate=generate))
    first = tools.execute(project_id=project, task_id='first', name='generate_image', arguments={'prompt': '图标', 'model': 'fixture'})
    second = tools.execute(project_id=project, task_id='second', name='generate_image', arguments={'prompt': 'Logo', 'model': 'fixture'})
    assert first['node']['position'] == observed[0]['position'] == {'x': 40, 'y': 40}
    assert second['node']['position'] == observed[1]['position'] == {'x': 808, 'y': 40}
    assert len(canvas.load(project)['nodes']) == 2
    assert all(not n['data']['generating'] for n in canvas.load(project)['nodes'])


def test_image_is_kept_clean_and_missing_parameters_are_saved_below_node(workspace):
    project, canvas, _, tools = workspace
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return b'test-image'

    tools.provider_registry = SimpleNamespace(image=lambda *a, **kw: SimpleNamespace(generate=generate))
    result = tools.execute(project_id=project, task_id=None, name='generate_image', arguments={
        'prompt': '生成可生产使用的船舶外观效果图',
        'negative_prompt': '模糊',
        'model': 'fixture',
        'production_notes': ['  船体最终尺寸待确认  ', '材质与表面工艺待确认', '船体最终尺寸待确认'],
    })
    assert captured['prompt'] == '生成可生产使用的船舶外观效果图'
    assert captured['negative_prompt'].startswith('模糊，')
    assert '额外说明角标' in captured['negative_prompt']
    notes = ['船体最终尺寸待确认', '材质与表面工艺待确认']
    assert result['productionNotes'] == notes
    assert result['node']['data']['productionNotes'] == notes
    assert result['asset']['metadata']['productionNotes'] == notes
    assert result['asset']['metadata']['negativePrompt'] == captured['negative_prompt']


def test_new_media_sizes_match_renderer_and_leave_legacy_and_explicit_sizes_intact(workspace):
    project, canvas, _, _ = workspace
    old = node('legacy', -500, -600, width=320, height=240)
    canvas.save(project, {'nodes': [old], 'edges': []})
    created = canvas.create_node(project, kind='image', title='大图', data={'params': {'aspectRatio': '2:3'}})
    assert created['data']['previewSizingVersion'] == 2
    assert node_preview_size(created['data']) == {'width': 720, 'height': 1080}
    assert node_preview_size({'kind': 'image', 'previewSizingVersion': 2}) == {'width': 720, 'height': 405}
    assert node_preview_size({'kind': 'image'}) == {'width': 300, 'height': 169}
    assert node_preview_size({**created['data'], 'previewSize': {'width': 500, 'height': 320}}) == {'width': 500, 'height': 750}
    assert canvas.load(project)['nodes'][0] == old


def test_automatic_nodes_reflow_when_earlier_markdown_outgrows_its_placeholder(workspace):
    project, canvas, _, _ = workspace
    intro = canvas.create_node(project, kind='text', title='方案说明', data={'text': ''})
    canvas.create_node(project, kind='image', title='视觉一')
    canvas.create_node(project, kind='image', title='视觉二')
    trailing = canvas.create_node(project, kind='image', title='视觉三')
    original_position = dict(trailing['position'])
    canvas.update_node(project, intro['id'], {'data': {'text': '# 方案说明\n\n' + ('这是一段需要完整展示的设计说明。' * 90)}})
    document = canvas.load(project)
    updated = next(item for item in document['nodes'] if item['id'] == trailing['id'])
    assert updated['position'] != original_position
    for current in document['nodes']:
        others = [item for item in document['nodes'] if item['id'] != current['id']]
        assert not nodes_colliding(others, current, current['position'])


def test_manual_alignment_survives_save_growth_and_new_automatic_nodes(workspace):
    project, canvas, _, _ = workspace
    first = canvas.create_node(project, kind='text', title='Alignment anchor', data={'text': ''})
    second = canvas.create_node(project, kind='image', title='Aligned image')
    positions = {first['id']: {'x': 40, 'y': 40}, second['id']: {'x': 40, 'y': 350}}
    canvas.apply_changes(project, {'upsertNodes': [
        {'id': identity, 'position': position, 'data': {'autoPositioned': False}}
        for identity, position in positions.items()
    ]})
    # User alignment may intentionally leave less space than automatic layout.
    canvas.update_node(project, first['id'], {'data': {'text': 'Long text. ' * 1000}})
    added = canvas.create_node(project, kind='image', title='New automatic image')
    saved = canvas.load(project)
    fixed = [n for n in saved['nodes'] if n['id'] in positions]
    assert {n['id']: n['position'] for n in fixed} == positions
    assert all(n['data']['autoPositioned'] is False for n in fixed)
    assert added['data']['autoPositioned'] is True
    assert not nodes_colliding(fixed, added, added['position'])
