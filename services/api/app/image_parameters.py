"""Translate layout intent into the selected provider's image wire protocol.

OpenAI: https://developers.openai.com/api/docs/guides/image-generation
OpenRouter: https://openrouter.ai/docs/guides/overview/multimodal/image-generation
"""
import math
import re
from fractions import Fraction
from functools import lru_cache

TIERS = {'512', '1K', '2K', '4K'}
ROUTER_RATIOS = {'1:1','1:2','1:4','1:8','2:1','2:3','2.35:1','3:2','3:4','4:1','4:3','4:5',
                 '5:2','5:4','8:1','9:16','16:9','9:19.5','19.5:9','9:20','20:9','9:21','21:9','auto'}


class ImageParameterError(ValueError):
    code = 'image_parameters_invalid'


def is_gpt_image_25(model):
    return bool(re.fullmatch(r'(?:openai/)?gpt-image-2\.5-(?:sunburst|flare)(?:-\d{4}-\d{2}-\d{2})?', str(model), re.I))


def _custom_gpt(model):
    return is_gpt_image_25(model) or bool(re.fullmatch(r'(?:openai/)?gpt-image-2(?:-\d{4}-\d{2}-\d{2})?',str(model),re.I))


def is_custom_gpt_image(model):
    """Public model-family check used by shared route preparation."""
    return _custom_gpt(model)


def pixel_dimensions(value):
    match = re.fullmatch(r'([1-9]\d*)x([1-9]\d*)',str(value).strip().lower().replace('×','x'))
    if not match:
        raise ImageParameterError('图像 size 请使用 WIDTHxHEIGHT（如 1152x1536）、分辨率档位或 auto。')
    return tuple(map(int,match.groups()))


def valid_native_gpt_dimensions(width, height):
    """Whether exact pixels satisfy the native GPT Image API contract."""
    return (
        width > 0 and height > 0
        and width % 16 == 0 and height % 16 == 0
        and max(width, height) <= 3840
        and max(width, height) <= 3 * min(width, height)
        and 655360 <= width * height <= 8294400
    )


@lru_cache(maxsize=256)
def nearest_native_gpt_size(value):
    """Return the closest valid native GPT Image size for derived pixels.

    This helper is intentionally opt-in. Callers must only use it for pixels
    inferred by the Agent; a size explicitly requested by the user remains a
    strict contract and is rejected by ``prepare_image_parameters``.
    """
    width, height = pixel_dimensions(value)
    if valid_native_gpt_dimensions(width, height):
        return f'{width}x{height}'
    landscape = width > height
    portrait = height > width
    target_ratio = width / height
    target_edge = min(max(width, height), 3840)
    target_area = width * height
    best = None
    best_key = None
    # Native dimensions are aligned to 16px. Exhaustively considering the
    # small 240x240 grid keeps all limits in one deterministic place.
    for candidate_width in range(16, 3841, 16):
        for candidate_height in range(16, 3841, 16):
            if landscape and candidate_width <= candidate_height:
                continue
            if portrait and candidate_height <= candidate_width:
                continue
            if not valid_native_gpt_dimensions(candidate_width, candidate_height):
                continue
            candidate_ratio = candidate_width / candidate_height
            key = (
                abs(math.log(candidate_ratio / target_ratio)),
                abs(max(candidate_width, candidate_height) - target_edge),
                abs(math.log((candidate_width * candidate_height) / target_area)),
                abs(candidate_width - width) + abs(candidate_height - height),
            )
            if best_key is None or key < best_key:
                best_key = key
                best = (candidate_width, candidate_height)
    if best is None:
        raise ImageParameterError('无法为当前 GPT Image 请求找到兼容的像素尺寸。')
    return f'{best[0]}x{best[1]}'


