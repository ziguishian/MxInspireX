"""Bounded visual previews for text/vision model context.

Generation providers continue to read original project assets. These previews
exist only to keep Agent understanding requests below transport and context
limits.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_EDGE = 1600
MAX_ITEM_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 8


def make_vision_preview(content: bytes) -> dict[str, Any] | None:
    """Return a JPEG preview no larger than the documented item limits."""
    try:
        with Image.open(BytesIO(content)) as opened:
            original_width, original_height = opened.size
            image = ImageOps.exif_transpose(opened)
            if getattr(image, "is_animated", False):
                image.seek(0)
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            encoded = b""
            for quality in (88, 80, 70, 60, 50):
                output = BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                encoded = output.getvalue()
                if len(encoded) <= MAX_ITEM_BYTES:
                    break
            while len(encoded) > MAX_ITEM_BYTES and max(image.size) > 640:
                image.thumbnail((max(640, int(image.width * 0.82)), max(640, int(image.height * 0.82))), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format="JPEG", quality=50, optimize=True)
                encoded = output.getvalue()
            if not encoded or len(encoded) > MAX_ITEM_BYTES:
                return None
            return {
                "content": encoded,
                "mime": "image/jpeg",
                "width": image.width,
                "height": image.height,
                "originalWidth": original_width,
                "originalHeight": original_height,
                "byteSize": len(encoded),
                "originalByteSize": len(content),
            }
    except (OSError, ValueError, UnidentifiedImageError):
        return None
