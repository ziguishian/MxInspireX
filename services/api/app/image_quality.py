"""Choose image model tier, provider quality, and output resolution together."""
from __future__ import annotations

import re
from math import gcd

from .image_parameters import prepare_image_parameters


_QUALITY_TO_TIER = {
    "draft": "draft",
    "low": "draft",
    "standard": "standard",
    "medium": "standard",
    "production": "final",
    "final": "final",
    "high": "final",
    "xhigh": "final",
    "max": "final",
}
_TIER_TO_QUALITY = {"draft": "low", "standard": "medium", "final": "high"}
_NEGATED = re.compile(r"不(?:要|用|需要)|禁止|别|无需|\b(?:not|never|don.t|without)\b", re.I)
_BEST = re.compile(
    r"最高(?:质量|画质|品质)|最好(?:的)?(?:质量|画质|品质|效果|成图|输出)|(?:要|用|给我|选择).{0,6}最好(?:的)?(?:档位|模型|设计|图像?|效果)?(?:$|[，。！？])|顶级(?:质量|画质|品质)|"
    r"(?:质量|画质|品质).{0,4}(?:拉满|最高)|极致画质|\b(?:best|highest|max(?:imum)?|ultra) quality\b",
    re.I,
)
_XHIGH = re.compile(r"超高(?:质量|画质|品质)|\bxhigh(?: quality)?\b", re.I)
_HIGH = re.compile(
    r"高(?:质量|画质|品质)|(?:做|生成|输出|给我|要).{0,10}高清|高清(?:输出|成图|质量|画质|交付)|精修|高保真|正式交付|生产用|可直接生产|定稿|成稿|最终(?:图|效果图?|版本|交付)|"
    r"\b(?:high|final|production) quality\b",
    re.I,
)
_STANDARD = re.compile(r"标准(?:质量|画质)|普通(?:质量|画质)|中等(?:质量|画质)|\b(?:standard|medium|normal) quality\b", re.I)
_DRAFT = re.compile(
    r"(?:用|要|做|给|来|生成|输出|画|出).{0,8}草稿|草稿(?:质量|画质|模式)|^\s*草稿\s*$|"
    r"降低(?:质量|画质)|低(?:质量|画质)|概念草图|构图测试|缩略图|"
    r"\b(?:use|generate|make|draw|create)\b.{0,20}\bdraft\b|\bdraft (?:quality|mode|image)\b|low quality",
    re.I,
)
_PRINT = re.compile(r"印刷|喷绘|大屏|展板|灯箱|户外广告|出版|包装展开|刀版|\b(?:print|large format|billboard)\b", re.I)
_EXPLORATION = re.compile(r"方向探索|风格探索|构图探索|概念探索|情绪板|灵感板|缩略图|构图测试|概念草图|\b(?:moodboard|thumbnail|composition test)\b", re.I)
_VARIATIONS = re.compile(r"(?:多个|几版|[二三四五六七八九十2-9]\s*(?:个|版|套)).{0,8}(?:方向|方案|候选|版本)|(?:方向|方案|候选).{0,8}(?:多个|几版|[二三四五六七八九十2-9]\s*(?:个|版|套))")
_EXACT_SIZE = re.compile(r"(?<!\d)([1-9]\d{2,4})\s*[x×]\s*([1-9]\d{2,4})(?!\d)", re.I)
_RESOLUTION = re.compile(r"(?<![A-Za-z0-9])([124])\s*[kK](?![A-Za-z0-9])")
_ASPECT_RATIO = re.compile(r"(?<!\d)(\d{1,2})\s*[:：比]\s*(\d{1,2})(?!\d)")
_CHINESE_RATIO = re.compile(r"([一二三四五六七八九十])\s*比\s*([一二三四五六七八九十])")
_CHINESE_NUMBER = {value: index for index, value in enumerate("零一二三四五六七八九十")}


def _clauses(text: str):
    return [part.strip() for part in re.split(r"[，。；;\n]|\bbut\b", str(text or ""), flags=re.I) if part.strip()]


