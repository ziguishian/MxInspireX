"""Short circuit for repeated transient failures, scoped to endpoint + model."""
import time


class ProviderHealth:
    def __init__(self, store):
        self.store=store
        with store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS provider_health (endpoint TEXT PRIMARY KEY, failures INTEGER, retry_at REAL)')

    @staticmethod
    def key(endpoint):
        return '\n'.join(str(endpoint.get(key,'')) for key in ('key','baseUrl','model','api'))

    def unavailable(self, endpoint):
        with self.store._connect() as db:
            row=db.execute('SELECT retry_at FROM provider_health WHERE endpoint=?',(self.key(endpoint),)).fetchone()
        return bool(row and row[0]>time.time())

    def record(self, endpoint, success, transient=False):
        if not success and not transient: return
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT failures FROM provider_health WHERE endpoint=?',(self.key(endpoint),)).fetchone()
            failures=0 if success else (row[0] if row else 0)+1
            db.execute('INSERT OR REPLACE INTO provider_health VALUES (?,?,?)',(self.key(endpoint),failures,time.time()+60 if failures>=3 else 0))
