"""Production-safe image prompt and out-of-band fabrication notes."""
from __future__ import annotations

import re


def append_visual_constraints(prompt: str, *constraints: str) -> str:
    """Append only missing visual constraints, without rewriting quoted copy."""
    result = str(prompt or '').strip()
    for constraint in constraints:
        value = str(constraint or '').strip()
        if value and value not in result:
            result = '\n'.join(part for part in (result, value) if part)
    return result


def image_edit_prompt(prompt: str) -> str:
    value = str(prompt or '').strip()
    return value if re.match(r'^图像编辑任务(?:[：:。\s]|$)', value) else '图像编辑任务：' + value


def explicit_image_disclaimer_requested(user_message: object) -> bool:
    """Require user wording about both the notice and its in-image placement."""
    value = " ".join(str(user_message or "").strip().split())
    notice = r"概念示意|仅供参考|参数待确认|尺寸待定|非等比例|免责声明"
    placement = r"图(?:片|像)?[中内上]|画面[中内上]|角标|水印|标注|写上|显示|加上|放在图"
    return bool(re.search(notice, value, re.I) and re.search(placement, value, re.I))
PRODUCTION_NEGATIVE_POLICY = "额外说明角标、水印、占位文字"


def normalize_production_notes(value: object) -> list[str]:
    """Keep short, visible node notes out of generated pixels."""
    if not isinstance(value, (list, tuple)):
        return []
    notes = []
    for item in value:
        note = " ".join(str(item or "").strip().split())[:300]
        if note and note not in notes:
            notes.append(note)
        if len(notes) >= 8:
            break
    return notes


def prepare_production_image_request(prompt: str, negative_prompt: str | None = None, *, allow_disclaimer: bool = False) -> tuple[str, str]:
    clean_prompt = str(prompt or "").strip()
    negative = str(negative_prompt or "").strip()
    if not allow_disclaimer and PRODUCTION_NEGATIVE_POLICY not in negative:
        negative = "，".join(part for part in (negative, PRODUCTION_NEGATIVE_POLICY) if part)
    return clean_prompt, negative
