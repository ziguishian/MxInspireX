import json
from pathlib import Path

import pytest

from app.design_state import _validated_review_revision
from app.image_reference_design import DesignSpecError, compile_design_spec
from app.main import new_project
from app.reference_library import ReferenceError, ReferenceLibraryStore
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA


def direction():
    return {
        'audience': '首次拥有家庭茶礼的年轻送礼者', 'theme': '山间清饮', 'coreConcept': '将茶山等高线收拢为盒面的留白',
        'visualHierarchy': ['品名、系列名与饮用场景三级阅读'], 'formLanguage': ['低矮横向礼盒、转角圆润'],
        'materialProcess': ['本色纸、凹压与局部烫银'], 'colorRelationships': ['雾青主色对温白留白'],
        'compositionLighting': ['正交略带低角度柔光'], 'avoid': ['不使用虚假文字或过量叠纹'],
        'evidence': [{'source': 'user', 'use': '用户指定为送礼茶礼盒'}],
    }


def image_spec():
    return {
        'subjectStructure': '低矮横向硬盒，盒盖与盒身分缝清晰', 'formProportion': '3:2 横向比例，盒体高度不超过宽度的三分之一',
        'materialConstruction': '粗纹本色纸包装，山线为凹压，品名局部烫银', 'compositionFraming': '正交略带上方微俯视，留出三分之一的桌面空白',
        'lightSurface': '左上方大面积柔光，纸纤维和凹压边缘可见', 'preserve': ['品名主位置与盒体比例'],
        'avoid': ['盒体不合理拼接、塑料反光、重复山纹和伪文字'], 'variationAxis': '用山线密度而非换主色区分系列',
    }


def test_design_spec_is_compiled_locally_and_rejects_generic_details():
    context = {'designPlan': {'visualDirection': direction(), 'deliverables': [{'id': 'box', 'title': '茶礼盒主视觉', 'kind': 'image', 'imageSpec': image_spec()}]}}
    result = compile_design_spec(context, {'itemIds': ['box']}, {'prompt': '为茶礼盒拍摄产品视觉'})
    assert result['prompt'] == '为茶礼盒拍摄产品视觉\n保留：品名主位置与盒体比例'
    assert result['_design_spec']['imageSpec'] == image_spec()
    assert result['_design_spec']['direction'] == direction()
    assert '伪文字' in result['negative_prompt']
    assert result['_design_spec']['itemId'] == 'box'
    invalid = image_spec()
    invalid['lightSurface'] = '高级感'
    context['designPlan']['deliverables'][0]['imageSpec'] = invalid
    with pytest.raises(DesignSpecError, match='imageSpec'):
        compile_design_spec(context, {'itemIds': ['box']}, {'prompt': '产品图'})


def test_confirmed_revision_is_bound_to_saved_error_and_workspace_lesson(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='审查修订', slug='revision', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'revision')))
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
        structured = {'structured_data': {'delivery': {'artifacts': [{'nodeId': 'node-a', 'assetId': 'asset-a', 'fingerprint': 'v1', 'ready': True, 'kind': 'image'}]},
            'review': {'checks': [{'status': 'error', 'category': 'ai_artifact', 'artifactId': 'node-a', 'code': 'review_ai_artifact_error', 'repair': {'change': '去除盒侧的伪文字', 'preserve': ['盒体比例']}}]}}}
        db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,output_json,created_at,updated_at) VALUES ('review',?,'design','design','succeeded',?,?, 'now','now')",
                   (project['id'], json.dumps({'designPlan': {'ready': True, 'deliverables': []}}, ensure_ascii=False), json.dumps(structured, ensure_ascii=False)))
    source, revision = _validated_review_revision(store, project['id'], {'sourceTaskId': 'review', 'nodeId': 'node-a', 'code': 'review_ai_artifact_error', 'artifactFingerprint': 'v1'})
    assert source['id'] == 'review' and revision['sourceAssetId'] == 'asset-a'
    with pytest.raises(ValueError, match='版本已变化'):
        _validated_review_revision(store, project['id'], {'sourceTaskId': 'review', 'nodeId': 'node-a', 'code': 'review_ai_artifact_error', 'artifactFingerprint': 'old'})
    library = ReferenceLibraryStore(store)
    library.record_confirmed_revision(revision)
    lessons = library.search_lessons(media_kind='image', limit=3)
    assert len(lessons) == 1 and lessons[0]['tags'] == ['ai_artifact']
    library.delete_lesson(lessons[0]['id'])
    assert library.search_lessons(media_kind='image') == []


def test_lesson_library_refuses_private_prompt_or_asset_data(tmp_path):
    store = ProjectStore(str(tmp_path))
    library = ReferenceLibraryStore(store)
    with pytest.raises(ReferenceError, match='原始提示词'):
        library.add_lesson({'mediaKind': 'image', 'tags': ['材质'], 'strategy': 'prompt: 保密要求', 'avoid': []})


def test_design_quality_blindset_has_fixed_coverage_and_conditions():
    fixture = Path(__file__).parent / 'fixtures' / 'design_quality_blindset.json'
    dataset = json.loads(fixture.read_text(encoding='utf-8'))
    cases = dataset['cases']
    categories = {case['category'] for case in cases}
    assert len(cases) == 12
    assert {'packaging', 'cultural_creative', 'brand_key_visual', 'product_photography', 'space_wayfinding', 'local_edit'} <= categories
    assert dataset['fixedRun']['repetitionsPerChain'] == 2
    assert all(case['constraints'] and case['reviewFocus'] and case['referenceSelection'] for case in cases)
