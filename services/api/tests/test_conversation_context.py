import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_contracts import AgentResult
from app.conversation_context import ConversationContext
from app.design_tools import DesignToolRegistry, DesignToolError
from app.execution_store import ExecutionStore
from app.knowledge import KnowledgeStore
from app.main import new_project
from app.storage import ProjectStore
from app.task_runtime import TASK_SCHEMA, TaskRuntime


@pytest.fixture
def workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    for name in ("one", "two"):
        store.create_project({**new_project(name=name, slug=name, brief="", budget_minor=None, currency="CNY", root_path=str(tmp_path/name)), "id": name})
    with store._connect() as db:
        db.executescript(TASK_SCHEMA)
    return store


def add_turn(store, id, user, answer="已收到", project="one", status="succeeded", output=None, extra=None):
    with store._connect() as db:
        db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,input_json,output_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (id, project, "design", "design", status, json.dumps({"userMessage": user, **(extra or {})}, ensure_ascii=False), json.dumps(output or {"structured_data": {"answer": answer}}, ensure_ascii=False), "2026-09-11T12:00:00Z", "2026-09-11T12:00:00Z"))


def test_same_conversation_reopen_corrections_and_project_isolation(workspace):
    add_turn(workspace, "a", "我叫 Alexi，品牌是 PawJoy，要求透明背景", "记住了")
    add_turn(workspace, "b", "品牌改叫 PawDays，背景要求不变")
    add_turn(workspace, "foreign", "我叫其他用户", project="two")
    add_turn(workspace, "current", "之前品牌叫什么？", status="running")
    add_turn(workspace, "future", "未来的修改不能进入较早一轮")
    context = ConversationContext(workspace).build("one", "current", "品牌")
    messages = context["messages"]
    assert [message["taskId"] for message in messages] == ["a", "a", "b", "b"]
    assert "PawDays" in messages[2]["content"] and "Alexi" in messages[0]["content"]
    assert "其他用户" not in json.dumps(context, ensure_ascii=False) and "未来" not in json.dumps(context, ensure_ascii=False)
    assert ConversationContext(ProjectStore(str(workspace.workspace_root))).build("one", "current", "品牌") == context
    add_turn(workspace, "new", "我叫什么？", project="two", status="running")
    assert "Alexi" not in json.dumps(ConversationContext(workspace).build("two", "new"))
    with pytest.raises(ValueError, match="不属于此项目"):
        ConversationContext(workspace).build("two", "current")


def test_long_history_is_bounded_and_original_text_remains_recallable(workspace):
    for index in range(70):
        add_turn(workspace, str(index), ("项目开场 " if index == 0 else "") + f"第{index}次修改 " + "细节"*6000, answer="冗长回答"*6000)
    add_turn(workspace, "current", "继续", status="running")
    context = ConversationContext(workspace).build("one", "current")
    assert context["historyTurnCount"] == 70 and len(context["messages"]) == 12
    assert len(json.dumps(context, ensure_ascii=False)) < 35000
    assert context["earlierUserExcerpts"][0]["taskId"] == "0"
    service = ConversationContext(workspace)
    first = service.read("one", "current", turn_id="5")
    assert first["results"][0]["nextTextOffset"] == 2500
    second = service.read("one", "current", turn_id="5", text_offset=2500)
    assert second["results"][0]["user"] == ("第5次修改 " + "细节"*6000)[2500:5000]
    assert service.read("one", "current", limit=2)["nextOffset"] == 2
    assert service.read("one", "current", query="项目开场")["results"][0]["taskId"] == "0"


def test_failed_cancelled_turns_are_not_successful_facts(workspace):
    add_turn(workspace, "failed", "透明底", status="failed", answer="透明图已成功生成")
    add_turn(workspace, "cancelled", "生成视频", status="cancelled", answer="视频已完成")
    add_turn(workspace, "current", "接着来", status="running")
    context = ConversationContext(workspace).build("one", "current")
    serialized = json.dumps(context, ensure_ascii=False)
    assert "透明图已成功生成" not in serialized and "视频已完成" not in serialized
    assert "该轮执行失败" in serialized and "该轮已取消" in serialized


def test_records_include_asset_lineage_parameters_and_clarification(workspace):
    output = {"structured_data": {"answer": "已生成", "clarification": {"questions": [{"question": "哪种颜色", "options": ["橙", "紫"]}]}},
              "warnings": ["没有透明像素"], "provenance": {"recovery": {"toolOutputs": [{"name": "generate_image", "output": {
                  "assetId": "asset", "status": "succeeded", "outputKind": "image", "node": {"id": "node", "data": {"title": "吹风机"}},
                  "asset": {"metadata": {"sourceAssetId": "source", "params": {"background": "transparent", "output_format": "png", "baseUrl": "http://private-gateway"}}},
                  "imageOutput": {"hasTransparency": False}}}]}}}
    add_turn(workspace, "a", "创建吹风机", output=output)
    add_turn(workspace, "current", "修改颜色", status="running")
    outcome = ConversationContext(workspace).build("one", "current")["recentOutcomes"][0]
    assert outcome["artifacts"][0]["sourceAssetId"] == "source"
    assert outcome["artifacts"][0]["params"]["background"] == "transparent"
    assert outcome["artifacts"][0]["hasTransparency"] is False
    assert "哪种颜色" in outcome["historicalClarification"] and outcome["warnings"]
    assert "private-gateway" not in json.dumps(outcome)


