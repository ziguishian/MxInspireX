import json
import base64
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.providers.http import ClaudeTextProvider, GeminiTextProvider, Native3DProvider, OpenAICompatibleEmbeddingProvider, OpenAICompatibleImageProvider, OpenAICompatibleTextProvider, SeedreamVideoProvider
from app.providers.registry import ProviderRegistry


class _CredentialStub:
    def get(self, provider_key: str):
        return "local-test-secret"


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "本地 Provider 已返回"}}]}).encode()


def test_openai_compatible_adapter_contract():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "auth": request.headers.get("Authorization"), "body": json.loads(request.data), "timeout": timeout})
        return _FakeResponse()

    provider = OpenAICompatibleTextProvider(base_url="http://provider.test/v1", provider_key="openai-compatible", model="test-model", credentials=_CredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.complete(system="system", prompt="hello") == "本地 Provider 已返回"
    assert captured["url"] == "http://provider.test/v1/chat/completions"
    assert captured["auth"] == "Bearer local-test-secret"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["messages"][1]["content"] == "hello"


def test_ollama_adapter_is_local_and_does_not_require_a_credential():
    captured = {}

    class NoCredentials:
        def get(self, _provider_key: str):
            return None

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "auth": request.headers.get("Authorization"), "body": json.loads(request.data)})
        return _FakeResponse()

    registry = ProviderRegistry(credentials=NoCredentials())
    spec = next(item for item in registry.list() if item["key"] == "ollama")
    assert spec["configured"] is True
    assert spec["requiresKey"] is False
    assert spec["local"] is True
    assert spec["defaultBaseUrl"] == "http://127.0.0.1:11434/v1"
    assert spec["defaultModel"] == "gpt-oss:20b"
    provider = registry.text("ollama")
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.complete(system="system", prompt="hello") == "本地 Provider 已返回"
    assert provider.local is True
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["auth"] == "Bearer ollama"
    assert captured["body"]["model"] == "gpt-oss:20b"


def test_openai_compatible_embedding_adapter_contract():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "auth": request.headers.get("Authorization"), "body": json.loads(request.data), "timeout": timeout})
        body = {"data": [{"index": 1, "embedding": [0.0, 1.0, 0.0]}, {"index": 0, "embedding": [1.0, 0.0, 0.0]}]}
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps(body).encode()})()

    provider = OpenAICompatibleEmbeddingProvider(base_url="http://provider.test/v1", provider_key="openai-embeddings", model="embedding-model", credentials=_CredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.embed(["first", "second"]) == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert captured["url"] == "http://provider.test/v1/embeddings"
    assert captured["auth"] == "Bearer local-test-secret"
    assert captured["body"] == {"model": "embedding-model", "input": ["first", "second"]}


def test_openai_compatible_image_adapter_contract():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "auth": request.headers.get("Authorization"), "body": json.loads(request.data), "timeout": timeout})
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"data": [{"b64_json": base64.b64encode(b"PNG-DATA").decode()}]}).encode()})()

    provider = OpenAICompatibleImageProvider(base_url="http://provider.test/v1", provider_key="openai-image", model="image-model", credentials=_CredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.generate(prompt="西湖茶器", size="1024x1024") == b"PNG-DATA"
    assert captured["url"] == "http://provider.test/v1/images/generations"
    assert captured["auth"] == "Bearer local-test-secret"
    assert captured["body"]["model"] == "image-model"
    assert captured["body"]["size"] == "1024x1024"


def test_openai_compatible_image_adapter_filters_ui_metadata_and_negative_prompt():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"data": [{"b64_json": base64.b64encode(b"PNG-DATA").decode()}]}).encode()})()

    provider = OpenAICompatibleImageProvider(base_url="http://provider.test/v1", provider_key="openai-image", model="image-model", credentials=_CredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        provider.generate(prompt="西湖茶器", negative_prompt="不要文字", style="vivid", material="陶瓷", purpose="ip-profile", response_format="b64_json", size="1024x1024")
    assert captured["body"] == {"model": "image-model", "prompt": "西湖茶器", "size": "1024x1024", "output_format": "png"}


def test_openai_compatible_image_adapter_reuses_shared_text_credential():
    class SharedCredentialStub:
        def get(self, provider_key: str):
            return "shared-secret" if provider_key == "openai-compatible" else None

    captured = {}

    def fake_urlopen(request, timeout):
        captured["auth"] = request.headers.get("Authorization")
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"data": [{"b64_json": base64.b64encode(b"PNG-DATA").decode()}]}).encode()})()

    provider = OpenAICompatibleImageProvider(base_url="http://provider.test/v1", provider_key="openai-image", model="image-model", credentials=SharedCredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.generate(prompt="共享网关") == b"PNG-DATA"
    assert captured["auth"] == "Bearer shared-secret"


def test_openai_compatible_image_edit_uses_images_edits_contract():
    captured = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "ip.png"
        source.write_bytes(b"PNG-DATA")

        def fake_urlopen(request, timeout):
            captured.update({"url": request.full_url, "auth": request.headers.get("Authorization"), "contentType": request.headers.get("Content-type"), "body": request.data})
            return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"data": [{"b64_json": base64.b64encode(b"EDITED").decode()}]}).encode()})()

        provider = OpenAICompatibleImageProvider(base_url="http://provider.test/v1", provider_key="openai-image", model="image-model", credentials=_CredentialStub())
        with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
            assert provider.generate(prompt="调整角色手部", source_asset_path=str(source)) == b"EDITED"
    assert captured["url"] == "http://provider.test/v1/images/edits"
    assert captured["auth"] == "Bearer local-test-secret"
    assert captured["contentType"].startswith("multipart/form-data; boundary=")
    assert b'name="image"' in captured["body"]
    assert "调整角色手部".encode() in captured["body"]


