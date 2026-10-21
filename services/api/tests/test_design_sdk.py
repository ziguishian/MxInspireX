import json
import os
import shutil
import subprocess
import sys
import pytest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry
from app.main import app, new_project
from app.storage import ProjectStore
from app import design_runtime
from app.providers.registry import ProviderRegistry

API_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def run_worker(tmp_path, *, fail=False, policy=None, model="fixture-model", api=None, expected_api="chat_completions", expected_effort="omit", network=False, planning=False, parallel=False, batching=False, batch_failure=False, refining=False, steering=False):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name="SDK 集成验证", slug="sdk", brief="船舶设计", budget_minor=None, currency="CNY", root_path=str(tmp_path / "sdk")))
    from io import BytesIO
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (20, 20), '#236b78').save(image, format='PNG')
    asset = AssetStore(store).add_bytes(project_id=project["id"], kind="image", filename="ship.png", content=image.getvalue())
    env = {**os.environ, "PYTHONPATH": str(API_ROOT), "FIXTURE_PYTHON": sys.executable,
           "FIXTURE_TOOL_SCRIPT": str(FIXTURES / "agent_tool_fixture.py"), "FIXTURE_WORKSPACE": str(tmp_path),
           "FIXTURE_PROJECT": project["id"], "FIXTURE_ASSET": asset["id"], "FIXTURE_ERROR": "socket" if fail == 'socket' else "1" if fail else ""}
    env.update(FIXTURE_API=expected_api, FIXTURE_EFFORT=expected_effort, FIXTURE_NETWORK="1" if network else "")
    env['FIXTURE_PARALLEL'] = '1' if parallel else ''
    env['FIXTURE_PARALLEL_COUNT'] = str(2 if parallel is True else parallel or 0)
    env['FIXTURE_BATCH'] = '1' if batching else ''
    env['FIXTURE_BATCH_FAILURE'] = '1' if batch_failure else ''
    env['FIXTURE_DESIGN_BRIEF'] = json.dumps({'summary': '设计一套品牌视觉，交付品牌使用手册', 'assumptions': ['采用简洁现代风格'], 'openQuestions': []}, ensure_ascii=False) if refining else ''
    payload = {"api": api, "executionPolicy": policy or {}, "apiKey": "test-only-never-saved", "model": model, "baseUrl": "http://fixture.invalid/v1",
               "toolGateway": {"baseUrl": "http://fixture.invalid", "projectId": project["id"]},
               "context": {"projectId": project["id"], "brief": "展示设计图和说明", "constraints": {"agentCollaboration": False, "allowExternalNetwork": network, "conversation": [
                   {"role": "user", "content": "之前的设计约束"}, {"role": "assistant", "content": "已记住"},
                   {"role": "user", "content": "展示设计图和说明"}]}}}
    if planning:
        from app.task_runtime import TaskRuntime
        from app.design_planning import planning_guide
        runtime = TaskRuntime(store)
        runtime._start_worker = lambda *args: False
        task = runtime.enqueue(project_id=project['id'],agent_key='design',workflow_step='design',brief='设计一套品牌视觉',run_async=True)
        payload['toolGateway']['taskId'] = task['id']
        payload['context']['taskId'] = task['id']
        payload['context']['constraints']['designPlanning'] = planning_guide('brand')
        env['FIXTURE_DESIGN_PLAN'] = json.dumps({'goal':'按要求交付品牌使用手册','preserve':['保留用户要求'],
            'deliverables':[{'id':'guide','title':'品牌使用手册','kind':'text','acceptance':'包含定位、识别、应用和使用规范'}],
            'coverage':[{'area':area['id'],'status':'included','detail':'纳入使用手册'} for area in planning_guide('brand')['areas']],
            'deferred':[],'openQuestions':[],'research':'已有资料足够，无需联网'},ensure_ascii=False)
    if steering:
        env['FIXTURE_STEERING'] = '1'
        payload['toolGateway']['supportsTaskUpdates'] = True
    if parallel: payload['maxParallelTools'] = 1  # Legacy settings cannot serialize ready work.
    if batching:
        payload['context']['constraints']['designPlan'] = {'ready':True,'scopeId':'batch-scope','deliverables':[
            {'id':f'item-{i}','title':f'产物 {i}','kind':'image','acceptance':'独立方案','dependsOn':[]} for i in range(parallel)]}
    if not planning:
        # Tool preflight validates generation bindings against the durable
        # task, just as production does. Keep this SDK fixture realistic.
        from app.task_runtime import TASK_SCHEMA
        task_id = 'sdk-fixture'
        saved_input = {'userMessage':payload['context']['brief'], **payload['context']['constraints']}
        with store._connect() as db:
            db.executescript(TASK_SCHEMA)
            db.execute("INSERT INTO tasks(id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','running',?,'now','now')", (task_id, project['id'], json.dumps(saved_input, ensure_ascii=False)))
        payload['toolGateway']['taskId'] = task_id
        payload['context']['taskId'] = task_id
        env['FIXTURE_TASK'] = task_id
    worker = os.environ.get("AICS_TEST_WORKER") or str(API_ROOT / "app/openai_agent_worker.mjs")
    result = subprocess.run([shutil.which("node") or "node", "--import", (FIXTURES / "agent_transport.mjs").as_uri(), worker], input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, env=env, timeout=30)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    return result, events, CanvasStore(store).load(project["id"]), asset


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_refines_with_main_agent_then_passes_brief_to_planning(tmp_path, api):
    result, events, _, _ = run_worker(tmp_path, planning=True, refining=True, api=api, expected_api=api)
    assert result.returncode == 0, result.stderr + result.stdout
    final = next(event['result'] for event in events if event['type'] == 'result')
    outputs = final['tool_outputs']
    assert [item['name'] for item in outputs] == ['design_state', 'design_plan', 'canvas_create_text']
    assert outputs[0]['output']['state']['brief']['status'] == 'derived'
    assert outputs[0]['output']['state']['decisions']['scope']['value'] == '一套品牌视觉'


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_submits_independent_images_concurrently(tmp_path, api):
    result, events, _, _ = run_worker(tmp_path, parallel=True, api=api, expected_api=api)
    assert result.returncode == 0, result.stderr + result.stdout
    final = next(event['result'] for event in events if event['type'] == 'result')
    assert [call['name'] for call in final['tool_outputs']] == ['generate_image', 'generate_image']
    assert len({call['output']['assetId'] for call in final['tool_outputs']}) == 2


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
@pytest.mark.parametrize('count', [4, 7])
def test_sdk_redirects_serial_model_to_one_complete_batch(tmp_path, api, count):
    result, events, _, _ = run_worker(tmp_path, parallel=count, batching=True, api=api, expected_api=api)
    assert result.returncode == 0, result.stderr + result.stdout
    final = next(event['result'] for event in events if event['type']=='result')
    generated = [call for call in final['tool_outputs'] if call['name'] == 'generate_image']
    assert len(generated) == count
    assert len({call['output']['assetId'] for call in generated}) == count


