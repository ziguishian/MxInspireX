import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.design_tools import DesignToolRegistry
from app.node_prompt import literal_prompt
from app.image_output import prepare_image_output
from app.prompt_templates import PromptTemplateStore, retrieve_templates
from test_canvas_interactions import workspace
from test_canvas_node_tasks import node_runtime, node_input


def test_node_submission_persists_literal_text(node_runtime):
    store, project, canvas, runtime = node_runtime
    target = canvas.create_node(project, kind='image', title='target')
    prompt = '  原文\n'
    inputs = node_input(project, target['id'])
    inputs['nodePrompt'] = {'version': 1, 'original': '原文', 'submitted': prompt}
    task = runtime.enqueue(project_id=project, agent_key='design', workflow_step='design', brief=prompt, input_data=inputs, run_async=True)
    with store._connect() as db:
        saved = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task['id'],)).fetchone()[0])
    assert saved['nodePrompt']['submitted'] == prompt
    assert saved['nodePrompt']['original'] == '原文'


def test_published_prompt_uses_final_payload_and_known_template_ids(workspace):
    project, store, canvas, assets = workspace
    tools = DesignToolRegistry(store)
    events = []
    tools.trace = lambda *args: events.append(args)
    context = {'promptTemplates': {'candidates': [{'id': 'known'}]}}
    with patch.object(tools, '_task_input', return_value=context):
        tools._publish_prompt(project, 'task', '图像', '最终\n提示词', ['known', 'invented'])
    assert events[0][1] == 'generation_prompt'
    assert events[0][2] == '图像提示词：\n最终\n提示词'
    assert events[0][3] == {'templateIds': ['known']}
    with patch.object(tools, '_task_input', return_value={'taskSurface': 'canvas_node'}):
        tools._publish_prompt(project, 'task', '图像', 'node')
    assert len(events) == 1


def test_real_worker_media_branch_never_calls_text_model(tmp_path):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    payload = {'apiKey': 'unused', 'model': 'fixture-model', 'baseUrl': 'http://fixture.invalid/v1',
        'toolGateway': {'baseUrl': 'http://fixture.invalid', 'projectId': 'project', 'taskId': 'task'},
        'context': {'projectId': 'project', 'taskId': 'task', 'brief': ' 原样\n', 'constraints': {
            'taskSurface': 'canvas_node', 'nodePrompt': {'version': 1, 'submitted': ' 原样\n'},
            'canvasParams': {'kind': 'image', 'canvasNodeId': 'target'}, 'agentCollaboration': False}}}
    run = subprocess.run(['node', '--import', './services/api/tests/fixtures/literal_node_transport.mjs',
        'services/api/app/openai_agent_worker.mjs'], cwd=root, input=json.dumps(payload),
        capture_output=True, text=True, encoding='utf-8', timeout=40)
    events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith('{')]
    assert run.returncode == 0, run.stderr + run.stdout
    assert any(event['type'] == 'result' for event in events), run.stdout
    assert not any(event['type'] == 'error' for event in events), run.stdout


def test_literal_image_reaches_provider_unchanged(workspace):
    project, store, canvas, assets = workspace
    target = canvas.create_node(project, kind='image', title='output')
    source = assets.add_bytes(project_id=project, kind='image', filename='source.png', content=b'original-image')
    prompt = '  原样中文。\n不要更换配色！  '
    context = {'taskSurface': 'canvas_node', 'nodePrompt': {'version': 1, 'submitted': prompt},
        'canvasParams': {'canvasNodeId': target['id'], 'kind': 'image', 'model': 'gpt-image-2.5-sunburst',
                         'source_asset_ids': [source['id']],
                         'aspectRatio': '1:1', 'quality': 'low', 'background': 'opaque', 'style': '不应隐藏追加'}}
    seen = []
    provider = SimpleNamespace(image=lambda *a, **k: SimpleNamespace(generate=lambda **args: seen.append(args) or b'fake-image'))
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets, provider_registry=provider)
    with patch.object(tools, '_task_input', return_value=context):
        result = tools.execute(project_id=project, task_id='task', name='generate_image', arguments={'prompt': 'model rewrite'})
    assert result['status'] == 'succeeded'
    assert seen[0]['prompt'] == prompt
    assert not seen[0]['negative_prompt']
    assert seen[0]['quality'] == 'low'
    assert seen[0]['source_asset_paths'] == [assets.get_asset(project_id=project, asset_id=source['id'])['absolutePath']]
    assert literal_prompt.get() is False


def test_literal_video_preserves_prompt_and_parameters(workspace):
    project, store, canvas, assets = workspace
    target = canvas.create_node(project, kind='video', title='output')
    prompt = '  镜头不要移动。\n'
    context = {'taskSurface': 'canvas_node', 'nodePrompt': {'version': 1, 'submitted': prompt},
        'canvasParams': {'canvasNodeId': target['id'], 'kind': 'video', 'model': 'fixture-video',
                         'duration': 7, 'style': '已可见合并', 'camera': '已可见合并'}}
    seen = []
    registry = SimpleNamespace(video=lambda *a, **k: SimpleNamespace(generate=lambda **args: seen.append(args) or {'content': b'video', 'extension': 'mp4'}))
    tools = DesignToolRegistry(store, canvas_store=canvas, asset_store=assets, provider_registry=registry)
    with patch.object(tools, '_task_input', return_value=context):
        result = tools.execute(project_id=project, task_id='task', name='generate_video', arguments={'prompt': 'rewritten'})
    assert result['status'] == 'submitted'
    assert seen[0]['prompt'] == prompt
    assert seen[0]['model'] == 'fixture-video'
    assert seen[0]['duration'] == 7


def test_literal_transparency_does_not_append_or_repair():
    token = literal_prompt.set(True)
    try:
        prompt, params = prepare_image_output(' 原文\n', {'background': 'transparent', 'output_format': 'png'})
        assert prompt == ' 原文\n'
        assert params['background'] == 'transparent'
        with pytest.raises(ValueError):
            prepare_image_output('原文', {'background': 'transparent', 'output_format': 'jpeg'})
    finally:
        literal_prompt.reset(token)


def test_empty_templates_skip_index_and_nodes_skip_store(tmp_path):
    with patch('app.prompt_templates.LocalVectorIndex', side_effect=AssertionError('must not open')):
        assert PromptTemplateStore(tmp_path).search('海报') == []
    with patch.object(PromptTemplateStore, 'search', side_effect=AssertionError('must not search')):
        retrieve_templates(tmp_path, '海报', {'taskSurface': 'canvas_node'}, lambda *a: None)


def test_templates_search_limit_and_errors(tmp_path):
    templates = PromptTemplateStore(tmp_path)
    for i in range(4):
        templates.upsert({'id': str(i), 'text': f'海报设计 {i}', 'kind': 'image', 'styles': ['排版'], 'source': 'user'})
    assert len(templates.search('海报设计')) == 3
    constraints, events = {}, []
    retrieve_templates(tmp_path, '海报', constraints, lambda *a: events.append(a))
    assert len(constraints['promptTemplates']['candidates']) == 3
    templates.catalog.write_text('invalid json', encoding='utf-8')
    constraints = {}
    retrieve_templates(tmp_path, '海报', constraints, lambda *a: events.append(a))
    assert not constraints
    assert '失败' in events[-1][1]
