import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from app.billing import BillingService, MeteredProvider, billing_scope
from app.evolink_billing import EvoLinkBillingClient, EvoLinkReconciler, normalize_usage
from app.model_catalog import ModelCatalog
from app.model_config import ModelPrice
from app.providers.http import ProviderError
from app.providers.registry import ProviderRegistry
from app.storage import ProjectStore

BASE = 'https://api.evolink.ai/v1'


class Credentials:
    def get(self, provider):
        return 'test-secret' if provider == 'evolink' else None


def response(body):
    return io.BytesIO(json.dumps(body).encode())


@pytest.fixture
def billing(tmp_path):
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    settings = catalog.settings()
    settings.prices[catalog.price_key('evolink', BASE, 'image-model')] = ModelPrice(currency='CNY', perImage=99)
    settings.credits.usdToCny = 7
    catalog.save_settings(settings)
    return BillingService(catalog.store, catalog)


def record(billing, **overrides):
    return billing.record(**dict(dict(provider='evolink', base_url=BASE, model='image-model', kind='image',
        record_id='local-1', provider_task_id='task-1', project_id='project-1', task_id='design-1',
        usage={'input_tokens':120, 'output_tokens':30}, units={'images':1}), **overrides))


def items(billing):
    with billing._connect() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT data_json FROM credit_ledger')]


@pytest.mark.parametrize('cost,expected', [
    ({'cny':1, 'usd':.148}, {'cost':1.,'cost_currency':'CNY'}),
    ({'cny':0, 'usd':.148}, {'cost':0.,'cost_currency':'CNY'}),
    ({'cny':-1, 'usd':.5}, {'cost':.5,'cost_currency':'USD'}),
    ({'credits':10}, {}), ({'cny':True}, {}), ({'cny':'NaN'}, {}), (1, {}),
])
def test_receipt_currency_is_explicit_and_cny_preferred(cost, expected):
    assert normalize_usage({'cost':cost}) == expected
    assert normalize_usage({'cost':cost}, completed=False) == {}


def test_tariff_and_reserved_credits_never_settle_evolink(billing):
    saved = record(billing, usage={'input_tokens':120,'output_tokens':30,'credits_reserved':99,'credits_used':99})
    assert saved['status'] == 'pending' and saved['costCny'] is None
    summary = billing.summary()
    assert summary['totalTokens'] == 150
    assert summary['reportedRequests'] == 0 and summary['awaitingReconciliation'] == 1
    assert summary['costCny'] == summary['estimatedCostCny'] == 0


def test_query_get_only_and_account_usage_is_never_request_cost():
    client = EvoLinkBillingClient(Credentials())
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.side_effect = [response({'id':'task-1','model':'image-model','status':'completed','usage':{'cost':{'cny':1}}}),
            response({'success':True,'data':{'user':{'used_credits':100,'remaining_credits':200},'token':{'used_credits':10}}})]
        assert client.query('task-1')['usage'] == {'cost':1,'cost_currency':'CNY'}
        account = client.query()
    requests = [call.args[0] for call in opener.return_value.open.call_args_list]
    assert [(r.get_method(), r.full_url) for r in requests] == [('GET', BASE+'/tasks/task-1'), ('GET', BASE+'/credits')]
    assert all(r.get_header('Authorization') == 'Bearer test-secret' for r in requests)
    assert account['scope'] == 'account' and account['attributableToRequest'] is False
    assert account['data']['token']['used_credits'] == 10 and 'cost' not in account
    assert 'test-secret' not in json.dumps(account)
    with patch('urllib.request.build_opener') as opener:
        with pytest.raises(ProviderError): client.query('../credits')
        with pytest.raises(ProviderError): EvoLinkBillingClient(Credentials(), base_url='https://untrusted.test/v1')
        opener.assert_not_called()


def test_reconciliation_updates_same_record_preserves_tokens_scope_and_fx(billing):
    original = record(billing, completed=False)
    settings = billing.catalog.settings(); settings.credits.usdToCny = 9; billing.catalog.save_settings(settings)
    reconciler = EvoLinkReconciler(billing, Credentials())
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.return_value = response({'id':'task-1','status':'completed','model':'image-model','usage':{'cost':{'usd':.5}}})
        result = reconciler.reconcile()
        assert result['checked'] == result['confirmed'] == 1 and result['pending'] == 0
        assert reconciler.reconcile()['checked'] == 0
        assert opener.return_value.open.call_count == 1
    saved = items(billing)
    assert len(saved) == 1 and saved[0]['id'] == original['id'] and saved[0]['date'] == original['date']
    assert saved[0]['costCny'] == 3.5 and saved[0]['reconciliation']['status'] == 'confirmed'
    assert billing.summary()['tokenByTask'] == {'design-1':150}
    assert billing.summary(project_id='project-1')['costCny'] == 3.5
    # A late processing poll cannot erase a confirmed receipt or duplicate Token.
    record(billing, usage={}, completed=False)
    assert billing.summary()['requests'] == 1 and billing.summary()['totalTokens'] == 150
    assert billing.summary()['costCny'] == 3.5


