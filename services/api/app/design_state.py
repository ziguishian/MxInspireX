"""Versioned user decisions and task continuation, derived from project records.

Snapshots live with each task. Original user messages remain the audit source;
model proposals never silently become user-confirmed requirements.
"""
import copy
import hashlib
import json
import re


def field_key(question, identity=''):
    text = str(question).lower()
    patterns = [('quantity', r'多少套|数量|制作.*套|quantity'),
                ('budget_scope', r'预算.*包含|费用.*包含|全包|budget.scope'),
                ('audience', r'赠送对象|礼赠对象|面向.*(?:嘉宾|贵宾)|audience'),
                ('official_identity', r'六色|官方.*(?:色|vi|标志)|色值|视觉规范'),
                ('dimensions', r'尺寸|纸材厚度|刀版.*比例|刀模.*比例'),
                ('budget', r'预算|budget')]
    # Bundled questions have their own identity: a quantity answer must not
    # falsely confirm the budget scope asked in the same sentence.
    matches = [key for key, pattern in patterns if re.search(pattern, text)]
    if len(matches) == 1 or matches == ['budget_scope', 'budget']:
        return matches[0]
    return 'question:' + hashlib.sha256(re.sub(r'\s|[？?。，,]', '', text).encode()).hexdigest()[:16]


def continuation_request(brief):
    text = str(brief).strip()
    if re.search(r'重新开始|新项目|换个需求|另做|另一个项目', text): return False
    from .design_batches import explicit_batch_intent
    if explicit_batch_intent(text): return True
    return bool(re.fullmatch(r'(?:好的?[，,。！!\s]*)?(?:好|好的|可以|继续|开始吧|没问题|确认|就这样|ok|OK)[。！!\s]*', text)
                or re.match(r'^(?:好的?[，,。!！\s]*)?(?:请|你|帮我|麻烦)?(?:按(?:照)?(?:你|原|刚才|这个|已确认|上述|计划|方案)|继续|接着|下一步)', text))


def acceptance_only(brief):
    if re.fullmatch(r'(?:请)?(?:继续|接着)(?:原|当前|上次|之前|已确认的)?(?:设计)?(?:任务|方案|计划)[。！!\s]*', str(brief).strip()):
        return True
    return bool(re.fullmatch(r'(?:好的?[，,。！!\s]*)?(?:好|好的|可以|继续|开始吧|没问题|确认|就这样|ok|OK|(?:请|你)?按(?:照)?(?:原)?(?:计划|方案)(?:继续|执行|生成(?:全部|所有)(?:图像|图片))?)[。！!\s]*', str(brief).strip()))


def review_request(context):
    """Pure acceptance can reuse the goal; additional instructions must recheck."""
    brief = context.get('userMessage', '').strip()
    if context.get('continuation') and acceptance_only(brief):
        return context.get('designState', {}).get('goal') or brief
    return brief


def _load(row, key):
    return json.loads(row[key] or '{}') if row else {}


