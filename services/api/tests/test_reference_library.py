import io
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.agent_contracts import AgentResult
from app.reference_library import ReferenceError, ReferenceLibraryStore
from app.reference_analysis import ReferenceAnalyzer
from app.reference_network import import_page, PageImages, fetch_public
from app.reference_workflow import ReferenceWorkflow, parse_choice, skips_references


@pytest.mark.parametrize('text', ['无需寻找外部参考，直接完成设计', '不需要搜索新的参考', '不用找参考', '不必查找参考', '跳过参考', '请直接生成一张图片并放到画布，不需要联网研究。', '直接制作一张咖啡海报', '无需联网或参考选图，完成后保存画布', '不需要联网研究和搜索新的参考'])
def test_explicit_reference_opt_out(text):
    assert skips_references(text)
    assert parse_choice(text, {'id':'card'})['action']=='skip'


def test_direct_html_and_cad_do_not_force_reference_selection():
    assert skips_references('只用HTML/CSS，直接完成单页，不需要图片或外部素材。')
    assert skips_references('直接创建一个参数化CAD底座。')


@pytest.mark.parametrize('text', ['不要跳过参考', '不能跳过参考', '请勿跳过参考', '需要寻找外部参考', '请查看上传的参考图', '不要直接生成，先选参考', '文案是「直接生成」，设计一张海报', '先找参考，然后直接生成海报', '不要跳过参考，确认后直接生成', '无需联网，但先选择本地参考', '说明文字是「无需联网或参考选图」，请寻找参考'])
def test_reference_requirements_are_not_opt_out(text):
    assert not skips_references(text)


def png(color='red', size=(320, 240)):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as c:
        def ready_design(**kwargs):
            # Simulate the Agent deciding that this fixture's brief is ready
            # for visual selection. Runtime itself must not make that decision.
            if not kwargs['constraints'].get('referenceQuestion'):
                result = ReferenceWorkflow(app.state.store, app.state.assets).preflight(app.state.design_tools, kwargs['project_id'], kwargs['task_id'], kwargs['attachments'])
                if result:
                    return result
            return AgentResult(status='succeeded', structured_data={'answer': '已生成'})
        app.state.tasks.design_runtime = Mock(run=Mock(side_effect=ready_design))
        app.state.reference_analyzer.rank = lambda q, items, *args: items[:6]
        yield c


def project(client):
    return client.post('/api/projects', json={'name': '视觉设计', 'brief': '品牌礼盒'}).json()['id']


def add(client, color='red'):
    result = client.post('/api/references/upload', files=[('files', ('包装.png', png(color), 'image/png'))])
    assert result.status_code == 201, result.text
    return result.json()['items'][0]


def turn(client, pid, brief='设计一个茶叶包装礼盒', inputs=None):
    return client.post(f'/api/projects/{pid}/tasks', json={'agentKey': 'design', 'workflowStep': 'design', 'brief': brief, 'input': {'allowExternalNetwork': False, **(inputs or {})}})


@pytest.mark.parametrize('brief', ['请直接生成一张咖啡海报并放到画布，不需要联网研究。', '制作一张 Logo 和一份应用清单。无需联网或参考选图，完成后保存画布。'])
def test_direct_generation_does_not_search_or_request_reference_confirmation(client, brief):
    with patch('app.reference_workflow.reference_search', side_effect=AssertionError('unexpected reference search')):
        result = turn(client, project(client), brief, {'allowExternalNetwork': True}).json()
    assert result['status'] == 'succeeded', result
    assert not result['output']['structured_data'].get('referenceSelection')
    assert app.state.tasks.design_runtime.run.call_args.kwargs['constraints']['referenceWorkflow']['status'] == 'skipped'


