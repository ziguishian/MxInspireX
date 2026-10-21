from types import SimpleNamespace

import pytest

from app.achievements import AchievementService
from app.assets import AssetStore
from app.canvas import CanvasStore
from app.easter_eggs import COSMIC_SUBTITLE, is_cosmic_future_question
from app.models import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


def make_workspace(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(
        new_project(
            name="彩蛋测试",
            slug="easter-eggs",
            brief="测试",
            budget_minor=None,
            currency="CNY",
            root_path=str(tmp_path / "project"),
        )
    )
    return store, project, AssetStore(store)


def test_image_century_unlocks_once_and_persists_claim(tmp_path):
    store, project, assets = make_workspace(tmp_path)
    achievements = AchievementService(store)
    for index in range(99):
        assets.add_bytes(
            project_id=project["id"],
            kind="image",
            filename=f"generated-{index}.png",
            content=f"image-{index}".encode(),
            metadata={"source": "design-agent-tool"},
        )
    assert achievements.status()["achievements"][0]["unlocked"] is False
    assets.add_bytes(
        project_id=project["id"],
        kind="image",
        filename="generated-100.png",
        content=b"image-100",
        metadata={"source": "user-requested"},
    )
    status = achievements.status()
    assert status["imageGenerationCount"] == 100
    assert status["achievements"][0] == {
        "id": "image-century",
        "title": "百图成章",
        "description": "你已经和小居一起完成了 100 次图像生成。",
        "milestone": 100,
        "unlocked": True,
        "claimed": False,
    }
    assert achievements.claim("image-century")["claimed"] is True
    assert AchievementService(store).status()["achievements"][0]["claimed"] is True


@pytest.mark.parametrize(
    "prompt",
    ["这个世界会被设计成什么样？", "未来会怎么样", "你觉得未来会变成什么样呢？"],
)
def test_cosmic_question_detection(prompt):
    assert is_cosmic_future_question(prompt)


def test_cosmic_answer_uses_prebuilt_image_and_never_calls_agent(tmp_path):
    store, project, assets = make_workspace(tmp_path)
    runtime = TaskRuntime(
        store,
        asset_store=assets,
        design_runtime=SimpleNamespace(run=lambda **_: pytest.fail("不应调用模型")),
    )
    task = runtime.enqueue(
        project_id=project["id"],
        agent_key="design",
        workflow_step="design",
        brief="这个世界会被设计成什么样？未来会怎么样？",
        input_data={"taskSurface": "conversation"},
        run_async=False,
    )
    assert task["status"] == "succeeded"
    assert task["output"]["structured_data"]["answer"] == f"42\n\n{COSMIC_SUBTITLE}"
    assert task["output"]["provenance"] == {
        "executionFlow": "local_easter_egg",
        "provider": "local-prebuilt",
        "model": None,
        "usage": {},
        "billable": False,
    }
    assert task["output"]["usage"] is None
    nodes = CanvasStore(store).load(project["id"])["nodes"]
    assert len(nodes) == 1 and nodes[0]["data"]["kind"] == "image"
    asset = assets.get_asset(project_id=project["id"], asset_id=nodes[0]["data"]["assetId"])
    assert asset and asset["metadata"]["source"] == "system-easter-egg"
    assert asset["metadata"]["preGenerated"] is True
    assert assets.list_assets(project["id"]) == []
    assert AchievementService(store).image_generation_count() == 0
