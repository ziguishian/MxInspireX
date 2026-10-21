import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_contracts import AgentResult
from app.main import app
from app.model_catalog import ModelCatalog
from app.model_config import DEFAULT_FAST_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL
from app.models import new_project
from app.project_titles import ProjectTitleService, local_title
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA, TaskRuntime


class TitleProviders:
    def __init__(self, store):
        self.catalog = ModelCatalog(store)
        self.catalog.save("openai-compatible", "https://gateway.test/v1", {"models": [DEFAULT_FAST_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL, "gpt-6-astra"]})
        self.calls = []
        self.respond = lambda: '{"title":"宠物用品 App 图标设计"}'

    def text(self, key, *, base_url=None, model=None):
        adapter = SimpleNamespace(base_url=base_url or "https://gateway.test/v1", model=model)
        def complete(**kwargs):
            self.calls.append({"key": key, "model": model, "adapter": adapter, **kwargs})
            return self.respond()
        adapter.complete_structured = complete
        return adapter


def add_project(store, name="新对话", mode="auto", brief="你好"):
    project = new_project(name=name, slug=str(uuid4()), brief=brief, budget_minor=None, currency="CNY", root_path=str(store.workspace_root / str(uuid4())))
    return store.create_project({**project, "titleMode": mode})


def add_turn(store, project_id, user="宠物用品 App 的图标", status="succeeded", **extra):
    with store._connect() as db:
        db.execute("""INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,input_json,output_json,created_at,updated_at)
            VALUES (?,?,'design','design',?,?,?,'2026-09-12T01:00:00Z','2026-09-12T01:00:00Z')""",
            (str(uuid4()), project_id, status, json.dumps({"userMessage": user, "textProvider": {"key": "openai-compatible", "baseUrl": "https://gateway.test/v1", "model": "gpt-6-astra"}, **extra}),
             json.dumps({"structured_data": {"answer": "理解了，使用圆润风格"}})))


def wait_until(check):
    deadline = time.monotonic() + 3
    while not check():
        assert time.monotonic() < deadline, "Background title did not settle"
        time.sleep(0.01)


@pytest.fixture
def setup(tmp_path):
    store = ProjectStore(str(tmp_path))
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
    providers = TitleProviders(store)
    service = ProjectTitleService(store, providers)
    project = add_project(store)
    yield store, providers, service, project
    service.stop()


def test_three_completed_turns_use_local_bounded_conversation_context(setup):
    store, providers, service, project = setup
    pid = project["id"]
    add_turn(store, pid, "你好")
    add_turn(store, pid, "帮我设计宠物用品 App")
    for status in ("failed", "cancelled", "running", "queued"):
        add_turn(store, pid, "失败或未完成的轮次", status)
    assert not service.generate(pid)
    assert not providers.calls
    add_turn(store, pid, "只需要圆润的图标，不要完整 App", referencedFiles=[{"text": "RAW_ATTACHMENT_SECRET"}])
    assert service.generate(pid)
    assert providers.calls == []
    updated = store.get_project(pid)
    assert updated["name"] == "宠物用品 App 图标设计"
    assert updated["titleGeneratedAt"]
    assert (updated["rootPath"], updated["slug"], updated["updatedAt"]) == (project["rootPath"], project["slug"], project["updatedAt"])
    assert json.loads(Path(updated["rootPath"], "project.json").read_text())["name"] == updated["name"]
    add_turn(store, pid, "再改一下颜色")
    assert not service.generate(pid)  # Keep a stable name once the topic is known.
    assert providers.calls == []


def test_greetings_wait_for_a_real_topic_without_repeating_same_call(setup):
    store, providers, service, project = setup
    for _ in range(3):
        add_turn(store, project["id"], "你好")
    assert not service.generate(project["id"])
    assert not service.schedule(project["id"])
    assert not providers.calls
    add_turn(store, project["id"], "我想制作宠物品牌图标")
    assert service.generate(project["id"])
    assert store.get_project(project["id"])["name"] == "宠物品牌 图标设计"


@pytest.mark.parametrize("action", ["rename", "delete"])
def test_manual_changes_win_over_an_inflight_title(setup, action):
    store, providers, service, project = setup
    for _ in range(3):
        add_turn(store, project["id"])
    if action == "rename":
        store.update_project(project["id"], {"name": "我的图标"})
    else:
        store.delete_project(project["id"])
    assert not service.generate(project["id"])
    if action == "rename":
        updated = store.get_project(project["id"])
        assert updated["name"] == "我的图标" and updated["titleMode"] == "manual"
        assert json.loads(Path(project["rootPath"], "project.json").read_text())["name"] == "我的图标"
    else:
        assert store.get_project(project["id"]) is None
        assert not Path(project["rootPath"]).exists()
    assert not providers.calls