def test_upload_validation_classification_and_persistent_search(client):
    item = add(client)
    assert add(client)['id'] == item['id']
    bad = client.post('/api/references/upload', files=[('files', ('bad.png', b'not an image', 'image/png'))]).json()
    assert not bad['items'] and bad['errors']
    update = client.patch('/api/references/' + item['id'], json={'industries': ['茶酒礼赠'], 'designTypes': ['包装礼盒'], 'tags': ['绿色', '留白'], 'description': '极简现代茶叶礼盒'}).json()
    assert update['industries'] == ['茶酒礼赠']
    result = client.get('/api/references', params={'q': '帮我找绿色茶叶的极简包装', 'industry': '茶酒礼赠'}).json()
    assert [i['id'] for i in result['items']] == [item['id']]
    assert client.get(item['thumbnailUrl']).headers['content-type'] == 'image/jpeg'
    assert ReferenceLibraryStore(app.state.store).get(item['id'])['tags'] == ['绿色', '留白']
    assert client.post('/api/references/categories', json={'dimension': 'industry', 'name': '船舶交通'}).status_code == 200


def test_tall_reference_thumbnail_preserves_complete_aspect_ratio(client):
    response = client.post('/api/references/upload', files=[('files', ('长图.png', png(size=(120, 900)), 'image/png'))])
    assert response.status_code == 201, response.text
    item = response.json()['items'][0]
    assert (item['width'], item['height']) == (120, 900)
    with Image.open(app.state.references.path(item['id'], True)) as thumbnail:
        assert thumbnail.size == (96, 720)


def test_global_reference_project_copies_and_delete_independence(client):
    item = add(client)
    a, b = project(client), project(client)
    library = app.state.references
    first = library.project_asset(a, item['id'], app.state.assets)
    assert library.project_asset(a, item['id'], app.state.assets)['id'] == first['id']
    second = library.project_asset(b, item['id'], app.state.assets)
    assert second['id'] != first['id']
    library.delete(item['id'])
    for pid, asset in [(a, first), (b, second)]:
        assert Path(app.state.assets.get_asset(project_id=pid, asset_id=asset['id'])['absolutePath']).read_bytes() == png()


def test_analysis_preserves_user_edits_and_recovers_interrupted(client):
    item = add(client)
    app.state.references.update(item['id'], {'title': '我的标题', 'tags': ['手动标签']})
    adapter = Mock(complete=Mock(return_value=json.dumps({'title': '模型标题', 'tags': ['AI标签'], 'description': '红色块构图'})))
    with patch('app.reference_analysis.visual_adapter', return_value=adapter):
        app.state.reference_analyzer.analyze(item['id'])
    result = app.state.references.get(item['id'])
    assert result['title'] == '我的标题' and result['tags'] == ['手动标签']
    assert result['description'] == '红色块构图' and result['analysisStatus'] == 'ready'
    with app.state.store._connect() as db:
        db.execute("UPDATE visual_references SET analysis_status='running' WHERE id=?", (item['id'],))
    ReferenceAnalyzer(app.state.references, None)
    assert app.state.references.get(item['id'])['analysisStatus'] == 'interrupted'


def test_real_page_images_only_and_cached_not_saved(client):
    html = b'<title>Tea packaging</title><meta property="og:image" content="https://cdn.example.com/p.png"><img src="/bad.jpg"><script type="application/ld+json">{"image":"https://cdn.example.com/p.png"}</script>'
    def fetch(url, **kwargs):
        if url.endswith('/project'): return html, 'text/html', url
        if url.endswith('p.png'): return png(), 'image/png', url
        return b'no image', 'image/jpeg', url
    with patch('app.reference_network.fetch_public', side_effect=fetch):
        result = import_page(app.state.references, 'https://example.com/project', saved=False)
    assert len(result['items']) == 1 and result['errors']
    assert result['items'][0]['sourceUrl'] == 'https://example.com/project'
    assert client.get('/api/references').json()['total'] == 0
    app.state.references.save(result['items'][0]['id'])
    assert client.get('/api/references').json()['total'] == 1


@pytest.mark.parametrize('url', ['http://127.0.0.1/x', 'http://169.254.169.254/x', 'file:///etc/passwd'])
def test_downloader_rejects_nonpublic_sources(url):
    with pytest.raises(ValueError):
        fetch_public(url)


