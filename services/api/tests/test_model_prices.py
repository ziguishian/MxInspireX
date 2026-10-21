from decimal import Decimal
from unittest.mock import patch

import pytest

from app.billing import BillingService, calculate_cost
from app.default_price_data import IMAGE_RATES, PAGE_PRICES, VIDEO_SKUS
from app.model_catalog import ModelCatalog
from app.model_config import ModelPrice
from app.model_prices import default_price, video_price
from app.storage import ProjectStore

BASE = 'https://openrouter.ai/api/v1'


@pytest.fixture
def catalog(tmp_path):
    return ModelCatalog(ProjectStore(str(tmp_path)))


def test_existing_catalog_gets_offline_prices_without_adding_models(catalog):
    ids = sorted(IMAGE_RATES.keys() | PAGE_PRICES.keys() | VIDEO_SKUS.keys())
    assert len(ids) == 72
    catalog.save('openrouter', BASE, {'models': ids + ['unknown-model']})
    with patch('urllib.request.urlopen', side_effect=AssertionError('must remain offline')):
        view = catalog.view('openrouter', BASE)
    assert view['models'] == sorted(ids + ['unknown-model'])
    prices = {item['id']: item['price'] for item in view['modelCatalog']}
    assert prices.pop('unknown-model') == {}
    assert all(price['source'] == 'default' and price['checkedAt'] == '2026-09-16' for price in prices.values())
    assert all(price['sourceUrl'].startswith('https://openrouter.ai/') for price in prices.values())
    assert catalog.get('openrouter', BASE)['modelCatalog'][0].get('pricing') is None


def test_price_precedence_manual_then_gateway_then_default(catalog):
    model = 'bytedance-seed/seedream-4.5'
    catalog.save('openrouter', BASE, {'models': [model]})
    assert catalog.price('openrouter', BASE, model)['perImage'] == .04
    catalog.save('openrouter', BASE, {'models': [model], 'modelCatalog': [
        {'id': model, 'pricing': {'currency': 'CNY', 'perImage': 0}},
    ]})
    gateway = catalog.price('openrouter', BASE, model)
    assert gateway == {'currency': 'CNY', 'perImage': 0, 'source': 'gateway'}
    settings = catalog.settings()
    settings.prices[catalog.price_key('openrouter', BASE, model)] = ModelPrice(currency='CNY', perImage=.25)
    catalog.save_settings(settings)
    assert catalog.price('openrouter', BASE, model) == {'currency': 'CNY', 'perImage': .25, 'source': 'manual'}
    assert catalog.view('openrouter', BASE)['modelCatalog'][0]['price'] == catalog.price('openrouter', BASE, model)


def test_public_prices_do_not_become_another_relays_tariff(catalog):
    price = catalog.price('openai-compatible', 'https://relay.test/v1', 'gpt-image-2.5-sunburst')
    assert price['referenceOnly'] is True
    assert calculate_cost('image', {'input_tokens': 10, 'output_tokens': 100}, {}, price) is None
    assert calculate_cost('image', {}, {}, price, reported=.25) == Decimal('.25')


@pytest.mark.parametrize('model', ['custom/gpt-image-2.5-sunburst', 'gpt-image-2.5-sunburst:free', 'gpt-image-99'])
def test_unknown_namespace_or_variant_never_inherits_a_price(model):
    assert default_price(model) == {}


def test_image_token_price_is_not_a_per_image_fee():
    price = default_price('openai/gpt-image-2.5-sunburst')
    assert price['inputPerMillion'] == 5
    assert price['imageInputPerMillion'] == 8
    assert price['imageOutputPerMillion'] == 30
    usage = {'input_tokens': 100, 'output_tokens': 1000, 'input_tokens_details': {'image_tokens': 80}}
    assert calculate_cost('image', usage, {}, price) == Decimal('.03074')
    assert calculate_cost('image', {}, {'images': 1}, price) is None


