from __future__ import annotations

from datetime import datetime, timezone


ACHIEVEMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS achievement_claims (
  id TEXT PRIMARY KEY,
  claimed_at TEXT NOT NULL
);
"""


IMAGE_CENTURY = {
    "id": "image-century",
    "title": "百图成章",
    "description": "你已经和MxinspireX一起完成了 100 次图像生成。",
    "milestone": 100,
}


class AchievementService:
    """Workspace-wide, locally persisted product achievements."""

    def __init__(self, store) -> None:
        self.store = store
        with self.store._connect() as connection:
            connection.executescript(ACHIEVEMENT_SCHEMA)

    def image_generation_count(self) -> int:
        with self.store._connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS total FROM assets
                   WHERE kind = 'image'
                   AND json_extract(metadata_json, '$.source') IN (
                     'design-agent-tool', 'user-requested', 'report-agent'
                   )"""
            ).fetchone()
        return int(row["total"] if row else 0)

    def status(self) -> dict:
        count = self.image_generation_count()
        with self.store._connect() as connection:
            claimed = {
                str(row["id"])
                for row in connection.execute("SELECT id FROM achievement_claims").fetchall()
            }
        achievement = {
            **IMAGE_CENTURY,
            "unlocked": count >= int(IMAGE_CENTURY["milestone"]),
            "claimed": IMAGE_CENTURY["id"] in claimed,
        }
        return {"imageGenerationCount": count, "achievements": [achievement]}

    def claim(self, achievement_id: str) -> dict:
        current = next(
            (item for item in self.status()["achievements"] if item["id"] == achievement_id),
            None,
        )
        if current is None:
            raise ValueError("成就不存在")
        if not current["unlocked"]:
            raise ValueError("成就尚未解锁")
        with self.store._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO achievement_claims(id, claimed_at) VALUES (?, ?)",
                (achievement_id, datetime.now(timezone.utc).isoformat()),
            )
        return {**current, "claimed": True}