def test_generation_waits_then_confirm_inherits_actual_images_and_goal(client):
    a, b = add(client), add(client, 'blue')
    pid = project(client)
    first = turn(client, pid).json()
    assert first['status'] == 'succeeded', first
    card = first['output']['structured_data']['referenceSelection']
    assert len(card['items']) == 2
    assert app.state.tasks.design_runtime.run.call_count == 1
    response = turn(client, pid, '按选择继续设计', {'referenceSelection': {'id': card['id'], 'action': 'confirm', 'selected': [{'id': a['id'], 'aspects': ['配色']}, {'id': b['id'], 'aspects': ['构图']}]}})
    assert response.status_code == 201, response.text
    second = response.json()
    assert second['status'] == 'succeeded', second
    call = app.state.tasks.design_runtime.run.call_args.kwargs
    assert len([a for a in call['attachments'] if a.get('mime', '').startswith('image/')]) == 2
    workflow = call['constraints']['referenceWorkflow']
    assert workflow['status'] == 'selected' and len(workflow['assetIds']) == 2
    assert call['constraints']['designState']['goal'] == '设计一个茶叶包装礼盒'
    assert {a['assetId'] for a in call['attachments'] if a.get('assetId')} == set(workflow['assetIds'])
    replay = turn(client, pid, '按选择继续设计', {'referenceSelection': {'id': card['id'], 'action': 'confirm', 'selected': [{'id': a['id'], 'aspects': ['配色']}, {'id': b['id'], 'aspects': ['构图']}]}}).json()
    assert replay['id'] == second['id']
    assert app.state.tasks.design_runtime.run.call_count == 2


def test_requirements_precede_reference_selection_and_answers_survive_both_steps(client):
    item = add(client)
    pid = project(client)
    ready = app.state.tasks.design_runtime.run.side_effect
    questions = [
        {'id':'product','question':'是什么类型的杯子？','options':['陶瓷杯','玻璃杯']},
        {'id':'usage','question':'包装主要用于什么场景？','options':['零售','礼赠']},
        {'id':'delivery','question':'希望交付哪些内容？','options':['概念效果图','结构和包装方案'],'multi':True},
    ]
    def decide(**kwargs):
        if not kwargs['constraints'].get('clarificationContinuation'):
            card = app.state.design_tools.request_clarification(project_id=pid, task_id=kwargs['task_id'], questions=questions)
            return AgentResult(status='succeeded', structured_data={'clarification':card})
        return ready(**kwargs)
    app.state.tasks.design_runtime.run.side_effect = decide
    with patch('app.reference_workflow.reference_search', side_effect=AssertionError('clarify before searching')):
        first = turn(client, pid, '为我的杯子设计一个包装').json()
    assert first['status'] == 'succeeded', first
    assert first['output']['structured_data']['clarification']['questions']
    assert not first['output']['structured_data'].get('referenceSelection')
    second = turn(client, pid, '根据补充信息继续原任务', {'clarificationTaskId':first['id'], 'clarificationAnswers':[
        {'questionId':q['id'],'questionIndex':i,'value':v,'skipped':False}
        for i,(q,v) in enumerate(zip(questions,['陶瓷杯','礼赠','概念效果图']))]}).json()
    assert second['status'] == 'succeeded', second
    card = second['output']['structured_data']['referenceSelection']
    third = turn(client, pid, '按参考继续', {'referenceSelection':{'id':card['id'],'action':'confirm','selected':[{'id':item['id']}]}}).json()
    data = app.state.design_tools._task_input(pid, third['id'])
    assert data['designState']['goal'] == '为我的杯子设计一个包装'
    assert {v['value'] for v in data['designState']['decisions'].values() if isinstance(v.get('value'), str)} >= {'陶瓷杯','礼赠','概念效果图'}


