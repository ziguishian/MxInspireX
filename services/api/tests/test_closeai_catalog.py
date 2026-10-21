import io
import json
from pathlib import Path
import urllib.error
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.closeai_catalog import category_kinds, management_models_url
from app.main import app
from app.model_capabilities import model_record


FIXTURES = Path(__file__).parent / "fixtures"


def test_closeai_category_mapping_does_not_turn_unknown_categories_into_chat():
    assert category_kinds("chat") == ["text"]
    assert category_kinds("image_generation") == ["image"]
    assert category_kinds(["video", "audio"]) == ["video", "audio"]
    assert category_kinds("moderation") == []
    assert management_models_url("https://api.openai-proxy.org/v1") == "https://api.openai-proxy.org/api/v1/management/models"


def test_classification_priority_is_category_then_modalities_endpoints_family_and_safe_default():
    explicit = model_record({"id": "gpt-image-looking-chat", "category": "chat"})
    assert explicit["kinds"] == ["text"]
    assert explicit["classificationSource"] == "provider-category"
    assert explicit["classificationConfidence"] == "authoritative"

    unknown = model_record({"id": "gpt-image-future", "category": "moderation"})
    assert unknown["kinds"] == ["unknown"]
    assert unknown["classificationSource"] == "unknown-provider-category"

    modality = model_record({"id": "custom-renderer", "output_modalities": ["image"]})
    assert modality["kinds"] == ["image"]
    assert modality["classificationSource"] == "output-modalities"

    endpoint = model_record({"id": "custom-renderer", "supported_endpoint_types": ["/v1/images/generations"]})
    assert endpoint["kinds"] == ["image"]
    assert endpoint["classificationSource"] == "supported-endpoints"

    family = model_record({"id": "gpt-image-2.5-sunburst", "output_modalities": ["text"]})
    assert family["kinds"] == ["image"]
    assert family["classificationSource"] == "model-family"

    fallback = model_record({"id": "future-chat-model"})
    assert fallback["kinds"] == ["text"]
    assert fallback["classificationSource"] == "openai-compatible-default"
    assert fallback["classificationConfidence"] == "low"
    persisted = model_record(fallback)
    assert persisted["classificationSource"] == "openai-compatible-default"
    assert persisted["classificationConfidence"] == "low"


def test_all_143_models_from_live_closeai_compatible_snapshot_have_expected_output_kind():
    fixture = json.loads((FIXTURES / "closeai_models_2026_09_17.json").read_text())
    expected = fixture["expected"]
    seen: set[str] = set()
    for kind, model_ids in expected.items():
        for model_id in model_ids:
            assert model_id not in seen, f"fixture contains duplicate model: {model_id}"
            seen.add(model_id)
            assert model_record({"id": model_id})["kinds"] == [kind], model_id
    assert len(seen) == 143
    assert len(expected["text"]) == 132
    assert len(expected["image"]) == 9
    assert len(expected["audio"]) == 2
    assert expected["video"] == expected["embedding"] == expected["3d"] == expected["unknown"] == []


def test_vendor_family_is_separate_from_unreliable_owned_by():
    expected = {
        "claude-opus-4-8": "anthropic",
        "gemini-3.1-pro-preview": "google",
        "deepseek-v4-pro": "deepseek",
        "doubao-seed-2-1-pro-260915": "bytedance",
        "glm-5.3": "z-ai",
        "kimi-k3": "moonshot",
        "qwen3.8-max": "alibaba",
        "MiniMax-M2.5": "minimax",
        "gpt-6-astra": "openai",
    }
    for model_id, vendor in expected.items():
        record = model_record({"id": model_id, "owned_by": "openai"})
        assert record["ownedBy"] == "openai"
        assert record["vendor"] == vendor


