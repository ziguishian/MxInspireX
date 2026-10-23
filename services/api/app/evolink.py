"""EvoLink catalog and image wire format; never invent available model IDs."""
import re

from .model_capabilities import model_record

EVOLINK_BASE_URL = 'https://api.evolink.ai/v1'


def normalize_evolink_model(item):
    record = model_record(item)
    name = str(item['id']).lower()
    # Minimal /models rows need strong family evidence. Music/moderation and
    # specialized edit/upscale routes are not chat or speech-generation models.
    unsupported = re.search(r'suno|moderation|upscale|motion-control|video-edit|video-extend|omnihuman|retalk|layerize|midjourney', name)
    if name == 'qwen-audio-3.1-tts-flash':
        record.update(providerCategory='audio', supportedEndpoints=['/audios/generations'], integrationNote='')
    elif unsupported:
        record.update(providerCategory='unsupported', integrationNote='当前工作区尚不支持此专用接口')
    elif re.search(r'krea|z-image|grok.*image|wan.*image', name):
        record.update(providerCategory='image', supportedEndpoints=['/images/generations'])
    elif re.search(r'hailuo|happyhorse|happy-horse|seedance|kling|sora|veo|wan.*video|grok.*video|minimax-h|gemini-omni', name):
        record.update(providerCategory='video', supportedEndpoints=['/videos/generations'])
    elif record['kinds'] == ['audio']:
        record.update(providerCategory='unsupported', integrationNote='当前语音工具使用朗读接口，此模型需专用音频接口')
    elif record['classificationSource'] == 'openai-compatible-default' and not re.search(
        r'^(?:[^/]+/)?(?:gpt-|o[134](?:-|$)|claude-|gemini-|deepseek-|kimi-|qwen|glm-|doubao-|minimax-|grok-)|^evolink/auto$', name
    ):
        record.update(providerCategory='unknown')
    if 'image' in record['kinds']:
        record['supportedEndpoints'] = ['/images/generations']
    return model_record(record)


def image_parameters(params, model):
    """Preserve size intent while mapping EvoLink's size/quality fields."""
    from .image_parameters import prepare_image_parameters, pixel_dimensions, ratio_value
    options = dict(params)
    name = model.lower()
    if 'gpt-image' in name:
        # GPT Image accepts exact pixels with the same native constraints.
        if ':' in str(options.get('size', '')):
            options['aspectRatio'] = options.pop('size')
        result = prepare_image_parameters(options, model=model, provider_api='images')
        result.pop('input_fidelity', None)
        # The node composer uses auto for an unspecified background. EvoLink's
        # GPT Image 2.5 endpoint rejects that literal; omit it and use its default.
        from .image_parameters import is_gpt_image_25
        if is_gpt_image_25(model) and result.get('background') == 'auto':
            result.pop('background')
        return result
    # Non-GPT EvoLink models use size for aspect ratio and quality for resolution.
    size = str(options.get('size') or '').replace('×', 'x')
    ratio = str(options.pop('aspect_ratio', None) or options.pop('aspectRatio', None) or 'auto')
    resolution = str(options.pop('resolution', None) or options.pop('image_size', None) or '').upper()
    if options.get('width') is not None or options.get('height') is not None:
        dimensions = f"{options.pop('width', '')}x{options.pop('height', '')}"
        if size and size != 'auto' and size != dimensions:
            raise ValueError('图像 size 与 width/height 冲突，请指定一致的尺寸。')
        size = dimensions
    if 'x' in size:
        width, height = pixel_dimensions(size)
        if 'seedream' in name or 'qwen-image' in name:
            options['size'] = size
        else:
            # Do not silently turn an exact pixel request into approximate tiers.
            raise ValueError('该 EvoLink 模型使用比例和分辨率档位，请使用 aspectRatio 与 resolution；精确像素可选择 GPT Image 或 Seedream。')
    else:
        if size.upper() in {'512', '0.5K', '1K', '1.5K', '2K', '3K', '4K'}:
            resolution = size.upper()
        elif size:
            ratio = size
        if ratio != 'auto':
            ratio_value(ratio)
        options['size'] = ratio
    if resolution:
        options['quality'] = '0.5K' if resolution == '512' else resolution
    elif options.get('quality') not in {'0.5K', '1K', '1.5K', '2K', '3K', '4K'}:
        options.pop('quality', None)
    return options