def test_requirement_answers_after_visual_choice_keep_selected_images(client):
    item = add(client); pid = project(client)
    card = turn(client, pid).json()['output']['structured_data']['referenceSelection']
    questions = [{'id':'size','question':'杯子尺寸是多少？','options':[]}]
    app.state.tasks.design_runtime.run.side_effect = lambda **kw: AgentResult(status='succeeded', structured_data={'clarification':app.state.design_tools.request_clarification(project_id=pid,task_id=kw['task_id'],questions=questions)})
    selected = turn(client, pid, '按参考继续', {'referenceSelection':{'id':card['id'],'action':'confirm','selected':[{'id':item['id']}]}}).json()
    before = app.state.design_tools._task_input(pid, selected['id'])
    app.state.tasks.design_runtime.run.side_effect = lambda **kw: AgentResult(status='succeeded', structured_data={'answer':'继续设计'})
    reply = turn(client, pid, '尺寸尚不确定，先看概念', {'clarificationTaskId':selected['id'],'clarificationAnswers':[{'questionId':'size','questionIndex':0,'value':'','skipped':True}]}).json()
    assert reply['status'] == 'succeeded', reply
    after = app.state.design_tools._task_input(pid, reply['id'])
    assert after['referenceWorkflow'] == before['referenceWorkflow']
    assert after['referencedAssets'] == before['referencedAssets']
    assert after['designState']['decisions']['dimensions']['status'] == 'skipped'


def test_refresh_skip_and_free_text_scoped_choices(client):
    add(client); add(client, 'blue')
    pid = project(client)
    card = turn(client, pid).json()['output']['structured_data']['referenceSelection']
    parsed = parse_choice('第2张的配色，第1张的排版', card)
    assert parsed['selected'][0]['aspects'] == ['色彩关系'] and parsed['selected'][1]['aspects'] == ['排版字体']
    assert parse_choice('第6张', card) is None
    next_card = turn(client, pid, '换一批', {'referenceSelection': {'id': card['id'], 'action': 'refresh'}}).json()['output']['structured_data']['referenceSelection']
    assert not next_card['items']
    assert app.state.tasks.design_runtime.run.call_count == 2
    skipped = turn(client, pid, '跳过参考', {'referenceSelection': {'id': next_card['id'], 'action': 'skip'}}).json()
    assert skipped['status'] == 'succeeded'
    assert app.state.tasks.design_runtime.run.call_args.kwargs['constraints']['referenceWorkflow']['status'] == 'skipped'


def test_untrusted_selection_and_missing_image_rejected(client):
    item = add(client); pid = project(client)
    card = turn(client, pid).json()['output']['structured_data']['referenceSelection']
    foreign = turn(client, project(client), inputs={'referenceSelection': {'id': card['id'], 'action': 'skip'}})
    assert foreign.status_code == 400
    invalid = turn(client, pid, inputs={'referenceSelection': {'id': card['id'], 'action': 'confirm', 'selected': [{'id': 'invented'}]}})
    assert invalid.status_code == 400
    client.delete('/api/references/' + item['id'])
    missing = turn(client, pid, inputs={'referenceSelection': {'id': card['id'], 'action': 'confirm', 'selected': [{'id': item['id']}]}})
    assert missing.status_code == 400
    assert app.state.tasks.design_runtime.run.call_count == 1


def test_upload_into_choice_and_reopen_keeps_candidates(client):
    pid = project(client)
    first = turn(client, pid).json()
    card = first['output']['structured_data']['referenceSelection']
    result = client.post(f'/api/references/selections/{card["id"]}/upload', params={'project_id': pid}, files=[('files', ('my.png', png(), 'image/png'))])
    assert result.status_code == 200, result.text
    saved = client.get(f'/api/projects/{pid}/tasks/{first["id"]}').json()
    assert len(saved['output']['structured_data']['referenceSelection']['items']) == 1
    final = turn(client, pid, '第1张的配色').json()
    assert final['status'] == 'succeeded', final
    assert app.state.tasks.design_runtime.run.call_count == 2