def _validated_review_revision(store, project_id, requested):
    """Resolve a user-clicked repair target from server-owned review evidence.

    The browser may request a revision, but it cannot choose an arbitrary asset
    or manufacture a defect.  Only a persisted reviewer error with a concrete
    repair contract can become a normal ``DesignBatch.intent=revise`` turn.
    """
    if not isinstance(requested, dict):
        raise ValueError('审查修订信息无效，请从对应检查项重新发起')
    task_id = str(requested.get('sourceTaskId') or '').strip()
    node_id = str(requested.get('nodeId') or '').strip()
    code = str(requested.get('code') or '').strip()
    if not task_id or not node_id or not code:
        raise ValueError('审查修订缺少来源任务、节点或问题标识')
    with store._connect() as db:
        source = db.execute("SELECT * FROM tasks WHERE id=? AND project_id=? AND agent_key='design' AND status='succeeded'",
                            (task_id, project_id)).fetchone()
    if not source:
        raise ValueError('审查修订对应的已完成任务不存在或不属于当前项目')
    structured = _load(source, 'output_json').get('structured_data') or {}
    review = structured.get('review') or {}
    report = structured.get('delivery') or {}
    artifact = next((item for item in report.get('artifacts') or []
                     if item.get('nodeId') == node_id and item.get('assetId') and item.get('ready')
                     and item.get('kind') == 'image'), None)
    if not artifact:
        raise ValueError('该审查项没有可作为来源的已保存图像，请刷新后重新选择')
    check = next((item for item in review.get('checks') or []
                  if item.get('status') == 'error' and item.get('artifactId') == node_id
                  and (item.get('code') or f"review_{item.get('category', 'content')}_error") == code), None)
    repair = check.get('repair') if isinstance(check, dict) else None
    if not isinstance(repair, dict) or not str(repair.get('change') or '').strip():
        raise ValueError('该检查项缺少可定点执行的修订建议，不能自动创建修订')
    fingerprint = str(artifact.get('fingerprint') or '')
    requested_fingerprint = str(requested.get('artifactFingerprint') or '')
    if requested_fingerprint and requested_fingerprint != fingerprint:
        raise ValueError('该产物版本已变化，请查看当前检查结果后再创建修订')
    preserve = [str(item).strip()[:300] for item in repair.get('preserve') or [] if str(item).strip()][:8]
    return source, {
        'sourceTaskId': task_id, 'nodeId': node_id, 'planItemId': check.get('planItemId'),
        'code': code, 'category': check.get('category') or 'content', 'sourceAssetId': artifact['assetId'], 'artifactFingerprint': fingerprint,
        'repair': {'change': str(repair['change']).strip()[:700], 'preserve': preserve},
    }


