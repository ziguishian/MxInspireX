"""CloseAI-specific model catalog normalization.

The normal OpenAI-compatible ``/v1/models`` response can omit media models.
CloseAI's management catalog is therefore an optional, explicit discovery
source.  Its high-privilege credential stays separate from the credential used
for inference, and this module only turns the documented response into the
application's provider-neutral model records.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit


CLOSEAI_CATALOG_CREDENTIAL = "closeai-catalog"


def is_closeai_base_url(base_url: str) -> bool:
    hostname = (urlsplit(base_url).hostname or "").casefold()
    return hostname == "api.openai-proxy.org" or hostname.endswith(".openai-proxy.org")


def management_models_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, "/api/v1/management/models", "", ""))


def _number(value):
    try:
        result = Decimal(str(value))
        return float(result) if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def category_kinds(category) -> list[str]:
    """Map provider categories without treating an unknown category as text."""
    values = category if isinstance(category, (list, tuple)) else [category]
    kinds: set[str] = set()
    exact = {
        "chat": "text", "text": "text", "llm": "text", "language": "text",
        "reasoning": "text", "vision": "text", "multimodal": "text",
        "image": "image", "images": "image", "image-generation": "image", "image-generation-model": "image",
        "text-to-image": "image", "image-edit": "image",
        "video": "video", "videos": "video", "video-generation": "video", "text-to-video": "video", "image-to-video": "video",
        "audio": "audio", "audios": "audio", "speech": "audio", "tts": "audio", "music": "audio",
        "transcription": "audio", "speech-to-text": "audio",
        "embedding": "embedding", "embeddings": "embedding", "rerank": "embedding",
        "3d": "3d", "3d-generation": "3d", "three-d": "3d", "three-dimensional": "3d",
    }
    for value in values:
        normalized = "-".join(str(value or "").strip().lower().replace("_", "-").split())
        if normalized in exact:
            kinds.add(exact[normalized])
        elif normalized.startswith("image-") and "understanding" not in normalized:
            kinds.add("image")
        elif normalized.startswith("video-"):
            kinds.add("video")
        elif normalized.startswith(("audio-", "speech-", "voice-")):
            kinds.add("audio")
    return [kind for kind in ("text", "image", "video", "embedding", "3d", "audio") if kind in kinds]


def _normalized_price(raw) -> dict:
    """Convert only documented, unambiguous per-million price fields."""
    if not isinstance(raw, dict):
        return {}
    aliases = {
        "text_input_price": "inputPerMillion",
        "text_output_price": "outputPerMillion",
        "cache_read_price": "cachedPerMillion",
        "cache_write_price": "cacheWritePerMillion",
        "image_input_price": "imageInputPerMillion",
        "image_output_price": "imageOutputPerMillion",
        "audio_input_price": "audioInputPerMillion",
        "audio_output_price": "audioOutputPerMillion",
        "video_input_price": "videoInputPerMillion",
        "video_output_price": "videoOutputPerMillion",
        "per_image_price": "perImage",
        "image_price": "perImage",
        "per_second_price": "perSecond",
    }
    result = {"currency": str(raw.get("currency") or "CNY").upper()}
    if result["currency"] not in {"CNY", "USD"}:
        result["currency"] = "CNY"
    for source, target in aliases.items():
        number = _number(raw.get(source))
        if number is not None:
            result[target] = number
    # CloseAI documents cache_read_rate as a multiplier of text input price.
    # Derive the cached-token tariff only when both values are numeric.
    input_price = _number(raw.get("text_input_price"))
    cache_rate = _number(raw.get("cache_read_rate"))
    if input_price is not None and cache_rate is not None:
        result["cachedPerMillion"] = input_price * cache_rate
    return result if len(result) > 1 else {}


def _normalized_tiers(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        threshold = _number(item.get("threshold"))
        input_rate = _number(item.get("input_rate"))
        output_rate = _number(item.get("output_rate"))
        if threshold is None or (input_rate is None and output_rate is None):
            continue
        tier = {"threshold": threshold}
        if input_rate is not None:
            tier["inputRate"] = input_rate
        if output_rate is not None:
            tier["outputRate"] = output_rate
        result.append(tier)
    return result


def normalize_management_model(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    model_id = str(item.get("model") or item.get("id") or "").strip()
    if not model_id:
        return None
    category = item.get("category")
    kinds = category_kinds(category)
    raw_pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    record = {
        "id": model_id,
        "name": str(item.get("name") or model_id),
        "owned_by": item.get("vendor") or item.get("owned_by"),
        "vendor": item.get("vendor") or item.get("owned_by"),
        "category": category,
        "providerCategory": category,
        "kinds": kinds or ["unknown"],
        "context_length": item.get("context_window") or item.get("context_length"),
        "maxOutputTokens": item.get("max_output_tokens"),
        "catalogSource": "closeai-management",
    }
    price = _normalized_price(raw_pricing)
    if price:
        record["pricing"] = price
    pricing_tiers = _normalized_tiers(raw_pricing.get("tiers"))
    if pricing_tiers:
        record["pricingTiers"] = pricing_tiers
    if raw_pricing:
        record["rawPricing"] = raw_pricing
    return record


def normalize_management_response(body: object) -> list[dict]:
    items = body.get("models") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise ValueError("CloseAI 管理目录未返回有效的 models 数组")
    return [record for item in items if (record := normalize_management_model(item)) is not None]


def model_aliases(model: str) -> list[str]:
    """Return exact and providerless IDs without crossing model families."""
    value = str(model).strip()
    aliases = [value]
    if "/" in value:
        aliases.append(value.rsplit("/", 1)[-1])
    return list(dict.fromkeys(alias for alias in aliases if alias))
