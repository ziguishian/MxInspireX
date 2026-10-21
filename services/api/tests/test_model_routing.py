import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage import ProjectStore
from app.model_catalog import ModelCatalog
from app.model_config import (
    DEFAULT_DRAFT_IMAGE_MODEL,
    DEFAULT_DRAFT_VIDEO_MODEL,
    DEFAULT_FAST_TEXT_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_SEARCH_MODEL,
    DEFAULT_TEXT_FALLBACK_MODEL,
    DEFAULT_TEXT_MODEL,
    EndpointModel,
    ModelSettings,
    ModelTier,
)
from app.model_router import ModelRouter, MediaModelRouter, RoutedDesignRuntime
from app.design_runtime import DesignRuntimeError
from app.agent_contracts import AgentResult
from app.providers.registry import ProviderRegistry
from app.billing import BillingService, calculate_cost


@pytest.fixture
def setup(tmp_path):
    store = ProjectStore(str(tmp_path))
    catalog = ModelCatalog(store)
    providers = ProviderRegistry()
    providers.catalog = catalog
    settings = catalog.settings()
    ids = ([tier.primary.model for tier in settings.tiers.values()]
           + [tier.fallback.model for tier in settings.tiers.values() if tier.fallback]
           + [DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_DRAFT_VIDEO_MODEL, DEFAULT_TEXT_FALLBACK_MODEL, 'gpt-5.6-terra', 'bytedance/seedance-2.5'])
    catalog.save('openrouter', 'https://relay.test/v1', {'models': ids, 'modelCatalog': [{'id': id} for id in ids]})
    return store, catalog, providers


CURRENT = {'key': 'openrouter', 'baseUrl': 'https://relay.test/v1', 'model': 'gpt-5.6-terra'}


@pytest.mark.parametrize('version', range(1, 10))
@pytest.mark.parametrize('prefix', ['', 'openai/'])
def test_previous_defaults_upgrade_to_gpt6_without_network_or_losing_configuration(setup, version, prefix):
    store, catalog, providers = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = version
    for name, model in {'FAST': 'gpt-5.6-luna', 'STANDARD': 'gpt-5.6-luna', 'REASONING': 'gpt-5.6-sol'}.items():
        saved['tiers'][name]['primary']['model'] = prefix + model
    saved['tiers']['REASONING']['maxTurns'] = 37
    saved['tiers']['REASONING']['fallback'] = EndpointModel(
        provider='openai-compatible', baseUrl='https://backup.test/v1', model='gpt-5.6-sol', api='responses',
    ).model_dump()
    saved['roles']['review'] = EndpointModel(model='gpt-5.6-sol').model_dump()
    saved['media']['image']['draft'] = 'custom-image'
    saved['preferredTextProvider'] = {'key': 'openai-compatible', 'baseUrl': 'https://preferred.test/v1'}
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    with patch('urllib.request.urlopen', side_effect=AssertionError('migration must remain offline')), patch.object(
        providers, 'text', side_effect=AssertionError('migration must not call a provider'),
    ):
        migrated = catalog.settings()
    assert migrated.defaultsVersion == 10
    assert [config.primary.model for config in migrated.tiers.values()] == [
        'openai/gpt-6-luna', 'openai/gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-astra',
    ]
    assert migrated.tiers[ModelTier.REASONING].maxTurns == 37
    assert migrated.tiers[ModelTier.REASONING].fallback.model_dump() == saved['tiers']['REASONING']['fallback']
    assert migrated.roles['review'].model == 'gpt-5.6-sol'
    assert migrated.media['image']['draft'] == 'custom-image'
    assert migrated.preferredTextProvider.model_dump() == saved['preferredTextProvider']
    assert catalog.settings() == migrated
    catalog.save_settings(migrated)
    assert catalog.settings() == migrated


@pytest.mark.parametrize('tier,model', [('FAST', 'gpt-5.6-luna'), ('STANDARD', 'gpt-5.6-terra'), ('REASONING', 'gpt-5.6-sol')])
@pytest.mark.parametrize('custom', [
    {'provider': 'openai-compatible'}, {'baseUrl': 'https://custom.test/v1'},
    {'api': 'responses'}, {'api': 'chat_completions'}, {'model': 'custom-model'},
])
def test_gpt6_migration_preserves_custom_tier_endpoints(setup, tier, model, custom):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 9
    saved['tiers'][tier]['primary'] = EndpointModel(**{'model': model, **custom}).model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    assert catalog.settings().tiers[ModelTier(tier)].primary.model_dump() == saved['tiers'][tier]['primary']


@pytest.mark.parametrize('search,expected', [
    (EndpointModel(model='gpt-5.6-luna', api='responses'), 'openai/gpt-6-luna'),
    (EndpointModel(provider='openrouter', baseUrl='https://openrouter.ai/api/v1', model='gpt-5.6-luna', api='responses'), 'gpt-5.6-luna'),
    (EndpointModel(baseUrl='https://custom.test/v1', model='gpt-5.6-luna', api='responses'), 'gpt-5.6-luna'),
    (EndpointModel(model='gpt-5.6-sol', api='responses'), 'gpt-5.6-sol'),
])
def test_gpt6_migration_only_updates_inherited_luna_search(setup, search, expected):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 9
    saved['search'] = search.model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    assert catalog.settings().search.model_dump() == {**search.model_dump(), 'model': expected}


def test_catalog_reports_each_automatic_tier_instead_of_any_text_model(setup):
    _, catalog, _ = setup
    complete = catalog.view('openrouter', CURRENT['baseUrl'])['routeAvailability']
    assert complete['autoReady'] is True
    assert complete['missingTiers'] == []
    assert complete['tiers']['STANDARD']['resolvedModel'] == DEFAULT_TEXT_MODEL

    relay = 'https://incomplete.test/v1'
    catalog.save('openai-compatible', relay, {'models': [
        ModelSettings().tiers[ModelTier.REASONING].primary.model,
        ModelSettings().tiers[ModelTier.PREMIUM].primary.model,
    ]})
    incomplete = catalog.view('openai-compatible', relay)['routeAvailability']
    assert incomplete['autoReady'] is False
    assert incomplete['missingTiers'] == ['FAST', 'STANDARD']
    assert incomplete['tiers']['STANDARD']['reason'] == 'configured_model_not_in_catalog'


