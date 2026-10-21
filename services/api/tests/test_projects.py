import base64
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import _safe_endpoint, app
from app.agent_contracts import AgentResult
from app.research import ResearchImportError, safe_source_uri
from app.storage import ProjectStore


def test_provider_endpoint_sanitization_removes_query_secrets():
    assert _safe_endpoint("https://gateway.test/v1?api_key=secret&region=cn#fragment") == "https://gateway.test/v1?region=cn"
    assert _safe_endpoint("https://gateway.test/v1?token=secret&Action=Submit") == "https://gateway.test/v1?Action=Submit"


def test_design_search_keeps_only_remote_preview_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_COMPATIBLE", "search-test-key")

    class SearchResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"results": [{"title": "Remote", "url": "https://example.com/item", "thumbnail": {"url": "https://cdn.example.com/preview.jpg"}}, {"title": "No preview", "url": "https://example.com/no-image", "thumbnail": "/bundled/local.png"}]}).encode()

    with TestClient(app) as client:
        with patch("app.main.urllib.request.urlopen", return_value=SearchResponse()):
            response = client.get("/api/research/search", params={"query": "cultural product"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["image"] == "https://cdn.example.com/preview.jpg"
    assert results[0]["imageSource"] == "network"
    assert results[1]["image"] is None
    assert results[1]["imageSource"] is None


def test_model_detection_returns_text_and_image_choices(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_COMPATIBLE", "detect-test-key")

    class ModelsResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "gpt-5.6-luna"},
                        {"id": "gpt-image-2"},
                        {"id": "flux-1.1-pro"},
                        {"id": "sora-video-1", "modalities": ["text", "video"]},
                        {"id": "text-embedding-3-small", "type": "embedding"},
                    ]
                }
            ).encode()

    with TestClient(app) as client:
        with patch("app.main.urllib.request.urlopen", return_value=ModelsResponse()):
            response = client.post("/api/providers/openai-compatible/detect", json={"provider": "openai-compatible", "baseUrl": "https://gateway.test/v1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["textModels"] == ["gpt-5.6-luna"]
    assert payload["imageModels"] == ["flux-1.1-pro", "gpt-image-2"]
    assert payload["videoModels"] == ["sora-video-1"]
    assert payload["embeddingModels"] == ["text-embedding-3-small"]
    assert payload["models"] == ["flux-1.1-pro", "gpt-5.6-luna", "gpt-image-2", "sora-video-1", "text-embedding-3-small"]
    assert [item["id"] for item in payload["modelCatalog"]] == payload["models"]


def test_provider_list_only_returns_a_masked_credential_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENROUTER", "sk-langju-secret-1234")

    with TestClient(app) as client:
        response = client.get("/api/providers")
    assert response.status_code == 200
    openrouter = next(item for item in response.json() if item["key"] == "openrouter")
    assert openrouter["configured"] is True
    assert openrouter["credentialHint"] == "••••••••1234"
    assert "sk-langju-secret" not in json.dumps(openrouter, ensure_ascii=False)


def test_closeai_catalog_credential_is_reported_only_as_a_masked_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_CLOSEAI_CATALOG", "sk-admin-catalog-5678")

    with TestClient(app) as client:
        response = client.get("/api/providers")
    assert response.status_code == 200
    compatible = next(item for item in response.json() if item["key"] == "openai-compatible")
    assert compatible["catalogCredentialConfigured"] is True
    assert compatible["catalogCredentialHint"] == "••••••••5678"
    assert "sk-admin-catalog" not in response.text


def test_openai_compatible_embeddings_can_drive_project_rag(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_EMBEDDING_PROVIDER", "openai-embeddings")
    monkeypatch.setenv("AICS_EMBEDDING_BASE_URL", "http://embedding.test/v1")
    monkeypatch.setenv("AICS_EMBEDDING_MODEL", "embedding-test-model")
    monkeypatch.setenv("AICS_PROVIDER_KEY_OPENAI_EMBEDDINGS", "embedding-local-test")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, json.loads(request.data)))
        inputs = calls[-1][1]["input"]
        body = {"data": [{"index": index, "embedding": [1.0, 0.0, 0.0] if "西湖" in text else [0.0, 1.0, 0.0]} for index, text in enumerate(inputs)]}
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps(body).encode()})()

    with TestClient(app) as client:
        with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
            project = client.post("/api/projects", json={"name": "Embedding RAG", "brief": "验证远程向量索引"}).json()
            ingested = client.post(f"/api/projects/{project['id']}/knowledge/text", json={"title": "西湖资料", "pathRelative": "xihu.txt", "text": "西湖宋韵礼赠设计资料"})
            assert ingested.status_code == 201
            results = client.get(f"/api/projects/{project['id']}/knowledge/vector-search?q=西湖")
        assert results.status_code == 200
        assert results.json()[0]["title"] == "西湖资料"
        embedding_status = client.get("/api/knowledge/embedding-status")
        assert embedding_status.json()["provider"] == "openai-embeddings"
        assert embedding_status.json()["model"] == "embedding-test-model"
        assert embedding_status.json()["remote"] is True

    assert len(calls) == 2
    assert all(url == "http://embedding.test/v1/embeddings" for url, _ in calls)