def test_gate_and_network_disabled_apply_to_tool_calls(client):
    add(client); pid = project(client)
    with patch.object(app.state.tasks, '_start_worker', return_value=True):
        task = client.post(f'/api/projects/{pid}/tasks', json={'agentKey': 'design', 'workflowStep': 'design', 'brief': '设计包装', 'async': True, 'input': {'allowExternalNetwork': False, 'referenceWorkflow': {'status': 'selected'}}}).json()
    with patch.object(app.state.design_tools, 'web_search', side_effect=AssertionError('network disabled')):
        result = app.state.design_tools.execute(project_id=pid, task_id=task['id'], name='generate_image', arguments={'prompt': '礼盒'})
    assert result['status'] == 'reference_selection_required'
    assert result['referenceSelection']['items']
    assert not app.state.assets.list_assets(pid)


def test_legacy_images_migrate_once_and_text_is_explicit_only(client):
    knowledge = app.state.knowledge
    knowledge.ingest_global_file(filename='old.png', content=png())
    knowledge.ingest_global_text(path_relative='facts.txt', text='旧报价和工艺文本')
    app.state.references.migrate(knowledge)
    assert client.get('/api/references').json()['total'] == 1
    identity = client.get('/api/references').json()['items'][0]['id']
    client.delete('/api/references/' + identity)
    app.state.references.migrate(knowledge)
    assert client.get('/api/references').json()['total'] == 0
    assert len(knowledge.list_global_documents()) == 2
    assert not knowledge.vector_search_for_project(project_id=project(client), query='报价')


@pytest.mark.parametrize('legacy_plan', [False, True])
def test_selected_images_are_analyzed_and_aspects_reach_generation_as_inspiration(client, legacy_plan):
    from types import SimpleNamespace
    from app.conversation_memory import ConversationMemoryService
    a, b = add(client), add(client, 'blue')
    pid = project(client)
    card = turn(client, pid, '生成一张包装图片').json()['output']['structured_data']['referenceSelection']
    completed = turn(client, pid, '第1张的配色，第2张的构图').json()
    task_id = completed['id']
    registry = app.state.design_tools
    context = registry._task_input(pid, task_id)
    ids = context['referenceWorkflow']['assetIds']
    memory = ConversationMemoryService(app.state.store)
    memory.update(pid, task_id, {'expected_revision': memory.read(pid, task_id)['revision'], 'selected_ids': ['asset:'+i for i in ids]}, 'select-visual-inputs')
    from app.design_planning import save_design_plan
    plan = {'goal':'包装设计', 'preserve':[], 'deliverables':[{'id':'cup','title':'包装图','kind':'image','acceptance':'使用两张参考',
        'inputs':[{'source':'asset','id':('asset:' if index == 0 else '@asset:') + identity,'purpose':'保留参考偏好'} for index,identity in enumerate(ids)]}],
        'coverage':[], 'deferred':[], 'openQuestions':[], 'research':'用户已提供参考'}
    saved_plan = save_design_plan(app.state.store, pid, task_id, plan)['plan']
    assert [ref['id'] for ref in saved_plan['deliverables'][0]['inputs']] == ids
    if legacy_plan:
        with app.state.store._connect() as db:
            data = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task_id,)).fetchone()[0])
            for ref in data['designPlan']['deliverables'][0]['inputs']:
                ref['id'] = 'asset:' + ref['id']
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data), task_id))
    requests = []
    def generate(**params):
        requests.append(params)
        assert 'source_asset_path' not in params and 'source_asset_paths' not in params
        assert '纯色背景、简洁构图' in params['prompt']
        assert '视觉反推描述' not in params['prompt'] and '用户确认的参考偏好' not in params['prompt']
        assert all(identity not in params['prompt'] for identity in ids)
        return png('green')
    with patch.object(registry.provider_registry, 'image', return_value=SimpleNamespace(generate=generate, api='images')):
        arguments = {'prompt':'产品包装，纯色背景、简洁构图，品名居中，侧面留白。', 'output_mode':'create', 'provider':'local-placeholder', 'source_asset_ids':['asset:'+i for i in ids],
                     'reference_analysis':{'images':[{'asset_id':identity,'mode':'inspiration','visual_prompt':'纯色画面，简洁构图',
                         'use':'借鉴配色和构图','avoid':'旧主体与文字'} for identity in ids], 'synthesis':'围绕用户包装需求重新组织内容和配色'}}
        checked = registry.execute(project_id=pid, task_id=task_id, name='generation_reference_check', arguments={'operations':[{'tool':'generate_image','arguments':arguments}]})
        assert checked['status'] == 'ready', checked
        result = registry.execute(project_id=pid, task_id=task_id, name='generate_image', arguments=arguments)
    assert result.get('assetId'), result
    assert result['asset']['metadata']['referenceSnapshot']['visualDirection']['choices'] == context['referenceWorkflow']['choices']
    assert set(result['asset']['metadata']['sourceAssetIds']) == set(ids)
    assert result['asset']['metadata']['providerInputAssetIds'] == []
    assert len(requests) == 1
    assert all(choice['assetId'] in ids for choice in context['referenceWorkflow']['choices'])
    app.state.references.delete(a['id'])
    assert all(Path(app.state.assets.get_asset(project_id=pid, asset_id=i)['absolutePath']).is_file() for i in ids)