def test_version_eight_only_migrates_the_builtin_search_endpoint(setup):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 7
    saved['search'] = EndpointModel(
        provider='openrouter', baseUrl='https://openrouter.ai/api/v1',
        model='openai/gpt-5.6-luna', api='responses',
    ).model_dump(mode='json')
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.search.provider == 'inherit' and not migrated.search.baseUrl and not migrated.search.model

    saved['search'] = EndpointModel(
        provider='openrouter', baseUrl='https://custom-search.test/v1',
        model='openai/gpt-5.6-luna', api='responses',
    ).model_dump(mode='json')
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    custom = catalog.settings()
    assert custom.search.provider == 'openrouter'
    assert custom.search.baseUrl == 'https://custom-search.test/v1'


@pytest.mark.parametrize('brief,tier', [
    ('给 500 张图片添加中英文标签', 'STANDARD'),
    ('给 500 条商品文案添加中英文标签', 'FAST'),
    ('总结这次设计需求', 'STANDARD'),
    ('游艇设计提出三个方向', 'STANDARD'),
    ('调研、竞品比较、设计方案、渲染计划并生成 PPT', 'STANDARD'),
    ('这次交付明确要求最高质量的设计方案', 'STANDARD'),
    pytest.param('需求总结' * 5000, 'STANDARD', id='long-request'),
])
def test_rules(setup, brief, tier):
    _, catalog, providers = setup
    assert ModelRouter(catalog, providers).route(brief, CURRENT).model_tier == tier


@pytest.mark.parametrize('mode', ['auto', 'fast'])
def test_visual_or_file_context_never_uses_text_only_fast_model(setup, mode):
    _, catalog, providers = setup
    constraints = {'attachments':[{'mime':'image/png'}], 'modelRouting':{'mode':mode}}
    policy = ModelRouter(catalog, providers).route('提取主要颜色', CURRENT, constraints)
    assert policy.model_tier == ModelTier.STANDARD


def test_media_router_is_separate_and_manual_override(setup):
    _, catalog, providers = setup
    policy = ModelRouter(catalog, providers).route('请生成一张海报图片', CURRENT)
    assert policy.task_type == 'media:image'
    assert policy.model_tier == 'STANDARD'
    router = MediaModelRouter(catalog)
    assert router.route('image', provider='openrouter', base_url=CURRENT['baseUrl']) == DEFAULT_DRAFT_IMAGE_MODEL
    assert router.route('video', provider='openrouter', base_url=CURRENT['baseUrl'], quality='final') == 'bytedance/seedance-2.5'
    with pytest.raises(ValueError):
        router.route('image', provider='openrouter', base_url=CURRENT['baseUrl'], model='missing')


def test_evolink_default_video_family_resolves_only_local_matching_mode():
    known = {'seedance-2.5-text-to-video', 'seedance-2.5-image-to-video'}
    catalog = SimpleNamespace(settings=lambda: SimpleNamespace(media={'video': {'standard': 'bytedance/seedance-2.5'}}),
                              resolve_id=lambda provider, base, name: name if name in known else None)
    router = MediaModelRouter(catalog)
    assert router.route('video', provider='evolink', base_url='local') == 'seedance-2.5-text-to-video'
    assert router.route('video', provider='evolink', base_url='local', params={'_hasReferences':True}) == 'seedance-2.5-image-to-video'
    with pytest.raises(ValueError):
        router.route('video', provider='evolink', base_url='local', model='bytedance/seedance-2.5')
    known.clear()
    with pytest.raises(ValueError):
        router.route('video', provider='evolink', base_url='local')


def test_automatic_routing_is_local_and_does_not_spend_a_classifier_call(setup):
    _, catalog, providers = setup
    router = ModelRouter(catalog, providers)
    with patch.object(providers, 'text', side_effect=AssertionError('automatic routing contacted a model')):
        assert router.route('蓝色的未来', CURRENT).model_tier == 'STANDARD'
        assert router.route('???', CURRENT).model_tier == 'STANDARD'


@pytest.mark.parametrize('assessment,complexity,expected', [
    ('STANDARD', 5, 'STANDARD'), ('REASONING', 8, 'STANDARD'),
    ('REASONING', 3, 'STANDARD'), ('PREMIUM', 9, 'STANDARD'),
])
def test_expensive_route_requires_agent_assessment(setup, assessment, complexity, expected):
    _, catalog, providers = setup
    router = ModelRouter(catalog, providers)
    answer = router.policy(ModelTier(assessment), complexity=complexity, reason='结构计算需要多约束推导').model_dump_json()
    classifier = SimpleNamespace(base_url=CURRENT['baseUrl'], complete_structured=lambda **_: answer)
    with patch.object(providers, 'text', return_value=classifier):
        result = router.route('复杂 CAD 结构计算', CURRENT)
    assert result.model_tier == expected


