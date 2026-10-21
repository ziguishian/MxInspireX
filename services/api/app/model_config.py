"""Model IDs live here, never in Agent instructions or task routing rules."""
from __future__ import annotations

import os
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelTier(StrEnum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    REASONING = "REASONING"
    PREMIUM = "PREMIUM"


DEFAULT_DRAFT_IMAGE_MODEL = "openai/gpt-image-2.5-flare"
DEFAULT_IMAGE_MODEL = "openai/gpt-image-2.5-sunburst"
FALLBACK_IMAGE_MODEL = "openai/gpt-image-2"
SEEDREAM_IMAGE_MODELS = (
    "bytedance-seed/seedream-5-0-lite",
    "bytedance-seed/seedream-5-0-pro",
    "bytedance-seed/seedream-4.5",
)
DEFAULT_VIDEO_MODEL = "bytedance/seedance-2.5"
DEFAULT_DRAFT_VIDEO_MODEL = "bytedance/seedance-2.0-mini"
DEFAULT_FAST_TEXT_MODEL = "openai/gpt-6-luna"
DEFAULT_TEXT_MODEL = DEFAULT_FAST_TEXT_MODEL
DEFAULT_TEXT_FALLBACK_MODEL = "openai/gpt-6-sol"
DEFAULT_REASONING_TEXT_MODEL = "gpt-6.1-sol"
DEFAULT_SEARCH_MODEL = DEFAULT_FAST_TEXT_MODEL


class EndpointModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: str = "inherit"
    baseUrl: str = ""
    model: str = ""
    api: Literal["auto", "responses", "chat_completions"] = "auto"

    @field_validator("baseUrl")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("模型地址必须是不含凭据、查询参数的 HTTP(S) 地址")
        return value.rstrip("/")


class ProviderPreference(BaseModel):
    """Last explicitly selected text gateway, without persisting credentials."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = ""
    baseUrl: str = ""

    @field_validator("baseUrl")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        return EndpointModel.safe_endpoint(value)


class TierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    primary: EndpointModel
    fallback: EndpointModel | None = None
    reasoningEffort: Literal["none", "low", "medium", "high", "xhigh"]
    maxTurns: int = Field(ge=1, le=60)
    # Accept old saved tier settings without reintroducing execution deadlines.
    timeout: None = Field(default=None, exclude=True)
    # Only confirmed pre-submit transient failures are retried. The SDK itself
    # keeps retries disabled so an uncertain, possibly billed request is never
    # replayed behind our accounting boundary.
    retries: int = Field(default=2, ge=0, le=2)

    @field_validator('timeout', mode='before')
    @classmethod
    def discard_legacy_timeout(cls, value):
        return None


class CreditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    # Legacy ledger/budget compatibility only; UI uses observed Token and costCny.
    pointsPerCny: float = Field(default=100, gt=0, le=100000)
    multiplier: float = Field(default=1, gt=0, le=100)
    # An explicit accounting assumption, not a live exchange-rate claim.
    usdToCny: float = Field(default=7.2, gt=0, le=100)


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    currency: Literal["USD", "CNY"] = "USD"
    inputPerMillion: float | None = Field(default=None, ge=0)
    outputPerMillion: float | None = Field(default=None, ge=0)
    cachedPerMillion: float | None = Field(default=None, ge=0)
    cacheWritePerMillion: float | None = Field(default=None, ge=0)
    imageInputPerMillion: float | None = Field(default=None, ge=0)
    imageOutputPerMillion: float | None = Field(default=None, ge=0)
    audioInputPerMillion: float | None = Field(default=None, ge=0)
    audioOutputPerMillion: float | None = Field(default=None, ge=0)
    videoInputPerMillion: float | None = Field(default=None, ge=0)
    videoOutputPerMillion: float | None = Field(default=None, ge=0)
    perInputImage: float | None = Field(default=None, ge=0)
    perImage: float | None = Field(default=None, ge=0)
    perSecond: float | None = Field(default=None, ge=0)
    perRequest: float | None = Field(default=None, ge=0)
    perSearch: float | None = Field(default=None, ge=0)


def default_tiers() -> dict[ModelTier, TierConfig]:
    values = {
        ModelTier.FAST: (DEFAULT_FAST_TEXT_MODEL, None, "low", 60),
        ModelTier.STANDARD: (DEFAULT_TEXT_MODEL, None, "low", 60),
        ModelTier.REASONING: (DEFAULT_REASONING_TEXT_MODEL, None, "high", 60),
        ModelTier.PREMIUM: ("gpt-6-astra", None, "high", 60),
    }
    result = {}
    for tier, (default_model, fallback_model, effort, turns) in values.items():
        model = os.getenv(f"AICS_MODEL_{tier}", default_model)
        fallback = (EndpointModel(model=fallback_model)
                    if fallback_model and model.split('/')[-1] != fallback_model.split('/')[-1]
                    else None)
        result[tier] = TierConfig(
            primary=EndpointModel(model=model), fallback=fallback,
            reasoningEffort=effort, maxTurns=turns,
        )
    return result


class MemorySettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    compactionEnabled: bool = True


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    defaultsVersion: int = 10
    svgDrawing: Literal['off'] = 'off'

    @field_validator('svgDrawing', mode='before')
    @classmethod
    def disable_legacy_svg_modes(cls, value):
        # Accept old saved configurations without restoring SVG capability.
        if value in ('off', 'explicit', 'auto'):
            return 'off'
        return value
    tiers: dict[ModelTier, TierConfig] = Field(default_factory=default_tiers)
    media: dict[str, dict[str, str]] = Field(default_factory=lambda: {
        "image": {
            quality: os.getenv("AICS_IMAGE_MODEL", DEFAULT_DRAFT_IMAGE_MODEL if quality == "draft" else DEFAULT_IMAGE_MODEL)
            for quality in ("draft", "standard", "final")
        },
        "video": {quality: os.getenv("AICS_VIDEO_MODEL", DEFAULT_DRAFT_VIDEO_MODEL if quality == "draft" else DEFAULT_VIDEO_MODEL) for quality in ("draft", "standard", "final")},
        "3d": {"draft": "", "final": ""},
    })
    maxEscalations: int = Field(default=0, ge=0, le=3)
    roles: dict[Literal['research','review'], EndpointModel] = Field(default_factory=lambda: {'research':EndpointModel()})
    # Accept old saved settings without letting them throttle new tasks.
    maxParallelTools: None = Field(default=None, exclude=True)

    @field_validator('maxParallelTools', mode='before')
    @classmethod
    def discard_legacy_parallel_limit(cls, value):
        return None

    taskBudgetPoints: float | None = Field(default=None, gt=0, le=10000000)
    maxOutputTokens: int = Field(default=4096, ge=256, le=32768)
    # Search follows the active Agent endpoint unless the user explicitly
    # configures an independent provider/model here.
    search: EndpointModel = Field(default_factory=lambda: EndpointModel(provider='inherit', api='responses'))
    preferredTextProvider: ProviderPreference = Field(default_factory=ProviderPreference)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    credits: CreditConfig = Field(default_factory=CreditConfig)
    # Keys include provider + endpoint + model, so relay tariffs never leak
    # into another gateway's accounting. See ModelCatalog.price_key.
    prices: dict[str, ModelPrice] = Field(default_factory=dict)

    @field_validator("tiers")
    @classmethod
    def all_tiers(cls, value):
        if set(value) != set(ModelTier):
            raise ValueError("必须配置 FAST、STANDARD、REASONING、PREMIUM 四个等级")
        return value

    @field_validator("media")
    @classmethod
    def media_slots(cls, value):
        for kind, qualities in {"image": {"draft", "standard", "final"}, "video": {"draft", "standard", "final"}, "3d": {"draft", "final"}}.items():
            if not qualities.issubset(value.get(kind, {})):
                raise ValueError(f"缺少 {kind} 的质量等级配置")
        return value
