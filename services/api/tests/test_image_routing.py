from types import SimpleNamespace

import pytest

from app.image_quality import decide_image_policy
from app.image_routing import ImageCandidate, build_image_route, dispatch_image_route
from app.model_catalog import ModelCatalog
from app.model_config import (
    DEFAULT_DRAFT_IMAGE_MODEL,
    DEFAULT_IMAGE_MODEL,
    FALLBACK_IMAGE_MODEL,
    ModelSettings,
)
from app.model_router import MediaModelRouter
from app.providers.http import ProviderError
from app.providers.image_request import image_request_started
from app.providers.registry import ProviderRegistry
from app.storage import ProjectStore


ALL_IMAGES = [
    DEFAULT_DRAFT_IMAGE_MODEL,
    DEFAULT_IMAGE_MODEL,
    FALLBACK_IMAGE_MODEL,
    'bytedance-seed/seedream-5-0-lite',
    'bytedance-seed/seedream-5-0-pro',
    'bytedance-seed/seedream-4.5',
    'openai/gpt-5.4-image-2',
    'openai/gpt-5.4-image-2-2026-09-08',
]


@pytest.fixture
def router(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    catalog.save('openrouter', 'https://relay.test/v1', {'models': ALL_IMAGES})
    return MediaModelRouter(catalog), catalog


def test_automatic_candidate_order_by_tier_and_resolution(router):
    route, _ = router
    draft = route.image_plan(provider='openrouter', base_url='https://relay.test/v1', quality='draft',
                             params={'resolution': '1K', '_resolutionSource': 'intent'})
    assert draft['candidateModels'] == [
        DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL,
        'bytedance-seed/seedream-5-0-lite', 'bytedance-seed/seedream-4.5',
        'bytedance-seed/seedream-5-0-pro',
    ]
    final = route.image_plan(provider='openrouter', base_url='https://relay.test/v1', quality='final', params={'resolution': '2K'})
    assert final['candidateModels'] == [
        DEFAULT_IMAGE_MODEL, DEFAULT_DRAFT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL,
        'bytedance-seed/seedream-5-0-pro', 'bytedance-seed/seedream-4.5',
        'bytedance-seed/seedream-5-0-lite',
    ]
    four_k = route.image_plan(provider='openrouter', base_url='https://relay.test/v1', quality='final', params={'resolution': '4K'})
    assert four_k['candidateModels'][-2:] == ['bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-lite']
    explicit_one_k = route.image_plan(provider='openrouter', base_url='https://relay.test/v1', quality='draft',
                                      params={'resolution': '1K', '_resolutionSource': 'user'})
    assert explicit_one_k['candidateModels'][-2:] == ['bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-pro']


def test_automatic_bans_gpt_54_but_manual_keeps_it(router):
    route, catalog = router
    settings = catalog.settings()
    settings.media['image']['standard'] = 'openai/gpt-5.4-image-2-2026-09-08'
    catalog.save_settings(settings)
    automatic = route.image_plan(provider='openrouter', base_url='https://relay.test/v1', quality='standard')
    assert all('gpt-5.4-image-2' not in model.lower() for model in automatic['allCandidateModels'])
    manual = route.image_plan(provider='openrouter', base_url='https://relay.test/v1',
                              model='openai/gpt-5.4-image-2-2026-09-08', quality='standard')
    assert manual['mode'] == 'manual'
    assert manual['candidateModels'] == ['openai/gpt-5.4-image-2-2026-09-08']


def test_openai_compatible_image_plan_normalizes_gateway_root_before_catalog_lookup(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    catalog.save('openai-compatible', 'https://relay.test/v1', {
        'models': ['gpt-image-2.5-flare', 'gpt-image-2.5-sunburst'],
    })
    registry = ProviderRegistry()
    registry.catalog = catalog

    plan, candidates = build_image_route(
        registry,
        provider='openai-compatible',
        base_url='https://relay.test/',
        requested_model=None,
        decision=decide_image_policy('draft', prompt='现代简约游船概念图'),
        params={'aspect_ratio': '16:9'},
        has_references=False,
    )

    assert plan['primaryModel'] == 'gpt-image-2.5-flare'
    assert [item.model for item in candidates] == ['gpt-image-2.5-flare', 'gpt-image-2.5-sunburst']
    assert all(item.adapter.base_url == 'https://relay.test/v1' for item in candidates)


@pytest.mark.parametrize('alias', [
    'openai/gpt-5.4-image-2',
    'Vendor/OpenAI/GPT-5.4-IMAGE-2',
    'openai/gpt-5.4-image-2-2026-09-08',
    'OPENAI/GPT-5_4-IMAGE-2',
])
def test_gpt_54_alias_normalization_is_blocked_in_auto(alias):
    assert MediaModelRouter.automatic_image_model_allowed(alias) is False


class Adapter:
    reports_image_request_start = True
    api = 'images'
    supported_parameters = None

    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.last_response = {}

    def generate(self, **_):
        self.calls += 1
        image_request_started()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def candidate(model, adapter):
    return ImageCandidate('openrouter', model, adapter, {}, {'model': model, 'tier': 'standard',
                          'requestedQuality': 'medium', 'status': 'unsupported'}, [])


@pytest.mark.parametrize('error', [
    ProviderError('model not found', status_code=404),
    ProviderError('model unavailable', status_code=400),
    ProviderError('no available image endpoints', status_code=422),
    ProviderError('rate limited', status_code=429),
])
def test_dispatch_falls_back_only_for_safe_model_rejection(error):
    first = Adapter(error)
    second = Adapter(b'png')
    plan = {'mode': 'auto', 'tier': 'standard', 'primaryModel': 'first',
            'candidateModels': ['first', 'second'], 'allCandidateModels': ['first', 'second'], 'unavailableModels': []}
    content, selected, summary, _ = dispatch_image_route(plan, [candidate('first', first), candidate('second', second)],
                                                         prompt='x', negative_prompt=None)
    assert content == b'png' and selected.model == 'second'
    assert summary['fallbackUsed'] is True
    assert [item['status'] for item in summary['candidates']] == ['safe_rejected', 'succeeded']


@pytest.mark.parametrize('error', [
    ProviderError('quality rejected', status_code=400),
    ProviderError('unauthorized', status_code=401),
    ProviderError('content policy', status_code=422),
    ProviderError('model unavailable because balance is insufficient', status_code=400),
    ProviderError('server failed', status_code=500),
    ProviderError('timeout'),
    ProviderError('invalid response', response_received=True),
])
def test_dispatch_does_not_fallback_for_unsafe_or_ambiguous_failures(error):
    first, second = Adapter(error), Adapter(b'png')
    plan = {'mode': 'auto', 'tier': 'standard', 'primaryModel': 'first',
            'candidateModels': ['first', 'second'], 'allCandidateModels': ['first', 'second'], 'unavailableModels': []}
    with pytest.raises(ProviderError):
        dispatch_image_route(plan, [candidate('first', first), candidate('second', second)], prompt='x', negative_prompt=None)
    assert first.calls == 1 and second.calls == 0


def test_manual_model_never_falls_back_even_for_safe_rejection():
    first = Adapter(ProviderError('model unavailable', status_code=429))
    plan = {'mode': 'manual', 'tier': 'standard', 'primaryModel': 'manual',
            'candidateModels': ['manual'], 'allCandidateModels': ['manual'], 'unavailableModels': []}
    with pytest.raises(ProviderError):
        dispatch_image_route(plan, [candidate('manual', first)], prompt='x', negative_prompt=None)
    assert first.calls == 1


def test_usage_on_rate_limit_prevents_fallback():
    error = ProviderError('rate limited', status_code=429)
    error.usage = {'output_tokens': 1}
    first, second = Adapter(error), Adapter(b'png')
    plan = {'mode': 'auto', 'tier': 'standard', 'primaryModel': 'first',
            'candidateModels': ['first', 'second'], 'allCandidateModels': ['first', 'second'], 'unavailableModels': []}
    with pytest.raises(ProviderError):
        dispatch_image_route(plan, [candidate('first', first), candidate('second', second)], prompt='x', negative_prompt=None)
    assert second.calls == 0


def test_seedream_lite_raises_automatic_draft_1k_to_2k():
    class Registry:
        catalog = None
        def image(self, _provider, **_):
            return Adapter(b'png')
    decision = decide_image_policy('draft', prompt='概念探索')
    plan, candidates = build_image_route(Registry(), provider='openrouter', base_url='https://relay.test/v1',
                                         requested_model=None, decision=decision, params={}, has_references=False)
    lite = next(item for item in candidates if 'seedream-5-0-lite' in item.model)
    assert lite.options['resolution'] == '2K'
    assert lite.quality['routeAdjustments'] == ['Seedream Lite 最低分辨率提升为 2K']
    assert plan['mode'] == 'auto'


def test_gpt_image_2_recomputes_max_as_its_highest_compatible_quality():
    class Registry:
        catalog = None
        def image(self, _provider, **_):
            return Adapter(b'png')
    decision = decide_image_policy('max', prompt='最高质量最终稿')
    _, candidates = build_image_route(Registry(), provider='openrouter', base_url='https://relay.test/v1',
                                      requested_model=None, decision=decision, params={}, has_references=False)
    gpt2 = next(item for item in candidates if item.model == FALLBACK_IMAGE_MODEL)
    assert gpt2.options['quality'] == 'high'
    assert gpt2.quality['model'] == FALLBACK_IMAGE_MODEL
    assert gpt2.quality['routeAdjustments'] == ['GPT Image 2 使用其最高兼容质量 high']


def test_agent_derived_native_gpt_pixels_only_supply_ratio_before_dispatch():
    class Registry:
        catalog = None
        def image(self, _provider, **_):
            return Adapter(b'png')
    decision = decide_image_policy(
        None, user_message='做成三比一横版背景', params={'size': '3840x1200'}, trust_dimensions=False,
    )
    plan, candidates = build_image_route(
        Registry(), provider='openai-image', base_url='https://relay.test/v1',
        requested_model='gpt-image-2.5-sunburst', decision=decision,
        params={'size': '3840x1200'}, has_references=True, reference_count=2,
    )
    assert plan['mode'] == 'manual'
    assert candidates[0].options['size'] == '1440x480'
    assert candidates[0].adjustments == []


def test_user_explicit_native_gpt_pixels_are_not_silently_changed():
    class Registry:
        catalog = None
        def image(self, _provider, **_):
            return Adapter(b'png')
    decision = decide_image_policy(
        None, user_message='尺寸必须是3840x1200', params={'size': '3840x1200'}, trust_dimensions=False,
    )
    with pytest.raises(ValueError, match='当前 size=3840x1200'):
        build_image_route(
            Registry(), provider='openai-image', base_url='https://relay.test/v1',
            requested_model='gpt-image-2.5-sunburst', decision=decision,
            params={'size': '3840x1200'}, has_references=False,
        )


@pytest.mark.parametrize('params,reference_count', [
    ({'background': 'transparent'}, 0),
    ({}, 15),
    ({'mask_asset_path': '/tmp/mask.png'}, 1),
])
def test_seedream_candidates_are_filtered_when_output_or_edit_requirements_are_incompatible(params, reference_count):
    class Registry:
        catalog = None
        def image(self, _provider, **_):
            return Adapter(b'png')
    decision = decide_image_policy('final', prompt='最终稿', params=params, has_references=reference_count > 0)
    _, candidates = build_image_route(Registry(), provider='openrouter', base_url='https://relay.test/v1',
                                      requested_model=None, decision=decision, params=params,
                                      has_references=reference_count > 0, reference_count=reference_count)
    assert all('seedream' not in item.model for item in candidates)


def test_image_model_environment_override_applies_to_all_slots(monkeypatch):
    monkeypatch.setenv('AICS_IMAGE_MODEL', 'custom/image')
    assert set(ModelSettings().media['image'].values()) == {'custom/image'}