def ratio_value(value):
    try:
        width,height = str(value).split(':')
        ratio = Fraction(width) / Fraction(height)
        if Fraction(width)<=0 or Fraction(height)<=0:
            raise ValueError()
        return ratio
    except (ValueError,ZeroDivisionError):
        raise ImageParameterError('图像比例请使用正数比（如 3:4、9:19.5）或 auto。') from None


def _gpt_size(ratio, resolution=''):
    width,height = ratio.numerator,ratio.denominator
    if max(width,height)>3*min(width,height):
        raise ImageParameterError('当前 GPT Image 模型要求长短边比不超过 3:1；请调整计划比例或选择支持该比例的模型。')
    edge = {'512':512,'1K':1024,'2K':2048,'4K':3840}.get(resolution,1024 if width==height else 1536)
    maximum = min(3840//(16*max(width,height)),math.isqrt(8294400//(256*width*height)))
    minimum = math.isqrt((655360-1)//(256*width*height))+1
    if maximum<minimum:
        raise ImageParameterError('该比例无法在当前 GPT Image 的像素限制内精确表示，请调整计划比例。')
    multiple = min(maximum,max(minimum,round(edge/(16*max(width,height)))))
    return f'{width*16*multiple}x{height*16*multiple}'


def _enum(parameters, field):
    definition = (parameters or {}).get(field) if isinstance(parameters,dict) else None
    return (definition.get('values') or definition.get('enum') or []) if isinstance(definition,dict) else []


def _check_enum(options, parameters, field):
    allowed = _enum(parameters,field)
    if allowed and options.get(field) not in (None,'') and options[field] not in allowed:
        raise ImageParameterError(f'所选接口/模型的 {field} 不支持 {options[field]}；目录声明的可用值：'+', '.join(map(str,allowed)))


def prepare_image_parameters(params, *, model, openrouter=False, provider_api='images', supported_parameters=None):
    if provider_api == 'evolink':
        from .evolink import image_parameters
        return image_parameters(params, model)
    options = dict(params or {})
    if is_gpt_image_25(model) and provider_api == 'images':
        options.setdefault('quality','max')
        if options['quality'] not in {'auto','low','medium','high','xhigh','max'}:
            raise ImageParameterError('图像 quality 需为 low、medium、high、xhigh、max 或 auto。')
    if _custom_gpt(model):
        options.pop('input_fidelity',None)
    if options.get('width') is not None or options.get('height') is not None:
        dimensions = pixel_dimensions(f"{options.get('width')}x{options.get('height')}")
        explicit = options.get('size')
        if explicit and str(explicit).lower()!='auto' and pixel_dimensions(explicit)!=dimensions:
            raise ImageParameterError('size 与 width/height 冲突；请仅保留一组尺寸参数。')
        options['size'] = f'{dimensions[0]}x{dimensions[1]}'
    options.pop('width',None); options.pop('height',None)
    size = str(options.get('size') or '').strip().lower().replace('×','x')
    ratio = str(options.get('aspect_ratio') or options.get('aspectRatio') or 'auto').strip()
    resolution = str(options.get('resolution') or options.get('image_size') or '').upper()
    for key in ('aspectRatio','aspect_ratio','resolution','image_size','size'):
        options.pop(key,None)
    if size.upper() in TIERS:
        resolution,size = size.upper(),''
    pixels = pixel_dimensions(size) if size and size!='auto' else None
    if pixels:
        # OpenRouter normalizes explicit pixels itself. Native model alignment
        # limits do not describe the router's input contract.
        size = f'{pixels[0]}x{pixels[1]}'
        ratio,resolution = 'auto',''
    elif resolution and resolution not in TIERS:
        raise ImageParameterError('图像 resolution 需为 512、1K、2K 或 4K；也可用 size 指定像素尺寸。')
    if openrouter:
        if pixels:
            options['size'] = size
        else:
            value = ratio_value(ratio) if ratio != 'auto' else None
            if value is not None and ratio not in ROUTER_RATIOS:
                # Ratios are geometric values, not spelling-sensitive IDs.
                # Preserve standard wire spellings (including decimal ratios).
                ratio = next((candidate for candidate in sorted(ROUTER_RATIOS - {'auto'})
                              if ratio_value(candidate) == value), ratio)
            allowed = _enum(supported_parameters,'aspect_ratio')
            if value is not None and _custom_gpt(model) and (ratio not in ROUTER_RATIOS or allowed and ratio not in allowed):
                # Custom GPT Image sizes also cover ratios absent from the
                # router's shorthand enum (e.g. 16:10 == 8:5). Keep the layout
                # and resolution intent; never replace it with a nearby ratio.
                options['size'] = _gpt_size(value,resolution)
            else:
                if ratio not in ROUTER_RATIOS:
                    raise ImageParameterError(f'当前接口/模型不支持 aspect_ratio={ratio} 的比例简写；请保留设计比例，使用该模型支持的 size 像素尺寸。')
                if ratio!='auto' or size=='auto': options['aspect_ratio'] = ratio
                if resolution: options['resolution'] = resolution
        for field in ('aspect_ratio','resolution','quality'):
            _check_enum(options,supported_parameters,field)
        return options
    if provider_api in {'chat_completions','gemini'}:
        if pixels:
            value = Fraction(*pixels)
            ratio = f'{value.numerator}:{value.denominator}'
            # These protocols expose a tier rather than exact pixel dimensions.
            resolution = '4K' if max(pixels)>2048 else '2K' if max(pixels)>1024 else '1K'
        if ratio!='auto':
            ratio_value(ratio)
            options['aspectRatio'] = ratio
        if resolution: options['resolution'] = resolution
        return options
    if _custom_gpt(model):
        if pixels:
            width,height = pixels
            if not valid_native_gpt_dimensions(width, height):
                suggestion = ''
                try: suggestion = ' 保持原比例可使用 size='+_gpt_size(Fraction(width,height))+'。'
                except ImageParameterError: pass
                raise ImageParameterError(f'{model} 的原生 Images API 要求宽高为 16 的倍数、单边≤3840、长短边比≤3:1、总像素 655360–8294400；当前 size={size}。'+suggestion)
        elif ratio!='auto' or resolution:
            size = _gpt_size(ratio_value(ratio if ratio!='auto' else '1:1'),resolution)
        if size: options['size'] = size
    else:
        family = str(model).lower().split('/')[-1]
        fixed = (['256x256','512x512','1024x1024'] if family=='dall-e-2' else
                 ['1024x1024','1792x1024','1024x1792'] if family=='dall-e-3' else
                 ['1024x1024','1536x1024','1024x1536'] if re.fullmatch(r'gpt-image-1(?:\.5|-mini)?(?:-\d{4}-\d{2}-\d{2})?',family) else [])
        if not pixels and (ratio!='auto' or resolution):
            value = ratio_value(ratio if ratio!='auto' else '1:1')
            if fixed:
                matches = [s for s in fixed if Fraction(*pixel_dimensions(s))==value]
                if not matches:
                    raise ImageParameterError(f'{model} 的原生 Images API 不支持 {ratio} 比例；可用尺寸为 '+', '.join(fixed)+'。请保留设计比例并选择支持它的模型，或先与用户确认调整。')
                size = matches[-1]
            else:
                # Other relays/models keep their own pixel and alignment limits.
                edge = {'512':512,'1K':1024,'2K':2048,'4K':4096}.get(resolution,1024)
                width,height = value.numerator,value.denominator
                size = f'{max(1,round(edge*width/max(width,height)))}x{max(1,round(edge*height/max(width,height)))}'
        if fixed and size and size!='auto' and size not in fixed:
            raise ImageParameterError(f'{model} 的原生 Images API 支持的尺寸为 '+', '.join(fixed))
        if size: options['size'] = size
    _check_enum(options,supported_parameters,'size')
    _check_enum(options,supported_parameters,'quality')
    return options