@pytest.mark.parametrize('api', ['responses','chat_completions'])
def test_batch_keeps_other_outputs_and_records_one_provider_error(tmp_path, api):
    result, events, _, _ = run_worker(tmp_path, parallel=4, batching=True, batch_failure=True, api=api, expected_api=api)
    assert result.returncode == 0, result.stderr + result.stdout
    final=next(event['result'] for event in events if event['type']=='result')
    generated = [call for call in final['tool_outputs'] if call['name'] == 'generate_image' and call['output'].get('assetId')]
    assert len({call['output']['assetId'] for call in generated}) == 3
    assert 'HTTP 400' in result.stderr
    assert any(event.get('phase')=='error' for event in events)


@pytest.mark.parametrize("model,api,expected_api,effort", [
    ("gpt-6.1-sol", None, "responses", "high"),
    ("openai/gpt-6.1-sol", None, "responses", "high"),
    ("gpt-6-sol", None, "responses", "high"),
    ("openai/gpt-6-luna", None, "responses", "high"),
    ("gpt-6-luna", "chat_completions", "chat_completions", "none"),
    ("gpt-6-astra", None, "responses", "high"),
    ("openai/gpt-6-astra", None, "responses", "high"),
    ("gpt-6-astra", "chat_completions", "chat_completions", "none"),
    ("gpt-5.6-terra", None, "responses", "high"),
    ("gpt-5.6-sol", None, "responses", "high"),
    ("gpt-5.6-luna", "chat_completions", "chat_completions", "none"),
    ("claude-sonnet-4", None, "chat_completions", "omit"),
    ("gemini-2.5-pro", None, "chat_completions", "omit"),
])
def test_model_specific_tool_protocols(tmp_path, model, api, expected_api, effort):
    result, events, canvas, _ = run_worker(tmp_path, model=model, api=api, expected_api=expected_api,
        expected_effort=effort, policy={"reasoning_effort": "high"}, network=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert len(canvas["nodes"]) == 2
    final = next(event["result"] for event in events if event["type"] == "result")
    assert final["provenance"]["api"] == expected_api


def test_installed_sdk_streams_tools_session_and_real_canvas(tmp_path):
    result, events, canvas, asset = run_worker(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    final = next(event["result"] for event in events if event["type"] == "result")
    assert final["structured_data"]["answer"] == "设计资产已保存，可以继续修改。"
    usage_events = [event["usage"] for event in events if event["type"] == "usage"]
    assert len(usage_events) == 3
    assert sum(item["prompt_tokens"] for item in usage_events) == 30
    assert sum(item["prompt_tokens_details"]["cached_tokens"] for item in usage_events) == 6
    assert sum(item["prompt_tokens_details"]["cache_write_tokens"] for item in usage_events) == 3
    totals = [event['usageTotals'] for event in events if event['type']=='usage'][-1]
    assert totals['cached_tokens'] == 6 and totals['cache_write_tokens'] == 3
    assert totals['cache_observed_input_tokens'] == 30 and totals['cache_reported_requests'] == 3
    assert final["provenance"]["runtime"] == "openai-agents-sdk"
    assert final["provenance"]["sessionItemCount"] > 3
    assert any(event.get("phase") == "text" for event in events)
    assert [tool["name"] for tool in final["tool_outputs"]] == ["canvas_create_media", "canvas_create_text"]
    assert len(canvas["nodes"]) == 2 and canvas["edges"] == []
    assert canvas["nodes"][0]["data"]["assetId"] == asset["id"]
    assert canvas["nodes"][0]["position"] != canvas["nodes"][1]["position"]
    assert "test-only-never-saved" not in result.stdout + result.stderr


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_ignores_legacy_task_deadline(tmp_path, api):
    result, events, canvas, _ = run_worker(tmp_path, api=api, expected_api=api, policy={'timeout':.00001})
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr
    assert len(canvas['nodes']) == 2
    assert any(event['type'] == 'result' for event in events)


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_sdk_plans_before_creation_and_does_not_cache_blocked_generation(tmp_path, api):
    result, events, canvas, _ = run_worker(tmp_path, api=api, expected_api=api, planning=True)
    assert result.returncode == 0, result.stderr + result.stdout
    final = next(event['result'] for event in events if event['type']=='result')
    assert len(canvas['nodes']) == 1
    assert final['structured_data']['designPlan']['deliverables'][0]['title'] == '品牌使用手册'
    assert any(event.get('phase')=='progress' and '本轮设计计划' in event.get('message','') for event in events)
    assert [tool['name'] for tool in final['tool_outputs']] == ['canvas_create_text','design_plan','canvas_create_text']


def test_sdk_errors_are_reported_in_worker_protocol(tmp_path):
    result, events, canvas, _ = run_worker(tmp_path, fail=True)
    assert result.returncode != 0
    assert any(event["type"] == "error" and "测试模型不可用" in event["message"] for event in events)
    assert canvas["nodes"] == []


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_socket_disconnect_is_not_a_local_failure_or_safe_paid_retry(tmp_path, api):
    result, events, canvas, _ = run_worker(tmp_path, fail='socket', api=api, expected_api=api)
    assert result.returncode != 0
    error = next(event for event in events if event['type'] == 'error')
    assert error['kind'] == 'provider'
    assert error['submitted'] is True and error['billingCertainty'] == 'unknown'
    assert 'model_stream_interrupted' in error['message']
    failure = design_runtime.DesignRuntimeError(error['message'], kind=error['kind'], submitted=error['submitted'], billing_certainty=error['billingCertainty'])
    assert failure.retryable is False
    assert canvas['nodes'] == []


def test_openrouter_does_not_reuse_another_gateways_credential():
    class LegacyCredentials:
        def get(self, provider_key):
            return "legacy-gateway-only" if provider_key == "openai-compatible" else None

    registry = ProviderRegistry(credentials=LegacyCredentials())
    provider = next(item for item in registry.list() if item["key"] == "openrouter")
    assert provider["configured"] is False
    assert provider["credentialHint"] is None
    runtime = design_runtime.DesignRuntime(registry)
    with pytest.raises(design_runtime.DesignRuntimeError, match="未找到 openrouter 的本地 API Key"):
        runtime.run(project_id="test", task_id="test", agent_key="design", workflow_step="design",
                    brief="你好", constraints={}, retrieved_context=[], research_sources=[],
                    attachments=[], prior_outputs=[], provider_ref={"key": "openrouter"})


def test_parallel_canvas_tools_preserve_every_asset_node(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name="并行画布", slug="parallel", brief="资产排列", budget_minor=None, currency="CNY", root_path=str(tmp_path / "parallel")))
    canvas = CanvasStore(store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: canvas.create_node(project["id"], kind="text", title=str(index)), range(12)))
    nodes = canvas.load(project["id"])["nodes"]
    assert len(nodes) == 12
    assert len({(node["position"]["x"], node["position"]["y"]) for node in nodes}) == 12