def test_claude_compatibility_alias_uses_chat_completions_contract():
    captured = {}

    def fake_urlopen(request, timeout):
        headers = {key.lower(): value for key, value in request.header_items()}
        captured.update({"url": request.full_url, "auth": headers.get("authorization"), "body": json.loads(request.data)})
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"choices": [{"message": {"content": "Claude OK"}}]}).encode()})()

    provider = ClaudeTextProvider(base_url="http://claude.test/v1", provider_key="claude", model="claude-test", credentials=_CredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.complete(system="system", prompt="hello") == "Claude OK"
    assert captured["url"] == "http://claude.test/v1/chat/completions"
    assert captured["auth"] == "Bearer local-test-secret"
    assert captured["body"]["messages"][0]["content"] == "system"
    assert captured["body"]["messages"][1]["content"] == "hello"


def test_gemini_compatibility_alias_uses_chat_completions_contract():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "body": json.loads(request.data)})
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"choices": [{"message": {"content": "Gemini OK"}}]}).encode()})()

    provider = GeminiTextProvider(base_url="http://gemini.test/v1beta", provider_key="gemini", model="gemini-test", credentials=_CredentialStub())
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.complete(system="system", prompt="hello") == "Gemini OK"
    assert captured["url"] == "http://gemini.test/v1beta/chat/completions"
    assert captured["body"]["messages"][1]["content"] == "hello"


def test_registry_uses_openai_compatible_aliases_and_detects_native_3d():
    registry = ProviderRegistry(credentials=_CredentialStub())
    assert isinstance(registry.text("claude"), OpenAICompatibleTextProvider)
    assert isinstance(registry.text("gemini"), OpenAICompatibleTextProvider)
    assert registry.detect_3d_provider("https://api.tripo3d.ai") == "tripo"
    assert registry.detect_3d_provider("https://api.hunyuan.tencentcloud.com") == "hunyuan3d"
    assert registry.detect_3d_provider("https://api.tripo3d.ai", "generic-3d") == "generic-3d"
    assert isinstance(registry.three_d("meshy", endpoint="https://meshy.test"), Native3DProvider)
    local_video = registry.video("local-video-placeholder")
    assert local_video.generate(prompt="test", source_asset="ip-asset", model="seedream-video")["status"] == "succeeded"


def test_registry_marks_image_configured_when_only_shared_text_key_exists():
    class SharedCredentialStub:
        def get(self, provider_key: str):
            return "shared-secret" if provider_key == "openai-compatible" else None

    providers = ProviderRegistry(credentials=SharedCredentialStub()).list()
    image = next(item for item in providers if item["key"] == "openai-image")
    assert image["configured"] is True