def test_global_knowledge_upload_is_independent_from_project_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "共享 RAG 项目", "brief": "验证共享知识库检索"}).json()
        uploaded = client.post(
            "/api/knowledge/upload",
            files={"file": ("shared-notes.txt", "所有项目都可引用的宋韵茶礼资料".encode("utf-8"), "text/plain")},
        )
        assert uploaded.status_code == 201
        payload = uploaded.json()
        assert payload["scope"] == "global"
        assert payload["chunkCount"] == 1

        documents = client.get("/api/knowledge/documents")
        assert documents.status_code == 200
        assert len(documents.json()) == 1
        document = documents.json()[0]
        assert document["scope"] == "global"
        assert document["chunkCount"] == 1
        assert (tmp_path / document["pathRelative"]).is_file()

        # Project intake knowledge remains isolated from the workspace-wide RAG
        # collection, while vector retrieval can still use the shared document.
        assert client.get(f"/api/projects/{project['id']}/knowledge/documents").json() == []
        vector_results = client.get("/api/knowledge/vector-search?q=宋韵").json()
        assert vector_results[0]["scope"] == "global"


def test_research_source_import_creates_snapshot_index_and_note(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))

    class WebResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __init__(self):
            self._read = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            if self._read:
                return b""
            self._read = True
            return "<html><head><title>西湖文化资料</title><script>ignore()</script></head><body><h1>宋韵</h1><p>断桥与茶礼可转化为现代东方产品叙事。</p></body></html>".encode("utf-8")

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "研究来源链路", "brief": "验证来源快照和引用记录"}).json()
        with patch("app.research.urllib.request.urlopen", return_value=WebResponse()):
            imported = client.post(
                f"/api/projects/{project['id']}/research/sources/import-url",
                json={"uri": "https://example.com/research?api_key=do-not-store&utm_source=test", "previewImageUrl": "https://cdn.example.com/x.jpg?token=do-not-store", "rightsStatus": "review"},
            )
        assert imported.status_code == 201
        source = imported.json()
        assert source["uri"] == "https://example.com/research?utm_source=test"
        assert source["title"] == "西湖文化资料"
        assert source["previewImageUrl"] == "https://cdn.example.com/x.jpg"
        assert source["textLength"] > 10
        snapshot = tmp_path / "project" / source["snapshotPath"]
        assert snapshot.is_file()
        assert "ignore" in snapshot.read_text(encoding="utf-8")

        sources = client.get(f"/api/projects/{project['id']}/research/sources")
        assert sources.status_code == 200
        assert sources.json()[0]["rightsStatus"] == "review"
        assert sources.json()[0]["previewImageUrl"] == "https://cdn.example.com/x.jpg"
        assert client.get(f"/api/projects/{project['id']}/knowledge/search?q=宋韵").json()

        note = client.post(
            f"/api/projects/{project['id']}/research/notes",
            json={"sourceId": source["id"], "category": "文化观察", "bodyMd": "将断桥与茶礼转译为克制的产品故事。", "confidence": 0.82},
        )
        assert note.status_code == 201
        assert note.json()["sourceId"] == source["id"]
        assert client.get(f"/api/projects/{project['id']}/research/notes").json()[0]["claims"] == []