def test_canvas_links_persist_handles_for_workflows(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name="工作流连接", slug="edges", brief="节点连接", budget_minor=None, currency="CNY", root_path=str(tmp_path / "edges")))
    canvas = CanvasStore(store)
    source = canvas.create_node(project["id"], kind="image", title="输入")
    target = canvas.create_node(project["id"], kind="video", title="输出")
    edge = canvas.link_nodes(project["id"], source_node_id=source["id"], target_node_id=target["id"], source_handle="output", target_handle="input")
    assert edge["sourceHandle"] == "output" and edge["targetHandle"] == "input"
    assert CanvasStore(store).load(project["id"])["edges"] == [edge]


def test_image_generation_creates_canvas_without_another_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "自动展示", "brief": "生成图像"}).json()
        prefix = f'/api/projects/{project["id"]}'
        response = client.post(f'{prefix}/agent-tools/generate_image', json={"prompt": "小狗", "provider": "local-placeholder"})
        assert response.status_code == 200, response.text
        generated = response.json()
        assert generated["node"]["data"]["assetId"] == generated["assetId"]
        assert client.get(f'{prefix}/assets/{generated["assetId"]}/content').status_code == 200
        for _ in range(2):
            assert len(client.get(f'{prefix}/canvas').json()["nodes"]) == 1
        # A model may still call the older explicit canvas tool. Reuse the
        # durable node and respect its requested placement instead of cloning it.
        reused = client.post(f'{prefix}/agent-tools/canvas_create_media', json={
            "asset_id": generated["assetId"], "title": "小狗形象", "x": 720, "y": 80,
        }).json()["node"]
        assert reused["id"] == generated["node"]["id"]
        assert reused["position"] == {"x": 720, "y": 80}
        assert len(client.get(f'{prefix}/canvas').json()["nodes"]) == 1


