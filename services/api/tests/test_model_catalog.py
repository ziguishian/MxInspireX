import io
import json
import urllib.error
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize("body", [
    {"data": [{"id": "relay-chat"}, {"id": "relay-image"}, {"id": "relay-video"}, {"id": "relay-3d"}, {"id": "relay-chat"}, {"id": " "}]},
    {"models": ["relay-chat", "relay-image", "relay-video", "relay-3d"]},
    ["relay-chat", "relay-image", "relay-video", "relay-3d"],
])
def test_catalog_uses_gateway_response_and_selected_credential(tmp_path, monkeypatch, body):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_COMPATIBLE", "relay-test-key")
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENROUTER", "different-provider-key")
    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as upstream:
        response = client.post("/api/providers/openai-compatible/detect", json={"provider": "openai-compatible", "baseUrl": "https://relay.test"})
    assert response.status_code == 200
    request = upstream.call_args.args[0]
    assert request.full_url == "https://relay.test/v1/models"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer relay-test-key"
    assert response.json()["models"] == ["relay-3d", "relay-chat", "relay-image", "relay-video"]
    assert response.json()["textModels"] == ["relay-chat"]
    assert response.json()["imageModels"] == ["relay-image"]
    assert response.json()["videoModels"] == ["relay-video"]
    assert response.json()["threeDModels"] == ["relay-3d"]
    assert "relay-test-key" not in response.text


@pytest.mark.parametrize("body, expected_status", [({"data": []}, 200), ({"error": "invalid key"}, 502), ({"models": None}, 502)])
def test_empty_and_invalid_catalogs_do_not_produce_defaults(tmp_path, monkeypatch, body, expected_status):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
        response = client.post("/api/providers/openai-compatible/detect", json={"provider": "openai-compatible", "baseUrl": "https://relay.test/v1", "secret": "test-only"})
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["models"] == []
        assert response.json()["textModels"] == []
        assert response.json()["imageModels"] == []


def test_catalog_does_not_borrow_another_providers_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client, patch.object(app.state.providers.credentials, "get", side_effect=lambda key: "other-key" if key == "openrouter" else None), patch("app.main.urllib.request.urlopen") as upstream:
        response = client.post("/api/providers/openai-compatible/detect", json={"provider": "openai-compatible", "baseUrl": "https://relay.test/v1"})
    assert response.status_code == 422
    upstream.assert_not_called()


def test_ollama_catalog_sync_does_not_require_or_persist_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    body = {"object": "list", "data": [{"id": "gpt-oss:20b", "object": "model", "owned_by": "library"}]}
    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as upstream, patch.object(app.state.providers, "set_credential") as save_credential:
        response = client.post("/api/providers/openai-compatible/detect", json={"provider": "ollama", "baseUrl": "http://127.0.0.1:11434", "saveCredential": True})
    assert response.status_code == 200
    assert response.json()["models"] == ["gpt-oss:20b"]
    assert response.json()["textModels"] == ["gpt-oss:20b"]
    assert response.json()["modelCatalog"][0]["inputModalities"] == ["text"]
    assert response.json()["modelCatalog"][0]["textApi"] == "chat_completions"
    request = upstream.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:11434/v1/models"
    assert request.get_header("Authorization") == "Bearer ollama"
    save_credential.assert_not_called()


@pytest.mark.parametrize("code", [401, 404, 500])
def test_catalog_reports_gateway_failures(tmp_path, monkeypatch, code):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    error = urllib.error.HTTPError("https://relay.test/v1/models", code, "error", {}, io.BytesIO(b"gateway error"))
    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", side_effect=error):
        response = client.post("/api/providers/openai-compatible/detect", json={"baseUrl": "https://relay.test/v1", "secret": "test-only"})
    assert response.status_code == 502
    assert "models" not in response.json()
