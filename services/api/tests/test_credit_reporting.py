from app.billing import BillingService
from app.model_catalog import ModelCatalog
from app.model_config import ModelPrice
from app.storage import ProjectStore
import pytest


def test_usage_estimates_are_separate_and_reading_never_reprices_or_double_counts(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    billing = BillingService(catalog.store, catalog)
    kwargs = dict(provider='openai-compatible', base_url='https://relay.test/v1', model='gpt-image-2.5-flare', kind='image', usage={'input_tokens':1000,'output_tokens':1000}, units={'images':1}, record_id='image-1')
    billing.record(**kwargs)
    billing.record(provider='openai-compatible', base_url='https://relay.test/v1', model='unknown', kind='text', usage={'input_tokens':120,'output_tokens':30}, record_id='text-1')
    before = billing.summary()
    assert before['points'] == 0 and before['estimatedPoints'] > 0 and before['unpriced'] == 1
    assert before['pending'] == 2
    assert next(item for item in before['byKind'] if item['kind'] == 'text')['inputTokens'] == 120
    with billing._connect() as db: original = db.execute('SELECT data_json FROM credit_ledger ORDER BY id').fetchall()
    billing.record(**kwargs)
    after = billing.summary()
    assert after['estimatedPoints'] == before['estimatedPoints']
    assert after['pending'] == 2
    with billing._connect() as db: assert [r[0] for r in original] == [r[0] for r in db.execute('SELECT data_json FROM credit_ledger ORDER BY id')]


def test_actual_cost_replaces_estimate_and_completed_false_has_no_estimate(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path))); billing = BillingService(catalog.store, catalog)
    args = dict(provider='openai-compatible', base_url='https://relay.test/v1', model='gpt-image-2.5-flare', kind='image', record_id='one')
    billing.record(**args, usage={'input_tokens':1000,'output_tokens':1000}, completed=False)
    assert billing.summary()['estimatedPoints'] == 0
    billing.record(**args, usage={'cost':.75,'cost_currency':'CNY'})
    result = billing.summary()
    assert result['points'] == 75 and result['pending'] == 0 and result['estimatedPoints'] == 0
    billing.record(**args, usage={'cost':100,'cost_currency':'CNY'})
    assert billing.summary()['points'] == 75


def test_manual_tariff_charges_new_usage_without_repricing_old_unknown_records(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path))); billing = BillingService(catalog.store, catalog)
    args = dict(provider='fixture', base_url='https://relay.test/v1', model='text', kind='text', usage={'input_tokens':1000,'output_tokens':1000})
    billing.record(**args, record_id='before')
    settings = catalog.settings(); settings.prices[catalog.price_key('fixture','https://relay.test/v1','text')] = ModelPrice(currency='CNY', inputPerMillion=10, outputPerMillion=20)
    catalog.save_settings(settings)
    billing.record(**args, record_id='after')
    summary = billing.summary()
    assert summary['points'] == 3 and summary['unpriced'] == 1


def test_conditional_tariff_cannot_be_estimated_as_a_flat_cost():
    from app.credit_reporting import estimated_points
    assert estimated_points({'status':'pending','kind':'video','price':{'perSecond':1,'currency':'USD','source':'gateway','referenceOnly':True},'units':{'seconds':8}}) is None


def test_tokens_and_rmb_are_independent_of_legacy_conversion_and_cache_subsets(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path))); billing = BillingService(catalog.store, catalog)
    settings = catalog.settings(); settings.credits.pointsPerCny = 999; settings.credits.multiplier = 3
    settings.credits.usdToCny = 7
    catalog.save_settings(settings)
    args = dict(provider='fixture', base_url='https://relay.test/v1', model='unknown', kind='text', task_id='task-a')
    billing.record(**args, record_id='one', usage={'input_tokens':1000,'output_tokens':200,'total_tokens':1200,'cached_tokens':500,'cache_write_tokens':100,'cost':.2,'cost_currency':'USD'})
    billing.record(**args, record_id='two', usage={'prompt_tokens':40,'completion_tokens':10})
    settings.credits.usdToCny = 9; settings.credits.pointsPerCny = 2
    catalog.save_settings(settings)
    result = billing.summary()
    assert result['totalTokens'] == 1250
    assert result['inputTokens'] == 1040 and result['outputTokens'] == 210
    assert result['costCny'] == pytest.approx(1.4) and result['estimatedCostCny'] == 0
    assert result['pricedRequests'] == 1 and result['unpriced'] == 1
    assert result['tokenUnreported'] == 0 and result['tokenByTask'] == {'task-a':1250}
    assert sum(result['tokenByDay'].values()) == 1250
    assert next(v for v in result['byKind'] if v['kind']=='text')['totalTokens'] == 1250