@pytest.mark.parametrize('prompt,quality,params,expected', [
    ('建筑漫游', 'standard', {}, 'bytedance/seedance-2.5'),
    ('简单单镜头', 'standard', {}, 'bytedance/seedance-2.5'),
    ('简单固定镜头预览', 'draft', {'duration': 4}, DEFAULT_DRAFT_VIDEO_MODEL),
    ('简单固定镜头草稿', 'standard', {}, DEFAULT_DRAFT_VIDEO_MODEL),
    ('简单镜头，但有人物对白', 'draft', {}, 'bytedance/seedance-2.5'),
    ('简单固定镜头预览', 'draft', {'duration': 10}, 'bytedance/seedance-2.5'),
    ('简单固定镜头预览', 'draft', {'generate_audio': True}, 'bytedance/seedance-2.5'),
    ('简单固定镜头', 'final', {}, 'bytedance/seedance-2.5'),
])
def test_video_prefers_quality_and_uses_mini_only_for_simple_drafts(setup, prompt, quality, params, expected):
    _, catalog, _ = setup
    router = MediaModelRouter(catalog)
    args = dict(provider='openrouter', base_url=CURRENT['baseUrl'], prompt=prompt, quality=quality, params=params)
    assert router.route('video', **args) == expected
    assert router.route('video', **args, model=DEFAULT_DRAFT_VIDEO_MODEL) == DEFAULT_DRAFT_VIDEO_MODEL


def test_saved_legacy_defaults_migrate_without_replacing_custom_models(setup):
    store, catalog, _ = setup
    legacy = ModelSettings().model_dump(mode='json')
    legacy.pop('defaultsVersion')
    legacy['tiers']['FAST']['primary']['model'] = 'gpt-5.6-luna'
    legacy['tiers']['STANDARD']['primary']['model'] = 'gpt-5.6-terra'
    legacy['media']['image'].update(draft='gpt-image-2.5-flare', final='custom-image')
    legacy['media']['video']['draft'] = 'bytedance/seedance-2.5'
    legacy['search'] = EndpointModel().model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(legacy),))
    migrated = catalog.settings()
    assert migrated.defaultsVersion == 10
    assert migrated.tiers[ModelTier.FAST].primary.model == DEFAULT_FAST_TEXT_MODEL
    assert migrated.tiers[ModelTier.STANDARD].primary.model == DEFAULT_TEXT_MODEL
    assert migrated.tiers[ModelTier.FAST].fallback is None
    assert migrated.tiers[ModelTier.STANDARD].fallback is None
    assert migrated.media['image']['draft'] == 'gpt-image-2.5-flare'
    assert migrated.media['image']['final'] == 'custom-image'
    assert migrated.media['video']['draft'] == DEFAULT_DRAFT_VIDEO_MODEL
    assert migrated.search.provider == 'inherit'
    assert migrated.search.model == DEFAULT_SEARCH_MODEL
    assert migrated.search.api == 'responses'
    catalog.save_settings(migrated)
    assert catalog.settings() == migrated


def test_version_five_untouched_image_slots_migrate_to_flare_and_sunburst(setup):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 5
    saved['media']['image'] = {level: DEFAULT_IMAGE_MODEL for level in ('draft', 'standard', 'final')}
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.defaultsVersion == 10
    assert migrated.media['image'] == {
        'draft': DEFAULT_DRAFT_IMAGE_MODEL,
        'standard': DEFAULT_IMAGE_MODEL,
        'final': DEFAULT_IMAGE_MODEL,
    }


def test_version_five_custom_image_slot_is_not_rewritten(setup):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 5
    saved['media']['image'] = {'draft': DEFAULT_IMAGE_MODEL, 'standard': 'custom/image', 'final': DEFAULT_IMAGE_MODEL}
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    assert catalog.settings().media['image'] == saved['media']['image']


def test_version_two_defaults_migrate_but_custom_endpoint_stays_untouched(setup):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 2
    saved['tiers']['FAST']['primary'] = EndpointModel(model='openai/gpt-5.6-luna').model_dump()
    saved['tiers']['FAST']['fallback'] = None
    saved['tiers']['STANDARD']['primary'] = EndpointModel(model='openai/gpt-5.6-luna').model_dump()
    saved['tiers']['STANDARD']['fallback'] = None
    # An explicit service choice is user configuration even when its model ID
    # happens to equal the old default.
    saved['tiers']['REASONING']['primary'] = EndpointModel(
        provider='openrouter', baseUrl='https://custom.test/v1', model='openai/gpt-5.6-luna'
    ).model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.tiers[ModelTier.FAST].primary.model == DEFAULT_FAST_TEXT_MODEL
    assert migrated.tiers[ModelTier.STANDARD].primary.model == DEFAULT_TEXT_MODEL
    assert migrated.tiers[ModelTier.FAST].fallback is None
    assert migrated.tiers[ModelTier.STANDARD].fallback is None
    assert migrated.tiers[ModelTier.REASONING].primary.baseUrl == 'https://custom.test/v1'
    assert migrated.tiers[ModelTier.REASONING].primary.model == 'openai/gpt-5.6-luna'


@pytest.mark.parametrize('prefix', ['', 'namespaced/'])
def test_version_three_defaults_restore_gpt_tiers(setup, prefix):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 3
    saved['tiers']['FAST']['primary']['model'] = prefix + 'deepseek-v4-flash-0731'
    saved['tiers']['FAST']['fallback'] = EndpointModel(model='openai/gpt-5.6-luna').model_dump()
    saved['tiers']['STANDARD']['primary']['model'] = prefix + 'glm-5.3-flash'
    saved['tiers']['STANDARD']['maxTurns'] = 17
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert [config.primary.model.split('/')[-1] for config in migrated.tiers.values()] == [
        'gpt-6-luna', 'gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-astra',
    ]
    assert migrated.tiers[ModelTier.FAST].fallback is None
    assert migrated.tiers[ModelTier.STANDARD].fallback is None
    assert migrated.tiers[ModelTier.STANDARD].maxTurns == 17
    assert migrated.defaultsVersion == 10
    assert catalog.settings() == migrated
    catalog.save_settings(migrated)
    assert catalog.settings() == migrated


