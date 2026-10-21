"""Read-only estimates from observed usage; never turn public prices into bills."""
import json
from decimal import Decimal
from .billing import calculate_cost, number
from .model_prices import default_price
from .evolink_billing import has_reported_cost, is_evolink

KINDS = {'text': '文本', 'image': '图像', 'video': '视频', 'audio': '音频', 'search': '联网搜索', 'embedding': '知识检索', '3d': '3D'}


def estimated_cost_cny(item):
    if has_reported_cost(item) or is_evolink(item.get('provider'), item.get('baseUrl', '')) or item.get('completed') is False:
        return None
    if item.get('status') == 'settled': return number(item.get('costCny'))  # Historic local calculation, not a provider receipt.
    price = dict(item.get('price') or {})
    # Only remove the cross-provider reference flag for an unconditional public
    # tariff. Tiered/starting/dynamic prices cannot estimate an entire request.
    if price.get('referenceOnly'):
        original = default_price(item.get('model', ''))
        if price.get('source') != 'default' or not original or original.get('referenceOnly'):
            return None
        price.pop('referenceOnly')
    cost = calculate_cost(item.get('kind'), item.get('usage') or {}, item.get('units') or {}, price)
    rules = item.get('rules') or {}
    factors = []
    if price.get('currency') == 'USD': factors.append(number(rules.get('usdToCny')))
    elif price.get('currency') != 'CNY': return None
    if cost is None or any(value is None for value in factors): return None
    for value in factors: cost *= value
    return cost


def estimated_points(item):
    """Legacy budget/API compatibility; never used for displayed usage or RMB."""
    if item.get('status') == 'settled': return None  # Preserve the legacy API contract.
    cost = estimated_cost_cny(item)
    rules = item.get('rules') or {}
    factors = [number(rules.get('pointsPerCny')), number(rules.get('multiplier'))]
    if cost is None or any(value is None for value in factors): return None
    for value in factors: cost *= value
    return cost


def observed_tokens(usage, kind='text'):
    """Cache and modality details are subsets, not additional tokens."""
    def counter(*keys):
        for key in keys:
            value = number(usage.get(key))
            if value is not None and value == value.to_integral_value(): return int(value)
        return None
    incoming = counter('input_tokens', 'prompt_tokens', 'inputTokens')
    outgoing = counter('output_tokens', 'completion_tokens', 'outputTokens')
    if kind == 'embedding' and outgoing is None: outgoing = 0
    total = counter('total_tokens', 'totalTokens')
    known_sum = (incoming or 0) + (outgoing or 0)
    if total is not None and total >= known_sum:
        return incoming or 0, outgoing or 0, total, False
    return incoming or 0, outgoing or 0, known_sum, incoming is None or outgoing is None


def usage_breakdown(rows):
    def metrics():
        return dict(requests=0, inputTokens=0, outputTokens=0, totalTokens=0, tokenUnreported=0,
                    costCny=Decimal(0), estimatedCostCny=Decimal(0), pricedRequests=0, unpriced=0,
                    reportedRequests=0, awaitingReconciliation=0, evolinkPending=0)
    totals, categories, by_day, by_task = metrics(), {}, {}, {}
    for row in rows:
        item = json.loads(row['data_json'])
        kind = item.get('kind', 'text')
        category = categories.setdefault(kind, metrics())
        incoming, outgoing, total, missing = observed_tokens(item.get('usage') or {}, kind)
        settled = number(item.get('costCny')) if has_reported_cost(item) else None
        estimate = estimated_cost_cny(item) if settled is None else None
        for target in (totals, category):
            target['requests'] += 1
            target['inputTokens'] += incoming
            target['outputTokens'] += outgoing
            target['totalTokens'] += total
            target['tokenUnreported'] += int(missing)
            target['costCny'] += settled or Decimal(0)
            target['estimatedCostCny'] += estimate or Decimal(0)
            known = settled is not None or estimate is not None
            target['pricedRequests'] += int(known)
            target['unpriced'] += int(not known)
            target['reportedRequests'] += int(settled is not None)
            target['awaitingReconciliation'] += int(settled is None)
            target['evolinkPending'] += int(settled is None and is_evolink(item.get('provider'), item.get('baseUrl', '')))
        day = item.get('date') or str(row['created_at'])[:10]
        by_day[day] = by_day.get(day, 0) + total
        if row['task_id']: by_task[row['task_id']] = by_task.get(row['task_id'], 0) + total
    def serializable(values):
        return {key: float(value) if isinstance(value, Decimal) else value for key, value in values.items()}
    return {**serializable(totals), 'tokenByDay': by_day, 'tokenByTask': by_task,
            'categories': {key: serializable(value) for key, value in categories.items()}}


def breakdown(rows):
    categories = {kind: {'kind': kind, 'label': label, 'points': 0., 'estimatedPoints': 0., 'pending': 0, 'unpriced': 0, 'requests': 0, 'inputTokens': 0, 'outputTokens': 0} for kind, label in KINDS.items()}
    estimated, by_day, by_task, unpriced = Decimal(0), {}, {}, 0
    for row in rows:
        item = json.loads(row['data_json'])
        kind = item.get('kind', 'text')
        category = categories.setdefault(kind, {'kind': kind, 'label': kind, 'points': 0., 'estimatedPoints': 0., 'pending': 0, 'unpriced': 0, 'requests': 0, 'inputTokens': 0, 'outputTokens': 0})
        category['requests'] += 1
        category['points'] += float(number(item.get('points')) or 0)
        usage = item.get('usage') or {}
        category['inputTokens'] += float(number(usage.get('input_tokens', usage.get('prompt_tokens'))) or 0)
        category['outputTokens'] += float(number(usage.get('output_tokens', usage.get('completion_tokens'))) or 0)
        if item.get('status') != 'pending': continue
        category['pending'] += 1
        value = estimated_points(item)
        if value is None:
            unpriced += 1; category['unpriced'] += 1
            continue
        estimated += value
        category['estimatedPoints'] += float(value)
        day = item.get('date') or str(row['created_at'])[:10]
        by_day[day] = by_day.get(day, Decimal(0)) + value
        if row['task_id']: by_task[row['task_id']] = by_task.get(row['task_id'], Decimal(0)) + value
    usage = usage_breakdown(rows)
    for kind, category in categories.items():
        category.update(usage['categories'].get(kind, dict(totalTokens=0, tokenUnreported=0, costCny=0., estimatedCostCny=0., pricedRequests=0, reportedRequests=0, awaitingReconciliation=0, evolinkPending=0)))
    usage.pop('categories')
    return {**usage, 'estimatedPoints': float(estimated), 'byKind': list(categories.values()),
            'estimatedByDay': {k: float(v) for k, v in by_day.items()}, 'estimatedByTask': {k: float(v) for k, v in by_task.items()}}


def price_catalog(catalog):
    """Only cached endpoints; no discovery, credential reads or provider calls."""
    with catalog.store._connect() as db:
        endpoints = db.execute('SELECT provider,base_url FROM model_catalogs').fetchall()
    result = []
    for row in endpoints:
        for item in catalog.view(row['provider'], row['base_url']).get('modelCatalog', []):
            result.append({'provider': row['provider'], 'baseUrl': row['base_url'], 'model': item['id'],
                           'kinds': item.get('kinds') or ['text'], 'price': item.get('price') or {}})
    return result
