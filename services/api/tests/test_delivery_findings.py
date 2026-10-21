import json
from io import BytesIO

import pytest
from PIL import Image

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.delivery import DeliveryService
from app.delivery_findings import annotate_delivery, collect_findings
from app.models import new_project
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='状态检查', slug='review', brief='', budget_minor=None,
        currency='CNY', root_path=str(tmp_path / 'review')))['id']
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
    assets, canvas = AssetStore(store), CanvasStore(store)
    return store, project, assets, canvas, DeliveryService(store, assets, canvas)


def image_node(workspace, title='包装'):
    _, project, assets, canvas, _ = workspace
    buffer = BytesIO()
    Image.new('RGB', (80, 100), 'white').save(buffer, 'PNG')
    asset = assets.add_bytes(project_id=project, kind='image', filename='box.png', content=buffer.getvalue())
    return canvas.ensure_asset_node(project, asset, task_id='task', title=title)


def test_known_spec_mismatch_and_fabrication_notes_remain_distinct(workspace):
    _, project, _, canvas, delivery = workspace
    node = image_node(workspace)
    canvas.update_node(project, node['id'], {'data': {'productionNotes': ['材质与工艺待确认']}})
    report = delivery.inspect(project, 'task', contract=[{'kind': 'image', 'width': 1024}])
    findings = collect_findings({'delivery': report})
    assert findings == []
    assert report['passed']
    assert canvas.load(project)['nodes'][0]['data']['productionNotes'] == ['材质与工艺待确认']


def test_unknown_outcome_keeps_contract_unpassed_without_suggesting_resubmission(workspace):
    _, project, _, canvas, delivery = workspace
    canvas.create_node(project, kind='image', title='生成中的图片', task_id='task', data={'status': '生成结果待确认', 'error': '超时'})
    report = delivery.inspect(project, 'task', required=['image'], contract=[{'kind': 'image', 'count': 1}])
    assert not report['passed']
    assert report['issues']
    assert {f['kind'] for f in report['findings']} == {'generation_unconfirmed'}
    assert all('核对前不要重新提交' in f['nextAction'] for f in report['findings'])


@pytest.mark.parametrize('code,kind', [('media_timeout', 'unverified'), ('media_transport', 'unverified'), ('media_decode', 'problem')])
def test_preview_failure_distinguishes_missing_evidence_from_decode_errors(workspace, code, kind):
    _, project, assets, canvas, delivery = workspace
    asset = assets.add_bytes(project_id=project, kind='video', filename='saved.mp4', content=b'saved-file')
    node = canvas.ensure_asset_node(project, asset, task_id='task')
    for _ in range(3):
        delivery.record_check(project, node['id'], delivery.fingerprint(node), {'passed': False, 'code': code, 'errors': ['预览未完成']})
    report = delivery.inspect(project, 'task', require_preview=True)
    assert not report['pendingPreview']
    assert report['findings'][0]['kind'] == kind
    assert '无需重新生成' in report['findings'][0]['nextAction']


@pytest.mark.parametrize('status', ['passed', 'failed', 'timed_out', 'unavailable'])
def test_legacy_review_does_not_block_saved_outputs_or_show_quality_findings(workspace, status):
    _, project, _, _, delivery = workspace
    image_node(workspace)
    report = delivery.inspect(project, 'task')
    report['findings'] = [{'kind':'unverified','code':'review_scope_limit','message':'尚未核实'}]
    report['issues'] = ['尚未核实']
    data = {'deliveryStatus':'needs_review','delivery':report,
            'review':{'status':status,'passed':False,'checks':[{'status':'error','message':'小字不清楚'}]}}
    assert annotate_delivery(data) == []
    assert 'review' not in data
    assert data['deliveryStatus'] == 'passed'
    assert data['answer'] == '作品已保存到右侧画布。'


def test_legacy_review_removal_preserves_real_missing_files(workspace):
    _, project, assets, _, delivery = workspace
    node = image_node(workspace)
    from pathlib import Path
    Path(assets.get_asset(project_id=project,asset_id=node['data']['assetId'])['absolutePath']).unlink()
    data = {'delivery':delivery.inspect(project,'task'),'review':{'passed':True}}
    findings = annotate_delivery(data)
    assert data['deliveryStatus'] == 'needs_review'
    assert any(item['code'] in {'file_missing','file_empty'} for item in findings)
    assert not data['delivery']['passed']
    assert data['answer'].startswith('本轮尚未保存作品。')