@pytest.mark.parametrize('custom', [
    {'provider': 'openrouter'}, {'baseUrl': 'https://custom.test/v1'},
    {'api': 'chat_completions'}, {'model': 'custom-model'},
])
def test_version_three_migration_preserves_custom_primary_and_fallback(setup, custom):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 3
    saved['tiers']['STANDARD']['primary'] = EndpointModel(
        **{'model': 'z-ai/glm-5.3-flash', **custom}
    ).model_dump()
    saved['tiers']['FAST']['primary']['model'] = 'deepseek/deepseek-v4-flash-0731'
    saved['tiers']['FAST']['fallback'] = EndpointModel(
        **{'model': 'openai/gpt-5.6-luna', **custom}
    ).model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.tiers[ModelTier.STANDARD].primary.model_dump() == saved['tiers']['STANDARD']['primary']
    assert migrated.tiers[ModelTier.FAST].primary.model == DEFAULT_FAST_TEXT_MODEL
    assert migrated.tiers[ModelTier.FAST].fallback.model_dump() == saved['tiers']['FAST']['fallback']


@pytest.mark.parametrize('prefix', ['', 'openai/'])
@pytest.mark.parametrize('custom_backup', [False, True])
def test_version_four_standard_restores_terra_and_preserves_custom_backup(setup, prefix, custom_backup):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 4
    standard = saved['tiers']['STANDARD']
    standard['primary']['model'] = prefix + 'gpt-5.6-terra'
    standard['fallback'] = EndpointModel(
        model='openai/gpt-5.6-luna', baseUrl='https://backup.test/v1' if custom_backup else '',
    ).model_dump()
    standard['maxTurns'] = 19
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.defaultsVersion == 10
    assert migrated.tiers[ModelTier.STANDARD].primary.model == DEFAULT_TEXT_MODEL
    assert migrated.tiers[ModelTier.STANDARD].maxTurns == 19
    if custom_backup:
        assert migrated.tiers[ModelTier.STANDARD].fallback.model_dump() == standard['fallback']
    else:
        assert migrated.tiers[ModelTier.STANDARD].fallback is None
    assert catalog.settings() == migrated
    catalog.save_settings(migrated)
    assert catalog.settings() == migrated


def test_version_six_untouched_standard_stays_on_luna(setup):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 6
    saved['tiers']['STANDARD']['primary'] = EndpointModel(model=DEFAULT_FAST_TEXT_MODEL).model_dump()
    saved['tiers']['STANDARD']['fallback'] = None
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.defaultsVersion == 10
    assert migrated.tiers[ModelTier.STANDARD].primary.model == DEFAULT_TEXT_MODEL
    assert migrated.tiers[ModelTier.STANDARD].fallback is None


@pytest.mark.parametrize('custom', [
    {'provider': 'openrouter'}, {'baseUrl': 'https://custom.test/v1'},
    {'api': 'responses'}, {'model': 'custom-model'},
])
def test_version_six_preserves_custom_standard_endpoint(setup, custom):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 6
    saved['tiers']['STANDARD']['primary'] = EndpointModel(
        **{'model': DEFAULT_FAST_TEXT_MODEL, **custom}
    ).model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    migrated = catalog.settings()
    assert migrated.defaultsVersion == 10
    assert migrated.tiers[ModelTier.STANDARD].primary.model_dump() == saved['tiers']['STANDARD']['primary']


@pytest.mark.parametrize('custom', [
    {'provider': 'openrouter'}, {'baseUrl': 'https://custom.test/v1'},
    {'api': 'responses'}, {'model': 'custom-model'},
])
def test_version_four_preserves_custom_standard_endpoint(setup, custom):
    store, catalog, _ = setup
    saved = ModelSettings().model_dump(mode='json')
    saved['defaultsVersion'] = 4
    saved['tiers']['STANDARD']['primary'] = EndpointModel(
        **{'model': 'openai/gpt-5.6-terra', **custom}
    ).model_dump()
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(saved),))
    assert catalog.settings().tiers[ModelTier.STANDARD].primary.model_dump() == saved['tiers']['STANDARD']['primary']


@pytest.mark.parametrize('model', ['z-ai/glm-5.3-flash', 'openai/gpt-5.6-terra'])
def test_current_version_preserves_explicit_model_selection(setup, model):
    _, catalog, _ = setup
    settings = ModelSettings()
    settings.tiers[ModelTier.STANDARD].primary.model = model
    catalog.save_settings(settings)
    assert catalog.settings() == settings


@pytest.mark.parametrize('old_limit', [1, 2, 4])
def test_legacy_parallel_settings_do_not_limit_new_tasks(setup, old_limit):
    store, catalog, providers = setup
    legacy = catalog.settings().model_dump(mode='json')
    legacy['maxParallelTools'] = old_limit
    with store._connect() as db:
        db.execute('INSERT OR REPLACE INTO model_settings VALUES (1, ?)', (json.dumps(legacy),))
    restored = catalog.settings()
    assert restored.maxParallelTools is None
    assert 'maxParallelTools' not in restored.model_dump(mode='json')
    assert 'parallelism' not in ModelRouter(catalog, providers).policy().model_dump(mode='json')
    assert restored.tiers == ModelSettings().tiers


def run_kwargs():
    return dict(project_id='project', task_id='task', agent_key='design', workflow_step='design', brief='总结设计需求',
                constraints={}, retrieved_context=['same context'], research_sources=[], attachments=[], prior_outputs=[], provider_ref=CURRENT)


def test_vision_fallback_is_selected_before_submission_from_local_capabilities(setup):
    store,catalog,providers=setup
    catalog.save('openrouter',CURRENT['baseUrl'],{'models':[DEFAULT_TEXT_MODEL,DEFAULT_TEXT_FALLBACK_MODEL],
        'modelCatalog':[
            {'id':DEFAULT_TEXT_MODEL,'input_modalities':['text'],'output_modalities':['text']},
            {'id':DEFAULT_TEXT_FALLBACK_MODEL,'input_modalities':['text','image'],'output_modalities':['text']},
        ]})
    calls=[]
    runtime=RoutedDesignRuntime(SimpleNamespace(run=lambda **kwargs: calls.append(kwargs['provider_ref']) or AgentResult(status='succeeded',structured_data={'answer':'ok'})),catalog,providers,store)
    runtime.run(**{**run_kwargs(),'attachments':[{'mime':'image/png','assetId':'image'}]})
    assert calls[0]['model'].split('/')[-1]=='gpt-6-sol'