def test_research_source_rejects_unsafe_or_invalid_url(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "研究来源安全", "brief": "验证来源 URL 校验"}).json()
        local = client.post(f"/api/projects/{project['id']}/research/sources/import-url", json={"uri": "http://127.0.0.1/private"})
        assert local.status_code == 422
        private = client.post(f"/api/projects/{project['id']}/research/sources/import-url", json={"uri": "http://10.0.0.1/private"})
        assert private.status_code == 422
        link_local = client.post(f"/api/projects/{project['id']}/research/sources/import-url", json={"uri": "http://169.254.169.254/latest/meta-data"})
        assert link_local.status_code == 422
        ipv6_loopback = client.post(f"/api/projects/{project['id']}/research/sources/import-url", json={"uri": "http://[::1]/private"})
        assert ipv6_loopback.status_code == 422
        invalid = client.post(f"/api/projects/{project['id']}/research/sources/import-url", json={"uri": "file:///tmp/private"})
        assert invalid.status_code == 422


def test_research_source_rejects_hostname_resolving_to_private_address():
    with patch("app.research.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.8", 443))]):
        try:
            safe_source_uri("https://public-looking.example/research")
        except ResearchImportError as error:
            assert "SSRF" in str(error)
        else:
            raise AssertionError("private DNS result should be rejected")


def test_intake_parses_multiple_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        intake = client.post(
            "/api/intake",
            data={"name": "多资料 intake", "brief": "做一套宋韵茶器礼盒", "currency": "CNY"},
            files=[
                ("files", ("brief.txt", "断桥与茶礼，面向商务礼赠。".encode("utf-8"), "text/plain")),
                ("files", ("notes.md", "控制留白，保持克制。".encode("utf-8"), "text/markdown")),
            ],
        )
        assert intake.status_code == 201
        payload = intake.json()
        project = payload["project"]
        assert payload["parsedCount"] == 2
        assert {item["parser"] for item in payload["files"]} == {"text"}
        documents = client.get(f"/api/projects/{project['id']}/knowledge/documents").json()
        assert len(documents) == 2



def test_project_delete_removes_catalog_row_and_project_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.tasks.design_runtime, 'run', lambda **kw: AgentResult(status='succeeded', structured_data={'answer':'完成'}, provenance={'agent':'design'}))
        created = client.post("/api/projects", json={"name": "待删除任务", "brief": "删除完整性验证"}).json()
        root = tmp_path / created["slug"]
        (root / "assets" / "originals" / "keep.txt").write_text("owned", encoding="utf-8")
        assert client.post(f"/api/projects/{created['id']}/tasks", json={"agentKey": "design", "workflowStep": "design", "input": {}}).status_code == 201
        assert client.post(f"/api/projects/{created['id']}/knowledge/text", json={"title": "删除测试资料", "pathRelative": "knowledge/delete-test.txt", "text": "仅用于删除完整性验证"}).status_code == 201
        assert client.post(f"/api/projects/{created['id']}/assets/upload", files={"file": ("delete-test.txt", b"owned", "text/plain")}, data={"kind": "document"}).status_code == 201
        deleted = client.delete(f"/api/projects/{created['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/projects/{created['id']}").status_code == 404
        assert not root.exists()
        with sqlite3.connect(tmp_path / "catalog.sqlite") as connection:
            for table in ("tasks", "assets", "knowledge_documents"):
                assert connection.execute(f"SELECT count(*) FROM {table} WHERE project_id = ?", (created["id"],)).fetchone()[0] == 0


