import pytest

from app.billing import calculate_cost
from app.credit_reporting import price_catalog
from app.evolink_prices import default_evolink_price, public_catalog
from app.model_catalog import ModelCatalog
from app.model_config import ModelPrice
from app.storage import ProjectStore


def test_public_snapshot_units_cache_and_long_context():
    price = default_evolink_price('gpt-6-luna')
    assert price['inputPerMillion'] == pytest.approx(.0062 / 68 * 1000)
    assert price['outputPerMillion'] == pytest.approx(.45)
    assert price['cachedPerMillion'] == pytest.approx(.0006 / 68 * 1000)
    assert any('272,000' in rate['label'] for rate in price['publicRates'])
    assert calculate_cost('text', {'input_tokens': 1_000_000}, {}, price) is None
    assert default_evolink_price('other/gpt-6-luna') == {}
    assert default_evolink_price('not-a-model') == {}


def test_image_video_audio_keep_different_billing_units():
    image = default_evolink_price('gpt-image-2.5-sunburst')
    output = next(r for r in image['publicRates'] if r['label'] == 'Image output')
    assert output['usd'] == 27
    assert 'perImage' not in image
    video = default_evolink_price('seedance-2.5-reference-to-video')
    assert video['publicRates'][0]['unit'] == '/input + output sec'
    assert video['publicRates'][0]['usd'] == .084
    assert default_evolink_price('seedance-2.5-text-to-video') == {}
    audio = default_evolink_price('suno-v6-beta')
    assert audio['publicRates'][0]['unit'] == '2 tracks'
    assert audio['publicRates'][0]['usd'] == pytest.approx(8 / 68)


def test_catalog_scope_precedence_and_no_model_availability_changes(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    base = 'https://api.evolink.ai/v1'
    catalog.save('evolink', base, {'models': ['gpt-6-luna']})
    assert catalog.price('evolink', base, 'gpt-6-luna')['source'] == 'evolink_public'
    assert catalog.price('openai-compatible', 'https://example.test/v1', 'gpt-6-luna').get('source') != 'evolink_public'
    quotes = price_catalog(catalog)
    assert len([q for q in quotes if q['model'] == 'gpt-6-luna']) == 1
    assert len(public_catalog()) == 135
    assert catalog.view('evolink', base)['models'] == ['gpt-6-luna']
    settings = catalog.settings()
    settings.prices[catalog.price_key('evolink', base, 'gpt-6-luna')] = ModelPrice(currency='CNY', inputPerMillion=2)
    catalog.save_settings(settings)
    assert catalog.price('evolink', base, 'gpt-6-luna')['source'] == 'manual'
    catalog.save('evolink', base, {'models': ['other'], 'modelCatalog': [{'id': 'other', 'pricing': {'currency': 'CNY', 'perImage': 0}}]})
    assert catalog.price('evolink', base, 'other')['source'] == 'gateway'