def _explicit_quality(text: str):
    """Return the last non-negated explicit quality request."""
    for clause in reversed(_clauses(text)):
        if _NEGATED.search(clause):
            if re.search(r"草稿|低(?:质量|画质)|\blow quality\b|\bdraft\b", clause, re.I):
                return "medium"
            continue
        if _BEST.search(clause):
            return "max"
        if _XHIGH.search(clause):
            return "xhigh"
        if _HIGH.search(clause):
            return "high"
        if _STANDARD.search(clause):
            return "medium"
        if _DRAFT.search(clause):
            return "low"
    return None


def _explicit_dimensions(text: str):
    """Return the last exact size or K tier explicitly requested by the user."""
    for clause in reversed(_clauses(text)):
        if _NEGATED.search(clause):
            continue
        exact = list(_EXACT_SIZE.finditer(clause))
        if exact:
            match = exact[-1]
            return f"{match.group(1)}x{match.group(2)}", None
        tiers = list(_RESOLUTION.finditer(clause))
        if tiers:
            return None, f"{tiers[-1].group(1)}K"
        if re.search(r"最高分辨率|最大分辨率|分辨率.{0,4}(?:拉满|最高)", clause):
            return None, "4K"
    return None, None


def _explicit_aspect_ratio(text: str) -> str | None:
    for clause in reversed(_clauses(text)):
        if _NEGATED.search(clause):
            continue
        matches = list(_ASPECT_RATIO.finditer(clause))
        if matches:
            width, height = int(matches[-1].group(1)), int(matches[-1].group(2))
            if width and height:
                divisor = gcd(width, height)
                return f"{width // divisor}:{height // divisor}"
        chinese = list(_CHINESE_RATIO.finditer(clause))
        if chinese:
            width = _CHINESE_NUMBER[chinese[-1].group(1)]
            height = _CHINESE_NUMBER[chinese[-1].group(2)]
            if width and height:
                divisor = gcd(width, height)
                return f"{width // divisor}:{height // divisor}"
    return None


def _memory_preference(memory, key):
    for record in reversed((memory or {}).get("selected", [])):
        if record.get("key") == key and record.get("status") == "confirmed":
            return str(record.get("content") or "")
    return ""


