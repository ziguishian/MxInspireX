"""Image output requirements and verification, without rewriting returned pixels."""
from __future__ import annotations

import io
import re
from typing import Any

from PIL import Image, UnidentifiedImageError

SVG_OUTPUT_ERROR = ('图像服务返回了 SVG，未返回要求的 PNG/JPEG/WebP 图片。SVG 绘图已全局禁用，未保存该结果。'
                    '本次请求已收到响应，可能已计费；本轮停止自动重试，请检查图像服务设置后由用户重新发起生成。')


def reject_svg_output(content: bytes, *, transparent_requested: bool = False):
    result = inspect_image_output(content, transparent_requested=transparent_requested)
    if not result.get('verified'):
        from .svg_policy import contains_svg
        # Scan the complete document, including a long XML preamble and
        # UTF-16/32 markup. Valid raster metadata is never interpreted as SVG.
        text = content.decode('utf-8', errors='ignore').replace('\0', '')
        if contains_svg(text):
            raise ValueError(SVG_OUTPUT_ERROR)
    return result


def prepare_image_output(prompt: str, params: dict[str, Any], *, background: str | None = None,
                         source_transparent: bool = False) -> tuple[str, dict[str, Any]]:
    options = dict(params)
    from .node_prompt import literal_prompt
    literal = literal_prompt.get()
    # Send a real raster format to the provider instead of relying on its
    # default. Reject unsupported formats before submitting a paid request.
    output_format = str(options.get('output_format') or 'png').strip().lower()
    output_format = 'jpeg' if output_format == 'jpg' else output_format
    if output_format not in {'png', 'jpeg', 'webp'}:
        raise ValueError('图像输出格式只允许 PNG、JPEG 或 WebP；SVG 绘图已全局禁用。')
    options['output_format'] = output_format
    # Explicit node settings take precedence over the Agent's inferred choice.
    choice = options.get("background")
    if choice in (None, "", "auto") and not literal:
        choice = background or choice
    if choice not in (None, "", "auto", "opaque", "transparent"):
        raise ValueError("图像背景必须为 auto、opaque 或 transparent")
    if choice in (None, "", "auto") and not literal:
        # A fallback for older tool callers; the SDK also has a typed field.
        # Inspect this image's prompt only, never an entire conversation.
        transparent = re.search(r"透明(?:的)?(?:背景|底[图色]?|图层)|(?:背景|底[图色]?)\s*(?:为|是|设为|设置为|改成)?\s*透明|(?:fully\s+)?transparent\s+(?:background|layer)|alpha\s+background", prompt, re.I)
        opaque = re.search(r"(?:不[要用需]|无需|不要使用).{0,4}透明|(?:不透明|非透明)(?:背景|底)?|(?:no|not|without)\s+(?:a\s+)?transparent\s+background|opaque\s+background", prompt, re.I)
        if opaque:
            choice = "opaque"
        elif transparent or source_transparent:
            choice = "transparent"
    if choice:
        options["background"] = choice
    if choice == "transparent":
        if str(options.get("output_format", "")).lower() not in {"png", "webp"}:
            if literal:
                raise ValueError('透明背景需要 PNG 或 WebP，请修改输出格式。')
            options["output_format"] = "png"
        # Text describes the desired pixels; the API field requests real alpha.
        constraint = "输出真实透明背景，保留干净的 alpha 边缘；不要绘制棋盘格或添加实色背景。"
        if not literal and constraint not in prompt:
            prompt += "\n" + constraint
    if str(options.get("output_format") or "png").lower() == "png":
        options.pop("output_compression", None)
    return prompt, options


def inspect_image_output(content: bytes, *, transparent_requested: bool = False) -> dict[str, Any]:
    """Report decoded alpha, including palette transparency; retain original bytes."""
    result: dict[str, Any] = {"verified": False, "hasTransparency": None}
    try:
        with Image.open(io.BytesIO(content)) as image:
            result.update(format=image.format.lower(), width=image.width, height=image.height)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            extrema = image.convert("RGBA").getchannel("A").getextrema() if has_alpha else (255, 255)
            result.update(verified=True, hasAlpha=has_alpha, hasTransparency=extrema[0] < 255,
                          alphaMin=extrema[0], alphaMax=extrema[1])
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        pass
    if transparent_requested and result["hasTransparency"] is not True:
        result["warning"] = ("已请求透明背景，但返回图片没有透明像素。请更换支持透明输出的模型或重试。"
                             if result["verified"] else "已请求透明背景，但无法验证返回图片的透明通道。")
    return result
