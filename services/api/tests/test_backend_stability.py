from fastapi.testclient import TestClient

from app.main import app


def test_malformed_nested_payloads_are_rejected_without_affecting_health(tmp_path, monkeypatch):
    """Exercise the request shapes that previously escaped as TypeError/500."""
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))

    with TestClient(app, raise_server_exceptions=False) as client:
        project = client.post(
            "/api/projects",
            json={"name": "后端稳定性冒烟", "brief": "验证异常请求不会让 API 失去响应"},
        ).json()
        project_id = project["id"]

        invalid_requests = [
            (f"/api/projects/{project_id}/tasks", {"agentKey": "design", "input": ["invalid"]}),
            (f"/api/projects/{project_id}/generations/image", {"prompt": "一张测试图", "params": ["invalid"]}),
            (f"/api/projects/{project_id}/generations/3d", {"prompt": "模型", "params": ["invalid"]}),
        ]
        for path, payload in invalid_requests:
            response = client.post(path, json=payload)
            assert response.status_code == 422, (path, response.text)
        assert client.get("/health").status_code == 200
        assert client.get(f"/api/projects/{project_id}").status_code == 200
