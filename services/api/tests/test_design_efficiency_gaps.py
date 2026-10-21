import json
from unittest.mock import Mock

import pytest

from app.reference_efficiency import optional_simple_reference
from app.reference_workflow import ReferenceWorkflow
from app.reference_library import ReferenceLibraryStore
from app.application_inventory import prepare_inventory, render_inventory
from test_design_execution import env, plan, BRIEF


def task_context(store, task, **values):
    with store._connect() as db:
        context = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task,)).fetchone()[0])
        context.update(values)
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context, ensure_ascii=False), task))


def test_empty_optional_references_continue_without_card_or_repeated_search(env, monkeypatch):
    store, project, _, tools, enqueue, call = env
    task = enqueue('设计一张咖啡店海报', allowExternalNetwork=True)
    task_context(store, task, executionPolicyVersion=2, designPlanning=None,
                 singleDeliveryTarget={'count': 1, 'kind': 'image'})
    search = Mock(return_value={'items': []})
    monkeypatch.setattr(ReferenceLibraryStore, 'search', search)
    web = Mock(side_effect=AssertionError('可选原创设计不应发起付费联网搜索'))
    monkeypatch.setattr(tools, 'web_search', web)
    workflow = ReferenceWorkflow(store, tools.asset_store)
    assert workflow.preflight(tools, project, task) is None
    assert tools._task_input(project, task)['referenceWorkflow']['status'] == 'unavailable'
    assert call(task, 'reference_search', query='换个关键词')['status'] == 'ready'
    assert call(task, 'request_reference_selection', items=[])['awaitingUser'] is False
    assert search.call_count == 1
    assert web.call_count == 0
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM reference_selections WHERE task_id=?', (task,)).fetchone()[0] == 0


def test_required_references_still_wait_and_identical_search_is_cached(env, monkeypatch):
    store, project, _, tools, enqueue, call = env
    task = enqueue('先找参考，设计一张咖啡店海报', allowExternalNetwork=False)
    task_context(store, task, executionPolicyVersion=2, designPlanning=None,
                 singleDeliveryTarget={'count': 1, 'kind': 'image'})
    search = Mock(return_value={'items': []})
    monkeypatch.setattr(ReferenceLibraryStore, 'search', search)
    first = call(task, 'reference_search', query='咖啡海报')
    again = call(task, 'reference_search', query='咖啡海报')
    assert first['items'] == again['items'] == [] and again['cached']
    assert search.call_count == 1
    assert call(task, 'request_reference_selection', items=[])['awaitingUser']
    assert tools._task_input(project, task)['referenceWorkflow']['status'] == 'required'


@pytest.mark.parametrize('extra', [
    {'referencedAssets':[{'id':'asset'}]}, {'referencedFiles':[{'id':'document'}]},
    {'canvasParams':{'source_asset_id':'asset'}}, {'referenceWorkflow':{'query':'按照参考图设计'}},
    {'referenceWorkflow':{'query':'结合最新趋势设计海报'}},
    {'designPlan':{'ready':True,'deliverables':[{'id':str(i),'kind':'image'} for i in range(3)]}},
])
def test_fallback_does_not_weaken_references_or_complex_scope(extra):
    assert not optional_simple_reference({'executionPolicyVersion':2, 'userMessage':'设计一张海报',
        'singleDeliveryTarget':{'count':1,'kind':'image'}, **extra})


def test_negative_research_is_not_an_explicit_reference_requirement():
    assert optional_simple_reference({'executionPolicyVersion':2,
        'userMessage':'创建一个网页，不做研究，不需要图片或外部素材。',
        'singleDeliveryTarget':{'count':1,'kind':'html'}})


def test_no_research_skips_external_discovery_but_preserves_product_dependencies(env):
    from app.reference_workflow import skips_references
    from test_mixed_delivery_scope import PLAN
    _,project,_,tools,enqueue,call=env
    task=enqueue('生成两张同款产品图片和一张文字卡，第二张沿用第一张产品原图，不做研究或审查。')
    assert tools._task_input(project,task)['referenceWorkflow']['status']=='skipped'
    result=call(task,'design_plan',plan=PLAN)
    assert result['plan']['deliverables'][1]['inputs'][0]['role']=='identity'
    assert not skips_references('不做研究，但先搜索参考，再制作场景图')
    assert not skips_references('海报标题为“不做研究”，设计一张海报')


def test_empty_search_before_plan_is_reused_after_plan_is_ready(env, monkeypatch):
    store, project, _, tools, enqueue, call = env
    task = enqueue('设计品牌标志和应用清单', allowExternalNetwork=False)
    search = Mock(return_value={'items':[]})
    monkeypatch.setattr(ReferenceLibraryStore, 'search', search)
    call(task, 'reference_search', query='品牌案例')
    task_context(store, task, executionPolicyVersion=2,
                 designPlan={'ready':True,'deliverables':[{'id':'logo','kind':'image'},{'id':'list','kind':'text'}]},
                 designBatch={'status':'ready','itemIds':['logo','list']})
    assert ReferenceWorkflow(store, tools.asset_store).preflight(tools, project, task) is None
    assert search.call_count == 1


ITEMS = [{'title':'标志概念','detail':'用于确认方向','priority':'recommended','deliverable_id':'outer'},
         {'title':'社交头像','detail':'确认标志后适配','priority':'recommended'},
         {'title':'展会物料','detail':'参加活动时制作','priority':'optional'}]


