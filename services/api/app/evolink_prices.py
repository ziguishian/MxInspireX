"""Read-only EvoLink public tariffs; never settle a receipt using website prices."""
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def snapshot():
    return json.loads(Path(__file__).with_name('evolink_price_data.json').read_text(encoding='utf-8'))


def published_price(row):
    data = snapshot()
    # The page's creditPrice/evolinkPrice pairs use 68 credits per USD.
    # These are tariff units only, never a conversion of account balances.
    def usd(sku, fallback):
        credit = data['skuPrices'].get(str(sku))
        return credit / 68 if isinstance(credit, (int, float)) else fallback

    rates = []
    price = dict(currency='USD', source='evolink_public', referenceOnly=True,
                 sourceUrl=data['sourceUrl'], checkedAt=data['checkedAt'],
                 priceNote='官网公开参考价；规格、长上下文及附加功能可能影响费用，以服务商实际账单为准。')
    fields = {'input': ('inputPerMillion', '文本输入'), 'output': ('outputPerMillion', '文本输出'),
              'cacheHit': ('cachedPerMillion', '缓存读取'), 'cacheWrite': ('cacheWritePerMillion', '缓存写入'),
              'audioInput': ('audioInputPerMillion', '音频输入')}
    for key, fallback in (row.get('fallbackTiers') or {}).items():
        if key not in fields or not isinstance(fallback, (float, int)):
            continue
        field, label = fields[key]
        amount = usd((row.get('tierSkus') or {}).get(key), fallback) * 1000
        price[field] = amount
        rates.append(dict(label=label, usd=amount, unit='/ 百万 Token'))
        tiers = (row.get('highVolumeTiers') or {}).get(key)
        for tier in (tiers if isinstance(tiers, list) else [tiers] if tiers else []):
            # Do not substitute the official vendor's undiscounted tariff.
            value = tier.get('fallbackCreditsPer1K')
            amount_high = value / 68 * 1000 if isinstance(value, (int, float)) else amount * tier.get('multiplier', 1)
            rates.append(dict(label=f'{label} · 上下文超过 {tier["threshold"]:,} Token', usd=amount_high, unit='/ 百万 Token'))
    if row['modality'] != 'text':
        if row.get('displayHeadline'):
            rates.append(row['displayHeadline'])
        details = row.get('expandedRates') or ([row['headlineRate']] if row.get('headlineRate') else [])
        for rate in details:
            fallback = rate.get('fallbackCredits')
            if not isinstance(fallback, (int, float)):
                continue
            amount = usd(rate.get('skuId'), fallback / 68)
            unit = rate['unit']
            if unit == '/1K tokens':
                amount *= 1000
                unit = '/ 百万 Token'
            rates.append(dict(label=rate['label'], usd=amount, unit=unit))
        if not rates:
            amount = row.get('fromUSD', row.get('minUSD', row.get('evolinkPrice')))
            if isinstance(amount, (int, float)):
                if row.get('minUSD') is None and row.get('fromUSD') is None:
                    amount = usd(row.get('skuId'), amount)
                unit = row['unit']
                if unit == '/1K tokens':
                    amount *= 1000
                    unit = '/ 百万 Token'
                rates.append(dict(label='官网起始价', usd=amount, unit=unit))
                if isinstance(row.get('maxUSD'), (int, float)) and row['maxUSD'] > amount and unit != '/ 百万 Token':
                    rates.append(dict(label='官网规格最高价', usd=row['maxUSD'], unit=unit))
    price['publicRates'] = rates
    return price


def public_catalog():
    return [dict(provider='evolink', baseUrl='https://api.evolink.ai/v1',
                 model=row.get('apiName') or row['id'], name=row['name'], kinds=[row['modality']],
                 publicCatalogOnly=True, price=published_price(row))
            for row in snapshot()['rows'] if not row.get('comingSoon')]


def default_evolink_price(model):
    # Only the exact published API ID; no namespace or product-name guessing.
    row = next((row for row in snapshot()['rows'] if row.get('apiName') == model and not row.get('comingSoon')), None)
    return deepcopy(published_price(row)) if row else {}
