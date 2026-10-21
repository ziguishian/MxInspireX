import copy
import io
import json

import pytest
from PIL import Image

from app.task_policy import delivery_contract, delivery_requirements, normalize_delivery_context
from app.design_planning import save_design_plan
from app.delivery import DeliveryService
from app.task_runtime import TaskRuntime
from app.svg_policy import ensure_task_policy
from test_delivery_contract import workspace, task


BRIEF = '为潮间设计 Logo，先生成 1 张 Logo 母版，再做杯子、手提袋和门头样机。共 4 张独立图片。不生成 SVG、HTML 排版页或 ZIP。'


def test_inventory_absence_and_explicit_no_generation_do_not_require_images():
    brief = '创建一个文本节点，整理品牌应用清单。本轮只交付这份清单，没有制作 Logo 或任何应用物料，不需要生成图片。'
    assert delivery_requirements(brief) == ['text']
    assert [item['kind'] for item in delivery_contract(brief)] == ['text']
    legacy = {'userMessage':brief, 'requiredArtifacts':['image','text'], 'deliveryContract':[{'kind':'image','count':1},{'kind':'text','count':1}]}
    assert normalize_delivery_context(legacy)['requiredArtifacts'] == ['text']
    for request in ['没有制作 Logo，请生成一个 Logo', '尚未制作海报，但现在需要一张海报',
                    '本轮没有制作 Logo，不需要生成图片。但请创建一个网页']:
        expected = ['html'] if '网页' in request else ['image']
        assert delivery_requirements(request) == expected


@pytest.mark.parametrize('exclusion', [
    '不生成 SVG、HTML 排版页或 ZIP。', '不要 SVG、HTML 或 ZIP。',
    '无需 SVG、HTML、ZIP。', '不需要生成 SVG, HTML 或 ZIP。',
    '不用 SVG/HTML/ZIP。', '禁止输出 SVG 和 HTML。',
    'SVG、HTML 均禁用。', 'Do not generate SVG, HTML or ZIP.',
    'No SVG, HTML or ZIP.', "Don't produce SVG or HTML.",
    '不生成 HTML 排版页、SVG 或 ZIP。',
])
def test_negative_lists_do_not_create_format_or_kind_requirements(exclusion):
    brief = '生成 4 张独立图片。' + exclusion
    assert delivery_requirements(brief) == ['image']
    assert delivery_contract(brief) == [{'kind': 'image', 'count': 4, 'transparent': False}]


@pytest.mark.parametrize('brief,kinds,fmt', [
    ('不要生成 SVG，但生成一张 PNG 图片和一个 HTML 网页', ['html', 'image'], 'png'),
    ('不要视频，生成一张图片', ['image'], None),
    ('生成一张 PNG 图片，不要 JPEG', ['image'], 'png'),
    ('生成网页，不要使用照片', ['html'], None),
    ('不需要网页。生成三张图片', ['image'], None),
    ('不用 HTML，改用图像模型生成图片', ['image'], None),
    ('不仅生成图片，还要生成网页', ['html', 'image'], None),
    ('Create an image without SVG, but create an HTML website', ['html', 'image'], None),
])
def test_positive_outputs_after_negations_still_required(brief, kinds, fmt):
    assert delivery_requirements(brief) == kinds
    images = [item for item in delivery_contract(brief) if item['kind'] == 'image']
    if images:
        assert images[0].get('format') == fmt


def legacy_context():
    plan = {'goal': '潮间品牌样机', 'preserve': [], 'deliverables': [
        {'id': f'image-{i}', 'title': f'图片 {i}', 'kind': 'image', 'acceptance': '独立图片、图案一致', 'representation': 'raster', 'blockingFields': [], 'dependsOn': []}
        for i in range(4)], 'coverage': [], 'deferred': [], 'openQuestions': [], 'research': '无需联网',
        'scopeId': 'task', 'version': 2, 'revision': 1, 'ready': True}
    plan['deliverables'].append({'id': 'html-not-applicable', 'title': 'HTML 排版页', 'kind': 'html', 'acceptance': '不生成', 'blockingFields': ['用户明确禁止 HTML'], 'dependsOn': []})
    contract = [{'kind': 'html', 'count': 1}, {'kind': 'image', 'count': 1, 'format': 'svg'}]
    return {'userMessage': BRIEF, 'deliveryContract': contract, 'requestedContract': copy.deepcopy(contract),
            'requiredArtifacts': ['html', 'image'], 'designPlan': plan}


