from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    DISCOVERY = "discovery"
    STRATEGY = "strategy"
    CONCEPT = "concept"
    DESIGN = "design"
    ENGINEERING = "engineering"
    COMMERCIAL = "commercial"
    EXPORT = "export"
    ARCHIVED = "archived"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    brief: str = Field(default="", max_length=20_000)
    budgetMinor: int | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=3)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    brief: str | None = Field(default=None, max_length=20_000)
    budgetMinor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class Project(BaseModel):
    id: UUID
    name: str
    slug: str
    brief: str
    budgetMinor: int | None
    currency: str
    status: ProjectStatus
    rootPath: str
    createdAt: datetime
    updatedAt: datetime
    titleMode: str = "manual"
    titleGeneratedAt: datetime | None = None
    titlePending: bool = False
    latestTaskId: str | None = None
    latestTaskStatus: str = 'empty'
    summary: str = ''
    activityAt: str | None = None
    previewRevision: str = 'empty'


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_project(*, name: str, slug: str, brief: str, budget_minor: int | None, currency: str, root_path: str) -> dict[str, Any]:
    timestamp = utc_now().isoformat()
    return {
        "id": str(uuid4()),
        "name": name,
        "slug": slug,
        "brief": brief,
        "budgetMinor": budget_minor,
        "currency": currency.upper(),
        "status": ProjectStatus.DRAFT.value,
        "rootPath": root_path,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }
