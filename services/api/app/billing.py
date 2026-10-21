"""Local cost ledger. Unknown cost stays pending; raw usage is never money."""
from __future__ import annotations

import contextvars
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from .token_usage import cache_counters, invalid_cache_counters

billing_context = contextvars.ContextVar("billing_context", default={})


@contextmanager
def billing_scope(**values):
    token = billing_context.set({**billing_context.get(), **values})
    try:
        yield
    finally:
        billing_context.reset(token)


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def calculate_cost(kind, usage, units, price, reported=None):
    """Return cost in the tariff currency, or None if any billed part is unknown."""
    if reported is not None and number(reported) is not None:
        return number(reported)
    if usage.get('cache_usage_invalid'):
        return None
    if price.get('referenceOnly'):
        return None  # Starting/conditional public prices are not a flat tariff.
    if not any(number(value) is not None for key, value in price.items() if key not in {"currency", "source"}):
        return None
    cost = Decimal(0)
    parts = []
    if kind != "search" and "perRequest" in price and not any(key in price for key in ("inputPerMillion", "outputPerMillion", "perImage", "perSecond", "imageInputPerMillion", "imageOutputPerMillion", "audioInputPerMillion", "audioOutputPerMillion", "videoInputPerMillion", "videoOutputPerMillion", "perInputImage")):
        rate, quantity = number(price["perRequest"]), number(units.get("requests", 1))
        return rate * quantity if rate is not None and quantity is not None else None
    if kind in {"text", "embedding", "router", "search"} or (kind in {'image','audio','video'} and usage and 'perSecond' not in price and 'perImage' not in price):
        incoming = number(usage.get("input_tokens", usage.get("inputTokens", usage.get("prompt_tokens"))))
        outgoing = number(usage.get("output_tokens", usage.get("outputTokens", usage.get("completion_tokens", 0 if kind == "embedding" else None))))
        if incoming is None or outgoing is None:
            return None
        details = usage.get("input_tokens_details", usage.get("inputTokensDetails", usage.get("prompt_tokens_details", {}))) or {}
        cached, written = cache_counters(usage)
        # Missing counters are compatible with older providers. An explicit
        # malformed counter must never be silently billed as zero.
        if invalid_cache_counters(usage):
            return None
        cached, written = cached or Decimal(0), written or Decimal(0)
        if cached + written > incoming:
            return None
        if kind == "image":
            # Image generation can bill text and image inputs at different rates.
            if not isinstance(details, dict):
                return None
            image_in = number(details.get("image_tokens", 0))
            if image_in is None or image_in > incoming or (image_in and (cached or written)):
                return None  # cache modality is unknown; do not invent a split
            parts += [(incoming-image_in-cached-written, "inputPerMillion", 1_000_000),
                      (image_in, "imageInputPerMillion", 1_000_000),
                      (outgoing, "imageOutputPerMillion", 1_000_000)]
        elif kind in {'audio', 'video'} and any(key in price for key in (f'{kind}InputPerMillion', f'{kind}OutputPerMillion')):
            output_details = usage.get('output_tokens_details', usage.get('completion_tokens_details', {})) or {}
            media_in = number(details.get(f'{kind}_tokens', 0 if incoming == 0 else None)) if isinstance(details, dict) else None
            media_out = number(output_details.get(f'{kind}_tokens', 0 if outgoing == 0 else None)) if isinstance(output_details, dict) else None
            if media_in is None or media_out is None or media_in > incoming or media_out > outgoing or (media_in and (cached or written)):
                return None  # Unknown modality/cache split must not be billed at text rates.
            parts += [(incoming-media_in-cached-written, 'inputPerMillion', 1_000_000),
                      (media_in, f'{kind}InputPerMillion', 1_000_000),
                      (outgoing-media_out, 'outputPerMillion', 1_000_000),
                      (media_out, f'{kind}OutputPerMillion', 1_000_000)]
        else:
            parts += [(incoming-cached-written, "inputPerMillion", 1_000_000), (outgoing, "outputPerMillion", 1_000_000)]
        parts.append((cached, "cachedPerMillion", 1_000_000))
        # Write price is the full per-token tariff, not a surcharge. Never
        # infer 1.25x for a relay; its contract may use another rate.
        parts.append((written, "cacheWritePerMillion", 1_000_000))
    elif kind == "image":
        parts.append((number(units.get("images")), "perImage", 1))
    elif kind in {'video','audio'} and "perSecond" in price:
        parts.append((number(units.get("seconds")), "perSecond", 1))
    elif "perRequest" not in price:
        return None
    if number(price.get("perInputImage")):
        parts.append((number(units.get("inputImages")), "perInputImage", 1))
    if "perRequest" in price:
        parts.append((number(units.get("requests", 1)), "perRequest", 1))
    if kind == "search":
        parts.append((number(units.get("searchCalls")), "perSearch", 1))
    for quantity, key, divisor in parts:
        if quantity is None:
            return None
        if quantity == 0:
            continue
        rate = number(price.get(key))
        if rate is None:
            return None
        cost += quantity * rate / divisor
    return cost if parts else None


class BillingService:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        self.path = store.workspace_root / "credits.sqlite"
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS credit_ledger (
                id TEXT PRIMARY KEY, project_id TEXT, task_id TEXT, created_at TEXT NOT NULL,
                data_json TEXT NOT NULL)""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def record(self, *, provider, base_url, model, kind, usage=None, units=None, record_id=None, completed=True,
               provider_task_id=None, provider_request_id=None, **scope):
        from .evolink_billing import is_evolink, normalize_usage, receipt_id, has_reported_cost
        evo = is_evolink(provider, base_url)
        usage, units = usage or {}, units or {}
        if evo: usage = normalize_usage(usage, completed=completed)
        allowed = {"input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cache_write_tokens", "cost", "requests", "seconds"}
        safe_usage = {k: float(number(v)) for k, v in usage.items() if k in allowed and number(v) is not None}
        for source, target in [('inputTokens','input_tokens'), ('outputTokens','output_tokens'), ('totalTokens','total_tokens')]:
            if target not in safe_usage and number(usage.get(source)) is not None:
                safe_usage[target] = float(number(usage[source]))
        if invalid_cache_counters(usage):
            safe_usage['cache_usage_invalid'] = True
        cached, written = cache_counters(usage)
        if cached is not None:
            safe_usage['cached_tokens'] = float(cached)
        if written is not None:
            safe_usage['cache_write_tokens'] = float(written)
        for field in ("input_tokens_details", "prompt_tokens_details", "output_tokens_details", "completion_tokens_details"):
            details = usage.get(field)
            if isinstance(details, dict):
                safe_usage[field] = {k: float(number(v)) for k, v in details.items() if k in {"cached_tokens", "cache_write_tokens", "image_tokens", "text_tokens", "audio_tokens", "video_tokens"} and number(v) is not None}
        if usage.get("cost_currency") in {"USD", "CNY"}:
            safe_usage["cost_currency"] = usage["cost_currency"]
        usage = safe_usage
        ctx = {**billing_context.get(), **scope}
        record_id = record_id or str(uuid4())
        with self._connect() as db:
            previous = db.execute("SELECT * FROM credit_ledger WHERE id=?", (record_id,)).fetchone()
        old = json.loads(previous["data_json"]) if previous else None
        if old and old["status"] == "settled" and (not evo or has_reported_cost(old)):
            return old  # polling/replay must never double-charge or reprice
        if old:
            usage = {**old.get('usage', {}), **usage}
            units = {**old.get('units', {}), **units}
        price = old["price"] if old else self.catalog.price(provider, base_url, model)
        rules = old["rules"] if old else self.catalog.settings().credits.model_dump()
        currency = usage.get("cost_currency") or ("USD" if provider == "openrouter" else None)
        reported = usage.get("cost") if currency in {"USD", "CNY"} else None
        if reported is not None:
            price = {**price, "currency": currency, "source": "reported"}
        # EvoLink only settles from a monetary receipt, never from a tariff.
        cost = number(reported) if evo else calculate_cost(kind, usage, units, price, reported) if completed or reported is not None else None
        cny = cost * number(rules["usdToCny"]) if cost is not None and price.get("currency") == "USD" else cost
        points = cny * number(rules["pointsPerCny"]) * number(rules["multiplier"]) if cny is not None else None
        value = {"id": record_id, "provider": provider, "baseUrl": base_url.rstrip('/'), "model": model, "kind": kind, "completed": completed,
                 "status": "settled" if points is not None else "pending", "points": float(points) if points is not None else None,
                 "costCny": float(cny) if cny is not None else None, "usage": usage, "units": units,
                 "costSource": 'provider_reported' if reported is not None else 'price_estimate' if cost is not None else None,
                 "providerTaskId": receipt_id(provider_task_id) or (old or {}).get('providerTaskId'),
                 "providerRequestId": receipt_id(provider_request_id) or (old or {}).get('providerRequestId'),
                 "price": price, "rules": rules, "date": old["date"] if old else datetime.now().astimezone().date().isoformat()}
        # No prompt, key, headers, or provider response body is stored here.
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT data_json FROM credit_ledger WHERE id=?', (record_id,)).fetchone()
            if evo and current and has_reported_cost(json.loads(current[0])):
                return json.loads(current[0])  # A stale poll must not overwrite a reconciled receipt.
            db.execute("INSERT OR REPLACE INTO credit_ledger VALUES (?,?,?,?,?)", (
                record_id, previous["project_id"] if previous else ctx.get("project_id"), previous["task_id"] if previous else ctx.get("task_id"),
                previous["created_at"] if previous else datetime.now(timezone.utc).isoformat(), json.dumps(value, ensure_ascii=False)))
        return value

    def summary(self, project_id=None):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM credit_ledger" + (" WHERE project_id=?" if project_id else ""), (project_id,) if project_id else ()).fetchall()
        total, pending, by_day, by_task = Decimal(0), 0, {}, {}
        for row in rows:
            item = json.loads(row["data_json"])
            points = number(item["points"]) or Decimal(0)
            total += points
            pending += item["status"] == "pending"
            by_day[item["date"]] = by_day.get(item["date"], Decimal(0)) + points
            if row["task_id"]:
                task = by_task.setdefault(row["task_id"], {"points": Decimal(0), "pending": 0})
                task["points"] += points
                task["pending"] += item["status"] == "pending"
        from .credit_reporting import breakdown
        return {**breakdown(rows), "points": float(total), "pending": pending, "updatedAt": datetime.now(timezone.utc).isoformat(), "byDay": {k: float(v) for k, v in by_day.items()},
                "byTask": {k: {**v, "points": float(v["points"])} for k, v in by_task.items()}}


class MeteredProvider:
    """Capture non-SDK calls at the provider boundary, including media polls."""
    def __init__(self, adapter, billing, kind):
        self._adapter, self._billing, self._kind = adapter, billing, kind

    def __getattr__(self, name):
        attr = getattr(self._adapter, name)
        if name not in {"complete", "complete_structured", "embed", "generate", "retrieve"}:
            return attr
        def call(*args, **kwargs):
            adapter = self._adapter
            adapter.last_response = {}
            from .budget import BudgetService
            budget=None
            ctx=billing_context.get();reservation={}
            if name!='retrieve' and ctx.get('task_id') and self._billing.catalog.settings().taskBudgetPoints is not None:
                budget=BudgetService(self._billing.store,self._billing.catalog)
                raw_prompt=str(kwargs.get('prompt') or kwargs.get('text') or '')+str(kwargs.get('system') or '')
                reservation=budget.reserve(ctx['task_id'],provider=adapter.provider_key,base_url=str(getattr(adapter,'base_url',None) or getattr(adapter,'endpoint','')).rstrip('/'),model=kwargs.get('model') or getattr(adapter,'model',''),kind=self._kind,
                    usage={'input_tokens':len(raw_prompt.encode('utf-8'))+2000,'output_tokens':0 if self._kind=='embedding' else self._billing.catalog.settings().maxOutputTokens} if self._kind in {'text','router','embedding'} else {},
                    units={'requests':1,'images':kwargs.get('n',1),'seconds':kwargs.get('duration',kwargs.get('seconds',8 if self._kind=='video' else None)),'inputImages':int(bool(kwargs.get('source_asset_path')))})
            try:
                result = attr(*args, **kwargs)
            except Exception as error:
                from .evolink_billing import is_evolink
                raw = getattr(adapter, 'last_response', {}) or {}
                endpoint = str(getattr(adapter, 'base_url', None) or getattr(adapter, 'endpoint', '')).rstrip('/')
                if is_evolink(adapter.provider_key, endpoint) and raw.get('id'):
                    ledger = self._billing.record(provider=adapter.provider_key, base_url=endpoint,
                        model=kwargs.get('model') or getattr(adapter, 'model', ''), kind=self._kind,
                        usage=raw.get('usage'), provider_task_id=raw['id'] if self._kind in {'image','video','audio'} else None,
                        provider_request_id=raw['id'], record_id=self._billing.catalog.price_key(adapter.provider_key, endpoint, f"{self._kind}:{raw['id']}"),
                        completed=self._kind not in {'image','video','audio'} or raw.get('status') == 'completed')
                    if reservation:
                        budget.bind_record(ctx['task_id'], reservation['reservationId'], ledger['id'])
                        budget.settle(ctx['task_id'], reservation['reservationId'], ledger.get('points'))
                if reservation and not (is_evolink(adapter.provider_key, endpoint) and raw.get('id')) and getattr(error,'status_code',None) in {400,401,402,403,404,405,413,415,422,429}:
                    budget.settle(ctx['task_id'],reservation['reservationId'],0)
                raise
            raw = getattr(adapter, "last_response", {}) or (result.get("raw", {}) if isinstance(result, dict) else {})
            usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
            usage = usage if isinstance(usage, dict) else {}
            provider = adapter.provider_key
            endpoint = str(getattr(adapter, "base_url", None) or getattr(adapter, "endpoint", "") or "").rstrip("/")
            model = kwargs.get("model") or getattr(adapter, "model", None) or (result.get("model") if isinstance(result, dict) else "") or provider
            job_id = (result.get("jobId") if isinstance(result, dict) else None) or kwargs.get("job_id")
            from .evolink_billing import is_evolink
            evo = is_evolink(provider, endpoint)
            if evo and self._kind in {'image','video','audio'}: job_id = job_id or raw.get('id')
            record_id = self._billing.catalog.price_key(provider, endpoint, f"{self._kind}:{job_id}") if job_id else None
            # Returned duration is authoritative. Requested duration alone may differ.
            data = raw.get("data", raw) if isinstance(raw, dict) else {}
            data = data[0] if isinstance(data, list) and data else data
            data = data if isinstance(data, dict) else {}
            attachments = kwargs.get("attachments") or []
            units = {"requests": 1, "inputImages": sum(1 for item in attachments if str(item.get("mime", "")).startswith("image/") and isinstance(item.get("data"), str))}
            if self._kind == "image":
                units["inputImages"] = 1 if kwargs.get("source_asset_path") else 0
            if self._kind == "image":
                units["images"] = len(raw["data"]) if isinstance(raw.get("data"), list) else 1
            if self._kind == "video":
                units["seconds"] = data.get("duration", data.get("seconds", usage.get("seconds")))
            completed = self._kind in {'text', 'router', 'embedding', 'search'} or not isinstance(result, dict) or result.get("status") in {"succeeded", "completed", "success", "SUCCEEDED"} or bool(result.get("content"))
            ledger=self._billing.record(provider=provider, base_url=endpoint, model=model, kind=self._kind,
                                 usage=usage, units=units, record_id=record_id, completed=completed,
                                 provider_task_id=job_id if evo else None, provider_request_id=raw.get('id') if evo else None)
            if reservation:
                budget.bind_record(ctx['task_id'],reservation['reservationId'],ledger['id'])
                budget.settle(ctx['task_id'],reservation['reservationId'],ledger.get('points'))
            elif record_id:
                BudgetService.settle_record(self._billing.store,record_id,ledger.get('points'))
            return result
        return call
