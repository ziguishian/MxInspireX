"""Normalize relay metadata without inventing model IDs or fetching a catalog.

Classification is deliberately evidence based.  Provider categories are the
strongest signal, followed by declared output modalities/endpoints, then a
small set of stable model-family rules.  A bare OpenAI-compatible model row is
still treated as text for backwards compatibility, while an unrecognised
*explicit* category remains unknown instead of leaking into the chat picker.
"""
from __future__ import annotations

import re

from .closeai_catalog import category_kinds


KIND_ORDER = ("text", "image", "video", "embedding", "3d", "audio", "unknown")

_FAMILY_KIND_PATTERNS = {
    "image": re.compile(
        r"gpt-?image|dall-?e|dalle|flux|sdxl|stable-?diffusion|midjourney|"
        r"imagen|seedream|wanx|qwen-?image|kolors|nano-?banana|gemini.*image|"
        r"(?:^|[/.-])image(?:[/.-]|$)"
    ),
    "video": re.compile(r"video|kling|sora|veo|runway|wan-?2|seedance"),
    "embedding": re.compile(r"embed|rerank|(?:^|[/.-])bge(?:[/.-]|$)|(?:^|[/.-])e5-"),
    "3d": re.compile(r"(?:^|[/.-])3d(?:[/.-]|$)|meshy|tripo|rodin"),
    "audio": re.compile(r"tts|audio|voice|music"),
}

_VENDOR_PATTERNS = (
    ("anthropic", re.compile(r"(?:^|/)claude-")),
    ("google", re.compile(r"(?:^|/)gemini-|(?:^|/)imagen-|(?:^|/)veo-")),
    ("deepseek", re.compile(r"(?:^|/)deepseek-")),
    ("bytedance", re.compile(r"(?:^|/)(?:doubao-|seedream-|seedance-)")),
    ("z-ai", re.compile(r"(?:^|/)glm-")),
    ("moonshot", re.compile(r"(?:^|/)kimi-")),
    ("alibaba", re.compile(r"(?:^|/)qwen")),
    ("minimax", re.compile(r"(?:^|/)minimax-")),
    ("black-forest-labs", re.compile(r"(?:^|/)flux(?:-|\b)")),
    ("kuaishou", re.compile(r"(?:^|/)kling(?:-|\b)")),
    ("stability-ai", re.compile(r"stable-?diffusion|(?:^|/)sdxl(?:-|\b)")),
    ("openai", re.compile(r"(?:^|/)(?:gpt-|o[134](?:-|$)|dall-?e)")),
)


def strings(value):
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()] if isinstance(value, (list, tuple)) else []


def normalized_model_name(model_id: str) -> str:
    return re.sub(r"[\s_]+", "-", str(model_id).strip().lower())


def family_kinds(model_id: str) -> set[str]:
    """Return only strong output-family matches; vision inputs stay text."""
    name = normalized_model_name(model_id)
    matches = {kind for kind, pattern in _FAMILY_KIND_PATTERNS.items() if pattern.search(name)}
    if "audio" in matches and re.search(r"transcrib|whisper|speech-to-text", name):
        matches.discard("audio")
        matches.add("text")
    return matches


def inferred_vendor(model_id: str) -> str | None:
    """Infer a display vendor without trusting a relay's generic ``owned_by``."""
    name = normalized_model_name(model_id)
    return next((vendor for vendor, pattern in _VENDOR_PATTERNS if pattern.search(name)), None)


def endpoint_kinds(endpoints: list[str]) -> set[str]:
    value = " ".join(endpoints).lower()
    result: set[str] = set()
    if re.search(r"images?/generations?|images?/edits?", value):
        result.add("image")
    if re.search(r"videos?/generations?|text-to-video|image-to-video", value):
        result.add("video")
    if re.search(r"audio/(?:speech|transcriptions?)|text-to-speech", value):
        result.add("audio")
    if re.search(r"embeddings?|rerank", value):
        result.add("embedding")
    if re.search(r"text-to-3d|image-to-3d", value):
        result.add("3d")
    return result


