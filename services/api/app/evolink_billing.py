"""EvoLink monetary receipts and read-only reconciliation. Never submit generation."""
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, quote

from .billing import number
from .providers.evolink import EvoLinkTransport
from .providers.http import ProviderError


def is_evolink(provider, base_url=''):
    return provider == 'evolink' or urlsplit(base_url).hostname in {'api.evolink.ai', 'direct.evolink.ai'}


def receipt_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', value) else None


def normalize_usage(usage, *, completed=True):
    """Keep provider currency explicit; reserved/used credits are not currency."""
    usage = dict(usage) if isinstance(usage, dict) else {}
    cost, currency = usage.pop('cost', None), usage.pop('cost_currency', None)
    if not completed: return usage
    candidates = [('CNY', cost.get('cny')), ('USD', cost.get('usd'))] if isinstance(cost, dict) else [(currency, cost)]
    for currency, value in candidates:
        amount = None if isinstance(value, bool) else number(value)
        if currency in {'CNY', 'USD'} and amount is not None:
            usage.update(cost=float(amount), cost_currency=currency)
            break
    return usage


def has_reported_cost(item):
    return (item.get('costSource') == 'provider_reported' or (item.get('price') or {}).get('source') == 'reported') and number(item.get('costCny')) is not None


class EvoLinkBillingClient(EvoLinkTransport):
    timeout_seconds = 10

    def __init__(self, credentials, provider='evolink', base_url='https://api.evolink.ai/v1'):
        # Only the documented task/account API accepts these lookups. Never
        # forward a stored key to a user-supplied URL or redirect destination.
        if base_url.rstrip('/') != 'https://api.evolink.ai/v1':
            raise ProviderError('此端点未提供已确认的逐笔计费查询接口', error_code='unsupported_endpoint')
        self.credentials, self.provider_key, self.base_url = credentials, provider, base_url.rstrip('/')

    def query(self, task_id=None):
        """No task ID means account scope; it must never settle any request."""
        if task_id is None:
            body = self._json('/credits')
            if body.get('success') is not True or not isinstance(body.get('data'), dict):
                raise ProviderError('EvoLink 账户用量响应无效', error_code='invalid_response')
            # Provider credits are retained as raw units, not Token or RMB.
            data = {}
            for scope in ('user', 'token'):
                row = body['data'].get(scope)
                row = row if isinstance(row, dict) else {}
                data[scope] = {field: float(number(row[field])) for field in ('used_credits', 'remaining_credits')
                               if field in row and not isinstance(row[field], bool) and number(row[field]) is not None}
            return {'scope': 'account', 'unit': 'provider_credits', 'attributableToRequest': False, 'data': data}
        if not receipt_id(task_id): raise ProviderError('无效的 EvoLink 任务编号', error_code='invalid_task_id')
        body = self._json('/tasks/' + quote(task_id, safe=''))
        if body.get('id') != task_id:
            raise ProviderError('EvoLink 任务编号不匹配', error_code='receipt_mismatch')
        return {'scope': 'request', 'id': task_id, 'status': body.get('status'), 'model': body.get('model'),
                'usage': normalize_usage(body.get('usage'), completed=body.get('status') == 'completed')}


class EvoLinkReconciler:
    """Explicit bounded batches; the UI's local three-second poll never networks."""
    def __init__(self, billing, credentials, client_factory=EvoLinkBillingClient):
        self.billing, self.credentials, self.client_factory = billing, credentials, client_factory
        self.lock = threading.Lock()
        self.last_query = float('-inf')

    def reconcile(self):
        if not self.lock.acquire(blocking=False): return {'checked': 0, 'confirmed': 0, 'retryAfter': 60}
        try:
            wait = 60 - (time.monotonic() - self.last_query)
            if wait > 0: return {'checked': 0, 'confirmed': 0, 'retryAfter': int(wait) + 1}
            with self.billing._connect() as db:
                rows = db.execute('SELECT * FROM credit_ledger ORDER BY created_at').fetchall()
            pending = [json.loads(row['data_json']) for row in rows]
            pending = [item for item in pending if is_evolink(item.get('provider'), item.get('baseUrl', '')) and not has_reported_cost(item)]
            pending.sort(key=lambda item: (item.get('reconciliation') or {}).get('checkedAt', ''))
            checked = confirmed = 0
            missing = sum(not item.get('providerTaskId') for item in pending)
            deadline = time.monotonic() + 20
            for item in pending:
                task_id = item.get('providerTaskId')
                if not task_id:
                    continue  # Text response IDs are not async task IDs.
                if checked >= 5 or time.monotonic() >= deadline: break
                if checked == 0: self.last_query = time.monotonic()
                checked += 1
                code = 'cost_not_reported'
                try:
                    result = self.client_factory(self.credentials, item['provider'], item['baseUrl']).query(task_id)
                    if result.get('model') and result['model'] != item['model']:
                        raise ProviderError('EvoLink 模型与原请求不匹配', error_code='receipt_mismatch')
                    usage = result['usage']
                    if result['status'] != 'completed': code = 'task_not_completed'
                    elif number(usage.get('cost')) is not None:
                        saved = self.billing.record(provider=item['provider'], base_url=item['baseUrl'], model=item['model'],
                            kind=item['kind'], usage=usage, units=item.get('units'), record_id=item['id'],
                            provider_task_id=task_id, completed=True)
                        if has_reported_cost(saved):
                            confirmed += 1
                            code = 'confirmed'
                            from .budget import BudgetService
                            BudgetService.settle_record(self.billing.store, item['id'], saved.get('points'))
                except ProviderError as error:
                    code = {401:'auth_failed', 403:'auth_failed', 404:'task_not_found', 429:'rate_limited'}.get(error.status_code, error.error_code or 'query_unavailable')
                self._mark(item['id'], code)
                if code in {'auth_failed', 'rate_limited'}: break
            return {'checked': checked, 'confirmed': confirmed, 'pending': len(pending) - confirmed,
                    'missingTaskId': missing, 'retryAfter': 60 if pending else 0}
        finally:
            self.lock.release()

    def _mark(self, record_id, code):
        with self.billing._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data_json FROM credit_ledger WHERE id=?', (record_id,)).fetchone()
            if row is None: return
            item = json.loads(row[0])
            item['reconciliation'] = {'status': 'confirmed' if has_reported_cost(item) else 'pending',
                                      'reason': code, 'checkedAt': datetime.now(timezone.utc).isoformat()}
            db.execute('UPDATE credit_ledger SET data_json=? WHERE id=?', (json.dumps(item, ensure_ascii=False), record_id))
