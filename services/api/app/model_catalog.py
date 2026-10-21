from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .model_config import EndpointModel, ModelPrice, ModelSettings, ModelTier
from .model_capabilities import normalize_snapshot
from .model_prices import default_price, video_price


class ModelCatalog:
    """Durable gateway snapshots. Reading this class never performs network I/O."""
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS model_catalogs (
                    provider TEXT NOT NULL, base_url TEXT NOT NULL, data_json TEXT NOT NULL,
                    saved_at TEXT NOT NULL, PRIMARY KEY(provider, base_url));
                CREATE TABLE IF NOT EXISTS model_settings (id INTEGER PRIMARY KEY CHECK(id=1), data_json TEXT NOT NULL);
            """)

    @staticmethod
    def price_key(provider: str, base_url: str, model: str) -> str:
        return json.dumps([provider, base_url.rstrip("/"), model], ensure_ascii=False, separators=(",", ":"))

    def save(self, provider: str, base_url: str, data: dict[str, Any]) -> dict[str, Any]:
        saved = {**normalize_snapshot(data), "savedAt": datetime.now(timezone.utc).isoformat(), "source": "local"}
        with self.store._connect() as db:
            db.execute("INSERT OR REPLACE INTO model_catalogs VALUES (?, ?, ?, ?)",
                       (provider, base_url.rstrip("/"), json.dumps(saved, ensure_ascii=False), saved["savedAt"]))
        return saved

    def get(self, provider: str, base_url: str) -> dict[str, Any]:
        with self.store._connect() as db:
            row = db.execute("SELECT data_json FROM model_catalogs WHERE provider=? AND base_url=?", (provider, base_url.rstrip("/"))).fetchone()
        if not row: return {"models": [], "modelCatalog": [], "savedAt": None, "source": "local"}
        data = json.loads(row[0])
        if provider == 'evolink':
            from .evolink import normalize_evolink_model
            data['modelCatalog'] = [normalize_evolink_model(item) for item in data.get('modelCatalog', [])]
        return normalize_snapshot(data)

    def record(self, provider: str, base_url: str, model: str) -> dict:
        return next((item for item in self.get(provider, base_url).get("modelCatalog", []) if item["id"] == model), {})

    def settings(self) -> ModelSettings:
        with self.store._connect() as db:
            row = db.execute("SELECT data_json FROM model_settings WHERE id=1").fetchone()
        if not row: return ModelSettings()
        data = json.loads(row[0])
        version = int(data.get('defaultsVersion', 1) or 1)
        legacy_before_v2 = version < 2
        if version < 2:
            from .model_config import DEFAULT_SEARCH_MODEL, DEFAULT_DRAFT_VIDEO_MODEL
            if data.get('media', {}).get('video', {}).get('draft') == 'bytedance/seedance-2.5':
                data['media']['video']['draft'] = DEFAULT_DRAFT_VIDEO_MODEL
            search = data.get('search', {})
            if search.get('provider', 'inherit') in {'inherit', 'openrouter'} and not search.get('model') and not search.get('baseUrl'):
                data['search'] = ModelSettings().search.model_copy(update={'model': DEFAULT_SEARCH_MODEL}).model_dump()
            elif search.get('provider') == 'openrouter':
                search['api'] = 'responses'
            data['defaultsVersion'] = 2
            version = 2
        if version < 3:
            def untouched_default(endpoint):
                return (endpoint.get('provider', 'inherit') == 'inherit'
                        and not endpoint.get('baseUrl')
                        and endpoint.get('api', 'auto') == 'auto')

            legacy_models = {'gpt-5.6-luna'}
            if legacy_before_v2:
                legacy_models.add('gpt-5.6-terra')
            for tier, replacement in (('FAST', 'deepseek/deepseek-v4-flash-0731'), ('STANDARD', 'z-ai/glm-5.3-flash')):
                config = data.get('tiers', {}).get(tier, {})
                primary = config.get('primary', {})
                if untouched_default(primary) and primary.get('model', '').split('/')[-1] in legacy_models:
                    primary['model'] = replacement
                    if not config.get('fallback'):
                        config['fallback'] = EndpointModel(model='openai/gpt-5.6-terra').model_dump()
            data['defaultsVersion'] = 3
            version = 3
        if version < 4:
            for tier, previous, replacement in (
                ('FAST', 'deepseek-v4-flash-0731', 'openai/gpt-5.6-luna'),
                ('STANDARD', 'glm-5.3-flash', 'openai/gpt-5.6-terra'),
            ):
                config = data.get('tiers', {}).get(tier, {})
                primary = config.get('primary', {})
                if (primary.get('provider', 'inherit') == 'inherit'
                        and not primary.get('baseUrl')
                        and primary.get('api', 'auto') == 'auto'
                        and primary.get('model', '').split('/')[-1] == previous):
                    primary['model'] = replacement
                    fallback = config.get('fallback') or {}
                    if (fallback.get('provider', 'inherit') == 'inherit'
                            and not fallback.get('baseUrl')
                            and fallback.get('api', 'auto') == 'auto'
                            and fallback.get('model', '').split('/')[-1] == replacement.split('/')[-1]):
                        config['fallback'] = None
            data['defaultsVersion'] = 4
            version = 4
        if version < 5:
            config = data.get('tiers', {}).get('STANDARD', {})
            primary = config.get('primary', {})
            if (primary.get('provider', 'inherit') == 'inherit'
                    and not primary.get('baseUrl')
                    and primary.get('api', 'auto') == 'auto'
                    and primary.get('model', '').split('/')[-1] == 'gpt-5.6-terra'):
                # Preserve the historical v5 migration before the v7 default
                # restores Terra as the STANDARD tier.
                primary['model'] = 'openai/gpt-5.6-luna'
                fallback = config.get('fallback') or {}
                if (fallback.get('provider', 'inherit') == 'inherit'
                        and not fallback.get('baseUrl')
                        and fallback.get('api', 'auto') == 'auto'
                        and fallback.get('model', '').split('/')[-1] == 'gpt-5.6-luna'):
                    config['fallback'] = None
            data['defaultsVersion'] = 5
            version = 5
        if version < 6:
            from .model_config import DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL

            image = data.get('media', {}).get('image', {})
            # The v5 default used Sunburst in all three slots. Only migrate the
            # untouched triplet; a user-customized media map remains authoritative.
            if image and all(str(image.get(level, '')).split('/')[-1].lower() == 'gpt-image-2.5-sunburst'
                             for level in ('draft', 'standard', 'final')):
                image.update(draft=DEFAULT_DRAFT_IMAGE_MODEL, standard=DEFAULT_IMAGE_MODEL, final=DEFAULT_IMAGE_MODEL)
            data['defaultsVersion'] = 6
            version = 6
        if version < 7:
            config = data.get('tiers', {}).get('STANDARD', {})
            primary = config.get('primary', {})
            # Version 5 temporarily collapsed FAST and STANDARD onto Luna.
            # Restore Terra only for the untouched inherited endpoint; custom
            # providers, URLs, protocols, models and fallbacks remain authoritative.
            if (primary.get('provider', 'inherit') == 'inherit'
                    and not primary.get('baseUrl')
                    and primary.get('api', 'auto') == 'auto'
                    and primary.get('model', '').split('/')[-1] == 'gpt-5.6-luna'):
                primary['model'] = 'openai/gpt-5.6-terra'
            data['defaultsVersion'] = 7
            version = 7
        if version < 8:
            search = data.get('search') or {}
            # Migrate only the exact old built-in search endpoint. A user
            # supplied address, provider, protocol or model remains untouched.
            if (search.get('provider') == 'openrouter'
                    and str(search.get('baseUrl') or '').rstrip('/') == 'https://openrouter.ai/api/v1'
                    and str(search.get('model') or '').split('/')[-1] == 'gpt-5.6-luna'
                    and search.get('api', 'responses') == 'responses'):
                data['search'] = EndpointModel(provider='inherit', api='responses').model_dump()
            data.setdefault('preferredTextProvider', {'key': '', 'baseUrl': ''})
            data['defaultsVersion'] = 8
            version = 8
        if version < 9:
            def inherited_builtin(endpoint, model):
                return (isinstance(endpoint, dict)
                        and endpoint.get('provider', 'inherit') == 'inherit'
                        and not endpoint.get('baseUrl')
                        and endpoint.get('api', 'auto') == 'auto'
                        and str(endpoint.get('model') or '').split('/')[-1] == model)

            tiers = data.get('tiers') or {}
            standard = tiers.get('STANDARD') or {}
            # Version 8's untouched STANDARD default was Terra. Restore Luna,
            # but never rewrite a custom model, endpoint, provider or protocol.
            if inherited_builtin(standard.get('primary'), 'gpt-5.6-terra'):
                standard['primary']['model'] = 'openai/gpt-5.6-luna'
                fallback = standard.get('fallback')
                if inherited_builtin(fallback, 'gpt-5.6-luna') or inherited_builtin(fallback, 'gpt-5.6-terra'):
                    standard['fallback'] = None
            old_turns = {'FAST': 6, 'STANDARD': 12, 'REASONING': 24, 'PREMIUM': 36}
            builtin_models = {
                'FAST': {'gpt-5.6-luna'}, 'STANDARD': {'gpt-5.6-luna', 'gpt-5.6-terra'},
                'REASONING': {'gpt-5.6-sol'}, 'PREMIUM': {'gpt-6-astra'},
            }
            for name, config in tiers.items():
                primary = config.get('primary') or {}
                leaf = str(primary.get('model') or '').split('/')[-1]
                untouched = (primary.get('provider', 'inherit') == 'inherit'
                             and not primary.get('baseUrl')
                             and primary.get('api', 'auto') == 'auto'
                             and leaf in builtin_models.get(name, set()))
                if untouched and config.get('maxTurns') == old_turns.get(name):
                    config['maxTurns'] = 60
                if untouched and config.get('retries', 1) == 1:
                    config['retries'] = 2
                fallback = config.get('fallback') or {}
                if name in {'FAST', 'STANDARD'} and untouched and inherited_builtin(fallback, 'gpt-5.6-terra'):
                    config['fallback'] = None
            data.setdefault('memory', {})['compactionEnabled'] = True
            if data.get('maxEscalations') == 2:
                data['maxEscalations'] = 0
            data['defaultsVersion'] = 9
            version = 9
        if version < 10:
            defaults = ModelSettings().tiers
            previous_models = {
                'FAST': {'gpt-5.6-luna'},
                'STANDARD': {'gpt-5.6-luna', 'gpt-5.6-terra'},
                'REASONING': {'gpt-5.6-sol'},
            }
            # Only inherited former defaults move to GPT-6. Explicit service,
            # URL, protocol, role models and fallback choices remain authoritative.
            for name, config in (data.get('tiers') or {}).items():
                primary = config.get('primary') or {}
                if (primary.get('provider', 'inherit') == 'inherit'
                        and not primary.get('baseUrl')
                        and primary.get('api', 'auto') == 'auto'
                        and str(primary.get('model') or '').split('/')[-1] in previous_models.get(name, set())):
                    primary['model'] = defaults[ModelTier(name)].primary.model
            search = data.get('search') or {}
            if (search.get('provider', 'inherit') == 'inherit'
                    and not search.get('baseUrl')
                    and search.get('api', 'auto') in {'auto', 'responses'}
                    and str(search.get('model') or '').split('/')[-1] == 'gpt-5.6-luna'):
                from .model_config import DEFAULT_SEARCH_MODEL
                search['model'] = DEFAULT_SEARCH_MODEL
            data['defaultsVersion'] = 10
        return ModelSettings.model_validate(data)

    def save_settings(self, settings: ModelSettings) -> ModelSettings:
        with self.store._connect() as db:
            db.execute("INSERT OR REPLACE INTO model_settings VALUES (1, ?)", (settings.model_dump_json(),))
        return settings

    def set_preferred_text_provider(self, key: str, base_url: str) -> ModelSettings:
        """Remember gateway affinity only; API keys continue to live in the credential store."""
        settings = self.settings()
        normalized_key = str(key or '').strip()
        normalized_url = str(base_url or '').strip().rstrip('/')
        if (settings.preferredTextProvider.key == normalized_key
                and settings.preferredTextProvider.baseUrl == normalized_url):
            return settings
        payload = settings.model_dump(mode='python')
        payload['preferredTextProvider'] = {'key': normalized_key, 'baseUrl': normalized_url}
        return self.save_settings(ModelSettings.model_validate(payload))

    def resolve_id(self, provider: str, base_url: str, requested: str) -> str | None:
        models = self.get(provider, base_url).get("models", [])
        if requested in models:
            return requested
        # Gateways may namespace OpenAI IDs; never replace a version/family.
        def comparable(value):
            return "-".join(value.split("/")[-1].lower().replace("_", "-").split())
        matching = [model for model in models if comparable(model) == comparable(requested)]
        return matching[0] if len(matching) == 1 else None

    def price(self, provider: str, base_url: str, model: str) -> dict[str, Any]:
        record = next((item for item in self.get(provider, base_url).get("modelCatalog", []) if item["id"] == model), {"id": model})
        return self._price(provider, base_url, record, self.settings().prices)

    def _price(self, provider, base_url, record, overrides):
        override = overrides.get(self.price_key(provider, base_url, record['id']))
        if override:
            return {**override.model_dump(exclude_none=True), "source": "manual"}
        gateway = self.normalize_price(record)
        if gateway:
            pricing_tiers = record.get('pricingTiers')
            if isinstance(pricing_tiers, list) and pricing_tiers:
                gateway.update(
                    referenceOnly=True,
                    priceDetails={'tiers': pricing_tiers},
                    priceNote='目录包含按用量阈值变化的输入/输出倍率；基础单价仅供展示，以服务账单为准',
                )
            return gateway
        price = default_price(record['id'])
        if price:
            from urllib.parse import urlsplit
            if provider != 'openrouter' or urlsplit(base_url).hostname != 'openrouter.ai':
                price.update(tariffConditional=bool(price.get('referenceOnly')), referenceOnly=True, priceNote='OpenRouter 公开参考价；当前服务费率请以返回费用或手动报价为准')
        return price

    @staticmethod
    def normalize_price(record):
        raw = record.get("pricing") or {}
        if not isinstance(raw, dict):
            return {}
        if (record.get('id') in {'openrouter/auto', 'openrouter/auto-beta', 'openrouter/bodybuilder',
                                 'openrouter/fusion', 'openrouter/pareto-code'}
                and str(raw.get('prompt')) == '-1' and str(raw.get('completion')) == '-1'):
            return {'currency': 'USD', 'source': 'gateway', 'pricingMode': 'dynamic',
                    'referenceOnly': True, 'priceNote': '无固定单价，按服务返回的实际费用计费'}
        # OpenRouter's standard prices are currency units per single unit.
        mapping = {"prompt": ("inputPerMillion", 1_000_000), "completion": ("outputPerMillion", 1_000_000),
                   "input_cache_read": ("cachedPerMillion", 1_000_000), "input_cache_write": ("cacheWritePerMillion", 1_000_000), "image": ("perInputImage", 1),
                   "request": ("perRequest", 1), "web_search": ("perSearch", 1)}
        normalized: dict[str, Any] = {"currency": raw.get("currency", "USD")}
        for key in ModelPrice.model_fields:
            if key in raw:
                normalized[key] = raw[key]
        for source, (target, scale) in mapping.items():
            try:
                if source in raw and raw[source] is not None and target not in normalized:
                    normalized[target] = float(raw[source]) * scale
            except (TypeError, ValueError):
                continue
        try:
            result = ModelPrice.model_validate(normalized).model_dump(exclude_none=True)
        except ValueError:
            return {}
        if len(result) > 1:
            return {**result, "source": "gateway"}
        video = video_price(record.get('pricing_skus'))
        return {**video, 'source': 'gateway'} if video else {}

    def view(self, provider: str, base_url: str) -> dict[str, Any]:
        data = self.get(provider, base_url)
        settings = self.settings()
        overrides = settings.prices
        def price(item):
            return self._price(provider, base_url, item, overrides)
        records = {item.get('id'): item for item in data.get('modelCatalog', [])}
        tiers: dict[str, dict[str, Any]] = {}
        for tier in ModelTier:
            configured = settings.tiers[tier].primary
            endpoint_provider = provider if configured.provider == 'inherit' else configured.provider
            endpoint_base_url = base_url if configured.provider == 'inherit' and not configured.baseUrl else configured.baseUrl
            resolved = self.resolve_id(endpoint_provider, endpoint_base_url, configured.model) if endpoint_provider and endpoint_base_url else None
            record = records.get(resolved) if endpoint_provider == provider and endpoint_base_url.rstrip('/') == base_url.rstrip('/') else self.record(endpoint_provider, endpoint_base_url, resolved or configured.model) if endpoint_provider and endpoint_base_url else {}
            kinds = record.get('kinds') if isinstance(record, dict) else []
            available = bool(resolved and (not kinds or 'text' in kinds))
            if not endpoint_provider or not endpoint_base_url:
                reason = 'provider_not_selected'
            elif not resolved:
                reason = 'configured_model_not_in_catalog'
            elif kinds and 'text' not in kinds:
                reason = 'model_not_text_capable'
            else:
                reason = None
            tiers[tier.value] = {
                'available': available,
                'configuredModel': configured.model,
                'resolvedModel': resolved,
                'provider': endpoint_provider,
                'baseUrl': endpoint_base_url,
                'inputModalities': record.get('inputModalities', []) if isinstance(record, dict) else [],
                'reason': reason,
            }
        return {
            **data,
            "baseUrl": base_url,
            "modelCatalog": [{**item, "price": price(item)} for item in data.get("modelCatalog", [])],
            "routeAvailability": {
                "tiers": tiers,
                "autoReady": all(item['available'] for item in tiers.values()),
                "missingTiers": [name for name, item in tiers.items() if not item['available']],
            },
        }