def test_media_cost_does_not_invent_tokens_and_zero_cost_is_known(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path))); billing = BillingService(catalog.store, catalog)
    assert billing.summary()['requests'] == 0
    args = dict(provider='fixture', base_url='https://relay.test/v1', model='unknown', kind='image')
    billing.record(**args, record_id='free', usage={'cost':0,'cost_currency':'CNY'}, units={'images':1})
    billing.record(**args, record_id='unknown', completed=False)
    result = billing.summary()
    assert result['totalTokens'] == 0 and result['tokenUnreported'] == 2
    assert result['costCny'] == 0 and result['pricedRequests'] == 1 and result['unpriced'] == 1


def test_estimate_uses_recorded_fx_but_never_point_conversion(tmp_path):
    from app.credit_reporting import estimated_cost_cny, observed_tokens
    item = {'status':'pending','kind':'text','price':{'inputPerMillion':1,'outputPerMillion':2,'currency':'USD'},'usage':{'input_tokens':1000000,'output_tokens':1000000},'rules':{'usdToCny':7}}
    assert estimated_cost_cny(item) == 21
    assert observed_tokens({'total_tokens':120,'input_tokens_details':{'cached_tokens':80}}) == (0,0,120,False)
    assert observed_tokens({'input_tokens':120}) == (120,0,120,True)
    assert observed_tokens({'input_tokens':120}, 'embedding') == (120,0,120,False)


@pytest.mark.parametrize('kind', ['audio', 'video'])
def test_media_token_prices_require_the_actual_modality_split(tmp_path, kind):
    catalog = ModelCatalog(ProjectStore(str(tmp_path))); billing = BillingService(catalog.store, catalog)
    price = {'currency':'CNY','inputPerMillion':10,'outputPerMillion':20,f'{kind}InputPerMillion':100,f'{kind}OutputPerMillion':200}
    settings = catalog.settings(); settings.prices[catalog.price_key('fixture','https://relay.test/v1','media')] = ModelPrice(**price)
    catalog.save_settings(settings)
    args = dict(provider='fixture',base_url='https://relay.test/v1',model='media',kind=kind)
    usage = {'input_tokens':1000,'output_tokens':1000,'input_tokens_details':{f'{kind}_tokens':600},'output_tokens_details':{f'{kind}_tokens':800}}
    billing.record(**args, usage=usage, record_id='known')
    assert billing.summary()['points'] == pytest.approx(22.8)
    billing.record(**args, usage={'input_tokens':1000,'output_tokens':1000}, record_id='unknown')
    assert billing.summary()['points'] == pytest.approx(22.8)
    assert billing.summary()['unpriced'] == 1


def test_price_endpoint_updates_one_quote_and_rejects_unknown_or_invalid_fields(tmp_path, monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    catalog.save('openai-compatible', 'https://relay.test/v1', {'models':['model-a','model-b']})
    settings = catalog.settings()
    original = settings.model_dump()
    monkeypatch.setattr(app.state, 'model_catalog', catalog, raising=False)
    client = TestClient(app)
    payload = {'provider':'openai-compatible','baseUrl':'https://relay.test/v1','model':'model-a','price':{'currency':'CNY','inputPerMillion':10,'outputPerMillion':20}}
    response = client.put('/api/credits/prices', json=payload)
    assert response.status_code == 200
    assert response.json()['price']['source'] == 'manual'
    saved = catalog.settings().model_dump()
    assert {k:v for k,v in saved.items() if k != 'prices'} == {k:v for k,v in original.items() if k != 'prices'}
    assert len(saved['prices']) == 1
    assert client.get('/api/credits/prices').status_code == 200
    assert client.put('/api/credits/prices', json={**payload,'price':{'currency':'CNY'}}).status_code == 422
    assert client.put('/api/credits/prices', json={**payload,'price':{'perImage':-1}}).status_code == 422
    assert client.put('/api/credits/prices', json={**payload,'price':{'perImage':1,'unexpectedFee':2}}).status_code == 422
