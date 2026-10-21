"""Reserve estimated credits before calls, settle when actual usage arrives."""
import json
from uuid import uuid4
from .billing import calculate_cost, number
from .providers.http import ProviderError


class BudgetService:
    def __init__(self, store, catalog):
        self.store,self.catalog=store,catalog
        with store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS budget_reservations (id TEXT PRIMARY KEY, task_id TEXT, points REAL, status TEXT)')
            if 'ledger_id' not in {row[1] for row in db.execute('PRAGMA table_info(budget_reservations)')}:
                db.execute('ALTER TABLE budget_reservations ADD COLUMN ledger_id TEXT')
            if 'scope' not in {row[1] for row in db.execute('PRAGMA table_info(budget_reservations)')}:
                db.execute("ALTER TABLE budget_reservations ADD COLUMN scope TEXT NOT NULL DEFAULT 'task'")
            db.execute('CREATE TABLE IF NOT EXISTS agent_repair_budget (task_id TEXT PRIMARY KEY, active INTEGER, searches INTEGER DEFAULT 0, reads INTEGER DEFAULT 0, nodes TEXT)')

    def reserve(self, task_id, *, provider, base_url, model, kind, usage=None, units=None, require_price=False):
        if not task_id: return {}
        with self.store._connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone(): return {}
            task=db.execute('SELECT input_json FROM tasks WHERE id=?',(task_id,)).fetchone()
            repair=db.execute('SELECT active FROM agent_repair_budget WHERE task_id=?',(task_id,)).fetchone()
        context=json.loads(task[0]) if task else {}
        cap=context.get('budgetPoints',self.catalog.settings().taskBudgetPoints)
        repair_active = bool(repair and repair[0])
        if cap is None and not repair_active and not require_price: return {}
        price=self.catalog.price(provider,base_url,model)
        # Reservations cannot assume a cache hit. When a write tariff is
        # explicitly known, reserve at the higher input rate; actual usage
        # still settles once against read/write/ordinary counters.
        if kind == 'text' and number(price.get('cacheWritePerMillion')) is not None and number(price.get('inputPerMillion')) is not None:
            price={**price,'inputPerMillion':max(price['inputPerMillion'],price['cacheWritePerMillion'])}
        cost=calculate_cost(kind,usage or {},units or {},price)
        if cost is None: raise ProviderError('已启用费用预算，但所选模型缺少价格或计费单位；请先配置价格。',status_code=402)
        rules=self.catalog.settings().credits
        points=cost*number(rules.pointsPerCny)*number(rules.multiplier)*(number(rules.usdToCny) if price.get('currency')=='USD' else 1)
        reservation=str(uuid4())
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            used=db.execute('SELECT COALESCE(SUM(points),0) FROM budget_reservations WHERE task_id=?',(task_id,)).fetchone()[0]
            if cap is not None and used+float(points)>float(cap): raise ProviderError('本轮费用预算不足，已停止新调用。请在用量与计费中核对实际消耗。',status_code=402)
            if repair_active:
                repair_used=db.execute("SELECT COALESCE(SUM(points),0) FROM budget_reservations WHERE task_id=? AND scope='repair'",(task_id,)).fetchone()[0]
                if repair_used+float(points)>50: raise ProviderError('自动补证、修复与复核的费用预算不足，已保留产物并停止新调用。',status_code=402)
            db.execute('INSERT INTO budget_reservations (id,task_id,points,status,scope) VALUES (?,?,?,?,?)',(reservation,task_id,float(points),'reserved','repair' if repair_active else 'task'))
        return {'reservationId':reservation,'estimatedPoints':float(points),'budgetPoints':cap}

    def repair_control(self, task_id, action, nodes=None):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if action == 'begin':
                row=db.execute('SELECT active FROM agent_repair_budget WHERE task_id=?',(task_id,)).fetchone()
                if row and not row[0]: return {'allowed':False,'reason':'本轮自动修复已使用'}
                db.execute('INSERT OR IGNORE INTO agent_repair_budget(task_id,active,nodes) VALUES(?,1,?)',(task_id,json.dumps(nodes or [])))
                return {'allowed':True,'budgetPoints':50}
            if action == 'finish':
                db.execute('UPDATE agent_repair_budget SET active=0 WHERE task_id=?',(task_id,))
                return {'allowed':False}
            raise ValueError('无效修复预算操作')

    def guard_repair_tool(self, task_id, name, args):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM agent_repair_budget WHERE task_id=? AND active=1',(task_id,)).fetchone()
            if not row: return
            if name in {'web_search','web_read'}:
                column, cap = ('searches',1) if name=='web_search' else ('reads',2)
                if row[column]>=cap: raise ProviderError('自动补证次数已用完，请使用已保存证据完成复核。',status_code=402)
                db.execute(f'UPDATE agent_repair_budget SET {column}={column}+1 WHERE task_id=?',(task_id,))
            allowed={'report_progress','search','knowledge_search','document_read','document_part_inspect','asset_search','asset_inspect','conversation_read','context_read','canvas_read','canvas_versions','list_models','web_search','web_read','delivery_verify','budget_check','repair_control'}
            if name == 'design_plan' and not args.get('plan'):
                allowed.add('design_plan')
            if name in allowed: return
            target=args.get('canvas_node_id') or args.get('node_id')
            if name not in {'canvas_create_html','canvas_create_text','canvas_update_node','generate_cad'} or target not in json.loads(row['nodes']):
                raise ProviderError('自动修复只能修改本轮已有节点，不得新增收费生成或其他操作。',status_code=402)

    def settle(self, task_id, reservation_id, points):
        if points is None: return  # Unknown charges retain their reservation.
        with self.store._connect() as db:
            db.execute("UPDATE budget_reservations SET points=?,status='settled' WHERE id=? AND task_id=?",(points,reservation_id,task_id))

    def bind_record(self, task_id, reservation_id, ledger_id):
        with self.store._connect() as db:
            db.execute('UPDATE budget_reservations SET ledger_id=? WHERE id=? AND task_id=?',(ledger_id,reservation_id,task_id))

    @staticmethod
    def settle_record(store, ledger_id, points):
        if points is None: return
        with store._connect() as db:
            if 'ledger_id' not in {row[1] for row in db.execute('PRAGMA table_info(budget_reservations)')}: return
            db.execute("UPDATE budget_reservations SET points=?,status='settled' WHERE ledger_id=?",(points,ledger_id))
