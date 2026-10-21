import base64
import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.billing import calculate_cost
from app.model_config import EndpointModel, ModelPrice
from app.providers.registry import ProviderRegistry
from app.providers.http import ProviderError, OpenAICompatibleSpeechProvider


class Credentials:
    def get(self, key):
        return "fixture-key" if key in {"openai-compatible", "openrouter", "meshy"} else None


def test_closeai_sync_completes_omitted_models_only_after_api_confirmation(tmp_path, monkeypatch):
    import urllib.error
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    seen = []
    def upstream(request, timeout):
        seen.append(request.full_url)
        if request.full_url.endswith('/models'):
            return io.BytesIO(json.dumps({"data": [{"id": "gpt-6-astra"}]}).encode())
        if request.full_url.endswith('/models/openai%2Fgpt-image-2.5-sunburst'):
            return io.BytesIO(json.dumps({"id": "openai/gpt-image-2.5-sunburst", "object": "model", "output_modalities": ["text"]}).encode())
        raise urllib.error.HTTPError(request.full_url, 404, 'not found', {}, io.BytesIO(b'{}'))
    with TestClient(app) as client, patch('urllib.request.urlopen', side_effect=upstream):
        response = client.post('/api/providers/openai-compatible/detect', json={"provider": "openai-compatible", "baseUrl": "https://api.openai-proxy.org/v1", "secret": "fixture-key"})
        assert response.status_code == 200, response.text
        assert response.json()['imageModels'] == ['openai/gpt-image-2.5-sunburst']
        assert response.json()['videoModels'] == []
        assert response.json()['unavailableModels'] == [
            'openai/gpt-image-2.5-flare',
            'bytedance/seedance-2.0-mini',
            'bytedance/seedance-2.5',
        ]
        before = len(seen)
        cached = client.get('/api/providers/model-catalog', params={"provider": "openai-compatible", "baseUrl": "https://api.openai-proxy.org/v1"}).json()
        assert cached['imageModels'] == ['openai/gpt-image-2.5-sunburst']
        assert len(seen) == before


def test_gpt_audio_calls_audio_chat_protocol():
    adapter = OpenAICompatibleSpeechProvider('https://relay.test/v1', 'openai-compatible', 'gpt-audio-1.5', Credentials())
    body = {'choices': [{'message': {'audio': {'data': base64.b64encode(b'mp3-content').decode()}}}], 'usage': {'prompt_tokens': 5, 'completion_tokens': 8}}
    with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())) as upstream:
        assert adapter.generate(text='欢迎来到文化展馆') == b'mp3-content'
    request = upstream.call_args.args[0]
    assert request.full_url == 'https://relay.test/v1/chat/completions'
    assert json.loads(request.data)['modalities'] == ['text', 'audio']
    assert adapter.last_response['usage']['prompt_tokens'] == 5


def test_cached_closeai_image_models_are_reclassified_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        # Reproduce an old snapshot with a relay's generic text metadata.
        raw = {"savedAt": "2026-09-01", "models": ["GPT-Image-2.5-Flare", "gemini-3-pro-image-preview", "vision-reader"],
               "imageModels": [], "modelCatalog": [
                   {"id": "GPT-Image-2.5-Flare", "outputModalities": ["text"], "kind": "text"},
                   {"id": "gemini-3-pro-image-preview", "outputModalities": ["text"]},
                   {"id": "vision-reader", "inputModalities": ["text", "image"], "outputModalities": ["text"]}]}
        with app.state.store._connect() as db:
            db.execute("INSERT INTO model_catalogs VALUES (?,?,?,?)", ("openai-compatible", "https://api.openai-proxy.org/v1", json.dumps(raw), raw["savedAt"]))
        with patch("urllib.request.urlopen", side_effect=AssertionError("must stay local")):
            response = client.get("/api/providers/model-catalog", params={"provider": "openai-compatible", "baseUrl": "https://api.openai-proxy.org/v1"})
            data = response.json()
            assert data["imageModels"] == ["GPT-Image-2.5-Flare", "gemini-3-pro-image-preview"]
            assert data["textModels"] == ["vision-reader"]
            assert data["savedAt"] == raw["savedAt"]
            assert app.state.model_catalog.resolve_id("openai-compatible", "https://api.openai-proxy.org/v1", "gpt-image-2.5-flare") == "GPT-Image-2.5-Flare"
            assert app.state.model_catalog.resolve_id("openai-compatible", "https://api.openai-proxy.org/v1", "gpt-image-1") is None