@pytest.mark.parametrize('status', [401,403,404,429,500])
def test_failed_lookup_keeps_pending_and_does_not_retry_or_store_secrets(billing, status):
    record(billing)
    reconciler = EvoLinkReconciler(billing, Credentials())
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.side_effect = urllib.error.HTTPError(BASE, status, 'failure', {}, io.BytesIO(b'test-secret'))
        result = reconciler.reconcile()
        assert result['confirmed'] == 0 and result['pending'] == 1
        assert opener.return_value.open.call_count == 1
    saved = items(billing)[0]
    assert saved['status'] == 'pending' and saved['costCny'] is None
    assert 'test-secret' not in json.dumps(saved)


@pytest.mark.parametrize('body', [
    {'id':'task-1','status':'processing','usage':{'cost':{'cny':1}}},
    {'id':'task-1','status':'completed','usage':{'credits_used':10}},
    {'id':'different-task','status':'completed','usage':{'cost':{'cny':1}}},
    {'id':'task-1','model':'different-model','status':'completed','usage':{'cost':{'cny':1}}},
])
def test_unconfirmed_or_mismatched_response_does_not_become_free_or_settled(billing, body):
    record(billing)
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.return_value = response(body)
        result = EvoLinkReconciler(billing, Credentials()).reconcile()
    assert result['confirmed'] == 0 and billing.summary()['awaitingReconciliation'] == 1
    assert items(billing)[0]['costCny'] is None


def test_text_response_id_is_not_sent_to_async_task_query(billing):
    record(billing, kind='text', provider_task_id=None, provider_request_id='chatcmpl-text-1')
    with patch('urllib.request.build_opener') as opener:
        reconciler = EvoLinkReconciler(billing, Credentials())
        result = reconciler.reconcile()
        assert reconciler.reconcile()['missingTaskId'] == 1  # No upstream request means no rate-limit cooldown.
        opener.assert_not_called()
    assert result['missingTaskId'] == result['pending'] == 1 and result['checked'] == 0


def test_structured_text_receipt_is_actual_cost_without_async_status(billing):
    class Adapter:
        provider_key, base_url, model = 'evolink', BASE, 'text-model'
        def complete_structured(self):
            self.last_response = {'id':'chatcmpl-1','usage':{'input_tokens':100,'output_tokens':20,'cost':{'cny':.2}}}
            return {'answer':'done'}
    assert MeteredProvider(Adapter(), billing, 'text').complete_structured() == {'answer':'done'}
    saved = items(billing)[0]
    assert saved['costCny'] == .2 and saved['providerRequestId'] == 'chatcmpl-1'
    assert saved['providerTaskId'] is None and billing.summary()['totalTokens'] == 120


def test_legacy_tariff_settlement_is_pending_and_can_receive_actual_receipt(billing):
    saved = record(billing)
    saved.update(status='settled', costCny=99, points=9900, costSource='price_estimate')
    with billing._connect() as db:
        db.execute('UPDATE credit_ledger SET data_json=?', (json.dumps(saved),))
    assert billing.summary()['costCny'] == 0 and billing.summary()['awaitingReconciliation'] == 1
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.return_value = response({'id':'task-1','status':'completed','usage':{'cost':{'cny':1}}})
        assert EvoLinkReconciler(billing, Credentials()).reconcile()['confirmed'] == 1
    assert billing.summary()['costCny'] == 1 and billing.summary()['totalTokens'] == 150


def test_accepted_image_query_failure_retains_id_without_duplicate_generation(billing):
    adapter = ProviderRegistry(Credentials()).image('evolink', model='gpt-image-2')
    adapter.poll_interval = 0
    metered = MeteredProvider(adapter, billing, 'image')
    with patch('urllib.request.build_opener') as opener, billing_scope(task_id='design-1'):
        opener.return_value.open.side_effect = [response({'id':'task-accepted','status':'pending'}),
            urllib.error.HTTPError(BASE, 404, 'not found', {}, io.BytesIO())]
        with pytest.raises(ProviderError): metered.generate(prompt='test')
        methods = [call.args[0].get_method() for call in opener.return_value.open.call_args_list]
    assert methods == ['POST','GET']
    assert len(items(billing)) == 1 and items(billing)[0]['providerTaskId'] == 'task-accepted'
    assert billing.summary()['awaitingReconciliation'] == 1


def test_reading_summary_never_networks_and_explicit_endpoint_only_queries(billing, monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient
    record(billing)
    monkeypatch.setattr(app.state, 'billing', billing, raising=False)
    monkeypatch.setattr(app.state, 'evolink_billing', EvoLinkReconciler(billing, Credentials()), raising=False)
    client = TestClient(app)
    with patch('urllib.request.build_opener', side_effect=AssertionError('summary must remain local')):
        assert client.get('/api/credits').json()['awaitingReconciliation'] == 1
    with patch('urllib.request.build_opener') as opener:
        opener.return_value.open.return_value = response({'id':'task-1','status':'completed','usage':{'cost':{'cny':0}}})
        assert client.post('/api/billing/evolink/reconcile').json()['confirmed'] == 1
        assert opener.return_value.open.call_args.args[0].get_method() == 'GET'
    result = client.get('/api/credits').json()
    assert result['reportedRequests'] == 1 and result['awaitingReconciliation'] == 0 and result['costCny'] == 0