def test_closeai_management_catalog_classifies_all_explicit_categories_and_uses_separate_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_COMPATIBLE", "sk-runtime-only")
    monkeypatch.setenv("AICS_PROVIDER_KEY_CLOSEAI_CATALOG", "sk-admin-catalog-only")
    management_models = [
        {"model": "closeai-chat", "category": "chat", "vendor": "closeai", "context_window": 1000,
         "pricing": {"text_input_price": "35", "text_output_price": "175", "cache_read_rate": 0.1,
                     "audio_input_price": "11", "audio_output_price": "12",
                     "image_input_price": "70", "image_output_price": "80",
                     "video_input_price": "90", "video_output_price": "100",
                     "tiers": [{"threshold": 200, "input_rate": 2, "output_rate": 1.5}]}},
        {"model": "gpt-image-2.5-flare", "category": "image", "vendor": "openai"},
        {"model": "gpt-image-2.5-sunburst", "category": "image", "vendor": "openai"},
        {"model": "bytedance/seedance-2.0-mini", "category": "video", "vendor": "bytedance"},
        {"model": "bytedance/seedance-2.5", "category": "video", "vendor": "bytedance"},
        {"model": "speech-one", "category": "audio", "vendor": "fixture"},
        {"model": "embedding-one", "category": "embedding", "vendor": "fixture"},
        {"model": "future-one", "category": "moderation", "vendor": "fixture"},
    ]
    requests = []

    def upstream(request, timeout):
        requests.append((request.full_url, request.get_header("Authorization"), timeout))
        if request.full_url.endswith("/v1/models"):
            return io.BytesIO(json.dumps({"data": [{"id": "gpt-6-astra"}]}).encode())
        if request.full_url.endswith("/api/v1/management/models"):
            return io.BytesIO(json.dumps({"models": management_models}).encode())
        raise AssertionError(request.full_url)

    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", side_effect=upstream):
        response = client.post("/api/providers/openai-compatible/detect", json={
            "provider": "openai-compatible",
            "baseUrl": "https://api.openai-proxy.org/v1",
        })

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["catalogCoverage"] == "complete"
    assert data["catalogSources"] == ["openai-compatible", "closeai-management"]
    assert data["catalogWarnings"] == []
    assert data["textModels"] == ["closeai-chat", "gpt-6-astra"]
    assert data["imageModels"] == ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]
    assert data["videoModels"] == ["bytedance/seedance-2.0-mini", "bytedance/seedance-2.5"]
    assert data["audioModels"] == ["speech-one"]
    assert data["embeddingModels"] == ["embedding-one"]
    assert "future-one" in data["models"] and "future-one" not in data["textModels"]
    chat = next(item for item in data["modelCatalog"] if item["id"] == "closeai-chat")
    assert chat["ownedBy"] == "closeai"
    assert chat["price"]["currency"] == "CNY"
    assert chat["price"]["inputPerMillion"] == 35
    assert chat["price"]["outputPerMillion"] == 175
    assert chat["price"]["cachedPerMillion"] == 3.5
    assert chat["price"]["audioInputPerMillion"] == 11
    assert chat["price"]["audioOutputPerMillion"] == 12
    assert chat["price"]["imageInputPerMillion"] == 70
    assert chat["price"]["imageOutputPerMillion"] == 80
    assert chat["price"]["videoInputPerMillion"] == 90
    assert chat["price"]["videoOutputPerMillion"] == 100
    assert chat["price"]["referenceOnly"] is True
    assert chat["price"]["priceDetails"] == {"tiers": [{"threshold": 200.0, "inputRate": 2.0, "outputRate": 1.5}]}
    assert "用量阈值" in chat["price"]["priceNote"]
    assert requests == [
        ("https://api.openai-proxy.org/v1/models", "Bearer sk-runtime-only", 20),
        ("https://api.openai-proxy.org/api/v1/management/models", "Bearer sk-admin-catalog-only", 20),
    ]
    assert "sk-runtime-only" not in response.text
    assert "sk-admin-catalog-only" not in response.text


def test_closeai_without_admin_key_probes_bare_media_aliases_and_marks_partial_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_COMPATIBLE", "sk-runtime-only")
    monkeypatch.delenv("AICS_PROVIDER_KEY_CLOSEAI_CATALOG", raising=False)
    requested = []

    def not_found(url):
        return urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b"{}"))

    def upstream(request, timeout):
        requested.append(request.full_url)
        if request.full_url.endswith("/v1/models"):
            return io.BytesIO(json.dumps({"data": [{"id": "gpt-6-astra"}]}).encode())
        for model in ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
            if request.full_url.endswith(f"/models/{model}"):
                return io.BytesIO(json.dumps({"id": model, "output_modalities": ["text"]}).encode())
        raise not_found(request.full_url)

    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", side_effect=upstream):
        response = client.post("/api/providers/openai-compatible/detect", json={
            "provider": "openai-compatible",
            "baseUrl": "https://api.openai-proxy.org/v1",
        })

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["catalogCoverage"] == "partial"
    assert data["imageModels"] == ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]
    assert data["unavailableModels"] == ["bytedance/seedance-2.0-mini", "bytedance/seedance-2.5"]
    assert any("目录管理密钥" in warning for warning in data["catalogWarnings"])
    assert any("openai%2Fgpt-image-2.5-sunburst" in url for url in requested)
    assert any(url.endswith("/models/gpt-image-2.5-sunburst") for url in requested)


def test_explicit_invalid_closeai_catalog_key_does_not_hide_the_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    error = urllib.error.HTTPError("https://api.openai-proxy.org/api/v1/management/models", 401, "unauthorized", {}, io.BytesIO(b'{"error":"bad key"}'))

    def upstream(request, timeout):
        if request.full_url.endswith("/v1/models"):
            return io.BytesIO(b'{"data":[]}')
        raise error

    with TestClient(app) as client, patch("app.main.urllib.request.urlopen", side_effect=upstream):
        response = client.post("/api/providers/openai-compatible/detect", json={
            "provider": "openai-compatible",
            "baseUrl": "https://api.openai-proxy.org/v1",
            "secret": "sk-runtime-only",
            "catalogSecret": "sk-admin-invalid-secret",
        })

    assert response.status_code == 502
    assert "CloseAI 完整目录同步失败" in response.json()["detail"]
    assert "sk-admin-invalid-secret" not in response.text
