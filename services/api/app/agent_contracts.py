from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArtifactRef:
    entity_type: str
    entity_id: str
    version: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class Citation:
    source_id: str
    quote: str
    locator: str | None = None




@dataclass
class AgentResult:
    status: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    confidence: float | None = None
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)




class TextProvider(Protocol):
    provider_key: str

    def complete(self, *, system: str, prompt: str, model: str | None = None, attachments: list[dict[str, Any]] | None = None) -> str:
        ...


class ImageProvider(Protocol):
    provider_key: str

    def generate(self, *, prompt: str, negative_prompt: str | None = None, **params: Any) -> bytes:
        ...


class ThreeDProvider(Protocol):
    provider_key: str

    def generate(self, *, prompt: str, source_asset: str | None = None, output_format: str = "glb", **params: Any) -> dict[str, Any]:
        ...

    def retrieve(self, *, job_id: str, prompt: str = "", source_asset: str | None = None, output_format: str = "glb", **params: Any) -> dict[str, Any]:
        ...


class VideoProvider(Protocol):
    provider_key: str

    def generate(self, *, prompt: str, source_asset: str | None = None, model: str | None = None, **params: Any) -> dict[str, Any]:
        ...
