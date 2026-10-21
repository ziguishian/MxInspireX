from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .assets import AssetStore
from .canvas import CanvasStore


COSMIC_ANSWER = "42"
COSMIC_SUBTITLE = "答案已知，问题仍在生成中。"
COSMIC_EASTER_EGG_ID = "cosmic-answer-42-v1"
COSMIC_PATTERNS = (
    "这个世界会被设计成什么样",
    "世界会被设计成什么样",
    "未来会怎么样",
    "未来会变成什么样",
    "未来是什么样",
)


def is_cosmic_future_question(text: str) -> bool:
    compact = re.sub(r"[\s，。！？!?、,.；;：:\"'“”‘’（）()]+", "", str(text or "")).casefold()
    return any(pattern in compact for pattern in COSMIC_PATTERNS)


class EasterEggService:
    """Creates deterministic local easter-egg outputs without provider calls."""

    def __init__(self, store, asset_store=None) -> None:
        self.store = store
        self.assets = asset_store or AssetStore(store)
        self.canvas = CanvasStore(store)

    def matches(self, brief: str, input_data: dict[str, Any]) -> bool:
        return input_data.get("taskSurface") != "canvas_node" and is_cosmic_future_question(brief)

    @staticmethod
    def _variant(task_id: str) -> int:
        digest = hashlib.sha256(task_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:2], "big") % 9 + 1

    def _asset(self, project_id: str, variant: int) -> dict[str, Any]:
        asset_key = f"{COSMIC_EASTER_EGG_ID}-{variant:02d}"
        with self.store._connect() as connection:
            row = connection.execute(
                """SELECT id FROM assets
                   WHERE project_id = ?
                   AND json_extract(metadata_json, '$.easterEggId') = ?
                   LIMIT 1""",
                (project_id, asset_key),
            ).fetchone()
        if row:
            existing = self.assets.get_asset(project_id=project_id, asset_id=str(row["id"]))
            if existing and Path(existing["absolutePath"]).is_file():
                return existing
        filename = f"cosmic-42-{variant:02d}.png"
        path = Path(__file__).resolve().parent / "easter_egg_assets" / filename
        if not path.is_file():
            raise RuntimeError("内置 42 彩蛋资源缺失")
        return self.assets.add_bytes(
            project_id=project_id,
            kind="image",
            filename=filename,
            content=path.read_bytes(),
            metadata={
                "source": "system-easter-egg",
                "systemHidden": True,
                "easterEggId": asset_key,
                "spriteSheet": "cosmic-42-sprite-v1.png",
                "spriteCell": variant,
                "preGenerated": True,
            },
        )

    def create_output(self, *, project_id: str, task_id: str) -> dict[str, Any]:
        variant = self._variant(task_id)
        asset = self._asset(project_id, variant)
        node = self.canvas.ensure_asset_node(
            project_id,
            asset,
            title=COSMIC_ANSWER,
            summary=COSMIC_SUBTITLE,
            task_id=task_id,
            data={
                "easterEggId": COSMIC_EASTER_EGG_ID,
                "preGenerated": True,
                "previewSize": {"width": 418, "height": 418},
            },
        )
        return {
            "status": "succeeded",
            "structured_data": {
                "answer": f"{COSMIC_ANSWER}\n\n{COSMIC_SUBTITLE}",
                "deliveryStatus": "passed",
                "easterEgg": {
                    "id": COSMIC_EASTER_EGG_ID,
                    "nodeId": node["id"],
                    "assetId": asset["id"],
                    "variant": variant,
                },
            },
            "artifact_refs": [
                {"entity_type": "canvas_node", "entity_id": node["id"], "label": COSMIC_ANSWER}
            ],
            "citations": [],
            "usage": None,
            "confidence": 1.0,
            "assumptions": [],
            "warnings": [],
            "next_actions": [],
            "provenance": {
                "executionFlow": "local_easter_egg",
                "provider": "local-prebuilt",
                "model": None,
                "usage": {},
                "billable": False,
            },
        }
