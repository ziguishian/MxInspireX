"""OpenAI-compatible cache counters. Missing metrics are not cache misses."""
from decimal import Decimal


def cache_counters(usage):
    details = usage.get('input_tokens_details', usage.get('inputTokensDetails', usage.get('prompt_tokens_details', {}))) or {}
    details = details if isinstance(details, list) else [details]

    def metric(name):
        values = [usage[name]] if name in usage else [item[name] for item in details if isinstance(item, dict) and name in item]
        if not values:
            return None
        try:
            numbers = [Decimal(str(value)) for value in values]
            return sum(numbers) if all(n.is_finite() and n >= 0 for n in numbers) else None
        except (ArithmeticError, ValueError, TypeError):
            return None

    return metric('cached_tokens'), metric('cache_write_tokens')


def cache_trace(usage):
    cached, written = cache_counters(usage)
    incoming = usage.get('input_tokens', usage.get('inputTokens', usage.get('prompt_tokens')))
    try:
        valid = not invalid_cache_counters(usage) and incoming is not None and Decimal(str(incoming)).is_finite() and (cached or 0)+(written or 0) <= Decimal(str(incoming))
    except (ArithmeticError, ValueError, TypeError):
        valid = False
    return {'cacheReported': valid and cached is not None, 'cacheWriteReported': valid and written is not None,
            **({'cachedTokens': float(cached)} if valid and cached is not None else {}),
            **({'cacheWriteTokens': float(written)} if valid and written is not None else {})}


def invalid_cache_counters(usage):
    details = usage.get('input_tokens_details', usage.get('inputTokensDetails', usage.get('prompt_tokens_details', {}))) or {}
    details = details if isinstance(details, list) else [details]
    return any(value is None and (name in usage or any(isinstance(item, dict) and name in item for item in details))
               for name, value in zip(('cached_tokens', 'cache_write_tokens'), cache_counters(usage)))
