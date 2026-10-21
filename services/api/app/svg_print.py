"""Structural preflight for self-contained vector print artwork (not press approval)."""
import math
import re

from pydantic import BaseModel, ConfigDict, Field


class PrintSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    trim_width_mm: float = Field(gt=0, le=10000)
    trim_height_mm: float = Field(gt=0, le=10000)
    bleed_mm: float = Field(ge=0, le=100)
    safe_margin_mm: float = Field(ge=0, le=100)


def preflight_svg(root, value):
    spec = PrintSpec.model_validate(value)
    if spec.safe_margin_mm * 2 >= min(spec.trim_width_mm, spec.trim_height_mm):
        raise ValueError('印前检查：安全边距必须小于成品短边的一半')
    dimensions = []
    for field in ('width', 'height'):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)mm\s*', root.get(field, ''))
        if not match:
            raise ValueError('印前检查：SVG width/height 必须使用明确的 mm 单位')
        dimensions.append(float(match[1]))
    expected = [spec.trim_width_mm + 2 * spec.bleed_mm, spec.trim_height_mm + 2 * spec.bleed_mm]
    if any(not math.isclose(a, b, abs_tol=0.01, rel_tol=0) for a, b in zip(dimensions, expected)):
        raise ValueError('印前检查：SVG 尺寸应为成品尺寸加四边出血')
    try:
        box = [float(n) for n in re.split(r'[\s,]+', root.get('viewBox', '').strip())]
    except ValueError as error:
        raise ValueError('印前检查：请提供有效 viewBox') from error
    if len(box) != 4 or any(not math.isfinite(n) for n in box) or any(
            not math.isclose(a, b, abs_tol=0.001, rel_tol=0) for a, b in zip(box, [0, 0, *dimensions])):
        raise ValueError('印前检查：viewBox 必须从 0 0 开始，且一个坐标单位对应 1 mm')
    for element in root.iter():
        tag = element.tag.split('}')[-1].lower()
        if tag in {'text', 'tspan', 'textpath'}:
            raise ValueError('印前检查：文字尚未转曲，请用真实字体轮廓路径替换文字后重试')
        if tag in {'style', 'svg'} and element is not root or element.get('style'):
            raise ValueError('印前检查：请使用显式 SVG 属性，移除 CSS 样式与嵌套 SVG 后重试')
    b, m = spec.bleed_mm, spec.safe_margin_mm
    return {'status': 'structure_checked', 'spec': spec.model_dump(), 'widthMm': dimensions[0], 'heightMm': dimensions[1],
            'trimBox': [b, b, spec.trim_width_mm, spec.trim_height_mm],
            'safeBox': [b+m, b+m, spec.trim_width_mm-2*m, spec.trim_height_mm-2*m],
            'checks': ['physical_dimensions', 'viewbox_scale', 'static_vector_only', 'no_live_fonts_or_external_resources'],
            'manualChecks': ['背景覆盖出血且净稿无技术线', '关键信息在安全区且避开打孔/折线',
                             '字体轮廓内容正确、细线可印', '印厂确认装订、色彩、工艺与实际尺寸打样'],
            'pressApproved': False}
