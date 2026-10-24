"""Read-only verification that shipped icons derive from the approved artwork."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'apps/desktop/assets'

def pixels(path):
    return Image.open(path).convert('RGBA')

def same(actual, expected, label):
    assert actual.size == expected.size and actual.tobytes() == expected.tobytes(), label

for mode in ('dark', 'light'):
    master = pixels(Path(__file__).with_name(f'mxinspirex-app-icon-{mode}.png'))
    web = master.resize((1024, 1024), Image.Resampling.LANCZOS)
    same(pixels(ROOT / f'apps/renderer/public/assets/mxinspirex-app-icon-{mode}.png'), web, f'{mode} web')
    bounds = web.getchannel('A').point(lambda v: 255 if v >= 128 else 0).getbbox()
    artwork = web.crop(bounds)
    scale = 944 / max(artwork.size)
    artwork = artwork.resize((round(artwork.width * scale), round(artwork.height * scale)), Image.Resampling.LANCZOS)
    native = Image.new('RGBA', (1024, 1024))
    native.alpha_composite(artwork, ((1024 - artwork.width) // 2, (1024 - artwork.height) // 2))
    same(pixels(ASSETS / f'langju-agent-icon-{mode}-1024.png'), native, f'{mode} native PNG')
    same(pixels(ASSETS / f'langju-agent-{mode}.icns'), native, f'{mode} ICNS')
    same(pixels(ROOT / f'apps/renderer/public/assets/mxinspirex-favicon-{mode}.png'), native.resize((64, 64), Image.Resampling.LANCZOS), f'{mode} favicon')
    print(f'PASS {mode}: approved master, web logo, native PNG, ICNS, favicon')

same(pixels(ASSETS / 'langju-agent.icns'), native, 'default ICNS')
ico = Image.open(ASSETS / 'langju-agent.ico')
for size in (16, 24, 32, 48, 64, 128, 256):
    assert (size, size) in ico.ico.sizes(), f'missing ICO size {size}'
same(ico.convert('RGBA'), native.resize((256, 256), Image.Resampling.LANCZOS), 'Windows ICO')
print('PASS default ICNS and Windows ICO sizes')