def test_missing_luna_is_not_treated_as_a_capability_fallback(setup):
    store,catalog,providers=setup
    catalog.save('openrouter',CURRENT['baseUrl'],{'models':[DEFAULT_TEXT_FALLBACK_MODEL],
        'modelCatalog':[{'id':DEFAULT_TEXT_FALLBACK_MODEL,'input_modalities':['text','image'],'output_modalities':['text']}]})
    runtime=RoutedDesignRuntime(SimpleNamespace(run=lambda **_: AgentResult(status='succeeded',structured_data={'answer':'ok'})),catalog,providers,store)
    with pytest.raises(DesignRuntimeError, match='Luna|luna|本地目录'):
        runtime.run(**run_kwargs())


def test_uncertain_provider_failure_does_not_fallback_or_repeat_saved_work(setup):
    store, catalog, providers = setup
    settings = catalog.settings()
    settings.tiers[ModelTier.STANDARD].fallback = EndpointModel(provider='inherit', baseUrl='https://backup.test/v1', model='gpt-5.6-terra')
    catalog.save_settings(settings)
    catalog.save('openrouter', 'https://backup.test/v1', {'models':['gpt-5.6-terra'], 'modelCatalog':[]})
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        if kwargs['provider_ref']['baseUrl'] == CURRENT['baseUrl']:
            raise DesignRuntimeError('HTTP 503', recovery={'toolOutputs':[{'name':'generate_image','output':{'assetId':'existing'}}]})
        return AgentResult(status='succeeded', structured_data={'answer':'ok'})
    runtime = RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store)
    with pytest.raises(DesignRuntimeError, match='HTTP 503'):
        runtime.run(**run_kwargs())
    assert [call['provider_ref']['model'] for call in calls] == [DEFAULT_TEXT_MODEL]
    assert calls[0]['provider_ref']['baseUrl'] == CURRENT['baseUrl']
    assert all(call['agent_key'] == 'design' and call['retrieved_context'] == ['same context'] for call in calls)
    trace = runtime.traces.list('task')[-1]
    assert trace['submitted'] is None and trace['billing_certainty'] == 'unknown'
    assert not trace['fallback']


@pytest.mark.parametrize('reason',['cost','health'])
def test_automatic_route_does_not_switch_models_for_cost_or_health_after_selection(setup,reason):
    from app.provider_health import ProviderHealth
    from app.model_config import ModelPrice
    store,catalog,providers=setup
    settings=catalog.settings()
    settings.tiers[ModelTier.STANDARD].fallback=EndpointModel(provider='inherit',baseUrl='https://backup.test/v1',model='gpt-5.6-terra')
    if reason=='cost':
        settings.taskBudgetPoints=100
        settings.prices[catalog.price_key('openrouter',CURRENT['baseUrl'],DEFAULT_TEXT_MODEL)]=ModelPrice(currency='CNY',perRequest=.5)
        settings.prices[catalog.price_key('openrouter','https://backup.test/v1','gpt-5.6-terra')]=ModelPrice(currency='CNY',perRequest=.1)
    catalog.save_settings(settings)
    catalog.save('openrouter','https://backup.test/v1',{'models':['gpt-5.6-terra']})
    primary=ModelRouter(catalog,providers).endpoint(ModelTier.STANDARD,CURRENT)
    health=ProviderHealth(store)
    if reason=='health':
        for _ in range(3):health.record(primary,False,transient=True)
        assert health.unavailable(primary)
    calls=[]
    def run(**kwargs):
        calls.append(kwargs['provider_ref'])
        return AgentResult(status='succeeded',structured_data={'answer':'ok'})
    runtime=RoutedDesignRuntime(SimpleNamespace(run=run),catalog,providers,store)
    runtime.run(**run_kwargs())
    assert calls[0]['baseUrl']==CURRENT['baseUrl']
    assert calls[0]['model']==DEFAULT_TEXT_MODEL
    runtime.run(**{**run_kwargs(),'task_id':'manual','constraints':{'modelRouting':{'mode':'manual'}}})
    assert calls[-1]['baseUrl']==CURRENT['baseUrl']
    health.record(primary,True)
    assert not health.unavailable(primary)


def test_capability_failure_does_not_upgrade_after_a_paid_run(setup):
    store, catalog, providers = setup
    calls=[]
    def run(**kwargs):
        calls.append(kwargs['provider_ref']['model'])
        if len(calls) == 1:
            raise DesignRuntimeError('Max turns', kind='capability')
        return AgentResult(status='succeeded', structured_data={'answer':'ok'})
    runtime = RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store)
    events=[]
    with pytest.raises(DesignRuntimeError, match='Max turns'):
        runtime.run(**{**run_kwargs(), 'trace':lambda phase,message:events.append((phase,message))})
    assert calls == [DEFAULT_TEXT_MODEL]
    assert not any(item.get('escalated_to') for item in runtime.traces.list('task'))
    assert not any(phase=='escalation' for phase,_ in events)


def test_fast_capability_failure_stays_on_luna(setup):
    store, catalog, providers = setup
    calls = []
    def run(**kwargs):
        calls.append(kwargs['provider_ref']['model'])
        if len(calls) < 3:
            raise DesignRuntimeError('能力不足', kind='capability')
        return AgentResult(status='succeeded', structured_data={'answer':'ok'})
    runtime = RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store)
    with pytest.raises(DesignRuntimeError, match='能力不足'):
        runtime.run(**{
            **run_kwargs(),
            'brief': '把以下字段转换为指定 JSON 结构',
            'constraints': {'modelRouting': {'mode': 'fast'}},
        })
    assert calls == [DEFAULT_FAST_TEXT_MODEL]