def prepare_state(store, project_id, brief, inputs, source=None, *, before_task_id=None, reference_continuation=False):
    """Return trusted server context; callers must discard client snapshots."""
    requested_revision = inputs.get('reviewRevision')
    if requested_revision is not None:
        source, revision = _validated_review_revision(store, project_id, requested_revision)
        inputs['reviewRevision'] = revision
        refs = [item for item in inputs.get('referencedAssets') or [] if isinstance(item, dict)
                and str(item.get('id') or item.get('assetId')) != revision['sourceAssetId']]
        refs.append({'id': revision['sourceAssetId'], 'projectId': project_id, 'referenceMode': 'edit',
                     'nodeId': revision['nodeId']})
        inputs['referencedAssets'] = refs
        # A click is the user's confirmation that this specific, de-identified
        # repair strategy is worth executing. It never stores client copy,
        # source pixels or prompts and has no effect on project conversation memory.
        from .reference_library import ReferenceLibraryStore
        ReferenceLibraryStore(store).record_confirmed_revision(revision)
        inputs['designLessons'] = ReferenceLibraryStore(store).search_lessons(brief, media_kind='image', limit=3)
    with store._connect() as db:
        cutoff = db.execute('SELECT created_at,COALESCE(turn_order,rowid) AS position FROM tasks WHERE id=? AND project_id=?', (before_task_id, project_id)).fetchone() if before_task_id else None
        where, args = ('AND (created_at<? OR (created_at=? AND COALESCE(turn_order,rowid)<?))', (cutoff['created_at'], cutoff['created_at'], cutoff['position'])) if cutoff else ('', ())
        candidates = db.execute(f"SELECT * FROM tasks WHERE project_id=? AND agent_key='design' AND superseded_by IS NULL {where} ORDER BY created_at DESC,COALESCE(turn_order,rowid) DESC", (project_id, *args)).fetchall()
        latest = next((row for row in candidates if _load(row, 'input_json').get('taskSurface', 'conversation') != 'canvas_node'), None)
    source = source or (latest if continuation_request(brief) else None)
    previous = _load(source, 'input_json')
    from .design_planning import planning_profile
    recent = _load(latest, 'input_json') if not (not source and planning_profile(brief)) and not re.search(r'重新开始|新项目|换个需求|另做|另一个项目', brief) else {}
    # Decisions are scoped to the same active goal, not all historical projects.
    state = copy.deepcopy(previous.get('designState') or recent.get('designState') or {'version': 1, 'revision': 0, 'goal': previous.get('userMessage') or brief, 'decisions': {}})
    # Only a plain acceptance can reuse the derived wording. Clarification
    # answers, edits and follow-up changes must be understood afresh.
    # Only the server-validated reference-card submission may set this flag.
    # Choosing/skipping references resumes the same deliverables, while new
    # notes may require fresh visual judgement and reference analysis.
    reference_resume = bool(reference_continuation and source and inputs.get('referenceWorkflow', {}).get('status') in {'selected', 'skipped'})
    plain_resume = acceptance_only(brief) or reference_resume
    if not (source and plain_resume and not inputs.get('referenceWorkflow', {}).get('notes') and not re.search(r'图像|图片', brief)):
        state.pop('brief', None)
    if source:
        state['goal'] = state.get('goal') or previous.get('userMessage', brief)
        inputs['continuation'] = {'taskId': source['id'], 'goal': state['goal']}
        plan = previous.get('designPlan') or previous.get('planBaseline')
        if plan:
            inputs['planBaseline'] = copy.deepcopy(plan)
            inputs['planBaselineTaskId'] = previous.get('planBaselineTaskId') or source['id']
            inputs['planAccepted'] = bool(plan.get('ready') and plain_resume)
            if inputs['planAccepted']:
                inputs['designPlan'] = copy.deepcopy(plan)
                # "Generate all images" continues the relevant part of the
                # accepted plan without requiring unrelated files again.
                if re.search(r'(?:全部|所有).*?(?:图像|图片)', brief):
                    items = [d for d in plan['deliverables'] if d['kind'] == 'image']
                    if items: inputs['designPlan']['deliverables'] = items
        if plain_resume:
            for key in ('deliveryContract', 'requiredArtifacts'):
                if previous.get(key): inputs[key] = copy.deepcopy(previous[key])
            if re.search(r'(?:全部|所有).*?(?:图像|图片)', brief):
                inputs['deliveryContract'] = [item for item in inputs.get('deliveryContract', []) if item['kind'] == 'image']
                inputs['requiredArtifacts'] = ['image']
        for key in ('referencedAssets', 'referencedNodes', 'referencedFiles'):
            if not inputs.get(key) and previous.get(key): inputs[key] = copy.deepcopy(previous[key])
        from .design_batches import prepare, explicit_batch_intent
        if plain_resume or explicit_batch_intent(brief):
            prepare(store, project_id, source, previous, inputs, brief)
            batch = inputs.get('designBatch') or {}
            if batch.get('intent') in {'next_batch', 'revise'}:
                # Old quantity/format contracts describe the preceding batch.
                for key in ('deliveryContract', 'requiredArtifacts'):
                    inputs.pop(key, None)
            elif re.search(r'(?:全部|所有).*?(?:图像|图片)', brief) and inputs.get('designPlan'):
                items = [d for d in inputs['designPlan']['deliverables'] if d['kind'] == 'image']
                inputs['designPlan']['deliverables'] = items
                batch['itemIds'] = [d['id'] for d in items]
                from .design_batches import set_progress
                set_progress(inputs, [r for r in inputs.get('deliveryProgress', []) if r['id'] in batch['itemIds']])
    # Lessons are workspace-local, confirmed process notes. They are merely
    # candidates for a design plan and never replace the user's brief, a real
    # source or the project-scoped conversation memory.
    if not inputs.get('designLessons') and planning_profile(brief, inputs):
        from .reference_library import ReferenceLibraryStore
        inputs['designLessons'] = ReferenceLibraryStore(store).search_lessons(brief, media_kind='image', limit=3)
    state['revision'] += 1
    inputs['designState'] = state
    return source


