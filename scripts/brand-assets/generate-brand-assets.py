from pathlib import Path
import argparse
import struct
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = Path(__file__).resolve().parent
OUT_WEB = ROOT / 'apps' / 'renderer' / 'public' / 'assets'
OUT_DESKTOP = ROOT / 'apps' / 'desktop' / 'assets'
OUT_WEB.mkdir(parents=True, exist_ok=True)
OUT_DESKTOP.mkdir(parents=True, exist_ok=True)

SOURCES = {
    'dark': (SOURCE_DIR / 'source-dark.png', (10, 13, 11)),
    'light': (SOURCE_DIR / 'source-light.png', (252, 254, 251)),
}

def remove_background(source: Path, background: tuple[int, int, int]) -> Image.Image:
    image = Image.open(source).convert('RGB')
    pixels = image.load()
    width, height = image.size
    alpha = Image.new('L', image.size, 0)
    alpha_pixels = alpha.load()
    # Estimate coverage from the channel with the strongest contrast to the
    # backdrop. This also lets us unmatte anti-aliased pixels so white/black
    # source backgrounds do not leave a halo around the transparent mark.
    is_light = sum(background) > 500
    foreground_channel = 1
    foreground_hint = 87 if is_light else 249
    bg_channel = background[foreground_channel]
    channel_span = foreground_hint - bg_channel
    for y in range(height):
        for x in range(width):
            rgb = pixels[x, y]
            raw = (rgb[foreground_channel] - bg_channel) / channel_span if channel_span else 0
            coverage = max(0.0, min(1.0, raw))
            # Background texture can move a few levels; suppress it while
            # retaining the soft edge of the logo.
            coverage = max(0.0, min(1.0, (coverage - 0.035) / 0.92))
            alpha_value = round(coverage * 255)
            alpha_pixels[x, y] = alpha_value
            if alpha_value > 5 and coverage < 0.98:
                # C = a*F + (1-a)*B -> recover an un-matted foreground color.
                recovered = []
                for channel, value in enumerate(rgb):
                    estimate = (value - (1 - coverage) * background[channel]) / coverage
                    recovered.append(max(0, min(255, round(estimate))))
                pixels[x, y] = tuple(recovered)
    bbox = alpha.getbbox()
    if not bbox:
        raise RuntimeError(f'No foreground detected in {source}')
    # Crop the artwork and keep a small transparent breathing room around it.
    pad = 18
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(width, bbox[2] + pad)
    bottom = min(height, bbox[3] + pad)
    artwork = image.crop((left, top, right, bottom))
    artwork.putalpha(alpha.crop((left, top, right, bottom)))
    size = max(artwork.size)
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(artwork, ((size - artwork.width) // 2, (size - artwork.height) // 2))
    return canvas

def export_logo(image: Image.Image, name: str):
    # A 1024px master keeps the mark crisp in the browser and in high-DPI UI.
    master = image.resize((1024, 1024), Image.Resampling.LANCZOS)
    master.save(OUT_WEB / f'langju-logo-{name}.png', optimize=True)

def write_icns(image: Image.Image, path: Path):
    # Use Pillow's ICNS writer instead of hand-assembling only the legacy
    # 1x resources.  macOS requests the Retina resource types (ic11–ic14) for
    # small Dock/Stage Manager previews; without those entries LaunchServices
    # can fall back to Electron's default icon even when CFBundleIconFile is
    # set correctly.  Pillow writes a TOC and all current PNG-backed 1x/2x
    # slots, while keeping the source PNG free of any SVG/code fallback.
    image.convert('RGBA').save(path, format='ICNS')


# macOS 10.14+ understands a private ICNS record containing a second icon
# family for Dark appearance. Keep the ordinary light family as the default
# (so older macOS releases and generic file viewers still have a valid icon),
# then embed the dark family without introducing another runtime dependency.
# Apple-produced adaptive ICNS files omit the outer TOC record; LaunchServices
# otherwise treats the private family as an opaque payload and keeps showing
# the light tile in Stage Manager.
# The nested family is stored without its eight-byte ``icns`` header, matching
# the format used by Apple's own system icons.
DARK_ICNS_RECORD = bytes.fromhex('fd d9 2f a8')


def _icns_records(data: bytes):
    """Yield top-level ICNS records as ``(kind, payload)`` pairs."""
    if len(data) < 8 or data[:4] != b'icns':
        raise RuntimeError('Invalid ICNS data')
    declared_size = int.from_bytes(data[4:8], 'big')
    if declared_size != len(data):
        raise RuntimeError('ICNS size header does not match file length')
    offset = 8
    while offset < len(data):
        if offset + 8 > len(data):
            raise RuntimeError('Truncated ICNS record header')
        kind = data[offset:offset + 4]
        record_size = int.from_bytes(data[offset + 4:offset + 8], 'big')
        if record_size < 8 or offset + record_size > len(data):
            raise RuntimeError('Invalid ICNS record size')
        yield kind, data[offset + 8:offset + record_size]
        offset += record_size


def _encode_icns(records: list[tuple[bytes, bytes]]) -> bytes:
    body = b''.join(kind + struct.pack('>I', len(payload) + 8) + payload for kind, payload in records)
    return b'icns' + struct.pack('>I', len(body) + 8) + body


def embed_dark_icns(light: bytes, dark: bytes) -> bytes:
    """Return a light/default ICNS with a native dark-mode family embedded."""
    light_records = [
        (kind, payload)
        for kind, payload in _icns_records(light)
        if kind not in {DARK_ICNS_RECORD, b'TOC '}
    ]
    dark_records = [(kind, payload) for kind, payload in _icns_records(dark) if kind != b'TOC ']
    dark_payload = b''.join(kind + struct.pack('>I', len(payload) + 8) + payload for kind, payload in dark_records)
    return _encode_icns(light_records + [(DARK_ICNS_RECORD, dark_payload)])

# The native tile occupies 824px of a 1024px icon, matching the optical size
# of macOS application icons. The transparent margin is part of the icon:
# Dock / Command-Tab do not add it when Electron supplies a PNG via setIcon.
APP_ICON_SIZE = 1024
APP_TILE_SIZE = 824
APP_TILE_INSET = (APP_ICON_SIZE - APP_TILE_SIZE) // 2
APP_TILE_RADIUS = round(220 * APP_TILE_SIZE / 960)
APP_MARK_SIZE = round(720 * APP_TILE_SIZE / 960)

def build_app_icon(logo: Image.Image, tile_color: tuple[int, int, int, int]) -> Image.Image:
    """Build one native macOS tile from a transparent logo master.

    Keep the two appearance variants as separate raster files.  Electron can
    switch the Dock tile at runtime with ``nativeTheme`` while the ICNS files
    remain useful to LaunchServices/Finder/Stage Manager as fallbacks.
    """
    icon_size = APP_ICON_SIZE
    icon_canvas = Image.new('RGBA', (icon_size, icon_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon_canvas)
    draw.rounded_rectangle(
        (APP_TILE_INSET, APP_TILE_INSET,
         icon_size - APP_TILE_INSET - 1, icon_size - APP_TILE_INSET - 1),
        radius=APP_TILE_RADIUS,
        fill=tile_color,
    )
    mark = logo.copy()
    # Leave a little more breathing room than the web mark for the macOS tile.
    mark.thumbnail((APP_MARK_SIZE, APP_MARK_SIZE), Image.Resampling.LANCZOS)
    icon_canvas.alpha_composite(mark, ((icon_size - mark.width) // 2, (icon_size - mark.height) // 2))
    return icon_canvas


def write_iconset(image: Image.Image, directory: Path):
    """Keep iconutil inputs aligned with the PNG and ICNS optical size."""
    directory.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = '@2x' if scale == 2 else ''
            image.resize((size * scale, size * scale), Image.Resampling.LANCZOS).save(
                directory / f'icon_{size}x{size}{suffix}.png', optimize=True,
            )


def main():
    parser = argparse.ArgumentParser(description='Generate Langju web and macOS brand assets')
    parser.add_argument('--desktop-only', action='store_true', help='Only regenerate native macOS icons')
    args = parser.parse_args()
    logos = {name: remove_background(path, bg) for name, (path, bg) in SOURCES.items()}
    if not args.desktop_only:
        for name, logo in logos.items():
            export_logo(logo, name)

    # Use the same native tile geometry for both appearance variants.
    app_icons = {
        'dark': build_app_icon(logos['dark'], (10, 14, 12, 255)),
        'light': build_app_icon(logos['light'], (246, 250, 245, 255)),
    }
    icns_bytes: dict[str, bytes] = {}
    for name, icon_canvas in app_icons.items():
        icon_canvas.save(OUT_DESKTOP / f'langju-agent-icon-{name}-1024.png', optimize=True)
        variant_path = OUT_DESKTOP / f'langju-agent-{name}.icns'
        write_icns(icon_canvas, variant_path)
        write_iconset(icon_canvas, OUT_DESKTOP / f'langju-agent-{name}.iconset')
        icns_bytes[name] = variant_path.read_bytes()

    # The canonical ICNS contains both system appearance variants.
    write_iconset(app_icons['dark'], OUT_DESKTOP / 'langju-agent.iconset')
    (OUT_DESKTOP / 'langju-agent.icns').write_bytes(embed_dark_icns(icns_bytes['light'], icns_bytes['dark']))
    print(f'Generated macOS icons: {APP_TILE_SIZE}px tile, {APP_TILE_INSET}px transparent margin')


if __name__ == '__main__':
    main()