def decide_image_policy(
    requested=None,
    *,
    user_message=None,
    prompt=None,
    params=None,
    memory=None,
    has_references=False,
    trust_requested=True,
    trust_dimensions=True,
):
    """Resolve model tier, provider quality, and resolution for one image."""
    options = dict(params or {})
    # ``None`` means there is no persisted user turn (for example the direct
    # image endpoint).  An empty persisted turn is still authoritative: do not
    # mine the Agent-expanded/provider prompt for quality signals, because it
    # may contain internal phrases such as “高质量成品”.
    has_user_message = user_message is not None
    user_text = str(user_message or "")
    direct_text = user_text if has_user_message else str(prompt or "")
    explicit_quality = _explicit_quality(direct_text)
    explicit_size, explicit_resolution = _explicit_dimensions(direct_text)
    # Composition ratios are safe to recover from the Agent's prepared prompt:
    # unlike quality/resolution, they do not silently buy a slower tier.  This
    # also lets a textual "三比一" correct a rough inferred 3840x1200 ratio.
    explicit_aspect_ratio = _explicit_aspect_ratio(direct_text) or _explicit_aspect_ratio(prompt or "")

    if not explicit_quality:
        explicit_quality = _explicit_quality(_memory_preference(memory, "image_quality"))
    if not explicit_size and not explicit_resolution:
        explicit_size, explicit_resolution = _explicit_dimensions(_memory_preference(memory, "image_resolution"))

    raw_requested = str(requested or "").strip().lower()
    raw_param_quality = str(options.get("quality") or "").strip().lower()
    requested_applies = trust_requested or raw_requested in {"draft", "low"} or bool(explicit_quality)
    effective_requested = raw_requested if requested_applies else ""
    base_tier = _QUALITY_TO_TIER.get(effective_requested, "draft")
    provider_quality = _TIER_TO_QUALITY[base_tier]
    quality_source = "parameter" if effective_requested in {"low", "medium", "high", "xhigh", "max"} else "tool" if effective_requested else "default"
    if effective_requested in {"low", "medium", "high", "xhigh", "max"}:
        provider_quality = effective_requested

    # Direct UI/provider controls are explicit. The original user message still
    # wins over an Agent-generated parameter.
    if not effective_requested and raw_param_quality in {"low", "medium", "high", "xhigh", "max"}:
        provider_quality = raw_param_quality
        base_tier = _QUALITY_TO_TIER[raw_param_quality]
        quality_source = "parameter"
    if explicit_quality:
        provider_quality = explicit_quality
        base_tier = _QUALITY_TO_TIER[explicit_quality]
        quality_source = "user"

    # Prefer the original user message over an Agent-expanded provider prompt.
    # References are capability inputs, not evidence that the user requested a
    # slower or more expensive quality tier.
    intent_text = direct_text
    param_size = str(options.get("size") or "").strip()
    param_resolution = str(options.get("resolution") or options.get("image_size") or "").strip().upper()
    param_pixels = re.fullmatch(r"([1-9]\d*)\s*[x×]\s*([1-9]\d*)", param_size, re.I)
    trusted_parameter_resolution = trust_dimensions and (
        param_resolution in {"2K", "4K"} or (
            bool(param_pixels) and max(int(param_pixels.group(1)), int(param_pixels.group(2))) >= 2048
        )
    )
    high_resolution = explicit_resolution in {"2K", "4K"} or (
        bool(explicit_size) and max(map(int, explicit_size.lower().split("x"))) >= 2048
    ) or trusted_parameter_resolution
    quality_was_selected = bool(explicit_quality or effective_requested in _QUALITY_TO_TIER or raw_param_quality in _QUALITY_TO_TIER)
    if not quality_was_selected:
        if _PRINT.search(intent_text) or high_resolution:
            base_tier, provider_quality, quality_source = "final", "high", "intent"
        elif _EXPLORATION.search(intent_text):
            base_tier, provider_quality, quality_source = "draft", "low", "intent"

    has_param_pixels = bool(param_size and param_size.lower() != "auto") or options.get("width") is not None or options.get("height") is not None
    size = None
    resolution = None
    resolution_source = "default"

    if explicit_size:
        size, resolution_source = explicit_size, "user"
    elif explicit_resolution:
        resolution, resolution_source = explicit_resolution, "user"
    elif has_param_pixels and trust_dimensions:
        resolution_source = "parameter"
    elif has_param_pixels:
        # Agent-inferred pixels describe composition, not an authorized output
        # size. Preserve only their ratio and keep the creative resolution.
        resolution, resolution_source = ("1K" if provider_quality == "low" else "2K"), "default"
    elif param_resolution in {"512", "1K", "2K", "4K"} and trust_dimensions:
        resolution, resolution_source = param_resolution, "parameter"
    elif param_resolution in {"512", "1K", "2K", "4K"}:
        resolution, resolution_source = ("1K" if provider_quality == "low" else "2K"), "default"
    elif provider_quality in {"xhigh", "max"} and quality_source in {"user", "parameter"}:
        resolution, resolution_source = "4K", "quality"
    elif _PRINT.search(intent_text):
        resolution, resolution_source = "4K", "intent"
    elif provider_quality == "low" or _EXPLORATION.search(intent_text):
        resolution, resolution_source = "1K", "intent"
    elif _VARIATIONS.search(intent_text) and provider_quality == "medium":
        resolution, resolution_source = "1K", "intent"
    else:
        resolution, resolution_source = "2K", "default"

    reason = {
        "user": "用户明确指定",
        "parameter": "界面或工具参数指定",
        "quality": "最高质量请求同步使用最高分辨率",
        "intent": "根据交付用途智能判断",
        "tool": "Agent 指定任务阶段",
        "default": "创意探索默认档",
    }
    inferred_aspect_ratio = explicit_aspect_ratio
    if param_pixels and not trust_dimensions and not explicit_size:
        width, height = int(param_pixels.group(1)), int(param_pixels.group(2))
        divisor = gcd(width, height)
        inferred_aspect_ratio = inferred_aspect_ratio or f"{width // divisor}:{height // divisor}"
    return {
        "tier": base_tier,
        "quality": provider_quality,
        "size": size,
        "resolution": resolution,
        "qualitySource": quality_source,
        "resolutionSource": resolution_source,
        "userOverride": quality_source == "user" or resolution_source == "user",
        "discardToolDimensions": bool(not trust_dimensions and (has_param_pixels or param_resolution)),
        "inferredAspectRatio": inferred_aspect_ratio,
        "aspectRatioSource": "user" if explicit_aspect_ratio else "tool" if inferred_aspect_ratio else None,
        "reason": f"{reason.get(quality_source, '智能判断')}；{reason.get(resolution_source, '智能判断')}",
    }