def test_asset_delete_removes_file_catalog_row_and_references(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "资产删除", "brief": "验证资产删除"}).json()
        uploaded = client.post(
            f"/api/projects/{project['id']}/assets/upload",
            files={"file": ("reference.png", b"fake-image", "image/png")},
            data={"kind": "image"},
        )
        assert uploaded.status_code == 201
        asset = uploaded.json()
        asset_path = tmp_path / project["slug"] / asset["pathRelative"]
        assert asset_path.is_file()
        deleted = client.delete(f"/api/projects/{project['id']}/assets/{asset['id']}")
        assert deleted.status_code == 204
        assert not asset_path.exists()
        assert client.get(f"/api/projects/{project['id']}/assets").json() == []
        assert client.delete(f"/api/projects/{project['id']}/assets/{asset['id']}").status_code == 404


def test_showcase_asset_upload_retains_source_credit_and_role(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "source-credit", "brief": "演示来源"}).json()
        path = f"/api/projects/{project['id']}/assets/upload"
        uploaded = client.post(
            path,
            files={"file": ("reviewed.png", b"reviewed-image", "image/png")},
            data={"kind": "image", "sourceCredit": "摄影师 / 工作室", "sourceFile": "原图.jpg", "sourceRole": "reference"},
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["metadata"] == {
            "source": "user-upload", "originalName": "reviewed.png", "sourceCredit": "摄影师 / 工作室",
            "sourceFile": "原图.jpg", "sourceRole": "reference",
        }
        listed = client.get(f"/api/projects/{project['id']}/assets").json()
        assert listed[0]["metadata"]["sourceCredit"] == "摄影师 / 工作室"
        invalid = client.post(path, files={"file": ("bad.png", b"image", "image/png")}, data={"kind": "image", "sourceRole": "deliverable-and-reference"})
        assert invalid.status_code == 422


def test_knowledge_document_delete_removes_file_chunks_and_vector_hits(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "知识删除", "brief": "验证知识文档删除"}).json()
        uploaded = client.post(
            "/api/knowledge/upload",
            files={"file": ("shared.txt", "只保留这一份资料".encode("utf-8"), "text/plain")},
        )
        assert uploaded.status_code == 201
        global_doc = uploaded.json()
        global_path = tmp_path / global_doc["pathRelative"]
        assert global_path.is_file()
        assert client.delete(f"/api/knowledge/documents/{global_doc['documentId']}").status_code == 204
        assert not global_path.exists()
        assert client.get("/api/knowledge/documents").json() == []
        assert client.get("/api/knowledge/search?q=资料").json() == []
        assert client.get("/api/knowledge/vector-search?q=资料").json() == []

        project_upload = client.post(
            f"/api/projects/{project['id']}/knowledge/upload",
            files={"file": ("local.txt", "项目私有资料".encode("utf-8"), "text/plain")},
        )
        assert project_upload.status_code == 201
        project_doc = project_upload.json()
        project_path = tmp_path / project["slug"] / project_doc["pathRelative"]
        assert project_path.is_file()
        assert client.delete(f"/api/projects/{project['id']}/knowledge/documents/{project_doc['documentId']}").status_code == 204
        assert not project_path.exists()
        assert client.get(f"/api/projects/{project['id']}/knowledge/documents").json() == []
        assert client.get(f"/api/projects/{project['id']}/knowledge/search?q=资料").json() == []
        assert client.delete(f"/api/projects/{project['id']}/knowledge/documents/{project_doc['documentId']}").status_code == 404