def test_local_title_never_contacts_provider_or_touches_tasks(setup):
    store, providers, service, project = setup
    for _ in range(3):
        add_turn(store, project["id"])
    assert service.schedule(project["id"])
    wait_until(lambda: not service.pending(project["id"]))
    assert not service.schedule(project["id"])
    assert not providers.calls
    with store._connect() as db:
        assert {row[0] for row in db.execute("SELECT status FROM tasks")} == {"succeeded"}


def test_long_history_is_bounded_and_projects_are_isolated(setup):
    store, providers, service, project = setup
    other = add_project(store)
    add_turn(store, other["id"], "OTHER_PROJECT_SECRET")
    for i in range(40):
        add_turn(store, project["id"], f"{i}轮 " + "详细描述" * 1000)
    turns = service._candidate(project["id"])["turns"]
    assert "OTHER_PROJECT_SECRET" not in json.dumps(turns)
    assert len(turns) == 8 and turns[0]["user"].startswith("0轮") and turns[-1]["user"].startswith("39轮")
    assert len(json.dumps(turns, ensure_ascii=False)) < 10000


@pytest.mark.parametrize("raw", ['{"title":""}', '{"title":"你好"}', '{"title":"第一行\\n第二行"}', '{"title":' + json.dumps("超长" * 30) + '}', 'not json'])
def test_local_title_rejects_greetings_and_bounds_long_subjects(raw):
    assert local_title([{"user":"你好"}] * 3) is None
    title = local_title([{"user":"帮我设计" + "超长主题" * 30 + "的包装"}])
    assert title and len(title) <= 32 and title.endswith("包装设计")


def test_legacy_defaults_migrate_once_and_custom_names_stay_manual(setup):
    store, providers, service, project = setup
    custom = add_project(store, name="我的命名", mode="manual")
    with store._connect() as db:
        db.execute("UPDATE projects SET title_mode='legacy'")
        db.execute("UPDATE projects SET name='你好' WHERE id=?", (project["id"],))
    reopened = ProjectStore(str(store.workspace_root))
    assert reopened.get_project(project["id"])["name"] == "新对话"
    assert reopened.get_project(project["id"])["titleMode"] == "auto"
    assert reopened.get_project(custom["id"])["name"] == "我的命名"
    assert reopened.get_project(custom["id"])["titleMode"] == "manual"
    reopened.update_project(project["id"], {"name": "你好"})
    again = ProjectStore(str(store.workspace_root))
    assert again.get_project(project["id"])["name"] == "你好"
    assert again.get_project(project["id"])["titleMode"] == "manual"


def test_intake_and_history_api_auto_titles_and_explicit_names(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/intake", data={"name": "你好", "brief": "你好", "autoTitle": "true"}).json()["project"]
        assert project["name"] == "新对话" and project["titleMode"] == "auto"
        manual = client.post("/api/intake", data={"name": "我的品牌", "brief": "你好"}).json()["project"]
        assert manual["titleMode"] == "manual"
        providers = TitleProviders(app.state.store)
        app.state.project_titles.providers = providers
        for _ in range(3):
            add_turn(app.state.store, project["id"])
            add_turn(app.state.store, manual["id"])
        assert client.get("/api/projects").status_code == 200
        wait_until(lambda: not app.state.project_titles.pending(project["id"]))
        listed = {item["id"]: item for item in client.get("/api/projects").json()}
        assert listed[project["id"]]["name"] == "宠物用品 App 图标设计"
        assert not listed[project["id"]]["titlePending"]
        assert listed[manual["id"]]["name"] == "我的品牌"
        assert not providers.calls
        renamed = client.put(f"/api/projects/{project['id']}", json={"name": "我的项目"}).json()
        assert renamed["titleMode"] == "manual" and renamed["name"] == "我的项目"


def test_task_completion_schedules_local_title_without_model_call(setup):
    store, providers, service, project = setup
    for _ in range(2):
        add_turn(store, project["id"])
    runtime = TaskRuntime(store, design_runtime=SimpleNamespace(run=lambda **kwargs: AgentResult(status="succeeded", structured_data={"answer": "已完成"})))
    runtime.project_titles = service
    task = runtime.enqueue(project_id=project["id"], agent_key="design", workflow_step="design", brief="继续制作", input_data={"textProvider": {"key": "openai-compatible", "baseUrl": "https://gateway.test/v1"}})
    assert task["status"] == "succeeded"
    wait_until(lambda: not service.pending(project["id"]))
    assert not providers.calls