def test_recall_tool_cannot_access_another_conversation(workspace):
    add_turn(workspace, "a", "本对话资料")
    add_turn(workspace, "foreign", "别的对话秘密", project="two")
    add_turn(workspace, "current", "回查", status="running")
    tools = DesignToolRegistry(workspace)
    result = tools.execute(project_id="one", task_id="current", name="conversation_read", arguments={"turn_id": "foreign"})
    assert result["results"] == []
    with pytest.raises(DesignToolError):
        tools.execute(project_id="two", task_id="current", name="conversation_read", arguments={})


def test_artifacts_survive_router_removing_recovery_payload(workspace):
    add_turn(workspace, "generated", "生成图片")
    receipts = ExecutionStore(workspace)
    fingerprint, _ = receipts.claim("generated", "generate_image", {"prompt": "产品"})
    receipts.complete("generated", fingerprint, {"assetId": "saved-asset", "outputKind": "image", "status": "succeeded", "node": {"id": "saved-node"}})
    add_turn(workspace, "current", "修改刚才那张", status="running")
    context = ConversationContext(workspace).build("one", "current")
    assert context["recentOutcomes"][0]["artifacts"][0]["assetId"] == "saved-asset"
    assert ConversationContext(workspace).read("one", "current", turn_id="generated")["results"][0]["artifacts"][0]["nodeId"] == "saved-node"


def test_runtime_uses_server_history_not_stale_client_and_never_writes_knowledge(workspace, monkeypatch):
    monkeypatch.delenv("AICS_TEST_MODE", raising=False)
    add_turn(workspace, "a", "我叫 Alexi")
    knowledge = KnowledgeStore(workspace)
    knowledge.ingest_global_text(path_relative="knowledge/brand.txt", text="上传的品牌资料", title="品牌")
    documents = knowledge.list_global_documents()
    captured = []
    def run(**kwargs): captured.append(kwargs); return AgentResult(status="succeeded", structured_data={"answer": "本对话中你叫 Alexi"})
    providers = SimpleNamespace(catalog=None, text=lambda *a, **kw: SimpleNamespace(model="fixture"))
    runtime = TaskRuntime(workspace, provider_registry=providers, knowledge_store=knowledge, design_runtime=SimpleNamespace(run=run))
    result = runtime.enqueue(project_id="one", agent_key="design", workflow_step="design", brief="我叫什么", input_data={"textProvider": {"key": "fixture"}, "conversation": [{"role": "user", "content": "来自另一项目"}], "conversationContext": {"projectId": "two"}})
    assert result["status"] == "succeeded", result
    assert captured[0]["constraints"]["conversationContext"]["messages"][0]["content"] == "我叫 Alexi"
    assert captured[0]["prior_outputs"] == [] and "conversation" not in captured[0]["constraints"]
    assert "来自另一项目" not in json.dumps(captured[0]["constraints"], ensure_ascii=False)
    assert knowledge.list_global_documents() == documents and knowledge.list_documents("one") == []
    with workspace._connect() as db:
        saved = json.loads(db.execute("SELECT input_json FROM tasks WHERE id=?", (result["id"],)).fetchone()[0])
        assert "conversation" not in saved and "conversationContext" not in saved


@pytest.mark.parametrize("api", ["chat_completions", "responses"])
@pytest.mark.parametrize("legacy", [False, True])
def test_sdk_remembers_recent_correction_without_dropping_last_assistant(workspace, api, legacy):
    add_turn(workspace, "a", "我叫 Alexi，品牌 PawJoy")
    add_turn(workspace, "b", "品牌改为 PawDays", answer="会沿用透明背景")
    add_turn(workspace, "current", "我叫什么，品牌改成什么了？", status="running")
    context = ConversationContext(workspace).build("one", "current")
    constraints = {"agentCollaboration": False, "conversation": context["messages"]} if legacy else {"agentCollaboration": False, "conversationContext": context}
    payload = {"api": api, "model": "fixture", "apiKey": "fixture", "baseUrl": "http://fixture.invalid/v1", "context": {"projectId": "one", "taskId": "current", "brief": "我叫什么，品牌改成什么了？", "constraints": constraints}}
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([shutil.which("node"), "--import", str(root/"tests/fixtures/conversation_transport.mjs"), str(root/"app/openai_agent_worker.mjs")], input=json.dumps(payload), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout[-8000:]
    final = next(json.loads(line)["result"] for line in result.stdout.splitlines() if line.startswith('{"type":"result"'))
    assert final["structured_data"]["answer"] == "你叫 Alexi，品牌已改为 PawDays。"
    assert final["tool_outputs"] == []