def test_image_generation_uses_shared_gateway_and_moves_style_metadata_into_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    calls = {}

    class FakeImageProvider:
        def generate(self, *, prompt, model, **params):
            calls.update({"prompt": prompt, "model": model, "params": params})
            return b"PNG-DATA"

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "共享图像网关", "brief": "验证图像 Provider 复用文本网关"}).json()
        with patch.object(app.state.providers, "image", return_value=FakeImageProvider()):
            generated = client.post(
                f"/api/projects/{project['id']}/generations/image",
                json={
                    "provider": "openai-image",
                    "model": "image-model",
                    "prompt": "生成园林守护者",
                    "style": "宋韵",
                    "material": "陶瓷",
                    "params": {"purpose": "ip-profile"},
                },
            )
    assert generated.status_code == 201
    assert calls["model"] == "image-model"
    assert "视觉风格：宋韵" in calls["prompt"]
    assert "材质表现：陶瓷" in calls["prompt"]
    assert calls["params"]["purpose"] == "ip-profile"


def test_image_generation_respects_manual_model_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    calls = {}

    class FakeImageProvider:
        def generate(self, *, prompt, model, **params):
            calls["model"] = model
            return b"PNG-DATA"

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "图像模型迁移", "brief": "验证旧图像模型别名升级"}).json()
        with patch.object(app.state.providers, "image", return_value=FakeImageProvider()):
            generated = client.post(
                f"/api/projects/{project['id']}/generations/image",
                json={"provider": "openai-image", "model": "dall-e-3", "prompt": "生成园林守护者"},
            )
    assert generated.status_code == 201
    assert calls["model"] == "dall-e-3"
    assert generated.json()["model"] == "dall-e-3"