def apply_answers(state, source, answers, task_id, created_at):
    if answers is not None and (not isinstance(answers, list) or any(not isinstance(answer, dict) for answer in answers)):
        raise ValueError('补充答案必须是结构化答案列表')
    if answers:
        state.pop('brief', None)
    questions = _load(source, 'output_json').get('structured_data', {}).get('clarification', {}).get('questions', [])
    allowed = {str(q.get('id', index)): q for index, q in enumerate(questions)}
    seen = set()
    for answer in answers or []:
        identity = str(answer.get('questionId', ''))
        index = answer.get('questionIndex')
        if index is not None:
            if not isinstance(index, int) or not 0 <= index < len(questions) or str(questions[index].get('id', index)) != identity: raise ValueError('补充答案与原问题不匹配')
            question = questions[index]
        else:
            if identity not in allowed: raise ValueError('补充答案与原问题不匹配')
            question = allowed[identity]
        marker = index if index is not None else identity
        if marker in seen: raise ValueError('补充答案重复')
        seen.add(marker)
        value = str(answer.get('value', '')).strip()
        if len(value) > 4000: raise ValueError('补充答案过长')
        skipped = answer.get('skipped') is True
        if not value and not skipped: raise ValueError('补充答案为空')
        key = field_key(question['question'], identity)
        if key.startswith('question:'):
            if re.search(r'数量|多少套', question['question']) and re.search(r'\d[^，。；\n]*套', value): key = 'quantity'
            elif re.search(r'预算.*包含', question['question']) and re.search(r'全部包含|全包', value): key = 'budget_scope'
        old = state['decisions'].get(key)
        if skipped and old and old['status'] == 'confirmed': continue
        state['decisions'][key] = {'field': key, 'label': question['question'], 'value': value,
            'status': 'skipped' if skipped else 'unknown' if re.search(r'尚未|暂未|暂无|不确定|待确认|不知道', value) else 'confirmed',
            'sourceTaskId': task_id, 'questionId': identity, 'quote': value, 'updatedAt': created_at}


def read_state(store, project_id, task_id):
    with store._connect() as db:
        row = db.execute('SELECT input_json FROM tasks WHERE project_id=? AND id=?', (project_id, task_id)).fetchone()
    if not row: raise ValueError('任务不存在')
    return json.loads(row[0]).get('designState') or {'version': 1, 'revision': 0, 'decisions': {}}


def record_decisions(store, project_id, task_id, decisions, *, brief=None):
    from .design_brief import normalize_brief
    derived = normalize_brief(brief, task_id) if brief is not None else None
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT input_json,created_at FROM tasks WHERE project_id=? AND id=?', (project_id, task_id)).fetchone()
        if not row: raise ValueError('任务不存在')
        data = json.loads(row['input_json'])
        state = data.get('designState') or {'version': 1, 'revision': 0, 'goal': data.get('userMessage', ''), 'decisions': {}}
        for decision in decisions:
            key, value = str(decision.get('field', '')), str(decision.get('value', '')).strip()
            if not re.fullmatch(r'[a-z][a-z0-9_:.-]{0,79}', key) or not value or len(value) > 1000: raise ValueError('需求字段或内容无效')
            status = decision.get('status', 'assumed')
            if status not in {'confirmed', 'assumed', 'unknown'}: raise ValueError('无效的需求状态')
            quote = str(decision.get('quote', '')).strip()
            source_id = decision.get('sourceTaskId') or task_id
            source = db.execute('SELECT input_json,created_at FROM tasks WHERE id=? AND project_id=? AND created_at<=?', (source_id, project_id, row['created_at'])).fetchone()
            if not source: raise ValueError('需求来源不属于当前项目历史')
            user = json.loads(source['input_json']).get('userMessage', '')
            if status != 'assumed' and (not quote or quote not in user or value not in quote):
                raise ValueError('确认需求必须逐字引用用户原文，不能把模型推测标为已确认')
            old = state['decisions'].get(key)
            if old and old['status'] == 'confirmed' and (status == 'assumed' or source['created_at'] < old['updatedAt']):
                raise ValueError('旧记录或临时假设不能覆盖已确认需求')
            state['decisions'][key] = {'field': key, 'label': str(decision.get('label') or key)[:150], 'value': value,
                'status': status, 'quote': quote, 'sourceTaskId': source_id, 'updatedAt': source['created_at']}
        if derived is not None:
            state['brief'] = derived
        elif decisions:
            # Changed constraints invalidate a previously written summary.
            state.pop('brief', None)
        state['revision'] += 1
        data['designState'] = state
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(data, ensure_ascii=False), task_id))
    return state


def unanswered_questions(state, questions):
    retained, answered = [], []
    for question in questions:
        key = field_key(question['question'], question.get('id', ''))
        existing = state.get('decisions', {}).get(key)
        # Even "not supplied" is an answer. Ask about a new specific dependency,
        # rather than endlessly asking whether the same VI file exists.
        if existing and existing['status'] in {'confirmed', 'unknown', 'skipped'}:
            answered.append(existing)
        else: retained.append(question)
    return retained, answered