def test_capability_failure_does_not_use_configured_backup_after_submission(setup):
    store, catalog, providers = setup
    settings = catalog.settings()
    settings.tiers[ModelTier.STANDARD].fallback = EndpointModel(model='gpt-5.6-terra')
    catalog.save_settings(settings)
    calls = []
    def run(**kwargs):
        calls.append(kwargs['provider_ref']['model'])
        if len(calls) == 1:
            raise DesignRuntimeError('invalid tool arguments', kind='capability')
        return AgentResult(status='succeeded', structured_data={'answer':'ok'})
    runtime = RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store)
    with pytest.raises(DesignRuntimeError, match='invalid tool arguments'):
        runtime.run(**run_kwargs())
    assert calls == [DEFAULT_TEXT_MODEL]
    assert not any(item.get('escalated_to') for item in runtime.traces.list('task'))


def test_manual_never_silently_changes_model_and_cancel_never_retries(setup):
    store,catalog,providers=setup
    count=[]
    def fail(**kwargs):
        count.append(kwargs)
        raise DesignRuntimeError('bad output', kind='capability')
    runtime=RoutedDesignRuntime(SimpleNamespace(run=fail),catalog,providers,store)
    with pytest.raises(DesignRuntimeError):
        runtime.run(**{**run_kwargs(),'constraints':{'modelRouting':{'mode':'manual'}}})
    assert len(count)==1
    with pytest.raises(DesignRuntimeError, match='停止'):
        runtime.run(**{**run_kwargs(),'should_cancel':lambda:True})
    assert len(count)==1


def test_cached_tokens_and_currency_credits(setup):
    store,catalog,_=setup
    settings=catalog.settings()
    key=catalog.price_key('openrouter', CURRENT['baseUrl'], CURRENT['model'])
    from app.model_config import ModelPrice
    settings.prices[key]=ModelPrice(currency='CNY',inputPerMillion=10,outputPerMillion=20,cachedPerMillion=2)
    catalog.save_settings(settings)
    billing=BillingService(store,catalog)
    item=billing.record(provider='openrouter',base_url=CURRENT['baseUrl'],model=CURRENT['model'],kind='text',usage={'input_tokens':1000,'output_tokens':100,'cached_tokens':200},record_id='one',task_id='task')
    assert item['points']==pytest.approx(1.04)
    settings.credits.multiplier=10
    catalog.save_settings(settings)
    billing.record(provider='openrouter',base_url=CURRENT['baseUrl'],model=CURRENT['model'],kind='text',usage={},record_id='one')
    assert billing.summary()['points']==pytest.approx(1.04)
    assert billing.summary()['byTask']['task']['points']==pytest.approx(1.04)


def test_media_pending_prices_and_poll_dedup(setup):
    store,catalog,_=setup
    from app.model_config import ModelPrice
    settings=catalog.settings()
    settings.prices[catalog.price_key('openrouter',CURRENT['baseUrl'],'bytedance/seedance-2.5')]=ModelPrice(currency='CNY',perSecond=.1)
    catalog.save_settings(settings)
    billing=BillingService(store,catalog)
    args=dict(provider='openrouter',base_url=CURRENT['baseUrl'],model='bytedance/seedance-2.5',kind='video',record_id='video:1')
    assert billing.record(**args,completed=False)['status']=='pending'
    assert billing.record(**args,units={'seconds':5})['points']==50
    billing.record(**args,units={'seconds':5})
    assert billing.summary()['points']==50
    assert calculate_cost('text',{'input_tokens':10,'output_tokens':5},{},{'inputPerMillion':1}) is None
    assert float(calculate_cost('image',{}, {'images':2}, {'perImage':.2})) == pytest.approx(.4)
    assert calculate_cost('video',{}, {}, {'perSecond':1}) is None
    assert calculate_cost('3d',{}, {}, {'perRequest':3}) == 3


def test_catalog_survives_restart_and_read_never_contacts_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT',str(tmp_path))
    body={'data':[{'id':'vision-chat','architecture':{'input_modalities':['text','image'],'output_modalities':['text']}},{'id':'gpt-image-2.5-flare','pricing':{'perImage':.1,'currency':'CNY'}}]}
    with TestClient(app) as client, patch('app.main.urllib.request.urlopen', side_effect=lambda request, **_: io.BytesIO(json.dumps({'data': []} if request.full_url.endswith(('/videos/models','/images/models')) else body).encode())) as upstream:
        response=client.post('/api/providers/openai-compatible/detect',json={'provider':'openrouter','baseUrl':CURRENT['baseUrl'],'secret':'test-secret'})
        assert response.status_code==200
        assert response.json()['imageModels']==['gpt-image-2.5-flare']
        assert upstream.call_count==3
    with TestClient(app) as client, patch('app.main.urllib.request.urlopen', side_effect=AssertionError('read contacted upstream')):
        data=client.get('/api/providers/model-catalog',params={'provider':'openrouter','baseUrl':CURRENT['baseUrl']}).json()
        assert data['models']==['gpt-image-2.5-flare','vision-chat']
        assert data['savedAt']
        assert 'test-secret' not in json.dumps(data)
        assert client.get('/api/credits').json()['points']==0