def test_normalization_repairs_only_excluded_obligations_and_is_idempotent():
    original = legacy_context()
    snapshot = copy.deepcopy(original)
    fixed = normalize_delivery_context(original)
    assert original == snapshot
    assert normalize_delivery_context(fixed) == fixed
    assert fixed['userMessage'] == original['userMessage']
    assert fixed['requiredArtifacts'] == ['image']
    assert fixed['deliveryContract'] == fixed['requestedContract'] == [{'kind': 'image', 'count': 1}]
    assert fixed['designPlan']['deliverables'] == original['designPlan']['deliverables'][:4]
    assert delivery_contract(BRIEF, original) == [{'kind': 'image', 'count': 4, 'transparent': False}]
    positive = {'userMessage': '生成网页与 2 张 PNG 图片', 'deliveryContract': [{'kind': 'html', 'count': 1}, {'kind': 'image', 'count': 2, 'format': 'png'}]}
    assert normalize_delivery_context(positive) == positive


def test_continuation_keeps_exclusions_but_unrelated_new_tasks_do_not():
    continuation = {**legacy_context(), 'userMessage': '继续', 'continuation': {'taskId': 'original'}, 'designState': {'goal': BRIEF}}
    assert len(normalize_delivery_context(continuation)['designPlan']['deliverables']) == 4
    new_task = {'userMessage': '生成 HTML 网页', 'designState': {'goal': BRIEF}}
    assert delivery_requirements(new_task['userMessage'], new_task) == ['html']
    changed = {**continuation, 'userMessage': '继续，并生成 HTML 网页'}
    assert 'html' in delivery_requirements(changed['userMessage'], changed)


def test_new_task_and_plan_do_not_require_forbidden_html(workspace, monkeypatch):
    store, project, _, _ = workspace
    runtime = TaskRuntime(store)
    monkeypatch.setattr(runtime, '_start_worker', lambda *args: False)
    created = runtime.enqueue(project_id=project, agent_key='design', workflow_step='design', brief=BRIEF, run_async=True)
    with store._connect() as db:
        context = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (created['id'],)).fetchone()[0])
    assert context['requestedContract'] == [{'kind': 'image', 'count': 4, 'transparent': False}]
    plan = legacy_context()['designPlan']
    for key in ('scopeId', 'version', 'revision', 'ready'):
        plan.pop(key)
    with pytest.raises(ValueError, match='明确排除'):
        save_design_plan(store, project, created['id'], plan)
    plan['deliverables'] = plan['deliverables'][:4]
    assert save_design_plan(store, project, created['id'], plan)['status'] == 'ready'


def test_legacy_review_rechecks_real_pngs_and_preserves_missing_image_checks(workspace):
    store, project, assets, canvas = workspace
    context = legacy_context()
    task(store, project, context=context)
    for i in range(3):
        content = io.BytesIO()
        Image.new('RGB', (16, 16), (i * 40, 100, 150)).save(content, format='PNG')
        asset = assets.add_bytes(project_id=project, kind='image', filename=f'{i}.png', content=content.getvalue())
        canvas.create_node(project, kind='image', title=f'图片 {i}', task_id='task', asset_id=asset['id'],
                           data={'deliveryBinding': {'scopeId': 'task', 'itemIds': [f'image-{i}']}})
    delivery = DeliveryService(store)
    missing = delivery.inspect_task(project, 'task')
    assert not missing['passed']
    assert any('数量不足' in issue for issue in missing['issues'])
    assert all('html' not in issue.lower() and 'svg' not in issue.lower() for issue in missing['issues'])
    content = io.BytesIO()
    Image.new('RGB', (16, 16), (200, 100, 150)).save(content, format='PNG')
    asset = assets.add_bytes(project_id=project, kind='image', filename='3.png', content=content.getvalue())
    canvas.create_node(project, kind='image', title='图片 3', task_id='task', asset_id=asset['id'],
                       data={'deliveryBinding': {'scopeId': 'task', 'itemIds': ['image-3']}})
    before = canvas.load(project)
    passed = delivery.inspect_task(project, 'task')
    assert passed['passed'] and not passed['issues']
    assert len(passed['deliverables']) == 4
    ensure_task_policy(store, 'task')
    with store._connect() as db:
        saved = json.loads(db.execute("SELECT input_json FROM tasks WHERE id='task'").fetchone()[0])
    assert saved['requestedContract'] == [{'kind': 'image', 'count': 1}]
    assert len(saved['designPlan']['deliverables']) == 4
    assert canvas.load(project) == before
