from __future__ import annotations

import json
from typing import Any


class LocalTextProvider:
    """Deterministic provider used for offline development and smoke tests.

    A production adapter can implement the same ``complete`` method for OpenAI,
    Claude, Gemini or an OpenAI-compatible endpoint without changing Agents.
    """

    provider_key = "local-deterministic"

    def complete(self, *, system: str, prompt: str, model: str | None = None, attachments: list[dict[str, Any]] | None = None) -> str:
        return json.dumps(
            {
                "provider": self.provider_key,
                "model": model or "deterministic-v0",
                "summary": prompt[:240],
                "attachments": [
                    f"{item.get('mention')} {item.get('filename') or '附件'}".strip()
                    for item in (attachments or [])
                ],
                "offline": True,
            },
            ensure_ascii=False,
        )


class LocalImageProvider:
    provider_key = "local-placeholder"
    reports_image_request_start = True

    def generate(self, *, prompt: str, negative_prompt: str | None = None, **params: Any) -> bytes:
        from .image_request import image_request_started
        image_request_started()
        # Offline previews use raster bytes too, so they cannot bypass the
        # Agent's SVG policy. This is an explicitly labelled test placeholder.
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont
        from pathlib import Path
        image = Image.new('RGB', (1024, 1024), '#151a1a')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((180, 150, 844, 740), radius=180, fill='#2c1f28', outline='#d6ff4b', width=4)
        draw.ellipse((394, 260, 630, 496), outline='#f1c56e', width=10)
        draw.rectangle((425, 535, 600, 690), fill='#3b8590')
        font_path = Path(__file__).resolve().parents[1] / 'print_fonts/NotoSansSC-Regular.otf'
        font = ImageFont.truetype(str(font_path), 24) if font_path.exists() else ImageFont.load_default(size=24)
        draw.text((80, 810), 'OFFLINE TEST PLACEHOLDER', fill='#f1c56e', font=font)
        draw.text((80, 870), (prompt or 'AI Creative Studio')[:34], fill='#e8e9e4', font=font)
        output = BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()