def test_registry_defaults_to_gpt_image_sunburst_for_openai_compatible_images():
    image = ProviderRegistry(credentials=_CredentialStub()).image("openai-image")
    assert image.model == "openai/gpt-image-2.5-sunburst"


def test_native_3d_adapter_normalizes_inline_model_bytes():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "body": json.loads(request.data)})
        body = {"data": {"task_id": "mesh-job-1", "status": "succeeded", "b64_json": base64.b64encode(b"GLB-DATA").decode()}}
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps(body).encode()})()

    provider = Native3DProvider(provider_key="meshy", credentials=_CredentialStub(), endpoint="http://meshy.test")
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.generate(prompt="茶器公仔", source_asset="/tmp/ip.png", output_format="glb")
    assert captured["url"] == "http://meshy.test/openapi/v2/text-to-3d"
    assert result["jobId"] == "mesh-job-1"
    assert result["content"] == b"GLB-DATA"
    assert result["extension"] == "glb"


def test_native_3d_adapter_retrieves_async_model_bytes():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "method": request.method, "auth": request.headers.get("Authorization")})
        body = {"data": {"task_id": "mesh-job-2", "status": "completed", "model_base64": base64.b64encode(b"ASYNC-GLB").decode()}}
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps(body).encode()})()

    provider = Native3DProvider(provider_key="meshy", credentials=_CredentialStub(), endpoint="http://meshy.test")
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.retrieve(job_id="mesh-job-2", prompt="茶器公仔", output_format="glb")
    assert captured["url"] == "http://meshy.test/openapi/v2/text-to-3d/mesh-job-2"
    assert captured["method"] == "GET"
    assert captured["auth"] == "Bearer local-test-secret"
    assert result["status"] == "succeeded"
    assert result["content"] == b"ASYNC-GLB"


def test_generic_3d_adapter_retrieves_task_without_vendor_schema():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        body = {"status": "processing", "id": "generic-job-1"}
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps(body).encode()})()

    provider = ProviderRegistry(credentials=_CredentialStub()).three_d("generic-3d", endpoint="http://gateway.test/api")
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.retrieve(job_id="generic-job-1", prompt="茶器公仔", output_format="obj")
    assert captured["url"] == "http://gateway.test/api/jobs/generic-job-1"
    assert result["status"] == "running"
    assert result["jobId"] == "generic-job-1"


def test_seedream_native_video_normalizes_job_and_bytes():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "auth": request.headers.get("Authorization"), "body": json.loads(request.data)})
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"status": "succeeded", "id": "seedream-job-1", "data": [{"b64_json": base64.b64encode(b"MP4-DATA").decode()}]}).encode()})()

    provider = SeedreamVideoProvider(provider_key="seedream", credentials=_CredentialStub(), endpoint="http://seedream.test/api", model="seedream-video")
    with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.generate(prompt="产品展示", source_asset="ip-asset")
    assert captured["url"] == "http://seedream.test/api/videos/generations"
    assert captured["auth"] == "Bearer local-test-secret"
    assert result["jobId"] == "seedream-job-1"
    assert result["content"] == b"MP4-DATA"


def test_seedream_volcengine_contract_uses_action_query_and_local_image_bytes():
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "body": json.loads(request.data)})
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps({"status": 10000, "data": {"task_id": "jimeng-job-1", "status": "submitted"}}).encode()})()

    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "ip.png"
        source.write_bytes(b"PNG-DATA")
        provider = SeedreamVideoProvider(provider_key="seedream", credentials=_CredentialStub(), endpoint="https://visual.volcengineapi.com", model="seedream-video")
        with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
            result = provider.generate(prompt="产品展示", source_asset=str(source))
    assert "Action=JimengI2VFirstV30SubmitTask" in captured["url"]
    assert "Version=2024-06-06" in captured["url"]
    assert captured["body"]["req_key"] == "jimeng_i2v_first_v30"
    assert captured["body"]["binary_data_base64"]
    assert result["jobId"] == "jimeng-job-1"
