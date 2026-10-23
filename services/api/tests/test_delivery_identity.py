from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from app.execution_store import ExecutionStore
from app.task_policy import single_delivery_target
from test_design_execution import env


@pytest.mark.parametrize('kind,name,brief,data', [
    ('image', 'generate_image', '生成海报', {'assetId': 'asset'}),
    ('text', 'canvas_create_text', '创建文本节点', {'text': '正文'}),
    ('html', 'canvas_create_html', '制作网页', {'html': '<h1>作品</h1>'}),
    ('audio', 'generate_audio', '生成音频', {'assetId': 'asset'}),
    ('cad', 'generate_cad', '创建 CAD', {'cad': {'files': ['part.step']}}),
])
def test_semantic_single_delivery_reuses_changed_arguments_across_restart(env, kind, name, brief, data):
    task = env[4](brief)
    store = env[0]
    journal = env[3].executions
    fingerprint, _ = journal.claim(task, name, {'prompt': 'first'})
    result = {'status': 'succeeded', 'node': {'id': 'node', 'data': data}}
    journal.complete(task, fingerprint, result)
    alternate = 'generate_text' if kind == 'text' else name
    assert ExecutionStore(store).claim(task, alternate, {'prompt': 'rewritten', 'deliverable_ids': ['new-id']}) == (fingerprint, result)
    next_task = env[4](brief)
    assert journal.claim(next_task, name, {'prompt': 'first'})[1] is None


@pytest.mark.parametrize('continuation', [{}, {'continuation': {'taskId': 'previous'}},
    {'continuation': {'taskId': 'previous'}, 'clarificationContinuation': True, 'clarificationTaskId': 'previous'}])
def test_single_contract_does_not_depend_on_repeating_quantity_or_turn_type(continuation):
    context = {'deliveryContract': [{'kind': 'image', 'count': 1}], **continuation}
    assert single_delivery_target('背景换成米白色', context) == {'kind': 'image', 'count': 1, 'nodeId': None}
    assert single_delivery_target('换成米白色，并导出文件', context) is None


def test_same_delivery_in_parallel_only_has_one_owner(env):
    task = env[4]('生成一张海报')
    def claim(index):
        try:
            return env[3].executions.claim(task, 'generate_image', {'prompt': str(index)})
        except RuntimeError:
            return None
    with ThreadPoolExecutor(4) as pool:
        claims = list(pool.map(claim, range(4)))
    assert sum(item is not None for item in claims) == 1


def test_optional_plan_cannot_rename_a_completed_single_delivery(env):
    task = env[4]('生成一张海报')
    journal = env[3].executions
    fingerprint, _ = journal.claim(task, 'generate_image', {'prompt': 'first'})
    result = {'status': 'succeeded', 'assetId': 'a', 'node': {'id': 'a'}}
    journal.complete(task, fingerprint, result)
    data = env[3]._task_input(env[1], task)
    data['designPlan'] = {'ready': True, 'scopeId': 'new', 'deliverables': [{'id': 'renamed', 'kind': 'image'}]}
    with env[0]._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task))
    assert journal.claim(task, 'generate_image', {'prompt': 'again'}, resources=['delivery:new:renamed']) == (fingerprint, result)


def test_inpainting_and_generation_share_delivery_identity(env):
    task = env[4]('修改一张图片')
    journal = env[3].executions
    fingerprint, _ = journal.claim(task, 'image_edit', {'operation': 'inpaint', 'params': {'prompt': 'first'}})
    result = {'status': 'succeeded', 'assetId': 'a', 'node': {'id': 'a'}}
    journal.complete(task, fingerprint, result)
    assert journal.claim(task, 'generate_image', {'prompt': 'again'}) == (fingerprint, result)


def test_planned_deliveries_keep_distinct_identity_and_reuse_only_matching_item(env):
    task = env[4]('生成两张海报')
    journal = env[3].executions
    first, _ = journal.claim(task, 'generate_image', {'prompt': 'one'}, resources=['delivery:scope:a'])
    result = {'status': 'succeeded', 'assetId': 'a', 'node': {'id': 'a'}}
    journal.complete(task, first, result)
    assert journal.claim(task, 'generate_image', {'prompt': 'changed'}, resources=['delivery:scope:a']) == (first, result)
    second, previous = journal.claim(task, 'generate_image', {'prompt': 'two'}, resources=['delivery:scope:b'])
    assert second != first and previous is None


def test_rejected_preflight_can_retry_but_unknown_result_cannot(env):
    task = env[4]('生成海报')
    journal = env[3].executions
    first, _ = journal.claim(task, 'generate_image', {'prompt': 'invalid'})
    journal.reject(task, first)
    second, previous = journal.claim(task, 'generate_image', {'prompt': 'corrected'})
    assert previous is None and first != second
    unknown = {'status': 'generation_unconfirmed'}
    journal.complete(task, second, unknown)
    assert journal.claim(task, 'generate_image', {'prompt': 'third'}) == (second, unknown)


def test_acknowledged_steering_opens_one_new_revision_not_unlimited_generations(env):
    task = env[4]('生成海报')
    journal = env[3].executions
    first, _ = journal.claim(task, 'generate_image', {'prompt': 'first'})
    result = {'status': 'succeeded', 'assetId': 'a', 'node': {'id': 'a'}}
    journal.complete(task, first, result)
    with env[0]._connect() as db:
        db.execute('INSERT INTO task_updates VALUES (?,?,?,?,?,?,NULL)', (task, env[1], 'update', '改成蓝色', 1, 'now'))
    assert journal.claim(task, 'generate_image', {'prompt': 'premature'}) == (first, result)
    with env[0]._connect() as db:
        db.execute('UPDATE task_updates SET applied_at=? WHERE task_id=?', ('now', task))
    second, previous = journal.claim(task, 'generate_image', {'prompt': 'blue'})
    assert second != first and previous is None
    updated = {'status': 'succeeded', 'assetId': 'b', 'node': {'id': 'b'}}
    journal.complete(task, second, updated)
    assert journal.claim(task, 'generate_image', {'prompt': 'blue again'}) == (second, updated)


def test_multiple_images_require_inventory_without_silently_capping_count(env):
    task = env[4]('生成两张海报，不需要参考')
    response = env[5](task, 'generate_image', prompt='第一张')
    assert response['status'] == 'planning_required' and response['submitted'] is False
    assert env[3]._task_input(env[1], task)['deliveryContract'][0]['count'] == 2


@pytest.mark.parametrize('brief,count', [('生成一张产品图', 1), ('生成两张落地灯渲染图', 2), ('画三幅陶瓷器物展示图', 3),
    ('设计两款海报', 2), ('生成三枚 logo', 3)])
def test_image_quantifier_supports_descriptive_nouns_without_a_product_dictionary(env, brief, count):
    task = env[4](brief)
    data = env[3]._task_input(env[1], task)
    assert data['deliveryContract'][0]['count'] == count
    assert bool(data.get('singleDeliveryTarget')) == (count == 1)


@pytest.mark.parametrize('brief', ['设计一个 Logo 和包装', '制作海报与书签', 'Design a logo and packaging'])
def test_partial_kind_inference_never_truncates_a_compound_design_request(env, brief):
    task = env[4](brief)
    assert not env[3]._task_input(env[1], task).get('singleDeliveryTarget')