def classify_model(item: dict, *, outputs: set[str], endpoints: list[str]) -> tuple[list[str], str, str]:
    """Classify one row and expose why it was classified that way."""
    declared_category = item.get("providerCategory", item.get("category"))
    if declared_category is not None:
        declared = category_kinds(declared_category)
        return (declared, "provider-category", "authoritative") if declared else (["unknown"], "unknown-provider-category", "authoritative")

    known_family = family_kinds(str(item.get("id") or ""))
    declared_outputs = outputs & set(KIND_ORDER)
    # CloseAI and some relays return generic text metadata from model-detail
    # for generation-only families.  A strong generation family is more useful
    # than that demonstrably generic text marker, but real media outputs remain.
    if known_family and declared_outputs <= {"text", "unknown"}:
        kinds = known_family
        source, confidence = "model-family", "high"
    elif declared_outputs:
        kinds = declared_outputs
        source, confidence = "output-modalities", "authoritative"
    else:
        endpoint_matches = endpoint_kinds(endpoints)
        if endpoint_matches:
            kinds = endpoint_matches
            source, confidence = "supported-endpoints", "high"
        else:
            legacy = set(strings(item.get("kinds"))) or ({str(item["kind"])} if item.get("kind") else set())
            legacy &= set(KIND_ORDER)
            if known_family:
                # Old cached ``kind=text`` values must not keep a known media
                # generator in the chat picker.
                kinds = known_family | (legacy - {"text", "unknown"})
                source, confidence = "model-family", "high"
            elif legacy:
                kinds = legacy
                existing_source = str(item.get("classificationSource") or "").strip()
                existing_confidence = str(item.get("classificationConfidence") or "").strip()
                if existing_source:
                    source, confidence = existing_source, existing_confidence or "medium"
                else:
                    source, confidence = "cached-capability", "medium"
            else:
                kinds = {"text"}
                source, confidence = "openai-compatible-default", "low"

    ordered = [kind for kind in KIND_ORDER if kind in kinds]
    return ordered or ["unknown"], source, confidence


def model_record(item):
    model_id = str(item["id"]).strip()
    architecture = item.get("architecture") or {}
    if not isinstance(architecture, dict):
        architecture = {}
    incoming = strings(item.get("input_modalities") or item.get("inputModalities") or architecture.get("input_modalities"))
    outgoing = strings(item.get("output_modalities") or item.get("outputModalities") or architecture.get("output_modalities"))
    modality = str(item.get("modality") or architecture.get("modality") or "")
    outputs = {x.lower().strip() for x in outgoing}
    if not outputs and "->" in modality:
        outputs = set(modality.lower().split("->")[-1].split("+"))
    if not incoming and "->" in modality:
        incoming = modality.lower().split("->")[0].split("+")
    endpoints = strings(item.get("supported_endpoint_types") or item.get("supportedEndpoints") or item.get("endpoints"))
    ordered, classification_source, classification_confidence = classify_model(item, outputs=outputs, endpoints=endpoints)
    kinds = set(ordered)
    name = normalized_model_name(model_id)
    endpoint_text = " ".join(endpoints).lower()
    image_api = "chat_completions" if ("image" in kinds and ("chat/completions" in endpoint_text or "gemini" in name or "nano-banana" in name) and "images/generations" not in endpoint_text) else "images"
    parameters = item.get("supported_parameters") or item.get("supportedParameters") or []
    text_api = "responses" if (re.search(r"(?:^|/)gpt-[56](?:[.-]|\b)", name) or ("responses" in endpoint_text and "chat" not in endpoint_text)) else "chat_completions"
    audio_api = "speech" if "audio/speech" in endpoint_text or re.search(r"tts|eleven|kokoro|speech", name) else "chat_completions" if "audio" in kinds else "auto"
    owned_by = item.get("owned_by") or item.get("ownedBy")
    vendor = item.get("vendor") or inferred_vendor(model_id) or owned_by
    return {**item, "id": model_id, "name": str(item.get("name") or model_id),
            "ownedBy": owned_by, "vendor": vendor,
            "inputModalities": incoming, "outputModalities": outgoing, "modality": modality or None,
            "supportedParameters": list(parameters) if isinstance(parameters, dict) else strings(parameters),
            "supportedEndpoints": endpoints, "contextLength": item.get("context_length") or item.get("contextLength"),
            "kind": ordered[0], "kinds": ordered,
            "classificationSource": classification_source, "classificationConfidence": classification_confidence,
            "imageApi": image_api, "textApi": text_api, "audioApi": audio_api}


def normalize_snapshot(data):
    # Only IDs actually returned by the relay are eligible, including on migration.
    models = sorted({x.strip() for x in data.get("models", []) if isinstance(x, str) and x.strip()})
    records = {item["id"]: item for item in data.get("modelCatalog", []) if isinstance(item, dict) and item.get("id")}
    catalog = [model_record(records.get(model, {"id": model})) for model in models]
    result = {**data, "models": models, "modelCatalog": catalog}
    for kind, field in {"text": "textModels", "image": "imageModels", "video": "videoModels", "audio": "audioModels", "embedding": "embeddingModels", "3d": "threeDModels", "unknown": "unknownModels"}.items():
        result[field] = [item["id"] for item in catalog if kind in item["kinds"]]
    return result