def test_inventory_status_uses_saved_artifacts_and_does_not_change_after_review(env):
    store, project, _, tools, enqueue, call = env
    task = enqueue(BRIEF + '。跳过参考')
    value = plan()
    value['deliverables'][2]['title'] = '品牌应用清单'
    assert call(task, 'design_plan', plan=value)['status'] == 'ready'
    result = call(task, 'canvas_create_text', text='范围与制作优先级。', title='应用清单',
                  application_items=ITEMS, deliverable_ids=['budget'])
    node_id = result['node']['id']
    assert '暂无其他已生成产物' in result['node']['data']['text']
    image = call(task, 'generate_image', prompt='外盒概念', provider='local-placeholder', deliverable_ids=['outer'])
    before = call(task, 'delivery_verify')
    node = next(n for n in tools.canvas_store.load(project)['nodes'] if n['id'] == node_id)
    text = node['data']['text']
    assert text.count('标志概念') == 1
    delivered, future = text.split('## 建议后续制作')
    assert '标志概念' in delivered and '社交头像' in future and '## 按需选配' in future
    assert call(task, 'delivery_verify')['artifacts'] == before['artifacts']
    tools.canvas_store.update_node(project, node_id, {'data':{'text':'用户手动修改的清单'}})
    call(task, 'delivery_verify')
    assert next(n for n in tools.canvas_store.load(project)['nodes'] if n['id'] == node_id)['data']['text'] == '用户手动修改的清单'


def test_inventory_rejects_invented_completion_and_keeps_ordinary_text():
    context = {'designPlan':{'deliverables':[{'id':'list','kind':'text','title':'品牌应用清单'}]}}
    assert prepare_inventory(None, '普通文字', context, None) is None
    with pytest.raises(ValueError):
        prepare_inventory(None, '清单', context, {'itemIds':['list']})
    with pytest.raises(ValueError):
        prepare_inventory([{'title':'不存在的图','priority':'recommended','deliverable_id':'invented'}], '', context, None)
    with pytest.raises(ValueError):
        prepare_inventory([{'title':'虚构完成','priority':'delivered'}], '', context, None)
    inventory = {'intro':'范围', 'items':[{'title':'图像','detail':'','priority':'recommended','deliverable_id':'image'}]}
    report = {'artifacts':[{'nodeId':'n','kind':'image','ready':False}], 'deliverables':[{'id':'image','nodeIds':['n']}]}
    assert '- 图像' not in render_inventory(inventory,report).split('## 建议后续制作')[0]


def test_duplicate_freeform_inventory_is_not_rendered_twice_and_caveats_survive():
    context = {'designPlan':{'deliverables':[{'id':'logo','kind':'image','title':'标志'}]}}
    items = [{'title':'Logo','detail':'本轮已交付：概念，不是印刷定稿','priority':'recommended','deliverable_id':'logo'},
             {'title':'头像','detail':'建议后续制作：适配小尺寸','priority':'recommended'}]
    text = '只交付概念。\n\n## 本轮已交付\n- Logo：概念\n\n## 建议后续制作\n- 头像：适配小尺寸\n\n注：实际尺寸需要后续确认。'
    inventory = prepare_inventory(items, text, context, None)
    output = render_inventory(inventory, {'artifacts':[{'nodeId':'n','kind':'image','ready':True}],
        'deliverables':[{'id':'logo','title':'标志','nodeIds':['n']}]})
    assert output.count('## 本轮已交付') == output.count('## 建议后续制作') == 1
    assert output.count('- 头像') == output.count('- Logo') == 1
    assert '只交付概念' in output and '实际尺寸需要后续确认' in output and '不是印刷定稿' in output
    assert inventory['sourceText'] == text
    assert '本轮已交付：' not in output


def test_inventory_itself_counts_as_a_saved_delivery():
    inventory = {'intro':'只交付清单', 'items':[{'title':'品牌应用清单','detail':'应用规划','priority':'recommended','deliverable_id':'list'},
        {'title':'头像','detail':'后续适配','priority':'recommended'}]}
    report = {'artifacts':[{'nodeId':'self','kind':'text','ready':True}],
        'deliverables':[{'id':'list','title':'品牌应用清单','nodeIds':['self']}]}
    output = render_inventory(inventory, report, 'self')
    delivered, future = output.split('## 建议后续制作')
    assert '品牌应用清单' in delivered and '品牌应用清单' not in future
    assert '头像' in future


def test_inspection_tracks_actual_file_changes_without_review_evidence(env):
    from app.delivery import DeliveryService
    from pathlib import Path
    from PIL import Image
    store, project, _, tools, enqueue, call = env
    task = enqueue('生成一张海报，不需要参考')
    result = call(task, 'generate_image', prompt='海报', provider='local-placeholder')
    service = DeliveryService(store, tools.asset_store, tools.canvas_store)
    first = service.inspect_task(project, task)
    task_context(store, task, transientAccounting={'updated':True})
    second = service.inspect_task(project, task)
    assert first['inspectionVersion'] != second['inspectionVersion']
    assert 'reviewEvidenceVersion' not in first and 'reviewCache' not in second
    asset = tools.asset_store.get_asset(project_id=project, asset_id=result['assetId'])
    with Image.open(asset['absolutePath']) as image:
        changed = Image.new('RGB', image.size, 'blue')
    changed.save(Path(asset['absolutePath']))
    third = service.inspect_task(project, task)
    assert third['inspectionVersion'] != second['inspectionVersion']