def apply_policy_dimensions(params, decision):
    options = dict(params or {})
    if decision.get("discardToolDimensions"):
        for key in ("size", "width", "height", "resolution", "image_size"):
            options.pop(key, None)
        if decision.get("inferredAspectRatio") and not options.get("aspectRatio"):
            options["aspectRatio"] = decision["inferredAspectRatio"]
    if decision.get("aspectRatioSource") == "user" and decision.get("inferredAspectRatio"):
        options["aspectRatio"] = decision["inferredAspectRatio"]
    if decision.get("size"):
        for key in ("width", "height", "resolution", "image_size"):
            options.pop(key, None)
        options["size"] = decision["size"]
    elif decision.get("resolution"):
        if decision.get("resolutionSource") == "user":
            for key in ("size", "width", "height", "resolution", "image_size"):
                options.pop(key, None)
            options["resolution"] = decision["resolution"]
        else:
            options["resolution"] = decision["resolution"]
    return options


def image_tier(requested=None, *, user_message=None, prompt=None, params=None, memory=None, has_references=False):
    """Compatibility helper for model routing."""
    return decide_image_policy(
        requested,
        user_message=user_message,
        prompt=prompt,
        params=params,
        memory=memory,
        has_references=has_references,
    )["tier"]


def apply_image_quality(
    params,
    *,
    model,
    provider_api="images",
    tier="draft",
    provider_quality=None,
    policy=None,
    has_references=False,
    provider_key=None,
    supported_parameters=None,
):
    options = dict(params or {})
    requested = provider_quality or _TIER_TO_QUALITY.get(tier, "low")
    gpt = bool(re.search(r"gpt-image", str(model), re.I))
    dalle = bool(re.search(r"dall[-_ ]?e[-_ ]?3", str(model), re.I))
    report = {"tier": tier, "requestedQuality": requested, "model": model, "status": "unsupported"}
    if policy:
        report.update({key: value for key, value in policy.items() if key not in {"size", "quality", "tier"} and value is not None})
        if policy.get("resolution"):
            report["requestedResolution"] = policy["resolution"]
        if policy.get("size"):
            report["requestedSize"] = policy["size"]
    options.pop("input_fidelity", None)
    if provider_api in {"images", "evolink"} and (gpt or dalle):
        quality = ("hd" if requested in {"high", "xhigh", "max"} else "standard") if dalle else requested
        options["quality"] = quality
        report.update(quality=quality, status="applied")
        if has_references and gpt and not re.search(r"gpt-image-2(?:\.|-|$)", str(model), re.I):
            options["input_fidelity"] = "high"
            report["inputFidelity"] = "high"
    else:
        options.pop("quality", None)
        report["notice"] = "当前模型/接口未声明可调质量档；保留所选模型，未宣称质量参数已生效。"
    options = prepare_image_parameters(
        options,
        model=model,
        openrouter=provider_key == "openrouter",
        provider_api=provider_api,
        supported_parameters=supported_parameters,
    )
    if provider_api == 'evolink' and not gpt and options.get('quality'):
        report.update(quality=options['quality'], status='applied')
        report.pop('notice', None)
    return options, report