def test_native_3d_async_refresh_persists_model_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AICS_PROVIDER_KEY_MESHY", "meshy-local-test")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.method, request.full_url))
        if request.method == "POST":
            body = {"data": {"task_id": "mesh-job-route", "status": "submitted"}}
        else:
            body = {"data": {"task_id": "mesh-job-route", "status": "completed", "file_base64": base64.b64encode(b"ROUTE-GLB").decode()}}
        return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False, "read": lambda self: json.dumps(body).encode()})()

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "异步 3D 验证", "brief": "验证原生模型任务刷新"}).json()
        with patch("app.providers.http.urllib.request.urlopen", side_effect=fake_urlopen):
            submitted = client.post(f"/api/projects/{project['id']}/generations/3d", json={"prompt": "可打印的茶器公仔", "provider": "meshy", "endpoint": "http://meshy.test", "outputFormat": "glb"})
            assert submitted.status_code == 201
            assert submitted.json()["status"] == "submitted"
            generation_id = submitted.json()["generationId"]
            refreshed = client.post(f"/api/projects/{project['id']}/generations/{generation_id}/3d/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["status"] == "succeeded"
        assert refreshed.json()["asset"]["kind"] == "3d"
        assert client.get(f"/api/projects/{project['id']}/assets/{refreshed.json()['asset']['id']}/content").content == b"ROUTE-GLB"
    assert calls == [("POST", "http://meshy.test/openapi/v2/text-to-3d"), ("GET", "http://meshy.test/openapi/v2/text-to-3d/mesh-job-route")]


def test_async_agent_task_can_be_polled(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.tasks.design_runtime, 'run', lambda **kw: AgentResult(status='succeeded', structured_data={'answer':'完成'}, provenance={'agent':'design'}))
        project = client.post("/api/projects", json={"name": "后台 Agent 验证", "brief": "验证可轮询的 Agent 任务"}).json()
        queued = client.post(f"/api/projects/{project['id']}/tasks", json={"agentKey": "design", "workflowStep": "design", "async": True})
        assert queued.status_code == 201
        task_id = queued.json()["id"]
        assert queued.json()["status"] == "queued"
        final = None
        for _ in range(40):
            final = client.get(f"/api/projects/{project['id']}/tasks/{task_id}").json()
            if final["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert final is not None
        assert final["status"] == "succeeded"
        assert final["output"]["provenance"]["agent"] == "design"


def test_task_request_id_is_idempotent_and_conflicts_on_changed_content(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    calls = []
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.tasks.design_runtime, 'run', lambda **kw: calls.append(kw) or AgentResult(status='succeeded', structured_data={'answer':'只执行一次'}, provenance={'agent':'design'}))
        project = client.post('/api/projects', json={'name':'幂等提交', 'brief':'原始需求'}).json()
        route = f"/api/projects/{project['id']}/tasks"
        payload = {'requestId':'stable-browser-request', 'agentKey':'design', 'workflowStep':'design', 'brief':'同一条需求', 'async':True, 'input':{'allowExternalNetwork':False}}
        first = client.post(route, json=payload)
        second = client.post(route, json=payload)
        assert first.status_code == second.status_code == 201
        assert first.json()['id'] == second.json()['id']
        for _ in range(100):
            if client.get(f"{route}/{first.json()['id']}").json()['status'] == 'succeeded':
                break
            time.sleep(.01)
        assert len(calls) == 1
        conflict = client.post(route, json={**payload, 'brief':'requestId 相同但内容已改变'})
        assert conflict.status_code == 409
        assert len(client.get(route).json()) == 1


def test_agent_failure_returns_cors_safe_json_error(tmp_path, monkeypatch):
    """Provider failures must remain visible to the browser instead of looking like CORS failures."""
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Agent 错误响应", "brief": "验证失败响应可读"}).json()
        with patch.object(app.state.tasks, "enqueue", side_effect=RuntimeError("provider unavailable")):
            response = client.post(
                f"/api/projects/{project['id']}/tasks",
                headers={"Origin": "http://127.0.0.1:5173"},
                json={"agentKey": "design", "workflowStep": "design"},
            )

    assert response.status_code == 502
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.json()["detail"] == "Agent 运行失败：provider unavailable"


def test_task_history_failure_keeps_cors_headers(tmp_path, monkeypatch):
    """Unexpected task-history errors must not be reported as a browser CORS failure."""
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "任务历史错误响应", "brief": "验证任务列表失败响应"}).json()
        with patch.object(app.state.tasks, "list_tasks", side_effect=RuntimeError("database unavailable")):
            response = client.get(
                f"/api/projects/{project['id']}/tasks",
                headers={"Origin": "http://127.0.0.1:5173"},
            )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.json()["detail"] == "任务历史读取失败：database unavailable"






def test_current_project_crud_has_no_retired_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        response = client.post('/api/projects', json={'name': '自由创作', 'brief': '设计一个图标'})
        assert response.status_code == 201
        project = response.json()
        assert 'workflowTemplate' not in project
        assert client.get('/api/projects').json()[0]['id'] == project['id']
        updated = client.put(f'/api/projects/{project["id"]}', json={'name': '图标设计'})
        assert updated.status_code == 200
        assert updated.json()['name'] == '图标设计'
        for endpoint in ['workflow', 'approvals', 'ip-profile', 'render/pages', 'products', 'commercial-plans', 'presentation', 'versions']:
            assert client.get(f'/api/projects/{project["id"]}/{endpoint}').status_code == 404
        assert client.post(f'/api/projects/{project["id"]}/tasks', json={'agentKey': 'report'}).status_code == 410
        with app.state.store._connect() as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names.intersection({'workflows', 'workflow_steps', 'products', 'ip_profiles', 'render_pages', 'approvals'})


def test_video_creation_accepts_prompt_without_ip_gate(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': '视频生成'}).json()
        response = client.post(f'/api/projects/{project["id"]}/video/jobs', json={
            'provider': 'local-video-placeholder', 'model': 'video-placeholder-v0', 'prompt': '海边日落',
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body['job']['sourceAssetId'] is None
        assert 'ipProfile' not in body and 'ipProfileId' not in body['job']