def test_text_questions_and_nonimage_attachments_do_not_bypass_visual_gate(client):
    from app.reference_workflow import wants_visual
    for brief in ['品牌设计包含什么内容？', '怎么选择包装材质？', '解释品牌视觉规范']:
        assert not wants_visual(brief, {})
    pid = project(client)
    asset = app.state.assets.add_bytes(project_id=pid, kind='text', filename='brief.txt', content=b'brief')
    response = turn(client, pid, inputs={'referencedAssets':[{'id':asset['id']}], 'referenceCandidates':['fake']}).json()
    assert 'referenceSelection' in response['output']['structured_data']
    assert 'fake' not in app.state.design_tools._task_input(pid, response['id']).get('referenceCandidates', [])


def test_batch_preflight_and_canvas_target_do_not_inject_unselected_candidates(client):
    add(client); pid = project(client)
    first = turn(client, pid).json()
    checked = app.state.design_tools.execute(project_id=pid, task_id=first['id'], name='generation_reference_check', arguments={'operations':[{'tool':'generate_image','arguments':{'prompt':'包装'}}]})
    assert checked['status'] == 'reference_selection_required'
    final = turn(client, pid, '第1张').json()
    registry = app.state.design_tools
    context = registry._task_input(pid, final['id'])
    node = registry.canvas_store.create_node(pid, kind='image', title='新图', data={})
    context['canvasParams'] = {'kind':'image', 'canvasNodeId':node['id'], 'source_asset_ids':[]}
    with app.state.store._connect() as db:
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context), final['id']))
    arguments = registry._focused_arguments(pid, final['id'], 'generate_image', {'prompt':'包装'})
    assert arguments['source_asset_ids'] == []
    chosen = registry._focused_arguments(pid, final['id'], 'generate_image', {'prompt':'包装', 'source_asset_ids':context['referenceWorkflow']['assetIds']})
    assert chosen['source_asset_ids'] == context['referenceWorkflow']['assetIds']


def test_online_search_downloads_real_candidates_then_can_be_adopted(client):
    pid = project(client)
    with patch.object(app.state.design_tools, 'web_search', return_value={'sources':[{'url':'https://example.com/project','title':'茶叶礼盒'}]}) as search, patch('app.reference_network.fetch_public', side_effect=lambda url, **kw: (b'<img src="https://example.com/tea.png">','text/html',url) if url.endswith('/project') else (png(),'image/png',url)):
        first = turn(client, pid, inputs={'allowExternalNetwork':True}).json()
    search.assert_called_once()
    card = first['output']['structured_data']['referenceSelection']
    assert len(card['items']) == 1 and not card['items'][0]['saved']
    assert client.get(card['items'][0]['contentUrl']).content == png()
    turn(client, pid, '第1张配色')
    assert app.state.references.get(card['items'][0]['id'])['saved']


