"""Offline public tariff fallbacks. Never infer prices for an unknown model."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .default_price_data import CHECKED_AT, IMAGE_RATES, PAGE_PRICES, VIDEO_SKUS


def _number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def image_price(rates):
    mapping = {
        ('input_text', 'token'): ('inputPerMillion', 1_000_000),
        ('input_image', 'token'): ('imageInputPerMillion', 1_000_000),
        ('output_image', 'token'): ('imageOutputPerMillion', 1_000_000),
        ('input_image', 'image'): ('perInputImage', 1),
        ('output_image', 'image'): ('perImage', 1),
        ('input_image', 'megapixel'): ('perInputMegapixel', 1),
        ('output_image', 'megapixel'): ('perOutputMegapixel', 1),
    }
    result = {'currency': 'USD'}
    for rate in rates:
        key = (rate.get('billable'), rate.get('unit'))
        value = _number(rate.get('cost_usd'))
        if key not in mapping or value is None:
            result['referenceOnly'] = True
            continue
        field, scale = mapping[key]
        value = float(value * scale)
        if field in result and result[field] != value:
            result['referenceOnly'] = True
            result[field] = min(result[field], value)
        else:
            result[field] = value
    # A megapixel headline can omit tiered pricing and reference-image fees.
    # Preserve the published unit for display; do not treat it as a flat rate.
    if any(key in result for key in ('perInputMegapixel', 'perOutputMegapixel')):
        result['referenceOnly'] = True
    if not any(key in result for key, _ in mapping.values()):
        return {}
    result['priceDetails'] = deepcopy(rates)
    if result.get('referenceOnly'):
        result['priceNote'] = '起始参考价；规格、参考素材或附加费会影响总价，以服务返回费用或手动报价结算'
    return result


def video_price(skus):
    if not isinstance(skus, dict) or not skus:
        return {}
    result = {'currency': 'USD'}
    for sku, raw in skus.items():
        value = _number(raw)
        if value is None:
            return {}
        if sku.startswith('video_tokens'):
            field, scale = 'videoOutputPerMillion', 1_000_000
        elif sku.startswith('cents_per_megapixel_second'):
            field, scale = 'perMegapixelSecond', .01
        elif sku.startswith(('duration_seconds', 'text_to_video_duration_seconds', 'image_to_video_duration_seconds')):
            field, scale = 'perSecond', 1
        elif sku.startswith(('cents_per_second_', 'cents_per_video_output_second')):
            field, scale = 'perSecond', .01
        elif sku in {'reference_images', 'cents_per_image_input'}:
            field, scale = 'perInputImage', .01 if sku.startswith('cents_') else 1
        else:
            result['referenceOnly'] = True
            continue
        value = float(value * Decimal(str(scale)))
        result[field] = min(result.get(field, value), value)
    # Only a single unconditional duration SKU (plus input images) is flat.
    if set(skus) - {'duration_seconds', 'cents_per_second_output', 'reference_images', 'cents_per_image_input'}:
        result['referenceOnly'] = True
    if not any(key in result for key in ('perSecond', 'videoOutputPerMillion', 'perMegapixelSecond')):
        return {}
    result['priceDetails'] = deepcopy(skus)
    if result.get('referenceOnly'):
        result['priceNote'] = '起始参考价；分辨率、音频及输入视频会影响总价，以服务返回费用或手动报价结算'
    return result


def default_price(model):
    known = IMAGE_RATES.keys() | VIDEO_SKUS.keys() | PAGE_PRICES.keys()
    key = model if model in known else None
    # Accept bare IDs, but never discard an explicit, different vendor namespace.
    if key is None and '/' not in model:
        matches = [item for item in known if item.split('/')[-1] == model]
        key = matches[0] if len(matches) == 1 else None
    if key is None:
        return {}
    if key in IMAGE_RATES:
        result = image_price(IMAGE_RATES[key])
        url = f'https://openrouter.ai/api/v1/images/models/{key}/endpoints'
    elif key in VIDEO_SKUS:
        result = video_price(VIDEO_SKUS[key])
        url = 'https://openrouter.ai/api/v1/videos/models'
    else:
        result = {'currency': 'USD', **PAGE_PRICES[key]}
        url = f'https://openrouter.ai/{key}'
        if result.get('referenceOnly'):
            result['priceNote'] = '起始参考价；风格参考或情绪板会影响总价，以服务返回费用或手动报价结算'
    return {**result, 'source': 'default', 'sourceUrl': url, 'checkedAt': CHECKED_AT}
