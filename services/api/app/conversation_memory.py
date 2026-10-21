"""Evidence-backed memory for one SDK conversation; request views never replace history."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from pathlib import Path
from uuid import uuid4

TOOLS = ('conversation_memory_read', 'conversation_memory_update')
ROLES = {'input', 'logo', 'key_visual', 'specialist', 'style', 'artifact'}
CATEGORIES = {'preference', 'fact', 'asset', 'decision', 'progress'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class MemoryError(ValueError):
    def __init__(self, message, code='memory_invalid', *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ConversationMemoryService:
    def __init__(self, store):
        self.store = store
        from .assets import AssetStore
        AssetStore(store)
        with store._connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS conversation_memories (
                session_id TEXT, id TEXT, key TEXT, version INTEGER, body TEXT,
                PRIMARY KEY(session_id,id), UNIQUE(session_id,key));
              CREATE TABLE IF NOT EXISTS conversation_memory_versions (
                session_id TEXT, id TEXT, version INTEGER, body TEXT,
                PRIMARY KEY(session_id,id,version));
              CREATE TABLE IF NOT EXISTS conversation_memory_sessions (
                session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS conversation_memory_tasks (
                task_id TEXT PRIMARY KEY, session_id TEXT, body TEXT);
              CREATE TABLE IF NOT EXISTS conversation_memory_operations (
                task_id TEXT, operation_id TEXT, fingerprint TEXT, body TEXT,
                PRIMARY KEY(task_id,operation_id));
              CREATE TABLE IF NOT EXISTS conversation_reference_snapshots (
                id TEXT PRIMARY KEY, task_id TEXT, body TEXT);
            ''')

    def _task(self, db, project_id, task_id):
        row = db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if not row or row['status'] == 'cancelled' or row['superseded_by']:
            raise MemoryError('对话任务不存在或已停止')
        data = json.loads(row['input_json'] or '{}')
        node_id = str(data.get('canvasNodeId') or (data.get('canvasParams') or {}).get('canvasNodeId') or '')
        session = f'project:{project_id}:node:{node_id}:task:{task_id}' if data.get('taskSurface') == 'canvas_node' and node_id else f'project:{project_id}'
        return row, data, session

    def _asset(self, db, project_id, asset_id):
        row = db.execute('SELECT * FROM assets WHERE id=? AND project_id=?', (asset_id, project_id)).fetchone()
        if not row:
            raise MemoryError('资料不属于当前对话或已被删除')
        return row, json.loads(row['metadata_json'] or '{}')

    def _source_evidence(self, db, project_id, task_id):
        """Return verbatim message evidence separately from server attachment labels."""
        _, data, _ = self._task(db, project_id, task_id)
        text = data.get('userMessage', '')
        answers = [str(a.get('value','')) for a in data.get('clarificationAnswers',[]) if not a.get('skipped')]
        if answers:
            text += '\n' + '\n'.join(answers)
        assets, contextual = [], []
        context_ids = {a['assetId'] for a in data.get('memoryContextAssets',[]) if a.get('assetId')}
        for asset in db.execute("SELECT id,metadata_json FROM assets WHERE project_id=? AND kind='image'", (project_id,)):
            meta = json.loads(asset['metadata_json'] or '{}')
            if self._associated(data, asset['id'], meta):
                assets.append({'assetId': asset['id'], 'kind': 'attachment',
                               'origin': 'user_upload' if meta.get('source') == 'input-reference' else 'artifact'})
            elif asset['id'] in context_ids:
                contextual.append({'assetId':asset['id'], 'kind':'context', 'sourceTaskId':meta.get('taskId'),
                                   'adoptionConfirmed':False})
        return {'taskId': task_id, 'userText': text[:6000], 'truncated': len(text)>6000,
                'attachments': assets[:40], 'contextAssets':contextual[:8], 'readMore': 'conversation_read'}

    def _validate_update_links(self, db, project_id, task_id, session, arguments, changes):
        """Report related identity/scope errors together before attempting any writes."""
        state = json.loads(db.execute('SELECT body FROM conversation_memory_tasks WHERE task_id=?',(task_id,)).fetchone()[0])
        records = self._records(db,session,task_id,'')
        projected = {r['key']:r for r in records}
        issues = []
        evidence_task = task_id
        for change in changes:
            key = str(change.get('key',''))
            old = projected.get(key)
            if old is None:
                old_row = db.execute('SELECT body FROM conversation_memories WHERE session_id=? AND key=?',(session,key)).fetchone()
                old = json.loads(old_row[0]) if old_row else {}
            value = {**old,**change}
            projected[key] = value
            if old and ((old['scope']!='task' and value.get('scope')=='task') or
                        (old['scope']=='topic' and value.get('scope')=='topic' and old.get('topic')!=value.get('topic'))):
                issues.append({'key':key,'field':'scope','instruction':'临时用途或不同主题使用独立 key；仅沿用图片时直接选用原记忆，不修改其范围和角色。'})
            asset_id = value.get('assetId')
            if asset_id and not db.execute('SELECT 1 FROM assets WHERE project_id=? AND id=?',(project_id,asset_id)).fetchone():
                issues.append({'key':key,'field':'assetId','value':asset_id,
                               'instruction':'资料 ID 不存在于本对话。逐字复制 availableAssets 中的 assetId 或直接选用其 key；不得缩写或猜测 ID。'})
            source = value.get('source') or {}
            owner = source.get('taskId') or task_id
            origin = db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?',(owner,project_id)).fetchone()
            if origin and source.get('quote'):
                data = json.loads(origin[0] or '{}')
                text = data.get('userMessage','')+'\n'+'\n'.join(str(a.get('value','')) for a in data.get('clarificationAnswers',[]) if not a.get('skipped'))
                if source['quote'] not in text:
                    evidence_task = owner
                    issues.append({'key':key,'field':'source.quote','taskId':owner,
                                   'instruction':'source.quote 未匹配用户原文。从 sourceEvidence.userText 或 conversation_read 逐字选取；图片附件标签不是用户原话。'})
        # A topic narrows automatic recall, but it is not an access boundary.
        # The design agent may explicitly reuse an applicable record from an
        # earlier topic without rewriting that record's original scope/topic.
        available = [r for r in projected.values() if r.get('active',True)]
        by_id = {identity:r for r in available for identity in (r.get('id'),r.get('key')) if identity}
        selected = arguments.get('selected_ids')
        if selected is not None and isinstance(selected,list):
            invalid = [identity for identity in selected if identity not in by_id]
            if invalid:
                issues.append({'field':'selected_ids','values':invalid,
                               'instruction':'记忆不存在、已失效或超出适用范围。同一设计主题可保留原 topic；新主题只选择适用记录，不直接搬用旧主题约束。'})
        else:
            selected = [r['id'] for r in state['selected']]
        selected_records = {by_id[i].get('key'):by_id[i] for i in selected if i in by_id}
        if arguments.get('selected_ids') is None and not changes:
            selected_records = {r['key']:r for r in state['selected']}
        image_ids = {identity for r in selected_records.values() if r.get('assetId')
                     for identity in (r.get('id'),r.get('key')) if identity}
        for binding in arguments.get('references') or []:
            invalid = [identity for identity in binding.get('memory_ids',[]) if identity not in image_ids]
            if invalid:
                issues.append({'field':'references.memory_ids','deliverableId':binding.get('deliverable_id'),'values':invalid,
                               'instruction':'这里只填写已选用的图片记忆 key 或 ID；文字需求留在 selected_ids。可省略 references，自动绑定所选图片为默认方案。'})
        if not issues:
            return
        evidence = self._source_evidence(db,project_id,evidence_task)
        preferred = {a['assetId'] for a in [*evidence['attachments'],*evidence['contextAssets']]}
        images = sorted((r for r in records if r.get('assetId')),key=lambda r:r['assetId'] not in preferred)
        fields = ('id','key','assetId','role','scope','topic','status')
        details = {**issues[0], 'issues':issues, 'sourceEvidence':evidence,
                   'availableAssets':[{k:r[k] for k in fields if k in r} for r in images[:20]],
                   'readMore':'conversation_memory_read'}
        raise MemoryError(issues[0]['instruction'] + (f' 另有 {len(issues)-1} 项关联错误，请按 validation.issues 一并修正。' if len(issues)>1 else ''),details=details)

    @staticmethod
    def _normalize_reference_bindings(data, arguments):
        """Resolve a lone model alias to the plan's sole current deliverable."""
        value = dict(arguments)
        bindings = value.get('references')
        plan = data.get('designPlan') or data.get('planBaseline') or {}
        if not isinstance(bindings,list) or not bindings or not plan.get('ready'):
            return value
        deliverable_ids = [str(item.get('id')) for item in plan.get('deliverables',[])
                           if isinstance(item,dict) and item.get('id')]
        known = set(deliverable_ids)
        invalid = [str(binding.get('deliverable_id') or '*') for binding in bindings
                   if isinstance(binding,dict) and str(binding.get('deliverable_id') or '*') not in known|{'*'}]
        if not invalid:
            return value
        current_ids = [str(identity) for identity in plan.get('currentItemIds',[]) if str(identity) in known]
        if not current_ids and len(deliverable_ids)==1:
            current_ids=deliverable_ids
        if len(bindings)==1 and len(invalid)==1 and len(current_ids)==1:
            value['references']=[{**bindings[0],'deliverable_id':current_ids[0]}]
            return value
        instruction='引用方案的交付项必须使用当前设计计划中的稳定 ID；请从 validation.currentItemIds 选择，不要创建临时别名。'
        raise MemoryError(instruction,details={'field':'references.deliverable_id','values':invalid,
            'availableDeliverableIds':deliverable_ids,'currentItemIds':current_ids,'instruction':instruction})

    def _write(self, db, session, key, value):
        old = db.execute('SELECT * FROM conversation_memories WHERE session_id=? AND key=?', (session, key)).fetchone()
        version, identity = (old['version']+1, old['id']) if old else (1, str(uuid4()))
        value = {**value, 'id': identity, 'key': key, 'version': version}
        if old:
            previous = json.loads(old['body'])
            # Compare without bookkeeping; a repeated analysis need not create a version.
            if {k:v for k,v in previous.items() if k != 'version'} == {k:v for k,v in value.items() if k != 'version'}:
                return previous
        body = encode(value)
        db.execute('INSERT OR REPLACE INTO conversation_memories VALUES(?,?,?,?,?)', (session, identity, key, version, body))
        db.execute('INSERT INTO conversation_memory_versions VALUES(?,?,?,?)', (session, identity, version, body))
        db.execute('UPDATE conversation_memory_sessions SET revision=revision+1 WHERE session_id=?', (session,))
        return value

    def _publish(self, db, task_id, data, state):
        data['conversationMemory'] = {k:v for k,v in state.items() if k != 'catalog'}
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (encode(data), task_id))
        db.execute('INSERT OR REPLACE INTO conversation_memory_tasks VALUES(?,?,?)', (task_id, state['sessionId'], encode(state)))

    def bootstrap(self, project_id, task_id):
        """Import factual asset provenance, not semantic roles guessed from generated prompts."""
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task, data, session = self._task(db, project_id, task_id)
            db.execute('INSERT OR IGNORE INTO conversation_memory_sessions VALUES(?,0)', (session,))
            assets = db.execute('SELECT * FROM assets WHERE project_id=? AND created_at<=? ORDER BY created_at,id', (project_id, task['created_at'])).fetchall()
            # Current uploads may be registered after task creation.
            assets += [asset for asset in db.execute('SELECT * FROM assets WHERE project_id=? AND created_at>?', (project_id, task['created_at']))
                       if (meta := json.loads(asset['metadata_json'] or '{}')).get('source') == 'input-reference' or self._associated(data, asset['id'], meta)]
            history = db.execute('SELECT id,input_json FROM tasks WHERE project_id=? AND superseded_by IS NULL AND created_at<=? ORDER BY created_at,COALESCE(turn_order,rowid)', (project_id, task['created_at'])).fetchall()
            if data.get('taskSurface') == 'canvas_node':
                history = [row for row in history if row['id'] == task_id]
            else:
                history = [row for row in history if json.loads(row['input_json'] or '{}').get('taskSurface', 'conversation') != 'canvas_node']
            for asset in assets:
                meta = json.loads(asset['metadata_json'] or '{}')
                original = meta.get('source') == 'input-reference'
                if asset['kind'] != 'image' or not (original or meta.get('taskId')):
                    continue
                key = 'asset:'+asset['id']
                if db.execute('SELECT 1 FROM conversation_memories WHERE session_id=? AND key=?', (session,key)).fetchone():
                    continue
                owner = meta.get('taskId')
                if original:
                    owner = next((row['id'] for row in history if self._associated(json.loads(row['input_json'] or '{}'), asset['id'], meta)), None)
                    if not owner:
                        continue
                elif not any(row['id']==owner for row in history):
                    continue
                self._write(db, session, key, {'content': Path(asset['path_relative']).name, 'category':'asset',
                    'scope':'conversation', 'topic':'', 'status':'observed', 'active':True, 'assetId':asset['id'],
                    'role':'input' if original else 'artifact', 'sha256':asset['sha256'],
                    'source':{'taskId':owner,'assetId':asset['id']}, 'sourceAssetIds':meta.get('sourceAssetIds') or ([meta['sourceAssetId']] if meta.get('sourceAssetId') else [])})
            saved = db.execute('SELECT body FROM conversation_memory_tasks WHERE task_id=? AND session_id=?', (task_id,session)).fetchone()
            if saved:
                return json.loads(saved[0])
            revision = db.execute('SELECT revision FROM conversation_memory_sessions WHERE session_id=?',(session,)).fetchone()[0]
            state = {'sessionId':session, 'memoryRevision':revision, 'analyzed':False, 'topic':'', 'selected':[], 'referenceSnapshots':[]}
            origin_id=(data.get('continuation') or {}).get('taskId') if data.get('planAccepted') else None
            if origin_id:
                origin=db.execute('SELECT body FROM conversation_memory_tasks WHERE task_id=? AND session_id=?',(origin_id,session)).fetchone()
                if origin:
                    previous=json.loads(origin[0])
                    state.update(topic=previous['topic'],selected=previous['selected'],progress=previous.get('progress',[]),inheritedFrom=origin_id)
                    for snapshot in previous['referenceSnapshots']:
                        value={**snapshot,'taskId':task_id};value.pop('id',None);value['id']=digest(value)
                        db.execute('INSERT OR IGNORE INTO conversation_reference_snapshots VALUES(?,?,?)',(value['id'],task_id,encode(value)))
                        state['referenceSnapshots'].append(value)
            self._publish(db, task_id, data, state)
            return state

    @staticmethod
    def _associated(data, asset_id, metadata):
        origin = metadata.get('referenceOrigin') or {}
        return (any(r.get('assetId')==asset_id for r in data.get('memoryInputAssets',[]))
            or any((r.get('id') or r.get('assetId'))==asset_id or
                    (origin and (r.get('id') or r.get('assetId'))==origin.get('assetId') and r.get('projectId')==origin.get('projectId')) for r in data.get('referencedAssets',[]))
            or f'@asset:{asset_id}' in data.get('userMessage','')
            or any((r.get('pathRelative') and r['pathRelative']==metadata.get('referenceFile'))
                   or (r.get('documentId') and r['documentId']==metadata.get('referenceDocumentId')) for r in data.get('referencedFiles',[])))

    def _records(self, db, session, task_id, topic=''):
        records = [json.loads(r[0]) for r in db.execute('SELECT body FROM conversation_memories WHERE session_id=? ORDER BY rowid',(session,))]
        task_scopes={task_id}
        row=db.execute('SELECT input_json FROM tasks WHERE id=?',(task_id,)).fetchone()
        data=json.loads(row[0] or '{}') if row else {}
        superseded = {r[0] for r in db.execute('SELECT id FROM tasks WHERE superseded_by IS NOT NULL')}
        if data.get('replacesTaskId'):
            from .conversation_context import ConversationContext
            allowed = {r['id'] for r in ConversationContext(self.store)._rows(session.removeprefix('project:'), task_id)} | {task_id}
            records = [r for r in records if r.get('source', {}).get('taskId') in allowed]
        if data.get('planAccepted'):task_scopes.add((data.get('continuation') or {}).get('taskId'))
        return [r for r in records if r.get('active') and r.get('source', {}).get('taskId') not in superseded and (r['scope']!='task' or r['source']['taskId'] in task_scopes)
                and (r['scope']!='topic' or not topic or r.get('topic')==topic)]

    def _planned_reference(self, project_id, data, source, asset_id, role):
        """An accepted dependency can authorize an auxiliary master, not invent an original Logo."""
        plan=data.get('planBaseline') or {}
        item_id=source.get('deliverableId')
        if not (data.get('planAccepted') and plan.get('ready') and item_id and role in {'key_visual','specialist','style'}
                and source.get('planTaskId')==(data.get('planBaselineTaskId') or (data.get('continuation') or {}).get('taskId'))):
            return False
        if not any(item_id in item.get('dependsOn',[]) for item in plan.get('deliverables',[])):
            return False
        from .canvas import CanvasStore
        return any((node.get('data',{}).get('assetId') or (node.get('data',{}).get('asset') or {}).get('id'))==asset_id
                   and node['data'].get('deliveryBinding',{}).get('scopeId')==plan.get('scopeId')
                   and item_id in node['data'].get('deliveryBinding',{}).get('itemIds',[])
                   for node in CanvasStore(self.store).load(project_id)['nodes'])

    def read(self, project_id, task_id, *, ids=None, query='', offset=0, limit=20, topic=None, version=None):
        state = self.bootstrap(project_id, task_id)
        with self.store._connect() as db:
            self._task(db, project_id, task_id)
            records = self._records(db,state['sessionId'],task_id,topic if topic is not None else state['topic'])
            revision = db.execute('SELECT revision FROM conversation_memory_sessions WHERE session_id=?',(state['sessionId'],)).fetchone()[0]
            if version is not None:
                if not isinstance(ids,list) or len(ids)!=1:raise MemoryError('读取版本时请指定一条记忆 ID 或 key')
                saved=db.execute('SELECT v.body FROM conversation_memory_versions v JOIN conversation_memories m ON v.session_id=m.session_id AND v.id=m.id WHERE v.session_id=? AND (m.id=? OR m.key=?) AND v.version=?',(state['sessionId'],ids[0],ids[0],version)).fetchone()
                if not saved:raise MemoryError('该记忆版本不存在')
                records=[json.loads(saved[0])]
        if ids is not None:
            wanted = set(ids)
            records = [r for r in records if r['id'] in wanted or r['key'] in wanted]
            if any(value not in {r['id'] for r in records}|{r['key'] for r in records} for value in wanted):
                raise MemoryError('记忆不存在、已停用或不属于当前任务范围')
        else:
            terms = set(re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]',str(query).lower()))
            records.reverse()
            records.sort(key=lambda r:(len(terms & set(re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]', (r['content']+' '+r.get('topic','')).lower()))), r.get('role') in {'logo','key_visual'},r.get('role')!='artifact'), reverse=True)
        start, size = max(0,int(offset)), max(1,min(40,int(limit)))
        return {'revision':revision,'records':records[start:start+size], 'total':len(records),
                'nextOffset':start+size if start+size<len(records) else None,'state':state}

    def update(self, project_id, task_id, arguments, operation_id):
        self.bootstrap(project_id,task_id)
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task,data,session = self._task(db,project_id,task_id)
            arguments=self._normalize_reference_bindings(data,arguments)
            fingerprint = digest(arguments)
            previous = db.execute('SELECT * FROM conversation_memory_operations WHERE task_id=? AND operation_id=?',(task_id,operation_id)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint: raise MemoryError('操作标识已用于其他记忆更新','memory_conflict')
                return json.loads(previous['body'])
            revision = db.execute('SELECT revision FROM conversation_memory_sessions WHERE session_id=?',(session,)).fetchone()[0]
            if arguments.get('expected_revision') != revision:
                raise MemoryError('记忆版本已更新，请重新读取后提交修改','memory_conflict')
            changes = arguments.get('changes') or []
            if not isinstance(changes,list) or len(changes)>30: raise MemoryError('每次最多维护 30 条记忆')
            self._validate_update_links(db,project_id,task_id,session,arguments,changes)
            for change in changes:
                key = str(change.get('key',''))
                if not key or len(key)>160: raise MemoryError('请提供稳定的记忆 key')
                old = db.execute('SELECT body FROM conversation_memories WHERE session_id=? AND key=?',(session,key)).fetchone()
                old = json.loads(old[0]) if old else {}
                value = {**old, **{k:v for k,v in change.items() if k in {'content','category','scope','topic','status','active','assetId','role','source'}}}
                value = {k:v for k,v in value.items() if k not in {'id','key','version'}}
                value.setdefault('active',True);value.setdefault('scope','conversation');value.setdefault('topic','');value.setdefault('status','assumed')
                if old and ((old['scope']!='task' and value['scope']=='task') or (old['scope']=='topic' and value['scope']=='topic' and old.get('topic')!=value['topic'])):
                    raise MemoryError('单次要求或另一个主题请使用独立 key，原适用范围的信息继续保留')
                if value.get('category') not in CATEGORIES or value['scope'] not in {'conversation','topic','task'} or value['status'] not in {'confirmed','assumed','proposed','observed'}:
                    raise MemoryError('记忆类别、范围或确认状态无效')
                if not isinstance(value.get('content'),str) or not 0<len(value['content'])<=2000 or len(value['topic'])>160:
                    raise MemoryError('记忆正文须为 1–2000 字符，主题最多 160 字符')
                if value['scope']=='topic' and not value['topic']: raise MemoryError('主题记忆需要 topic')
                source = value.get('source') or {};owner=source.get('taskId') or task_id
                origin = db.execute('SELECT input_json,created_at FROM tasks WHERE id=? AND project_id=? AND superseded_by IS NULL AND created_at<=?',(owner,project_id,task['created_at'])).fetchone()
                if not origin: raise MemoryError('记忆依据必须来自本聊天的已有消息')
                origin_data = json.loads(origin['input_json'] or '{}');quote=source.get('quote','')
                user_text=origin_data.get('userMessage','')+'\n'+'\n'.join(str(a.get('value','')) for a in origin_data.get('clarificationAnswers',[]) if not a.get('skipped'))
                if quote and quote not in user_text:
                    raise MemoryError(f'记忆 {key} 的 source.quote 未匹配用户原文。请从 sourceEvidence.userText 逐字选取相关短句；附件身份由 assetId 和 taskId 的真实关联证明，界面附件标签不是用户引文。',
                        details={'key':key,'field':'source.quote','sourceEvidence':self._source_evidence(db,project_id,owner)})
                if old.get('status')=='confirmed' and value['active'] and value['status'] in {'assumed','proposed'}:
                    raise MemoryError('临时推断不能覆盖已确认信息')
                if old and old['source'].get('taskId'):
                    old_time=db.execute('SELECT created_at FROM tasks WHERE id=?',(old['source']['taskId'],)).fetchone()
                    if old_time and origin['created_at']<old_time[0]:raise MemoryError('较早信息不能覆盖用户后续更正')
                if value.get('assetId'):
                    asset,meta = self._asset(db,project_id,value['assetId'])
                    if source.get('assetId') and source['assetId']!=asset['id']:raise MemoryError('来源图片 ID 与该资料不一致')
                    source={**source,'assetId':asset['id']}
                    if asset['kind']!='image' or value.get('role') not in ROLES: raise MemoryError('图片记忆需要有效的角色')
                    associated=self._associated(origin_data,asset['id'],meta)
                    planned=self._planned_reference(project_id,origin_data,source,asset['id'],value['role'])
                    if value['active'] and value['status']=='confirmed' and not (planned or quote and associated): raise MemoryError('确认图片用途需要用户原话及对应的附件/资产引用，或用户已接受的计划依赖')
                    if value['active'] and value['role'] not in {'artifact','input'} and meta.get('source')!='input-reference':
                        if not ((planned or quote and associated) and value['status']=='confirmed'):
                            raise MemoryError('采用生成图为母版需要用户明确采用该图的依据')
                    if old.get('assetId') and old['assetId']!=asset['id']: raise MemoryError('更换图片请创建新资料记忆，并停用旧的采用关系')
                    value['sha256']=asset['sha256'];value['sourceAssetIds']=meta.get('sourceAssetIds',[])
                elif value['status']=='confirmed' and not quote:
                    raise MemoryError('已确认信息需要用户原文依据')
                value['source']={**source,'taskId':owner}
                self._write(db,session,key,value)
            state=json.loads(db.execute('SELECT body FROM conversation_memory_tasks WHERE task_id=?',(task_id,)).fetchone()[0])
            before=encode(state)
            state['topic']=str(arguments.get('topic',state['topic']))[:160]
            selected_ids=arguments.get('selected_ids')
            if selected_ids is not None:
                # Explicit selection may reuse records from an earlier design
                # topic. Their stored topic remains unchanged.
                records=self._records(db,session,task_id,'');by_id={r['id']:r for r in records};by_id.update({r['key']:r for r in records})
                if not isinstance(selected_ids,list) or len(selected_ids)>30 or any(i not in by_id for i in selected_ids):
                    raise MemoryError('本轮选用记忆不存在、已失效或超出适用范围')
                state['selected']=list({by_id[i]['id']:by_id[i] for i in selected_ids}.values())
            elif changes:
                # Explicit edits update this turn's view, while previous tasks keep frozen copies.
                current={r['id']:r for r in self._records(db,session,task_id,'')}
                state['selected']=[current[r['id']] for r in state['selected'] if r['id'] in current]
            bindings=arguments.get('references')
            # Merely refreshing the candidate list must not erase a required
            # per-item/legacy binding. Changing it needs explicit references.
            required = any(s.get('bindingPolicy') != 'candidates' for s in state['referenceSnapshots'])
            candidates_only = bindings is None and selected_ids is not None and not required
            if bindings is None and selected_ids is not None and required:
                bindings=[{'deliverable_id':s['deliverableId'], 'memory_ids':[r['memoryId'] for r in s['references']],
                           '_bindingPolicy':s.get('bindingPolicy')} for s in state['referenceSnapshots']]
            if bindings is None and selected_ids is not None:
                bindings=[{'deliverable_id':'*','memory_ids':[r['id'] for r in state['selected'] if r.get('assetId')]}]
            if bindings is None:
                # Refresh existing bindings to the updated selected records.
                bindings=[{'deliverable_id':s['deliverableId'],'memory_ids':[r['memoryId'] for r in s['references']], '_bindingPolicy':s.get('bindingPolicy')} for s in state['referenceSnapshots']]
                selected_assets={r['id'] for r in state['selected'] if r.get('assetId')}
                bindings=[{**b,'memory_ids':[i for i in b['memory_ids'] if i in selected_assets]} for b in bindings]
                if not bindings:bindings=[{'deliverable_id':'*','memory_ids':list(selected_assets)}]
            elif bindings == []:
                # Explicitly choosing no references is a complete decision,
                # not a missing per-deliverable plan. Unlike omission above,
                # never add selected images to this empty generation plan.
                bindings=[{'deliverable_id':'*','memory_ids':[]}]
            if not isinstance(bindings,list) or len(bindings)>40: raise MemoryError('引用方案过长')
            by_id={r['id']:r for r in state['selected']};by_id.update({r['key']:r for r in state['selected']})
            snapshots=[]
            for binding in bindings:
                refs=[]
                for identity in binding.get('memory_ids',[]):
                    record=by_id.get(identity)
                    if not record or not record.get('assetId'):raise MemoryError('引用方案须选自本轮已选用的图片记忆')
                    refs.append({'memoryId':record['id'],'memoryVersion':record['version'],'assetId':record['assetId'],
                        'sha256':record['sha256'],'role':record['role'],'purpose':record['content']})
                if len(refs)>8:raise MemoryError('一个交付项最多引用 8 张图片，请拆分任务')
                value={'taskId':task_id,'deliverableId':binding.get('deliverable_id') or '*','references':refs}
                if candidates_only or (arguments.get('references') is None and binding.get('_bindingPolicy') == 'candidates'): value['bindingPolicy'] = 'candidates'
                value['id']=digest(value)
                db.execute('INSERT OR IGNORE INTO conversation_reference_snapshots VALUES(?,?,?)',(value['id'],task_id,encode(value)))
                snapshots.append(value)
            references = {r['assetId']:r for s in snapshots for r in s['references']}
            if len(references)>8:
                raise MemoryError('本轮必要参考超过 8 张，请缩小当前批次；已有选择保持不变','memory_capacity')
            for ref in references.values():
                asset,_=self._asset(db,project_id,ref['assetId'])
                root=db.execute('SELECT root_path FROM projects WHERE id=?',(project_id,)).fetchone()[0]
                path=Path(root)/asset['path_relative']
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:
                    raise MemoryError('参考资料缺失或已变更，请重新选择；已有记忆保持不变','reference_missing')
            state.update(referenceSnapshots=snapshots,analyzed=True,memoryRevision=db.execute('SELECT revision FROM conversation_memory_sessions WHERE session_id=?',(session,)).fetchone()[0])
            if encode(state)!=before and state['memoryRevision']==revision:
                db.execute('UPDATE conversation_memory_sessions SET revision=revision+1 WHERE session_id=?',(session,))
                state['memoryRevision']+=1
            self._publish(db,task_id,data,state)
            result={'status':'recorded','state':state,'revision':state['memoryRevision']}
            db.execute('INSERT INTO conversation_memory_operations VALUES(?,?,?,?)',(task_id,operation_id,fingerprint,encode(result)))
            return result

    def prepare_single_image_selection(self, project_id, task_id, attachments, constraints):
        """Select one explicit first-turn candidate, never infer its visual role."""
        target = constraints.get('singleDeliveryTarget') or {}
        if constraints.get('executionPolicyVersion', 0) < 2 or target.get('kind') != 'image' or target.get('count') != 1:
            return
        if constraints.get('taskSurface') == 'canvas_node' or len(attachments) != 1:
            return
        if any(constraints.get(key) for key in ('designPlanning', 'designPlan', 'planBaseline', 'designBatch', 'planAccepted', 'continuation', 'referencedSkills',
                'clarificationContinuation', 'replacesTaskId', 'deliveryRepairOnly', 'deliveryReviewOnly')):
            return
        focus = constraints.get('focusContext') or {}
        if any(focus.get(key) for key in ('selectionRequired', 'unattachedFileCount', 'unattachedAssetReferences')):
            return
        if (constraints.get('referenceWorkflow') or {}).get('status') == 'required':
            return
        image = attachments[0]
        if not image.get('assetId') or not image.get('data') or not str(image.get('mime', '')).startswith('image/'):
            return
        listing = self.read(project_id, task_id)
        if listing['state'].get('analyzed') or listing['state'].get('selected') or listing['state'].get('referenceSnapshots'):
            return
        with self.store._connect() as db:
            _, data, session = self._task(db, project_id, task_id)
            if db.execute('SELECT 1 FROM tasks WHERE project_id=? AND id!=? AND superseded_by IS NULL LIMIT 1', (project_id, task_id)).fetchone():
                return
            records = self._records(db, session, task_id, '')
            # Other facts/preferences require semantic selection. Keep the old path.
            if len(records) != 1 or records[0].get('assetId') != image['assetId'] or records[0].get('role') != 'input':
                return
            asset, metadata = self._asset(db, project_id, image['assetId'])
            if not self._associated(data, image['assetId'], metadata):
                return
        # Omit references: this is a candidate, not an adopted identity/layout.
        self.update(project_id, task_id, {'expected_revision': listing['revision'],
            'selected_ids': [records[0]['id']]}, 'local:single-image-candidate')
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _, data, _ = self._task(db, project_id, task_id)
            state = data['conversationMemory']
            state['analysisMode'] = 'explicit_single_image'
            self._publish(db, task_id, data, state)

    def prepare_empty_selection(self, project_id, task_id):
        """Initialize an actually empty first-turn context without a model round.

        This selects no facts: the original request remains authoritative and
        the Agent can still record useful information. Existing conversations,
        references, plans and recovery snapshots always keep semantic selection.
        """
        self.bootstrap(project_id, task_id)
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task, data, session = self._task(db, project_id, task_id)
            state = json.loads(db.execute('SELECT body FROM conversation_memory_tasks WHERE task_id=?', (task_id,)).fetchone()[0])
            if state.get('analyzed') or any(data.get(key) for key in (
                'referencedAssets', 'referencedFiles', 'referencedNodes', 'memoryInputAssets', 'memoryContextAssets',
                'continuation', 'designPlan', 'planBaseline', 'designBatch', 'replacesTaskId',
            )):
                return state
            if db.execute('SELECT 1 FROM tasks WHERE project_id=? AND id!=? AND superseded_by IS NULL LIMIT 1', (project_id, task_id)).fetchone():
                return state
            if self._records(db, session, task_id) or state.get('selected') or state.get('referenceSnapshots'):
                return state
            # No sources exist to select or misclassify. Do not invent a fact,
            # a confirmed preference or a mandatory reference binding.
            state.update(analyzed=True, analysisMode='empty_catalog')
            self._publish(db, task_id, data, state)
            return state

    def runtime(self, project_id, task_id, *, images=False):
        with self.store._connect() as db:
            _,data,_=self._task(db,project_id,task_id)
        listing=self.read(project_id,task_id,query=data.get('userMessage',''))
        state=listing['state']
        context={**state,'revision':listing['revision'],'catalog':[{
            k:r[k] for k in ('id','key','content','category','scope','topic','status','role','assetId','version','source') if k in r
        } for r in listing['records']], 'catalogTotal':listing['total'],'nextOffset':listing['nextOffset']}
        with self.store._connect() as db:
            context['sourceEvidence']=self._source_evidence(db,project_id,task_id)
        attachments=[]
        if images:
            refs={r['assetId']:r for s in state['referenceSnapshots'] for r in s['references']}
            if len(refs)>8:raise MemoryError('本轮必要图片超过上下文附件预算，请按交付项分批选择')
            from .assets import AssetStore
            for ref in refs.values():
                asset=AssetStore(self.store).get_asset(project_id=project_id,asset_id=ref['assetId'])
                if not asset or asset['sha256']!=ref['sha256']:raise MemoryError('必要参考图已缺失或内容变更，请重新选择')
                content=Path(asset['absolutePath']).read_bytes()
                if hashlib.sha256(content).hexdigest()!=ref['sha256']:raise MemoryError('参考图文件校验失败')
                # Only the model preview is resized. Generation always receives the original file.
                from PIL import Image, ImageOps
                with Image.open(io.BytesIO(content)) as image:
                    image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1280,1280))
                    preview=io.BytesIO();image.save(preview,format='JPEG',quality=90)
                attachments.append({**ref,'mime':'image/jpeg','data':base64.b64encode(preview.getvalue()).decode()})
        context['attachments']=attachments
        return context

    def failure(self, name, project_id, task_id, error, *, role='design'):
        result={'tool':name,'status':error.code,'instruction':str(error),'validation':error.details}
        # A rejected transaction rolls back in full. Publish the current version
        # for correction, without marking the analysis complete or changing refs.
        if role=='design':
            try:
                context=self.runtime(project_id,task_id,images=True)
                result.update(revision=context['revision'],memoryContext=context)
            except MemoryError:
                pass  # Preserve the original cause if the task/asset disappeared.
        return result

    def record_output(self, project_id, task_id, result):
        """Persist only real receipts; generated images keep their artifact identity."""
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _,data,session=self._task(db,project_id,task_id)
            state=data.get('conversationMemory')
            if not state:return
            node=result.get('node') or {};asset=result.get('asset') or {}
            if not node:return
            if asset.get('id'):
                row,meta=self._asset(db,project_id,asset['id'])
                if row['kind']=='image':
                    self._write(db,session,'asset:'+asset['id'],{'content':str(node.get('data',{}).get('title') or '生成图像'),
                        'category':'asset','scope':'conversation','topic':state['topic'],'status':'observed','active':True,
                        'assetId':asset['id'],'role':'artifact','sha256':row['sha256'],'source':{'taskId':task_id,'assetId':asset['id']},
                        'sourceAssetIds':meta.get('sourceAssetIds',[])})
            progress={p['nodeId']:p for p in state.get('progress',[])}
            progress[node['id']]={'nodeId':node['id'],'title':node.get('data',{}).get('title',''),
                'assetId':asset.get('id') or result.get('assetId'),'status':result.get('status','saved'),
                'imageQuality':(asset.get('metadata') or {}).get('imageQuality'),
                'imageRoute':(asset.get('metadata') or {}).get('imageRoute'),
                'dimensions':(asset.get('metadata') or {}).get('imageOutput'),
                'referenceSnapshot':(asset.get('metadata') or {}).get('referenceSnapshot')}
            state['progress']=list(progress.values())
            self._write(db,session,'progress:'+task_id,{'content':encode([{'nodeId':p['nodeId'],'title':p['title'],'assetId':p['assetId'],'status':p['status']} for p in state['progress']]),
                'category':'progress','scope':'topic' if state['topic'] else 'conversation','topic':state['topic'],'status':'observed','active':True,'source':{'taskId':task_id}})
            state['memoryRevision']=db.execute('SELECT revision FROM conversation_memory_sessions WHERE session_id=?',(session,)).fetchone()[0]
            self._publish(db,task_id,data,state)

    def validate_generation(self, project_id, task_id, args, *, freeze=True):
        from .design_tools import image_reference_ids
        ids=image_reference_ids(args.get('source_asset_id'),args.get('source_asset_ids'))
        with self.store._connect() as db:
            task,data,session=self._task(db,project_id,task_id) if task_id else (None,{},f'project:{project_id}')
            state=data.get('conversationMemory') or {}
            if data.get('memoryProtocol') and not state.get('analyzed'):
                raise MemoryError('生成前请用 conversation_memory_update 分析本轮信息并选择实际参考；从零设计可保存空引用方案','memory_required')
            snapshots=state.get('referenceSnapshots',[])
            requested=args.get('reference_snapshot_id')
            if requested:
                snap=next((s for s in snapshots if s['id']==requested),None)
                if not snap:raise MemoryError('引用快照不属于本轮当前选择','reference_mismatch')
            else:
                item_ids=args.get('deliverable_ids') or []
                matches=[s for s in snapshots if s['deliverableId'] in item_ids]
                if len({encode(s['references']) for s in matches})>1:raise MemoryError('不同参考方案的交付项需要分别生成','reference_mismatch')
                wildcard=[s for s in snapshots if s['deliverableId']=='*']
                snap=(matches or wildcard or [None])[0]
                if snap is None and len(snapshots)==1 and len(item_ids)==1:
                    # Recover snapshots saved by older workers with an ad-hoc
                    # alias (for example "poster") when the current plan has
                    # exactly one unambiguous item. New writes are normalized
                    # before storage by _normalize_reference_bindings().
                    plan=data.get('designPlan') or data.get('planBaseline') or {}
                    known={str(item.get('id')) for item in plan.get('deliverables',[])
                           if isinstance(item,dict) and item.get('id')}
                    current=[str(identity) for identity in plan.get('currentItemIds',[]) if str(identity) in known]
                    if not current and len(known)==1:current=list(known)
                    legacy=snapshots[0]
                    if len(current)==1 and item_ids[0]==current[0] and legacy.get('deliverableId') not in known|{'*'}:
                        snap=legacy
            if state.get('analyzed') and snap is None:
                # Older workers saved references=[] as no snapshots at all.
                # Recover only an unambiguous text-only choice. Existing item
                # bindings, selected images and explicit snapshot IDs must
                # still pass the original scope and reference checks.
                empty_choice = not snapshots and not ids and not any(r.get('assetId') for r in state.get('selected', []))
                if not empty_choice:
                    raise MemoryError('请用 conversation_memory_update 为本交付项保存引用方案：deliverable_id 使用当前计划的交付项 ID；'
                                      '本轮不使用参考图时设置 references=[]，使用图片时填写已选图片的 memory_ids。', 'reference_mismatch')
            if snap and snap.get('bindingPolicy') == 'candidates':
                allowed = {r['assetId'] for r in snap['references']}
                if not set(ids).issubset(allowed):
                    raise MemoryError('实际参考图不在本轮选用候选中，请先明确选用该资料', 'reference_mismatch')
                snap = {**snap, 'references':[r for r in snap['references'] if r['assetId'] in ids]}
                snap.pop('id', None)
                snap['id'] = digest(snap)
                if freeze: db.execute('INSERT OR IGNORE INTO conversation_reference_snapshots VALUES(?,?,?)',(snap['id'],task_id,encode(snap)))
            if snap and set(ids)!={r['assetId'] for r in snap['references']}:
                submitted_ids = list(ids)
                expected_ids = list(dict.fromkeys(r['assetId'] for r in snap['references']))
                analyzed = {
                    str(image.get('asset_id')): image
                    for image in ((args.get('reference_analysis') or {}).get('images') or [])
                    if isinstance(image, dict) and image.get('asset_id')
                }
                # The saved per-item binding is authoritative. If the Agent has
                # already inspected and described every bound image, reconcile
                # its transport list locally instead of spending another model
                # turn restating the same IDs. Never invent an analysis for a
                # missing image: that still returns a precise repair request.
                if (expected_ids and set(submitted_ids).issubset(expected_ids)
                        and set(expected_ids).issubset(analyzed)):
                    ids = expected_ids
                    args['source_asset_id'] = ids[0] if ids else None
                    args['source_asset_ids'] = ids
                    analysis = dict(args.get('reference_analysis') or {})
                    analysis['images'] = [analyzed[identity] for identity in ids]
                    args['reference_analysis'] = analysis
                    resolution = args.get('_image_resolution')
                    if isinstance(resolution, dict):
                        origins = resolution.setdefault('origins', {})
                        for identity in ids:
                            origins.setdefault(identity, ['memory_binding'])
                        resolution['memoryReconciliation'] = {
                            'submittedAssetIds': submitted_ids,
                            'expectedAssetIds': ids,
                        }
                else:
                    missing = [identity for identity in expected_ids if identity not in ids]
                    unexpected = [identity for identity in ids if identity not in expected_ids]
                    instruction = (
                        '实际参考图与本轮引用方案不一致。请将 source_asset_ids 调整为 expectedAssetIds，'
                        '并为 missingAssetIds 中每张图片补齐 reference_analysis；不要猜测或缩写资产 ID。'
                    )
                    raise MemoryError(instruction, 'reference_mismatch', details={
                        'field': 'source_asset_ids',
                        'deliverableId': snap.get('deliverableId'),
                        'expectedAssetIds': expected_ids,
                        'actualAssetIds': submitted_ids,
                        'missingAssetIds': missing,
                        'unexpectedAssetIds': unexpected,
                        'instruction': instruction,
                    })
            refs=[]
            for identity in ids:
                asset,_=self._asset(db,project_id,identity)
                root=db.execute('SELECT root_path FROM projects WHERE id=?',(project_id,)).fetchone()[0]
                path=Path(root)/asset['path_relative']
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
                    raise MemoryError('引用文件缺失或哈希不一致','reference_missing')
                refs.append({'assetId':identity,'sha256':asset['sha256'],'role':'input','purpose':'本次显式参考'})
            if snap:
                if {r['assetId']:r['sha256'] for r in refs}!={r['assetId']:r['sha256'] for r in snap['references']}:raise MemoryError('引用内容与快照版本不一致','reference_mismatch')
                return snap
            value={'taskId':task_id,'deliverableId':'*','references':refs};value['id']=digest(value)
            if freeze:db.execute('INSERT OR IGNORE INTO conversation_reference_snapshots VALUES(?,?,?)',(value['id'],task_id,encode(value)))
            return value

    def execute(self, name, project_id, task_id, args, *, role='design', operation_id=None):
        if not task_id:raise MemoryError('对话记忆需要真实任务')
        if name==TOOLS[1]:
            if role!='design':raise MemoryError('研究、审查和修复角色只读对话记忆')
            result=self.update(project_id,task_id,args,operation_id or digest(args))
        else:
            if role!='design':
                state=self.bootstrap(project_id,task_id)
                records=state['selected']
                if args.get('ids'):records=[r for r in records if r['id'] in args['ids'] or r['key'] in args['ids']]
                result={'status':'read','records':records,'state':state,'revision':state['memoryRevision'],'snapshotOnly':True}
            else:result={'status':'read',**self.read(project_id,task_id,**args)}
            from .canvas import CanvasStore
            from .task_focus import TaskFocus
            TaskFocus(self.store,CanvasStore(self.store)).remember_candidates(project_id,task_id,'asset',
                [r['assetId'] for r in result['records'] if r.get('assetId')],limit=None)
        context=self.runtime(project_id,task_id,images=True)
        if role!='design':
            context.update(catalog=context['selected'],revision=context['memoryRevision'],nextOffset=None,catalogTotal=len(context['selected']))
        return {'tool':name,**result,'memoryContext':context}
