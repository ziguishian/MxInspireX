"""Derive whether each selected image is an edit target or a reference.

The Agent still describes how a reference is used.  This module only enforces
high-confidence intent that is present in the user's original request or an
explicit UI override, before a paid image request can be submitted.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable


REFERENCE_MODES = {"auto", "edit", "identity", "layout", "inspiration"}

_NO_EDIT = re.compile(
    r"(?:不要|不用|无需|不需要|禁止|别)(?:直接)?(?:修改|改动|改变|编辑|调整|重绘|覆盖)(?:原图|这张图|图片)?|"
    r"(?:只|仅)(?:作|做|作为|用于)?(?:风格|配色|色彩|氛围|材质|视觉|构图|排版)?参考|"
    r"(?:原图|这张图|图片).{0,10}(?:保持不变|不要动)",
    re.I,
)
_REFERENCE_ONLY = re.compile(
    r"(?:参考|借鉴|提取|沿用).{0,12}(?:风格|配色|色彩|氛围|材质|视觉语言|调性)|"
    r"(?:类似|相似|同样|同风格).{0,10}(?:风格|配色|氛围|设计)|"
    r"(?:另一|另外|全新)(?:张|个|款|套|版|艘)?.{0,8}(?:设计|方案|作品|海报|船|产品)",
    re.I,
)
_IMAGE_TARGET = re.compile(
    r"这张(?:图|图片|照片)|该(?:图|图片|照片)|原图|"
    r"(?:这张)?(?:图|图片|照片|画面)(?:中|里|内|上)的?|"
    r"(?:图|图片|照片|画面)(?:中|里|内|上)|"
    r"这(?:条|艘|个|只|位|件|台|辆|栋|座)",
    re.I,
)
_EDIT_ACTION = re.compile(
    r"修改|编辑|改成|改为|变成|变为|换成|换掉|替换|删除|删掉|去掉|移除|抹掉|"
    r"增加|添加|加上|放上|补上|加入|改色|换背景|修复|重绘|扩图|扩展|调整|"
    r"让.{0,20}(?:有|出现|穿|戴|拿|站|坐)|(?:要|需要|希望).{0,10}(?:有|出现|增加|添加)",
    re.I,
)
_STATE_CHANGE = re.compile(
    r"夜晚|夜间|白天|清晨|黄昏|傍晚|雨天|下雨|雪天|雪景|冬季|夏季|春季|秋季|"
    r"背景|环境|场景|灯光|光照|人物|有人|无人|天气|季节",
    re.I,
)
_IDENTITY_REFERENCE = re.compile(
    r"(?:保持|保留|沿用|维持|锁定).{0,12}(?:主体|身份|形状|外观|人物|角色|产品|船|车辆|建筑|Logo|标志|IP)|"
    r"(?:主体|人物|角色|产品|船|车辆|建筑|Logo|标志|IP).{0,12}(?:保真|一致|不变)",
    re.I,
)
_LAYOUT_REFERENCE = re.compile(r"(?:沿用|保持|复用|套用).{0,10}(?:布局|版式|排版|构图|位置|结构)", re.I)
_COLLECTIVE_IMAGE_TARGET = re.compile(
    r"(?:全部|所有|每张|这些|多张|(?:这)?[两二三四五六七八九十\d]+张)(?:参考)?(?:图|图片|照片|画面)",
    re.I,
)
_CLAUSE_SPLIT = re.compile(r"[，,。！？!?；;\n]+")
_CHINESE_INDEXES = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


class ReferenceModeMismatchError(ValueError):
    code = "reference_mode_mismatch"
    field = "reference_analysis"

    def __init__(self, intent: dict[str, Any], actual_mode: str | None):
        expected_mode = intent.get("expectedMode") or (
            "edit" if intent.get("expectedOperation") == "edit" else "非 edit 参考模式"
        )
        evidence = intent.get("evidence") or []
        explanation = "；".join(evidence[:3])
        message = (
            f"图片 {intent['assetId']} 的用途与用户要求不一致：预期 {expected_mode}，实际 {actual_mode or '未填写'}。"
            + (f" 判断依据：{explanation}。" if explanation else "")
            + "请按用户原话修正 reference_analysis；修改原图时使用 mode=edit，写清修改范围和 preserve，未明确改变的内容保持不变。"
        )
        super().__init__(message)
        self.asset_ids = [intent["assetId"]]
        self.node_ids: list[str] = []
        self.details = {
            "expectedOperation": intent.get("expectedOperation"),
            "expectedMode": intent.get("expectedMode"),
            "actualMode": actual_mode,
            "confidence": intent.get("confidence"),
            "evidence": evidence,
            "source": intent.get("source"),
        }


def normalize_reference_mode(value: object) -> str:
    mode = str(value or "auto").strip().lower()
    return mode if mode in REFERENCE_MODES else "auto"


def _asset_metadata(asset_lookup: Callable[[str], dict[str, Any] | None] | None, asset_id: str) -> dict[str, Any]:
    asset = asset_lookup(asset_id) if asset_lookup else None
    return (asset or {}).get("metadata") or {}


def _override_for_asset(
    context: dict[str, Any],
    asset_id: str,
    asset_lookup: Callable[[str], dict[str, Any] | None] | None,
) -> str:
    canvas_modes = (context.get("canvasParams") or {}).get("referenceModes") or {}
    if isinstance(canvas_modes, dict) and asset_id in canvas_modes:
        return normalize_reference_mode(canvas_modes[asset_id])

    for item in context.get("memoryInputAssets") or []:
        if isinstance(item, dict) and item.get("assetId") == asset_id and item.get("referenceMode"):
            return normalize_reference_mode(item["referenceMode"])

    metadata = _asset_metadata(asset_lookup, asset_id)
    origin = metadata.get("referenceOrigin") or {}
    for item in context.get("referencedAssets") or []:
        if not isinstance(item, dict):
            continue
        identity = item.get("assetId") or item.get("id")
        direct = identity == asset_id
        copied = identity == origin.get("assetId") and item.get("projectId") == origin.get("projectId")
        if (direct or copied) and item.get("referenceMode"):
            return normalize_reference_mode(item["referenceMode"])

    for item in context.get("referencedFiles") or []:
        if not isinstance(item, dict) or not item.get("referenceMode"):
            continue
        if ((item.get("pathRelative") and item.get("pathRelative") == metadata.get("referenceFile"))
                or (item.get("documentId") and item.get("documentId") == metadata.get("referenceDocumentId"))):
            return normalize_reference_mode(item["referenceMode"])
    return "auto"


def _asset_aliases(
    context: dict[str, Any],
    asset_id: str,
    asset_lookup: Callable[[str], dict[str, Any] | None] | None,
) -> set[str]:
    aliases = {f"@asset:{asset_id}"}
    metadata = _asset_metadata(asset_lookup, asset_id)
    origin = metadata.get("referenceOrigin") or {}
    for position, item in enumerate(context.get("referencedAssets") or [], start=1):
        if not isinstance(item, dict):
            continue
        identity = item.get("assetId") or item.get("id")
        if identity == asset_id or (identity == origin.get("assetId") and item.get("projectId") == origin.get("projectId")):
            aliases.update(str(value) for value in (item.get("mention"), item.get("filename"), f"@asset:{identity}") if value)
            aliases.update({f"图{position}", f"图片{position}", f"第{position}张图"})
            if position <= len(_CHINESE_INDEXES):
                aliases.add(f"第{_CHINESE_INDEXES[position - 1]}张图")
    for item in context.get("referencedFiles") or []:
        if not isinstance(item, dict):
            continue
        matched = ((item.get("pathRelative") and item.get("pathRelative") == metadata.get("referenceFile"))
                   or (item.get("documentId") and item.get("documentId") == metadata.get("referenceDocumentId")))
        if matched:
            aliases.update(str(value) for value in (item.get("filename"), f"@{item.get('index')}" if item.get("index") else None) if value)
            raw_index = str(item.get("index") or "")
            if raw_index.isdigit():
                position = int(raw_index)
                aliases.update({f"图{position}", f"图片{position}", f"第{position}张图"})
                if 0 < position <= len(_CHINESE_INDEXES):
                    aliases.add(f"第{_CHINESE_INDEXES[position - 1]}张图")
    return aliases


def _bound_text(context: dict[str, Any], asset_id: str, source_ids: list[str], text: str,
                asset_lookup: Callable[[str], dict[str, Any] | None] | None) -> str:
    """Return clauses that uniquely name this asset; shared mentions are ambiguous."""
    aliases = _asset_aliases(context, asset_id, asset_lookup)
    aliases_by_asset = {identity: _asset_aliases(context, identity, asset_lookup) for identity in source_ids}
    clauses = [clause.strip() for clause in _CLAUSE_SPLIT.split(text) if clause.strip()]
    matched = []
    for clause in clauses:
        if not any(alias in clause for alias in aliases):
            continue
        named = {
            identity for identity, candidate_aliases in aliases_by_asset.items()
            if any(alias in clause for alias in candidate_aliases)
        }
        if named == {asset_id}:
            matched.append(clause)
    return " ".join(matched)


def derive_image_intents(
    context: dict[str, Any],
    source_ids: list[str],
    *,
    asset_lookup: Callable[[str], dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Return auditable, per-image intent without guessing ambiguous multi-image roles."""
    source_ids = list(dict.fromkeys(str(identity) for identity in source_ids if identity))
    text = " ".join(str(context.get("userMessage") or "").split())
    results: list[dict[str, Any]] = []
    for identity in source_ids:
        override = _override_for_asset(context, identity, asset_lookup)
        if override != "auto":
            results.append({
                "assetId": identity,
                "expectedOperation": "edit" if override == "edit" else "reference",
                "expectedMode": override,
                "confidence": "high",
                "evidence": [f"用户在图片用途菜单中选择“{override}”"],
                "source": "user_override",
            })
            continue

        metadata = _asset_metadata(asset_lookup, identity)
        if metadata.get("source") == "canvas-drawing":
            results.append({
                "assetId": identity,
                "expectedOperation": "reference",
                "expectedMode": "layout",
                "confidence": "high",
                "evidence": ["该资产是用户画板结构草图"],
                "source": "asset_policy",
            })
            continue

        bound_text = _bound_text(context, identity, source_ids, text, asset_lookup)
        collective = _COLLECTIVE_IMAGE_TARGET.search(text)
        if len(source_ids) > 1 and not bound_text and not collective:
            results.append({
                "assetId": identity,
                "expectedOperation": "ambiguous",
                "confidence": "low",
                "evidence": [],
                "source": "agent",
            })
            continue
        evidence_text = bound_text or text
        no_edit = _NO_EDIT.search(evidence_text)
        edit_action = _EDIT_ACTION.search(evidence_text)
        state_change = _STATE_CHANGE.search(evidence_text)
        target = _IMAGE_TARGET.search(evidence_text)
        # An explicit asset mention or a single bound image makes ordinary
        # edit verbs ("把杯子改红") specific enough without saying "图中".
        target_change = bool((target and (edit_action or state_change))
                             or (collective and (edit_action or state_change))
                             or (bound_text and (edit_action or state_change))
                             or (len(source_ids) == 1 and edit_action))
        reference_match = _REFERENCE_ONLY.search(evidence_text)
        layout_match = _LAYOUT_REFERENCE.search(evidence_text)
        identity_match = _IDENTITY_REFERENCE.search(evidence_text)

        if no_edit:
            results.append({
                "assetId": identity,
                "expectedOperation": "reference",
                "expectedMode": "layout" if layout_match else "identity" if identity_match else "inspiration" if reference_match else None,
                "confidence": "high",
                "evidence": [no_edit.group(0)[:160]],
                "source": "user_text",
            })
        elif target_change:
            change = edit_action or state_change
            results.append({
                "assetId": identity,
                "expectedOperation": "edit",
                "expectedMode": "edit",
                "confidence": "high",
                "evidence": [part.group(0)[:160] for part in (target, change) if part],
                "source": "user_text",
            })
        elif layout_match or identity_match or reference_match:
            matched = layout_match or identity_match or reference_match
            expected_mode = ("layout" if layout_match else "identity" if identity_match else "inspiration") if bound_text or len(source_ids) == 1 else None
            results.append({
                "assetId": identity,
                "expectedOperation": "reference",
                "expectedMode": expected_mode,
                "confidence": "high" if bound_text or len(source_ids) == 1 else "medium",
                "evidence": [matched.group(0)[:160]],
                "source": "user_text",
            })
        else:
            results.append({
                "assetId": identity,
                "expectedOperation": "ambiguous",
                "confidence": "low",
                "evidence": [],
                "source": "agent",
            })
    return results