def test_fixed_image_price_counts_images_even_when_response_has_usage():
    price = default_price('bytedance-seed/seedream-4.5')
    assert calculate_cost('image', {'input_tokens': 99}, {'images': 2}, price) == Decimal('.08')


def test_conditional_image_prices_keep_the_floor_and_do_not_settle_as_flat():
    price = default_price('qwen/qwen-image-3-pro')
    assert price['perImage'] == .04
    assert price['perInputImage'] == .003
    assert price['referenceOnly']
    assert len(price['priceDetails']) == 3
    assert calculate_cost('image', {}, {'images': 1, 'inputImages': 1}, price) is None
    assert calculate_cost('image', {}, {}, price, reported=.078) == Decimal('.078')


def test_existing_video_skus_are_used_and_cents_are_converted():
    assert ModelCatalog.normalize_price({'pricing_skus': {'cents_per_second_output': '12'}})['perSecond'] == .12
    price = ModelCatalog.normalize_price({'pricing_skus': {'duration_seconds': '.13', 'reference_images': '.04'}})
    assert price['source'] == 'gateway'
    assert calculate_cost('video', {}, {'seconds': 5, 'inputImages': 2}, price) == Decimal('.73')
    assert calculate_cost('video', {}, {'seconds': 5}, price) is None
    assert video_price({'cents_per_second_output': '-1'}) == {}
    assert video_price({'cents_per_second_output': 'NaN'}) == {}


def test_video_tokens_megapixels_and_minimum_charges_are_not_seconds():
    seedance = default_price('bytedance/seedance-2.5')
    assert seedance['videoOutputPerMillion'] == 6.4
    assert 'perSecond' not in seedance
    assert seedance['referenceOnly']
    upscale = default_price('black-forest-labs/flux-video-upscale')
    assert upscale['perMegapixelSecond'] == .075
    assert 'perSecond' not in upscale
    aleph = default_price('runway/aleph-2')
    assert aleph['perSecond'] == .28 and aleph['referenceOnly']
    for price in (seedance, upscale, aleph):
        assert calculate_cost('video', {}, {'seconds': 5}, price) is None


def test_search_fee_is_not_dropped_from_gateway_pricing():
    price = ModelCatalog.normalize_price({'pricing': {'prompt': '.000001', 'completion': '.000002', 'web_search': '.01'}})
    assert price['perSearch'] == .01
    assert calculate_cost('search', {'input_tokens': 100, 'output_tokens': 20}, {'searchCalls': 2}, price) == Decimal('.02014')


def test_new_default_does_not_reprice_an_existing_ledger(catalog):
    billing = BillingService(catalog.store, catalog)
    args = dict(provider='openrouter', base_url=BASE, model='bytedance-seed/seedream-4.5', kind='image', units={'images': 1}, usage={}, record_id='once')
    original = billing.record(**args)
    assert original['status'] == 'settled'
    settings = catalog.settings()
    settings.prices[catalog.price_key('openrouter', BASE, args['model'])] = ModelPrice(perImage=10)
    catalog.save_settings(settings)
    assert billing.record(**args) == original
    assert billing.summary()['points'] == pytest.approx(28.8)


def test_unknown_price_stays_unknown(catalog):
    assert catalog.price('openrouter', BASE, 'unknown-model') == {}
    assert calculate_cost('image', {}, {'images': 1}, {}) is None


def test_router_sentinel_is_dynamic_not_free():
    price = ModelCatalog.normalize_price({'id': 'openrouter/auto', 'pricing': {'prompt': '-1', 'completion': '-1'}})
    assert price['pricingMode'] == 'dynamic'
    assert calculate_cost('text', {'input_tokens': 100, 'output_tokens': 100}, {}, price) is None
    assert calculate_cost('text', {}, {}, price, reported=.12) == Decimal('.12')
    assert ModelCatalog.normalize_price({'id': 'unknown-model', 'pricing': {'prompt': '-1', 'completion': '-1'}}) == {}