def test_main_task_pipeline_routes_real_sdk_and_records_credits(tmp_path, monkeypatch):
    import os
    import sys
    from pathlib import Path
    from app.assets import AssetStore
    from app.model_config import ModelPrice
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.delenv('AICS_TEST_MODE', raising=False)
    monkeypatch.setenv('AICS_PROVIDER_KEY_OPENROUTER', 'test-only-never-saved')
    monkeypatch.setenv('FIXTURE_API', 'responses')
    monkeypatch.setenv('FIXTURE_EFFORT', 'low')
    monkeypatch.setenv('FIXTURE_PARALLEL_ENABLED', '1')
    root=Path(__file__).resolve().parents[1]
    fixtures=Path(__file__).parent/'fixtures'
    for key,value in {'NODE_OPTIONS':f'--import={(fixtures / "agent_transport.mjs").resolve().as_uri()}', 'PYTHONPATH':str(root), 'FIXTURE_PYTHON':sys.executable,
                      'FIXTURE_TOOL_SCRIPT':str(fixtures/'agent_tool_fixture.py'),'FIXTURE_WORKSPACE':str(tmp_path), 'FIXTURE_ERROR':''}.items():
        monkeypatch.setenv(key,value)
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'name':'路由主流程','brief':'总结设计需求'}).json()
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (16, 16), '#809090').save(image, format='PNG')
        asset=AssetStore(app.state.store).add_bytes(project_id=project['id'],kind='image',filename='ship.png',content=image.getvalue())
        monkeypatch.setenv('FIXTURE_PROJECT',project['id'])
        monkeypatch.setenv('FIXTURE_ASSET',asset['id'])
        catalog=app.state.model_catalog
        ids=([v.primary.model for v in catalog.settings().tiers.values()]
             + [v.fallback.model for v in catalog.settings().tiers.values() if v.fallback])
        catalog.save('openrouter',CURRENT['baseUrl'],{'models':ids,'modelCatalog':[{'id':v} for v in ids]})
        settings=catalog.settings()
        settings.prices[catalog.price_key('openrouter',CURRENT['baseUrl'],DEFAULT_TEXT_MODEL)]=ModelPrice(currency='CNY',inputPerMillion=1,outputPerMillion=2,cachedPerMillion=.5,cacheWritePerMillion=1)
        catalog.save_settings(settings)
        # Production context is rebuilt from this project's stored turns.
        with app.state.store._connect() as db:
            db.execute("INSERT INTO tasks (id, project_id, agent_key, workflow_step, status, input_json, output_json, created_at, updated_at) VALUES (?,?,'design','design','succeeded',?,?,'2026-01-01','2026-01-01')", ('routing-history', project['id'], json.dumps({'userMessage':'之前的设计约束'}), json.dumps({'structured_data':{'answer':'已收到'}})))
        result=app.state.tasks.enqueue(project_id=project['id'],agent_key='design',workflow_step='design',brief='总结设计需求',input_data={
            'textProvider':CURRENT,'modelRouting':{'mode':'auto'},'agentCollaboration':False,'conversation':[{'role':'user','content':'之前的设计约束'},{'role':'user','content':'总结设计需求'}]})
        assert result['status']=='succeeded',result
        assert result['output']['provenance']['model']==DEFAULT_TEXT_MODEL
        assert result['output']['provenance']['executionPolicy']['model_tier']=='STANDARD'
        summary=client.get('/api/credits').json()
        # Responses fixtures report usage for the memory handshake as well as
        # the three design turns: four requests at 0.0025 points each.
        assert summary['points']==pytest.approx(.01)
        assert summary['byTask'][result['id']]['points']==pytest.approx(.01)
        trace=client.get(f'/api/tasks/{result["id"]}/model-trace').json()
        assert any(item.get('phase')=='sdk' for item in trace)
        assert trace[-1]['status']=='succeeded'
        assert 'test-only-never-saved' not in json.dumps(trace)+json.dumps(summary)+json.dumps(result)


def test_gateway_input_image_price_is_not_output_image_price(setup):
    _,catalog,_=setup
    price=catalog.normalize_price({'pricing':{'image':'0.02','prompt':'0.000001','completion':'0.000002'}})
    assert price['perInputImage']==.02
    assert 'perImage' not in price
    assert calculate_cost('image',{}, {'images':1}, price) is None
    assert float(calculate_cost('text',{'input_tokens':10,'output_tokens':5},{'inputImages':2},price))==pytest.approx(.04002)


def test_missing_primary_reports_configuration_instead_of_switching_models(setup):
    store,catalog,providers=setup
    settings=catalog.settings()
    settings.tiers[ModelTier.STANDARD].primary.model='not-in-catalog'
    settings.tiers[ModelTier.STANDARD].fallback = EndpointModel(model=DEFAULT_TEXT_FALLBACK_MODEL)
    catalog.save_settings(settings)
    calls = []
    def run(**kwargs):
        calls.append(kwargs['provider_ref']['model'])
        return AgentResult(status='succeeded', structured_data={'answer':'ok'})
    with pytest.raises(DesignRuntimeError, match='not-in-catalog'):
        RoutedDesignRuntime(SimpleNamespace(run=run),catalog,providers,store).run(**run_kwargs())
    assert calls == []


def test_unknown_price_and_empty_usage_are_never_free():
    assert calculate_cost('text', {'input_tokens':0,'output_tokens':0}, {}, {}) is None


@pytest.mark.parametrize('brief', ['你好', '您好！', 'Hi!', '谢谢你', '在吗？', '你是谁？'])
def test_simple_conversation_uses_fast_model_without_tools_or_review(setup, brief):
    store, catalog, providers = setup
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return AgentResult(status='succeeded', structured_data={'answer':'你好！'})
    RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store).run(**{**run_kwargs(), 'brief':brief})
    assert len(calls) == 1
    call = calls[0]
    assert call['provider_ref']['model'] == DEFAULT_FAST_TEXT_MODEL
    assert call['execution_policy']['max_turns'] == 60
    assert 'timeout' not in call['execution_policy']
    assert call['constraints']['simpleConversation']
    assert call['constraints']['executionFlow'] == 'direct'
    assert call['constraints']['deliveryVerification'] is False