@pytest.mark.parametrize("provider,base,model,path,shape", [
    ("openai-compatible", "https://api.openai-proxy.org/v1", "gpt-image-2.5-flare", "/v1/images/generations", "images"),
    ("openai-compatible", "https://api.openai-proxy.org/v1", "flux-pro", "/v1/images/generations", "images"),
    ("openrouter", "https://openrouter.ai/api/v1", "google/gemini-3-pro-image-preview", "/api/v1/images", "images"),
    ("openai-compatible", "https://api.openai-proxy.org/v1", "gemini-3-pro-image-preview", "/google/v1beta/models/gemini-3-pro-image-preview:generateContent", "gemini"),
])
def test_multiple_image_model_wire_contracts(provider, base, model, path, shape):
    encoded = base64.b64encode(b"image-content").decode()
    bodies = {"images": {"data": [{"b64_json": encoded}]},
              "chat": {"choices": [{"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{encoded}"}}]}}]},
              "gemini": {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": encoded}}]}}]}}
    adapter = ProviderRegistry(Credentials()).image(provider, base_url=base, model=model)
    with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(bodies[shape]).encode())) as upstream:
        assert adapter.generate(prompt="生成船舶图像", aspectRatio="16:9", resolution="2K") == b"image-content"
    request = upstream.call_args.args[0]
    assert request.full_url.endswith(path)
    assert request.get_header("Authorization") == "Bearer fixture-key"
    payload = json.loads(request.data)
    if shape != "gemini":
        assert payload["model"] == model
    if shape == "chat":
        assert payload["modalities"] == ["image", "text"]
        assert payload["image_config"]["aspect_ratio"] == "16:9"
    if shape == "gemini":
        assert payload["generationConfig"]["imageConfig"]["imageSize"] == "2K"
    if shape == "images" and "gpt-image" in model:
        assert "response_format" not in payload


def test_multimodal_image_edit_sends_image_bytes_not_local_path(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    adapter = ProviderRegistry(Credentials()).image("openrouter", model="google/gemini-3-pro-image-preview")
    body = {"data": [{"b64_json": "aW1hZ2U=", "media_type": "image/png"}]}
    with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as upstream:
        assert adapter.generate(prompt="修改背景", source_asset_path=str(source)) == b"image"
    payload = json.loads(upstream.call_args.args[0].data)
    assert payload["input_references"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert str(tmp_path) not in json.dumps(payload)
    with pytest.raises(ProviderError, match="蒙版"):
        adapter.generate(prompt="编辑", source_asset_path=str(source), mask_asset_path=str(source))


def task_for_tools(client, *, network=True, three_d=None):
    project = client.post("/api/projects", json={"name": "Agent 能力验证", "brief": "调研并生成设计"}).json()
    with patch.object(app.state.tasks, "_start_worker", return_value=True):
        task = client.post(f"/api/projects/{project['id']}/tasks", json={"agentKey": "design", "workflowStep": "design", "async": True,
            "input": {"allowExternalNetwork": network, "textProvider": {"key": "openai-compatible", "baseUrl": "https://relay.test/v1", "model": "claude-sonnet-4"}, "mediaProvider": {"threeD": three_d or {}}}}).json()
    return project["id"], {"x-aics-task-id": task["taskId"] if "taskId" in task else task["id"]}


def test_openai_search_is_a_real_tool_with_sources_billing_and_network_guard(tmp_path, monkeypatch):
    from test_search_recovery import native_transport
    requests = native_transport(monkeypatch, tmp_path)
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_COMPATIBLE", "fixture-key")
    with TestClient(app) as client:
        catalog = app.state.model_catalog
        catalog.save("openai-compatible", "https://relay.test/v1", {"models": ["claude-sonnet-4", "gpt-5.6-terra"]})
        settings = catalog.settings()
        settings.search = EndpointModel(provider='openai-compatible',baseUrl='https://relay.test/v1',model='gpt-5.6-terra',api='responses')
        settings.prices[catalog.price_key("openai-compatible", "https://relay.test/v1", "gpt-5.6-terra")] = ModelPrice(currency="CNY", inputPerMillion=1, outputPerMillion=2, perSearch=.1)
        catalog.save_settings(settings)
        project, headers = task_for_tools(client)
        result = client.post(f"/api/projects/{project}/agent-tools/web_search", headers=headers, json={"query": "最新文旅设计案例"})
        assert result.status_code == 200, result.text
        assert result.json()["sources"] == [{"url": "https://93.184.216.34/source", "title": "原始资料"}]
        request = json.loads(requests.read_text())
        assert request["model"] == "gpt-5.6-terra"
        assert request["tools"][0]['type'] == 'web_search'
        assert client.get("/api/credits").json()["points"] == pytest.approx(10.0028)
        project, headers = task_for_tools(client, network=False)
        with patch("app.providers.web_search.subprocess.Popen") as upstream:
            result = client.post(f"/api/projects/{project}/agent-tools/web_search", headers=headers, json={"query": "查询", "allowExternalNetwork": True})
        assert result.status_code >= 400
        upstream.assert_not_called()


def test_unknown_search_tariff_does_not_undercharge():
    assert calculate_cost("search", {"input_tokens": 10, "output_tokens": 5}, {"searchCalls": 1}, {"inputPerMillion": 1, "outputPerMillion": 2}) is None


def test_native_3d_tool_returns_real_asset_and_updates_canvas(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_MESHY", "fixture-key")
    with TestClient(app) as client:
        project, headers = task_for_tools(client, three_d={"key": "meshy", "endpoint": "https://meshy.test", "model": "meshy-custom"})
        body = {"status": "succeeded", "b64_json": base64.b64encode(b"glTF-model").decode(), "extension": "glb"}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as upstream:
            result = client.post(f"/api/projects/{project}/agent-tools/generate_3d", headers=headers, json={"prompt": "生成船舶模型"})
        assert result.status_code == 200, result.text
        assert result.json()["assetId"]
        assert result.json()["node"]["data"]["kind"] == "3d"
        assert json.loads(upstream.call_args.args[0].data)["model"] == "meshy-custom"
        assert upstream.call_args.args[0].full_url == "https://meshy.test/openapi/v2/text-to-3d"