def test_question_during_selection_preserves_pending_batch_and_chosen_state(client):
    add(client); pid = project(client)
    first = turn(client, pid).json()
    card = first['output']['structured_data']['referenceSelection']
    question = turn(client, pid, '怎么选择包装材质？').json()
    assert not question['output']['structured_data'].get('referenceSelection')
    assert app.state.tasks.design_runtime.run.call_count == 2
    chosen = turn(client, pid, '第1张的配色').json()
    context = app.state.design_tools._task_input(pid, chosen['id'])
    assert context['referenceWorkflow']['status'] == 'selected'
    assert context['referenceWorkflow']['selectionId'] == card['id']
    restored = client.get(f'/api/projects/{pid}/tasks/{first["id"]}').json()['output']['structured_data']['referenceSelection']
    assert restored['selected'][0]['aspects'] == ['色彩关系'] and restored['submittedAction'] == 'confirm'
    for text in ['第12张', '第0张', '第1张或者第2张', '不要第1张']:
        assert parse_choice(text, card) is None


def test_visual_relevance_shortfall_triggers_online_supplement(client):
    for color in ['red','green','blue','yellow','purple','orange']:
        add(client, color)
    pid = project(client)
    app.state.reference_analyzer.rank = lambda q, items, *args: [i for i in items if i.get('sourceType') == 'web'][:6]
    with patch.object(app.state.design_tools, 'web_search', return_value={'sources':[{'url':'https://example.com/project'}]}) as search, patch('app.reference_network.fetch_public', side_effect=lambda url, **kw: (b'<img src="https://example.com/new.png">','text/html',url) if url.endswith('/project') else (png('pink'),'image/png',url)):
        result = turn(client, pid, inputs={'allowExternalNetwork':True}).json()
    search.assert_called_once()
    assert len(result['output']['structured_data']['referenceSelection']['items']) == 1


def test_general_industries_lead_and_existing_industry_references_survive(client):
    item = add(client)
    library = app.state.references
    with app.state.store._connect() as db:
        db.execute("DELETE FROM reference_migrations WHERE source_id='taxonomy:primary-industries-v1'")
        db.execute("DELETE FROM reference_categories WHERE dimension='industry' AND name IN ('文旅','船舶')")
        db.execute("INSERT INTO reference_categories VALUES ('legacy-tourism','industry','文旅景区')")
        db.execute("INSERT INTO reference_categories VALUES ('legacy-ships','industry','船舶')")
        db.execute('UPDATE visual_references SET metadata_json=? WHERE id=?', (json.dumps({'industries':['文旅景区','自定义行业'],'tags':['手动标签'],'userEditedFields':['industries','tags']}), item['id']))
    restarted = ReferenceLibraryStore(app.state.store)
    industries = [c for c in restarted.categories() if c['dimension'] == 'industry']
    assert [c['name'] for c in industries[:2]] == ['科技数码', '消费零售']
    assert next(c for c in industries if c['name'] == '文旅')['id'] == 'legacy-tourism'
    assert next(c for c in industries if c['name'] == '船舶')['id'] == 'legacy-ships'
    assert restarted.get(item['id'])['industries'] == ['文旅', '自定义行业']
    assert restarted.get(item['id'])['tags'] == ['手动标签']
    assert restarted.search(industry='文旅')['total'] == restarted.search(industry='文旅景区')['total'] == 1
    restarted.category('industry', '自定义行业')
    again = ReferenceLibraryStore(app.state.store)
    assert [c['name'] for c in again.categories() if c['dimension'] == 'industry'][:2] == ['科技数码', '消费零售']
    assert sum(c['name'] == '船舶' for c in again.categories()) == 1