@pytest.mark.parametrize('constraints', [
    {'referencedAssets':[{'assetId':'image'}]}, {'referencedFiles':[{'filename':'brief.pdf'}]},
    {'referencedNodes':[{'id':'node'}]}, {'canvasParams':{'kind':'text'}},
])
def test_greeting_with_referenced_work_retains_tools(setup, constraints):
    _, catalog, providers = setup
    assert ModelRouter(catalog, providers).route('你好', CURRENT, constraints).task_type != 'conversation'
    assert ModelRouter(catalog, providers).route('你好，请生成一张海报', CURRENT).task_type == 'media:image'


@pytest.mark.parametrize('message,status,submitted,attempts', [
    ('参数不兼容',400,False,1), ('认证失败',401,False,1), ('模型不可用',404,False,1),
    ('临时服务异常',503,False,3), ('触发限流',429,False,3),
    ('Connection timed out',None,None,1), ('Unrecognized provider response',None,None,1),
])
def test_provider_errors_never_escalate_and_only_confirmed_pre_submit_failures_retry(setup, message, status, submitted, attempts):
    store, catalog, providers = setup
    settings = catalog.settings()
    settings.tiers[ModelTier.STANDARD].fallback = EndpointModel(model='gpt-5.6-terra')
    catalog.save_settings(settings)
    calls, events = [], []
    def fail(**kwargs):
        calls.append(kwargs)
        raise DesignRuntimeError(message, status_code=status, submitted=submitted)
    runtime = RoutedDesignRuntime(SimpleNamespace(run=fail), catalog, providers, store)
    with pytest.raises(DesignRuntimeError, match=message):
        runtime.run(**{**run_kwargs(), 'trace':lambda *event:events.append(event)})
    assert len(calls) == attempts
    assert {call['provider_ref']['model'] for call in calls} == {DEFAULT_TEXT_MODEL}
    assert len([event for event in events if event[0]=='route_failed']) == attempts
    assert len([event for event in events if event[0]=='retry']) == attempts - 1
    assert not any(event[0]=='escalation' for event in events)
    assert all(item['error_message']==message for item in runtime.traces.list('task'))


def test_local_runtime_failure_does_not_retry_or_blame_model(setup):
    store,catalog,providers=setup
    calls,events=[],[]
    def fail(**kwargs):
        calls.append(kwargs)
        raise DesignRuntimeError('Agent 本地运行时启动失败',kind='runtime')
    with pytest.raises(DesignRuntimeError):
        RoutedDesignRuntime(SimpleNamespace(run=fail),catalog,providers,store).run(**{**run_kwargs(),'trace':lambda *event:events.append(event)})
    assert len(calls)==1
    assert any(phase=='route_failed' and message.startswith('本地执行环境异常') for phase,message in events)
    assert not any(phase in {'retry','escalation'} for phase,_ in events)


def test_memory_validation_failure_keeps_original_model_and_receipts(setup):
    store,catalog,providers=setup
    calls,events=[],[]
    def fail(**kwargs):
        calls.append(kwargs)
        raise DesignRuntimeError('对话信息保存校验未通过，已停止重复提交。',kind='tool',recovery={'toolOutputs':[{'name':'conversation_memory_update','output':{'status':'memory_invalid'}}]})
    with pytest.raises(DesignRuntimeError) as raised:
        RoutedDesignRuntime(SimpleNamespace(run=fail),catalog,providers,store).run(**{**run_kwargs(),'trace':lambda *event:events.append(event)})
    assert len(calls)==1 and raised.value.recovery['toolOutputs']
    assert not any(phase in {'retry','escalation'} for phase,_ in events)


def test_simple_conversation_cannot_escalate_on_bad_output(setup):
    store, catalog, providers = setup
    calls=[]
    def fail(**kwargs):
        calls.append(kwargs['provider_ref']['model'])
        raise DesignRuntimeError('空回复', kind='capability')
    with pytest.raises(DesignRuntimeError, match='空回复'):
        RoutedDesignRuntime(SimpleNamespace(run=fail), catalog, providers, store).run(**{**run_kwargs(),'brief':'你好'})
    assert calls == [DEFAULT_FAST_TEXT_MODEL]


def test_manual_greeting_respects_explicit_model_but_keeps_direct_flow(setup):
    store, catalog, providers = setup
    calls=[]
    def run(**kwargs):
        calls.append(kwargs)
        return AgentResult(status='succeeded', structured_data={'answer':'你好'})
    RoutedDesignRuntime(SimpleNamespace(run=run), catalog, providers, store).run(**{
        **run_kwargs(), 'brief':'你好', 'constraints':{'modelRouting':{'mode':'manual'}},
        'provider_ref':{**CURRENT,'model':'gpt-6-astra'},
    })
    assert calls[0]['provider_ref']['model']=='gpt-6-astra'
    assert calls[0]['constraints']['simpleConversation']


def test_missing_fast_and_fallback_models_do_not_fall_through_to_premium(setup):
    store, catalog, providers = setup
    catalog.save('openrouter', CURRENT['baseUrl'], {'models':['gpt-6-astra'], 'modelCatalog':[]})
    runtime = RoutedDesignRuntime(SimpleNamespace(run=lambda **_:pytest.fail('wrong model')), catalog, providers, store)
    with pytest.raises(DesignRuntimeError, match='gpt-6-luna'):
        runtime.run(**{**run_kwargs(),'brief':'你好'})


@pytest.mark.parametrize('kind',['tool','execution_timeout'])
def test_search_or_overall_deadline_never_retries_another_text_model(setup,kind):
    store,catalog,providers=setup
    calls,events=[],[]
    def fail(**kwargs):
        calls.append(kwargs)
        raise DesignRuntimeError('本轮搜索等待达到总时限',kind=kind)
    with pytest.raises(DesignRuntimeError):
        RoutedDesignRuntime(SimpleNamespace(run=fail),catalog,providers,store).run(**{**run_kwargs(),'trace':lambda *event:events.append(event)})
    assert len(calls)==1
    assert not any(phase in {'retry','escalation'} or '调用失败' in text for phase,text in events)
    assert any('任务执行中断' in text for phase,text in events)