def test_canvas_backfills_only_missing_design_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "历史产物", "brief": "恢复"}).json()
        generated = app.state.assets.add_bytes(project_id=project["id"], kind="image", filename="dog.svg",
            content=b'<svg xmlns="http://www.w3.org/2000/svg"/>', metadata={"source": "design-agent-tool", "taskId": "old-turn"})
        app.state.assets.add_bytes(project_id=project["id"], kind="image", filename="upload.svg", content=b'<svg/>', metadata={"source": "user-upload"})
        for _ in range(2):
            canvas = client.get(f'/api/projects/{project["id"]}/canvas').json()
            assert len(canvas["nodes"]) == 1
            assert canvas["nodes"][0]["data"]["assetId"] == generated["id"]
            assert canvas["nodes"][0]["meta"]["taskId"] == "old-turn"


def test_video_content_is_placed_on_canvas_but_pending_jobs_are_not_marked_complete(tmp_path):
    from types import SimpleNamespace

    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name="视频展示", slug="video", brief="视频", budget_minor=None, currency="CNY", root_path=str(tmp_path / "video")))
    result = {"status": "submitted", "jobId": "video-job"}
    registry = SimpleNamespace(video=lambda *args, **kwargs: SimpleNamespace(generate=lambda **options: dict(result)))
    tools = DesignToolRegistry(store, asset_store=AssetStore(store), provider_registry=registry)
    pending = tools.generate_video(project_id=project["id"], task_id="video-turn", prompt="展示设计")
    assert pending["assetId"] is None and pending["node"] is None
    result.update(status="succeeded", content=b"video-fixture-bytes", extension="mp4")
    complete = tools.generate_video(project_id=project["id"], task_id="video-turn", prompt="展示设计")
    assert complete["node"]["data"]["kind"] == "video"
    assert complete["node"]["data"]["assetId"] == complete["assetId"]
    assert len(tools.canvas_store.load(project["id"])["nodes"]) == 1