def validate_reference_modes(intents: list[dict[str, Any]], analysis: object) -> None:
    images = analysis.get("images") if isinstance(analysis, dict) else None
    if not isinstance(images, list):
        return  # The existing reference-analysis validator reports this first.
    actual = {item.get("asset_id"): item.get("mode") for item in images if isinstance(item, dict)}
    for intent in intents:
        if intent.get("confidence") != "high":
            continue
        mode = actual.get(intent["assetId"])
        expected_mode = intent.get("expectedMode")
        if expected_mode and mode and mode != expected_mode:
            raise ReferenceModeMismatchError(intent, mode)
        if intent.get("expectedOperation") == "edit" and mode and mode != "edit":
            raise ReferenceModeMismatchError(intent, mode)
        if intent.get("expectedOperation") == "reference" and mode == "edit":
            raise ReferenceModeMismatchError(intent, mode)


def canonicalize_reference_modes(
    intents: list[dict[str, Any]],
    analysis: object,
) -> tuple[object, list[dict[str, Any]]]:
    """Apply high-confidence user intent without spending another Agent turn.

    Only mode and the minimum edit preservation rule are corrected. Existing
    descriptions, intended use and avoid lists remain untouched. A missing
    asset binding is not invented and is left to the normal validator.
    """
    if not isinstance(analysis, dict) or not isinstance(analysis.get("images"), list):
        return analysis, []
    normalized = deepcopy(analysis)
    by_asset = {
        str(item.get("asset_id")): item
        for item in normalized["images"]
        if isinstance(item, dict) and item.get("asset_id")
    }
    corrections: list[dict[str, Any]] = []
    for intent in intents:
        if intent.get("confidence") != "high":
            continue
        item = by_asset.get(str(intent.get("assetId") or ""))
        if not item:
            continue
        expected = intent.get("expectedMode")
        if not expected:
            expected = "edit" if intent.get("expectedOperation") == "edit" else "inspiration"
        before = str(item.get("mode") or "")
        if before == expected:
            continue
        item["mode"] = expected
        if expected == "edit":
            default_rule = "未明确要求改变的主体、文字、Logo、构图和装饰保持不变"
            # reference_analysis is a wire contract consumed by
            # prepare_reference_design; ``preserve`` must remain text.  Keep
            # the Agent's concrete scope and append the safety boundary rather
            # than replacing it or changing the field shape.
            preserve = str(item.get("preserve") or "").strip()
            if default_rule not in preserve:
                preserve = "；".join(part for part in (preserve, default_rule) if part)
            item["preserve"] = preserve
        corrections.append({
            "assetId": intent.get("assetId"),
            "beforeMode": before or None,
            "afterMode": expected,
            "reason": "；".join((intent.get("evidence") or [])[:3]) or "用户明确用途",
            "source": intent.get("source"),
        })
    return normalized, corrections
