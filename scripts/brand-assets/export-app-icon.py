"""Export approved artwork, fitting native icons to the OS icon canvas."""
from pathlib import Path
import importlib.util
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('brand_assets', Path(__file__).with_name('generate-brand-assets.py'))
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
out = ROOT / 'apps/desktop/assets'

def native_icon(image):
    # Ignore almost-transparent generator noise when measuring visual bounds.
    bounds = image.getchannel('A').point(lambda value: 255 if value >= 128 else 0).getbbox()
    if bounds is None:
        raise ValueError('App icon has no visible artwork')
    artwork = image.crop(bounds)
    scale = 944 / max(artwork.size)
    artwork = artwork.resize((round(artwork.width * scale), round(artwork.height * scale)), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (1024, 1024))
    canvas.alpha_composite(artwork, ((1024 - artwork.width) // 2, (1024 - artwork.height) // 2))
    return canvas

for mode in ('dark', 'light'):
    image = Image.open(Path(__file__).with_name(f'mxinspirex-app-icon-{mode}.png')).convert('RGBA')
    image = image.resize((1024, 1024), Image.Resampling.LANCZOS)
    image.save(ROOT / f'apps/renderer/public/assets/mxinspirex-app-icon-{mode}.png')
    if mode == 'light':
        image.save(ROOT / 'apps/renderer/public/assets/mxinspirex-app-icon.png')
    image = native_icon(image)
    image.resize((64, 64), Image.Resampling.LANCZOS).save(ROOT / f'apps/renderer/public/assets/mxinspirex-favicon-{mode}.png')
    image.save(out / f'langju-agent-icon-{mode}-1024.png')
    brand.write_icns(image, out / f'langju-agent-{mode}.icns')
    brand.write_iconset(image, out / f'langju-agent-{mode}.iconset')
brand.write_icns(image, out / 'langju-agent.icns')
brand.write_iconset(image, out / 'langju-agent.iconset')
image.save(out / 'langju-agent.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