def test_sse_replays_terminal_task_and_preserves_user_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "会话恢复", "brief": "最初的目标"}).json()
        from app.agent_contracts import AgentResult
        monkeypatch.setattr(app.state.tasks.design_runtime, 'run', lambda **kw: AgentResult(status='succeeded', structured_data={'answer':'完成'}))
        task = app.state.tasks.enqueue(project_id=project["id"], agent_key="design", workflow_step="design", brief="第二轮的修改目标")
        stream = client.get(f'/api/projects/{project["id"]}/tasks/{task["id"]}/events')
        assert stream.status_code == 200
        snapshot = json.loads(stream.text.split("data: ")[1].split("\n\n")[0])
        assert snapshot["userMessage"] == "第二轮的修改目标"
        assert snapshot["status"] == "succeeded"
        assert client.get(f'/api/projects/missing/tasks/{task["id"]}/events').status_code == 404


def test_worker_path_uses_source_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv("AICS_AGENT_WORKER", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    source_worker = design_runtime.resolve_worker_path()
    assert source_worker == API_ROOT / "app/openai_agent_worker.mjs"
    assert source_worker.is_file()
    # An explicit deployment path must not silently run a different version.
    requested_worker = tmp_path / "selected/openai_agent_worker.mjs"
    monkeypatch.setenv("AICS_AGENT_WORKER", str(requested_worker))
    assert design_runtime.resolve_worker_path() == requested_worker
    assert design_runtime.resolve_worker_path(source_worker) == source_worker


def test_worker_path_finds_frozen_package_data_without_source_or_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("AICS_AGENT_WORKER", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(design_runtime, "__file__", str(tmp_path / "missing/app/design_runtime.py"))
    extracted = tmp_path / "frozen/_internal"
    worker = extracted / "app/openai_agent_worker.mjs"
    worker.parent.mkdir(parents=True)
    worker.write_text("// frozen package data", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(extracted), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "frozen/aics-api"))
    monkeypatch.chdir(tmp_path)
    assert design_runtime.resolve_worker_path() == worker


def test_worker_path_finds_desktop_sibling_when_frozen_data_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("AICS_AGENT_WORKER", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    api_dir = tmp_path / "朗居设计Agent.app/Contents/Resources/app/services/api"
    monkeypatch.setattr(sys, "executable", str(api_dir / "sidecar/aics-api/aics-api"))
    monkeypatch.setattr(sys, "_MEIPASS", str(api_dir / "sidecar/aics-api/_internal"), raising=False)
    monkeypatch.setattr(design_runtime, "__file__", str(api_dir / "sidecar/aics-api/_internal/app/design_runtime.py"))
    worker = api_dir / "app/openai_agent_worker.mjs"
    worker.parent.mkdir(parents=True)
    worker.write_text("// adjacent standalone bundle", encoding="utf-8")
    assert design_runtime.resolve_worker_path() == worker


def test_sdk_ignores_legacy_cost_turn_limit_and_completes_tools(tmp_path):
    result, events, canvas, asset = run_worker(tmp_path, policy={"max_turns":1,"reasoning_effort":"low","parallelism":1})
    assert result.returncode == 0
    final = next(event['result'] for event in events if event['type'] == 'result')
    assert final['status'] == 'succeeded'
    assert final['structured_data']['deliveryStatus'] == 'passed'
    assert final['provenance']['recovery']['toolOutputs'][0]['name'] == 'canvas_create_media'
    assert len(canvas["nodes"]) == 2


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_running_supplement_reaches_subsequent_model_calls(tmp_path, api):
    result, events, _, _ = run_worker(tmp_path, steering=True, api=api, expected_api=api)
    assert result.returncode == 0, result.stderr + result.stdout
    assert any(event['type'] == 'result' for event in events)
