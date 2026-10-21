from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..billing import MeteredProvider
from ..model_config import DEFAULT_TEXT_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL
from ..credentials import CredentialError, LocalCredentialStore, mask_secret
from ..closeai_catalog import CLOSEAI_CATALOG_CREDENTIAL
from ..evolink import EVOLINK_BASE_URL
from .http import Generic3DProvider, Native3DProvider, OpenAICompatibleEmbeddingProvider, OpenAICompatibleImageProvider, OpenAICompatibleTextProvider, SeedreamVideoProvider
from .local import LocalImageProvider, LocalTextProvider


def _test_providers_enabled() -> bool:
    """Keep deterministic adapters available only to the automated test suite."""
    return os.environ.get("AICS_TEST_MODE", "").strip().lower() in {"1", "true", "yes"}


def _default_openai_base_url() -> str:
    """Resolve the local OpenAI-compatible gateway without handling secrets."""
    configured = os.environ.get("AICS_OPENAI_COMPATIBLE_BASE_URL", "https://api.openai-proxy.org").strip().rstrip("/")
    if not configured:
        configured = "https://api.openai-proxy.org"
    return configured if configured.endswith("/v1") else f"{configured}/v1"


def _default_openrouter_base_url() -> str:
    configured = os.environ.get("AICS_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    return configured or "https://openrouter.ai/api/v1"


def _default_ollama_base_url() -> str:
    configured = os.environ.get("AICS_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").strip().rstrip("/")
    if not configured:
        configured = "http://127.0.0.1:11434/v1"
    return configured if configured.endswith("/v1") else f"{configured}/v1"


def _normalize_openai_base_url(value: str | None) -> str:
    clean = (value or _default_openai_base_url()).strip().rstrip("/")
    if not clean:
        clean = _default_openai_base_url()
    return clean if clean.endswith("/v1") else f"{clean}/v1"


def _normalize_openrouter_base_url(value: str | None) -> str:
    clean = (value or _default_openrouter_base_url()).strip().rstrip("/")
    clean = clean or _default_openrouter_base_url()
    return clean if clean.endswith("/v1") else f"{clean}/v1"


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    kind: str
    label: str
    capabilities: tuple[str, ...]
    requires_key: bool = True
    default_base_url: str | None = None
    default_model: str | None = None
    local: bool = False


class ProviderRegistry:
    def __init__(self, credentials: LocalCredentialStore | None = None) -> None:
        self.credentials = credentials or LocalCredentialStore()
        self.catalog = None
        self.billing = None
        openai_base_url = _default_openai_base_url()
        specs = [
            ProviderSpec("openrouter", "llm", "OpenRouter · 多模型路由", ("text", "json"), True, _default_openrouter_base_url(), DEFAULT_TEXT_MODEL),
            ProviderSpec("evolink", "llm", "EvoLink · 文本 / 图像 / 视频 / 语音", ("text", "json", "image", "video", "audio"), True, EVOLINK_BASE_URL, "gpt-5.4"),
            ProviderSpec("openai-compatible", "llm", "OpenAI Compatible LLM", ("text", "json"), True, openai_base_url, DEFAULT_TEXT_MODEL),
            ProviderSpec("ollama", "llm", "Ollama · 本地模型", ("text", "json"), False, _default_ollama_base_url(), "gpt-oss:20b", True),
            # These aliases intentionally use the same OpenAI-compatible
            # adapter. Users can point them at an OpenAI-compatible gateway
            # for Claude/Gemini models without leaking native vendor keys or
            # coupling the orchestration contract to vendor-specific APIs.
            ProviderSpec("claude", "llm", "Claude · OpenAI-compatible", ("text", "json"), True, openai_base_url, "claude-3-5-sonnet-latest"),
            ProviderSpec("gemini", "llm", "Gemini · OpenAI-compatible", ("text", "json"), True, openai_base_url, "gemini-2.0-flash"),
            ProviderSpec("openai-embeddings", "embedding", "OpenAI-compatible Embeddings", ("embedding",), True, openai_base_url, "text-embedding-3-small"),
            ProviderSpec("openai-image", "image", "OpenAI-compatible Image · 智能路由", ("image",), True, openai_base_url, DEFAULT_IMAGE_MODEL),
            ProviderSpec("generic-3d", "3d", "Generic 3D Adapter", ("text-to-3d", "image-to-3d"), True, None, "generic-3d"),
            ProviderSpec("meshy", "3d", "Meshy · native", ("text-to-3d", "image-to-3d"), True, None, "meshy-v1"),
            ProviderSpec("tripo", "3d", "Tripo · native", ("text-to-3d", "image-to-3d"), True, None, "tripo-v1"),
            ProviderSpec("rodin", "3d", "Rodin · native", ("text-to-3d", "image-to-3d"), True, None, "rodin-v1"),
            ProviderSpec("hunyuan3d", "3d", "Hunyuan3D · native", ("text-to-3d", "image-to-3d"), True, None, "hunyuan3d-v1"),
            ProviderSpec("seedream", "video", "Seedream · native", ("image-to-video", "text-to-video"), True, None, DEFAULT_VIDEO_MODEL),
        ]
        if _test_providers_enabled():
            specs.extend([
                ProviderSpec("local-deterministic", "llm", "测试用确定性文本 Provider", ("text",), False, None, "deterministic-v0", True),
                ProviderSpec("local-placeholder", "image", "测试用图像替身", ("image",), False, None, "placeholder-v0", True),
                ProviderSpec("local-video-placeholder", "video", "测试用视频替身", ("image-to-video", "text-to-video"), False, None, "video-placeholder-v0", True),
            ])
        self.specs = tuple(specs)

    def list(self) -> list[dict[str, Any]]:
        def configured(spec: ProviderSpec) -> bool:
            if not spec.requires_key:
                return True
            # Image and text intentionally share the same OpenAI-compatible
            # gateway credential. Keep the legacy alias as a fallback only.
            if spec.key == "openai-image":
                return bool(self.credentials.get("openai-image") or self.credentials.get("openrouter") or self.credentials.get("openai-compatible"))
            return bool(self.credentials.get(spec.key))

        def credential_hint(spec: ProviderSpec) -> str | None:
            if not spec.requires_key:
                return None
            # The image adapter intentionally shares the OpenRouter /
            # OpenAI-compatible credential. Report the same safe hint that
            # the actual adapter will use, without returning the secret.
            secret = self.credentials.get(spec.key)
            if not secret and spec.key == "openai-image":
                secret = self.credentials.get("openrouter") or self.credentials.get("openai-compatible")
            return mask_secret(secret)

        def public_spec(spec: ProviderSpec) -> dict[str, Any]:
            result = {
                "key": spec.key,
                "kind": spec.kind,
                "label": spec.label,
                "capabilities": list(spec.capabilities),
                "requiresKey": spec.requires_key,
                "defaultBaseUrl": spec.default_base_url,
                "defaultModel": spec.default_model,
                "local": spec.local,
                "configured": configured(spec),
                "credentialHint": credential_hint(spec),
            }
            if spec.key == "openai-compatible":
                catalog_secret = self.credentials.get(CLOSEAI_CATALOG_CREDENTIAL)
                result.update(
                    catalogCredentialConfigured=bool(catalog_secret),
                    catalogCredentialHint=mask_secret(catalog_secret),
                )
            return result

        return [public_spec(spec) for spec in self.specs]

    def is_local(self, key: str) -> bool:
        return any(spec.key == key and spec.local for spec in self.specs)

    def _meter(self, kind, adapter):
        return MeteredProvider(adapter, self.billing, kind) if self.billing and not getattr(adapter, "local", False) and not isinstance(adapter, (LocalTextProvider, LocalImageProvider)) else adapter

    def text(self, *args, **kwargs):
        return self._meter("text", self._text(*args, **kwargs))

    def image(self, *args, **kwargs):
        return self._meter("image", self._image(*args, **kwargs))

    def embedding(self, *args, **kwargs):
        return self._meter("embedding", self._embedding(*args, **kwargs))

    def three_d(self, *args, **kwargs):
        return self._meter("3d", self._three_d(*args, **kwargs))

    def video(self, *args, **kwargs):
        return self._meter("video", self._video(*args, **kwargs))

    def _text(self, key: str, *, base_url: str | None = None, model: str | None = None):
        if key == "local-deterministic" and _test_providers_enabled():
            return LocalTextProvider()
        if key == "openrouter":
            return OpenAICompatibleTextProvider(
                base_url=_normalize_openrouter_base_url(base_url),
                provider_key=key,
                model=model or DEFAULT_TEXT_MODEL,
                credentials=self.credentials,
            )
        if key == "ollama":
            return OpenAICompatibleTextProvider(
                base_url=_normalize_openai_base_url(base_url or _default_ollama_base_url()),
                provider_key=key,
                model=model or "gpt-oss:20b",
                credentials=self.credentials,
                requires_key=False,
                local=True,
            )
        if key == "evolink":
            return OpenAICompatibleTextProvider(base_url=_normalize_openai_base_url(base_url or EVOLINK_BASE_URL), provider_key=key, model=model or "gpt-5.4", credentials=self.credentials)
        if key in {"openai-compatible", "claude", "gemini"}:
            default_base_url = _default_openai_base_url()
            defaults = {"openai-compatible": (default_base_url, DEFAULT_TEXT_MODEL), "claude": (default_base_url, "claude-3-5-sonnet-latest"), "gemini": (default_base_url, "gemini-2.0-flash")}
            default_base_url, default_model = defaults[key]
            return OpenAICompatibleTextProvider(base_url=_normalize_openai_base_url(base_url or default_base_url), provider_key=key, model=model or default_model, credentials=self.credentials)
        raise ValueError(f"{key} 不是文本 Provider")

    def _image(self, key: str, *, base_url: str | None = None, model: str = DEFAULT_IMAGE_MODEL):
        if key == "local-placeholder" and _test_providers_enabled():
            return LocalImageProvider()
        if key == "evolink":
            from .evolink import EvoLinkImageProvider
            return EvoLinkImageProvider(base_url=_normalize_openai_base_url(base_url or EVOLINK_BASE_URL), provider_key=key, model=model, credentials=self.credentials, api='evolink')
        if key in {"openai-image", "openrouter", "openai-compatible"}:
            base = _normalize_openrouter_base_url(base_url) if key == "openrouter" else _normalize_openai_base_url(base_url)
            from ..model_capabilities import model_record
            record = self.catalog.record(key, base, model) if self.catalog else {}
            api = model_record({**record, "id": model})["imageApi"]
            parameters = record.get('supported_parameters') or record.get('supportedParameters')
            parameters = parameters if isinstance(parameters, dict) else None
            if key == "openrouter":
                from .openrouter_image import OpenRouterImageProvider
                return OpenRouterImageProvider(base_url=base, provider_key=key, model=model, credentials=self.credentials,
                                               supported_parameters=parameters, supports_streaming=record.get('supports_streaming') is True)
            if api == "chat_completions" and "openai-proxy.org" in base and "gemini" in model.lower():
                api = "gemini"
            return OpenAICompatibleImageProvider(base_url=base, provider_key=key, model=model, credentials=self.credentials, api=api, supported_parameters=parameters)
        raise ValueError(f"{key} 不是图像 Provider")

    def _embedding(self, key: str = "openai-embeddings", *, base_url: str | None = None, model: str | None = None):
        if key != "openai-embeddings":
            raise ValueError(f"{key} 不是 Embedding Provider")
        return OpenAICompatibleEmbeddingProvider(
            base_url=_normalize_openai_base_url(base_url or _default_openai_base_url()),
            provider_key=key,
            model=model or "text-embedding-3-small",
            credentials=self.credentials,
        )

    def _three_d(self, key: str, *, endpoint: str | None = None):
        if key == "generic-3d":
            return Generic3DProvider(provider_key=key, credentials=self.credentials, endpoint=endpoint)
        if key in {"meshy", "tripo", "rodin", "hunyuan3d"}:
            return Native3DProvider(provider_key=key, credentials=self.credentials, endpoint=endpoint)
        raise ValueError(f"{key} 不是 3D Provider")

    def _video(self, key: str, *, endpoint: str | None = None, model: str = DEFAULT_VIDEO_MODEL):
        if key == "local-video-placeholder" and _test_providers_enabled():
            return SeedreamVideoProvider(provider_key=key, credentials=self.credentials, endpoint=endpoint, model=model, local=True)
        if key == "openrouter":
            from .openrouter_video import OpenRouterVideoProvider
            return OpenRouterVideoProvider(provider_key=key, credentials=self.credentials, endpoint=_normalize_openrouter_base_url(endpoint), model=model)
        if key == "evolink":
            from .evolink import EvoLinkVideoProvider
            return EvoLinkVideoProvider(provider_key=key, credentials=self.credentials, endpoint=_normalize_openai_base_url(endpoint or EVOLINK_BASE_URL), model=model)
        if key in {"seedream", "openai-compatible"}:
            return SeedreamVideoProvider(provider_key=key, credentials=self.credentials, endpoint=endpoint, model=model)
        raise ValueError(f"{key} 不是视频 Provider")

    @staticmethod
    def detect_3d_provider(endpoint: str | None, hint: str | None = None) -> str:
        """Infer a native 3D adapter from a provider hint or endpoint host."""
        if hint in {"generic-3d", "meshy", "tripo", "rodin", "hunyuan3d"}:
            return hint
        haystack = f"{hint or ''} {endpoint or ''}".lower()
        for key, needles in {
            "meshy": ("meshy",),
            "tripo": ("tripo",),
            "rodin": ("rodin", "hyper3d"),
            "hunyuan3d": ("hunyuan", "tencentcloud"),
        }.items():
            if any(needle in haystack for needle in needles):
                return key
        return hint or "generic-3d"

    def set_credential(self, key: str, secret: str) -> None:
        if key not in {spec.key for spec in self.specs if spec.requires_key}:
            raise CredentialError("该 Provider 不需要或不支持凭据配置")
        self.credentials.set(key, secret)

    def set_catalog_credential(self, key: str, secret: str) -> None:
        if key != "openai-compatible":
            raise CredentialError("该 Provider 不支持独立目录凭据")
        self.credentials.set(CLOSEAI_CATALOG_CREDENTIAL, secret)
