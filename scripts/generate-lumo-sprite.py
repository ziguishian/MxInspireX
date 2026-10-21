from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/renderer/public/assets/lumo-composer-perch-v1.png"
OUTPUT = ROOT / "apps/renderer/public/assets/lumo-composer-sprite-v1.png"


def ellipse_mask(size: tuple[int, int], boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.ellipse(box, fill=255)
    return mask


def clear_eyes(source: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    """Fill the selected face-screen regions from their nearest clean screen pixels."""

    rgba = np.asarray(source.convert("RGBA")).copy()
    mask_image = ellipse_mask(source.size, boxes)
    mask = np.asarray(mask_image) > 0
    _, indices = ndimage.distance_transform_edt(mask, return_indices=True)
    nearest = rgba[indices[0], indices[1], :3]
    softened = ndimage.gaussian_filter(nearest.astype(np.float32), sigma=(13, 13, 0))
    feather = ndimage.gaussian_filter(mask.astype(np.float32), sigma=8)[..., None]
    rgba[..., :3] = np.clip(rgba[..., :3] * (1 - feather) + softened * feather, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def rounded_line_mask(
    size: tuple[int, int],
    start: tuple[int, int],
    end: tuple[int, int],
    width: int,
) -> Image.Image:
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    draw.line((start, end), fill=255, width=width)
    radius = width // 2
    for x, y in (start, end):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return mask


def add_glowing_lines(
    image: Image.Image,
    lines: list[tuple[tuple[int, int], tuple[int, int], int]],
) -> Image.Image:
    result = image.copy()
    for start, end, width in lines:
        core = rounded_line_mask(image.size, start, end, width)
        glow_wide = core.filter(ImageFilter.GaussianBlur(width * 1.05))
        glow_tight = core.filter(ImageFilter.GaussianBlur(width * 0.42))
        wide_alpha = glow_wide.point(lambda value: round(value * 0.36))
        tight_alpha = glow_tight.point(lambda value: round(value * 0.62))
        orange_wide = Image.new("RGBA", image.size, (255, 82, 8, 0))
        orange_wide.putalpha(wide_alpha)
        orange_tight = Image.new("RGBA", image.size, (255, 119, 30, 0))
        orange_tight.putalpha(tight_alpha)
        white = Image.new("RGBA", image.size, (255, 252, 244, 0))
        white.putalpha(core)
        result = Image.alpha_composite(result, orange_wide)
        result = Image.alpha_composite(result, orange_tight)
        result = Image.alpha_composite(result, white)
    return result


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    left_eye = (810, 330, 1010, 520)
    right_eye = (1050, 390, 1270, 575)

    clean_face = clear_eyes(source, [left_eye, right_eye])
    calm = add_glowing_lines(
        clean_face,
        [((914, 397), (902, 458), 25), ((1176, 458), (1164, 519), 25)],
    )
    blink = add_glowing_lines(
        clean_face,
        [((867, 433), (935, 445), 15), ((1128, 489), (1194, 501), 15)],
    )
    wink = add_glowing_lines(
        clear_eyes(source, [left_eye]),
        [((914, 397), (902, 458), 25)],
    )

    frames = [calm, source, blink, wink]
    sheet = Image.new("RGBA", (1536, 1024), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        cell = frame.resize((768, 512), Image.Resampling.LANCZOS)
        sheet.alpha_composite(cell, ((index % 2) * 768, (index // 2) * 512))
    sheet.save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
