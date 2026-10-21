from decimal import Decimal

import pytest

from app.billing import BillingService, calculate_cost
from app.model_catalog import ModelCatalog
from app.model_config import ModelPrice
from app.closeai_catalog import _normalized_price
from app.storage import ProjectStore
from app.token_usage import cache_trace
from test_delivery_contract import workspace, task


PRICE = {'currency':'CNY', 'inputPerMillion':10, 'outputPerMillion':20,
         'cachedPerMillion':2, 'cacheWritePerMillion':12.5}


@pytest.mark.parametrize('field', ['input_tokens_details', 'prompt_tokens_details'])
def test_cache_write_replaces_ordinary_input_cost_and_read_is_not_charged_twice(field):
    usage = {'input_tokens':1000, 'output_tokens':50, field:{'cached_tokens':200, 'cache_write_tokens':600}}
    assert calculate_cost('text',usage,{},PRICE) == Decimal('0.0109')
    assert cache_trace(usage) == {'cacheReported':True, 'cacheWriteReported':True, 'cachedTokens':200, 'cacheWriteTokens':600}


def test_missing_write_price_stays_pending_and_actual_cost_has_priority():
    price = {key:value for key,value in PRICE.items() if key != 'cacheWritePerMillion'}
    usage = {'prompt_tokens':1000,'completion_tokens':0,'prompt_tokens_details':{'cache_write_tokens':1000}}
    assert calculate_cost('text',usage,{},price) is None
    assert calculate_cost('text',usage,{},price,reported='.7') == Decimal('.7')
    usage['prompt_tokens_details']['cache_write_tokens'] = 0
    assert calculate_cost('text',usage,{},price) == Decimal('.01')


@pytest.mark.parametrize('cached,written', [(800,300),(-1,10),(10,'invalid'),(10,float('nan'))])
def test_inconsistent_cache_usage_never_invents_a_cost(cached,written):
    usage={'input_tokens':1000,'output_tokens':0,'input_tokens_details':{'cached_tokens':cached,'cache_write_tokens':written}}
    assert calculate_cost('text',usage,{},PRICE) is None
    assert cache_trace(usage)['cacheWriteReported'] is False


def test_gateway_catalogs_keep_their_own_write_price_instead_of_assuming_openai_multiplier():
    assert ModelCatalog.normalize_price({'pricing':{'prompt':'.00001','input_cache_write':'.00003'}})['cacheWritePerMillion'] == 30
    assert _normalized_price({'text_input_price':10,'cache_write_price':17})['cacheWritePerMillion'] == 17
    assert 'cacheWritePerMillion' not in _normalized_price({'text_input_price':10})
    assert 'cacheWritePerMillion' in ModelPrice.model_fields


def test_ledger_preserves_write_usage_and_replay_never_reprices_settled_records(tmp_path):
    store=ProjectStore(str(tmp_path)); catalog=ModelCatalog(store)
    endpoint='https://relay.test/v1'
    key=catalog.price_key('openrouter',endpoint,'cache-model')
    settings=catalog.settings(); settings.prices[key]=ModelPrice(**PRICE); catalog.save_settings(settings)
    billing=BillingService(store,catalog)
    usage={'prompt_tokens':1000,'completion_tokens':50,'prompt_tokens_details':{'cached_tokens':200,'cache_write_tokens':600}}
    first=billing.record(provider='openrouter',base_url=endpoint,model='cache-model',kind='text',usage=usage,record_id='response-one')
    assert first['status'] == 'settled'
    assert first['usage']['prompt_tokens_details']['cache_write_tokens'] == 600
    assert first['usage']['cache_write_tokens'] == 600
    settings.prices[key]=ModelPrice(**{**PRICE,'cacheWritePerMillion':100}); catalog.save_settings(settings)
    second=billing.record(provider='openrouter',base_url=endpoint,model='cache-model',kind='text',usage=usage,record_id='response-one')
    assert second == first
    with billing._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM credit_ledger').fetchone()[0] == 1
    invalid=billing.record(provider='openrouter',base_url=endpoint,model='cache-model',kind='text',
        usage={'input_tokens':100,'output_tokens':0,'cache_write_tokens':-1},record_id='invalid')
    assert invalid['status'] == 'pending'


def test_missing_cache_counters_differ_from_confirmed_zero():
    assert cache_trace({'prompt_tokens':10})['cacheReported'] is False
    assert cache_trace({'prompt_tokens':10,'prompt_tokens_details':{'cached_tokens':0}})['cacheReported'] is True
    sdk={'inputTokens':1000,'outputTokens':50,'inputTokensDetails':[{'cached_tokens':100,'cache_write_tokens':300},{'cached_tokens':100,'cache_write_tokens':300}]}
    assert calculate_cost('text',sdk,{},PRICE) == Decimal('0.0109')


def test_budget_reserves_known_write_tariff_without_assuming_cache_hits(workspace):
    from app.budget import BudgetService
    store,project,*_=workspace
    task(store,project)
    catalog=ModelCatalog(store)
    settings=catalog.settings()
    settings.prices[catalog.price_key('closeai','https://relay.test/v1','cache-model')]=ModelPrice(**PRICE)
    catalog.save_settings(settings)
    result=BudgetService(store,catalog).reserve('task',provider='closeai',base_url='https://relay.test/v1',model='cache-model',kind='text',
        usage={'input_tokens':1000,'output_tokens':50},require_price=True)
    expected=Decimal('.0135')*Decimal(str(settings.credits.pointsPerCny))*Decimal(str(settings.credits.multiplier))
    assert result['estimatedPoints'] == float(expected)
