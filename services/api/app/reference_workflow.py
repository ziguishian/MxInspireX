"""Trusted reference choices and the generation prerequisite shared by all tools."""
import json
import re
from uuid import uuid4, uuid5, NAMESPACE_URL

from .agent_contracts import AgentResult, utc_now
from .reference_library import ReferenceLibraryStore, ReferenceError

REFERENCE_ASPECTS = ('造型语言', '材质工艺', '色彩关系', '构图/信息层级', '光影摄影', '排版字体')
LEGACY_ASPECTS = {'配色': '色彩关系', '构图': '构图/信息层级', '排版': '排版字体', '材质': '材质工艺', '字体': '排版字体', '整体风格': '造型语言'}


def loads(value):
    return json.loads(value or '{}')


def is_question(brief):
    return bool(re.match(r'^(?:请)?(?:解释|介绍|什么是|如何|怎么|为什么|what|how|why)', brief.strip(), re.I) or re.search(r'包含什么|包括什么|有什么区别', brief))


def wants_visual(brief, context):
    from .task_policy import delivery_requirements, is_skill_management, is_schedule_management
    if is_skill_management(brief, context) or is_schedule_management(brief, context) or context.get('deliveryReviewOnly') or context.get('deliveryRepairOnly'):
        return False
    kind = (context.get('canvasParams') or {}).get('kind')
    if not kind and is_question(brief):
        return False
    if kind in {'audio', 'text', 'cad'}:
        return False
    return kind in {'image', 'html', 'video', '3d'} or bool(set(delivery_requirements(brief, context)) & {'image', 'html', 'video', '3d'}) or bool(re.search(r'(?:设计|制作|创作|做).{0,30}(?:包装|礼盒|文创|品牌|海报|导视|插画|标志|logo|IP)|(?:包装|礼盒|文创|品牌|海报|导视|插画).{0,15}设计', brief, re.I))


def skips_references(text):
    from .task_policy import delivery_request_spans
    # Quoted copy/reference material is not an instruction to skip selection.
    text = re.sub(r'```[\s\S]*?```|`[^`]*`|“[^”]*”|「[^」]*」|"[^"\n]*"|(?m:^\s*>.*$)', '', str(text))
    if re.search(r'(?:不要|不能|请勿|不许)跳过(?:参考|风格)', text):
        return False
    positive, _ = delivery_request_spans(text)
    direct = re.search(r'直接\s*(?:生成|制作|创作|创建|画|完成(?:设计|单页|网页|页面))|\b(?:generate|create|make)\b.{0,30}\bdirectly\b', positive, re.I)
    explicit_skip = re.search(r'(?<!不)(?<!不要)(?<!不能)(?<!请勿)跳过(?:参考|风格)?|(?:无需|不必|不用|不要|不需要)(?:再|另外)?(?:联网(?:研究|搜索)?\s*(?:或|和|与|及|、)\s*)?(?:寻找|搜索|查找|找|选|搜)?(?:外部|新的)?参考', text)
    # A request to find/select references still takes precedence over "then generate directly".
    asks_references = re.search(r'(?:先|需要|请)?(?:寻找|搜索|查找|选择|找|选)\s*(?:外部|新的|视觉|风格)?参考', positive)
    no_discovery = re.search(r'(?:不做|不进行|无需|不用|不需要)(?:联网)?(?:研究|调研|搜索)', text)
    return bool(explicit_skip or (direct or no_discovery) and not asks_references)


def parse_choice(text, card):
    if skips_references(text):
        return {'id': card['id'], 'action': 'skip', 'notes': text}
    if re.search(r'换一批|重新(?:找|搜)|更多参考', text):
        return {'id': card['id'], 'action': 'refresh', 'notes': text}
    if re.search(r'还是|或者|不确定|也许|不喜欢|不要第', text):
        return None
    matches = list(re.finditer(r'第?\s*([0-9]+|[一二三四五六七八九十]+)\s*张', text))
    selected = []
    for index, match in enumerate(matches):
        value = match.group(1)
        number = int(value) if value.isdigit() else '一二三四五六'.find(value) + 1 if len(value) == 1 else 0
        if not 1 <= number <= len(card['items']):
            return None
        section = text[match.end():matches[index+1].start() if index+1 < len(matches) else len(text)]
        aliases = {'配色':'色彩关系', '构图':'构图/信息层级', '排版':'排版字体', '材质':'材质工艺', '字体':'排版字体', '整体风格':'造型语言'}
        aspects = list(dict.fromkeys(aliases[a] for a in aliases if a in section))
        selected.append({'id': card['items'][number-1]['id'], 'aspects': aspects or ['造型语言']})
    return {'id': card['id'], 'action': 'confirm', 'selected': selected, 'notes': text} if selected else None


class ReferenceWorkflow:
    def __init__(self, store, assets=None):
        self.store = store
        self.library = ReferenceLibraryStore(store)
        from .assets import AssetStore
        self.assets = assets or AssetStore(store)

    def prepare(self, project_id, brief, inputs):
        """Rebuild choices from saved server rows, never accept a client status."""
        for key in ('referenceWorkflow', 'referenceCandidates', 'referenceContinuationTaskId', 'referenceQuestion', 'referenceSearchCache'):
            inputs.pop(key, None)
        selection = inputs.pop('referenceSelection', None)
        with self.store._connect() as db:
            candidates = db.execute("SELECT * FROM tasks WHERE project_id=? AND agent_key='design' AND superseded_by IS NULL ORDER BY created_at DESC,COALESCE(turn_order,rowid) DESC", (project_id,)).fetchall()
            latest = next((row for row in candidates if json.loads(row['input_json'] or '{}').get('taskSurface', 'conversation') != 'canvas_node'), None)
        old = loads(latest['input_json']) if latest else {}
        previous = old.get('referenceWorkflow', {})
        # Requirement answers are restored from their source by TaskRuntime;
        # never interpret them as a reference-card selection or refresh.
        # A review revision already has one server-validated source image and
        # a user-confirmed, narrow target. It must not be diverted into a new
        # reference-selection card before the ordinary revise batch is made.
        if inputs.get('clarificationTaskId') or inputs.get('reviewRevision'):
            return None
        if not selection and not (inputs.get('canvasParams') or {}).get('kind') and is_question(brief):
            inputs['referenceQuestion'] = True
            if previous:
                inputs['referenceWorkflow'] = previous
            return None
        latest_card = loads(latest['output_json']).get('structured_data', {}).get('referenceSelection') if latest else None
        if latest_card and not latest_card.get('items'):
            latest_card = None
        if not latest_card and previous.get('status') == 'required':
            with self.store._connect() as db:
                pending = db.execute("SELECT data_json FROM reference_selections WHERE project_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
            latest_card = loads(pending[0]) if pending else None
            if latest_card and not latest_card.get('items'):
                latest_card = None
        new_goal = bool(re.search(r'重新开始|新项目|换个需求|另做|另一个项目', brief))
        if not selection and latest_card and not new_goal:
            selection = parse_choice(brief, latest_card)
            if not selection:
                inputs['referenceWorkflow'] = {'status': 'required', 'query': previous.get('query') or brief, 'exclude': latest_card.get('excludedIds', []), 'notice': '可选择下列图片，填写“第2张的配色”，或明确跳过参考。'}
        if selection:
            return self._submit(project_id, selection, inputs)
        changing = bool(re.search(r'换.{0,5}风格|重新选|更换参考', brief))
        from .design_state import continuation_request
        continuing = continuation_request(brief) or bool(re.search(r'修改|调整|改成|改为|再加|保持|延续|沿用', brief)) or bool((inputs.get('canvasParams') or {}).get('canvasNodeId'))
        supplied = [a.get('id') for a in inputs.get('referencedAssets', []) if isinstance(a, dict)]
        supplied += [(inputs.get('canvasParams') or {}).get('source_asset_id'), *((inputs.get('canvasParams') or {}).get('source_asset_ids') or [])]
        explicit = bool(self.assets and any((self.assets.get_asset(project_id=project_id, asset_id=aid) or {}).get('mime', '').startswith('image/') for aid in supplied if aid))
        if not new_goal and not changing and continuing and previous.get('status') in {'selected', 'skipped', 'provided'}:
            inputs['referenceWorkflow'] = previous
            if previous.get('assetIds'):
                existing = inputs.get('referencedAssets') or []
                inputs['referencedAssets'] = existing + [{'id': identity, 'projectId': project_id} for identity in previous['assetIds'] if identity not in {a.get('id') for a in existing}]
        elif explicit and not changing:
            inputs['referenceWorkflow'] = {'status': 'provided'}
        elif skips_references(brief):
            inputs['referenceWorkflow'] = {'status': 'skipped'}
        elif wants_visual(brief, inputs) or changing or latest_card and not new_goal:
            inputs.setdefault('referenceWorkflow', {'status': 'required', 'query': brief, 'exclude': []})
        return None

    def _submit(self, project_id, selection, inputs):
        if not isinstance(selection, dict):
            raise ReferenceError('参考选择格式无效')
        with self.store._connect() as db:
            row = db.execute('SELECT * FROM reference_selections WHERE id=? AND project_id=?', (str(selection.get('id', '')), project_id)).fetchone()
            source = db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?', (row['task_id'], project_id)).fetchone() if row else None
        if not row or not source or source['status'] != 'succeeded':
            raise ReferenceError('参考选择对应的任务不存在或尚未完成')
        card = loads(row['data_json'])
        action = selection.get('action')
        if action not in {'confirm', 'skip', 'refresh'}:
            raise ReferenceError('请选择参考、换一批或跳过')
        chosen = selection.get('selected') or []
        if action == 'confirm' and not chosen:
            parsed = parse_choice(str(selection.get('notes') or ''), card)
            chosen = parsed.get('selected', []) if parsed and parsed['action'] == 'confirm' else []
        allowed = {item['id'] for item in card['items']}
        if not isinstance(chosen, list) or any(not isinstance(i, dict) or i.get('id') not in allowed for i in chosen):
            raise ReferenceError('只能选择当前批次中展示的参考图')
        if action == 'confirm' and not chosen:
            raise ReferenceError('请选择至少一张参考图，或填写明确的图片序号')
        if any(not isinstance(i.get('aspects', []), list) for i in chosen):
            raise ReferenceError('借鉴要点必须是列表')
        normalized_aspects = []
        for item in chosen:
            aspects = [LEGACY_ASPECTS.get(str(a)[:50], str(a)[:50]) for a in item.get('aspects', [])]
            aspects = [aspect for aspect in aspects if aspect in REFERENCE_ASPECTS]
            normalized_aspects.append({'id': item['id'], 'aspects': list(dict.fromkeys(aspects)) or ['造型语言']})
        normalized = {'action': action, 'selected': normalized_aspects, 'notes': str(selection.get('notes') or '')[:4000]}
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        task_id = uuid5(NAMESPACE_URL, f'reference:{project_id}:{row["id"]}:{encoded}').hex
        if row['submission_json'] and row['submission_json'] != encoded:
            raise ReferenceError('该批参考已处理，请在最新对话中更换方向')
        original = loads(source['input_json'])
        for key in ('referencedAssets', 'referencedNodes', 'referencedFiles', 'canvasParams', 'requiredArtifacts', 'deliveryContract', 'imageStyle', 'designPlanning', 'textProvider', 'mediaProvider', 'modelRouting', 'allowExternalNetwork'):
            if key in original:
                inputs[key] = original[key]
        asset_ids, choice_assets = [], {}
        if action == 'confirm':
            for item in chosen:
                asset = self.library.project_asset(project_id, item['id'], self.assets)
                choice_assets[item['id']] = asset['id']
                if asset['id'] not in asset_ids:
                    asset_ids.append(asset['id'])
            inputs['referencedAssets'] = [*(inputs.get('referencedAssets') or []), *({'id': aid, 'projectId': project_id} for aid in asset_ids)]
        state = {'status': {'confirm': 'selected', 'skip': 'skipped', 'refresh': 'required'}[action],
                 'selectionId': row['id'], 'assetIds': asset_ids, 'choices': [{**i, 'assetId': choice_assets.get(i['id'])} for i in normalized['selected']], 'notes': normalized['notes'],
                 'query': original.get('referenceWorkflow', {}).get('query') or original.get('userMessage', ''),
                 'exclude': list(dict.fromkeys([*card.get('excludedIds', []), *allowed])) if action == 'refresh' else []}
        inputs['referenceWorkflow'] = state
        inputs['referenceContinuationTaskId'] = source['id']
        with self.store._connect() as db:
            updated = db.execute('UPDATE reference_selections SET status=?,submission_json=?,continuation_task_id=? WHERE id=? AND (submission_json IS NULL OR submission_json=?)', (action, encoded, task_id, row['id'], encoded)).rowcount
            if not updated:
                raise ReferenceError('参考选择已在另一处更新，请刷新对话')
            # Keep a recoverable submission on the source card, including if a
            # process stops between this receipt and enqueueing its continuation.
            card.update(selected=normalized['selected'], notes=normalized['notes'], submittedAction=action)
            db.execute('UPDATE reference_selections SET data_json=? WHERE id=?', (json.dumps(card, ensure_ascii=False), row['id']))
            output = loads(source['output_json'])
            output.setdefault('structured_data', {})['referenceSelection'] = card
            db.execute('UPDATE tasks SET output_json=? WHERE id=?', (json.dumps(output, ensure_ascii=False), source['id']))
        return {'taskId': task_id, 'source': source}

    def present(self, project_id, task_id, items, *, intro='选几张你喜欢的参考，也可以只借鉴其中的配色或构图。', errors=None):
        with self.store._connect() as db:
            existing = db.execute('SELECT data_json FROM reference_selections WHERE task_id=?', (task_id,)).fetchone()
            task = db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if existing and loads(existing[0]).get('items'):
            return loads(existing[0])
        if not task:
            raise ReferenceError('参考选择必须关联当前项目任务')
        context = loads(task[0])
        if not items:
            from .reference_efficiency import empty_reference_fallback
            if not empty_reference_fallback(context):
                context['referenceWorkflow'] = {**context.get('referenceWorkflow', {}), 'status': 'unavailable',
                    'reason': 'no_reference_candidates', 'notice': '没有可供选择的参考案例，不展示选择卡；保留用户资料及原有设计约束。'}
            with self.store._connect() as db:
                db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context, ensure_ascii=False), task_id))
            return None
        safe_items = []
        for item in items[:6]:
            actual = self.library.get(item['id'])
            self.library.path(item['id'], True)
            safe_items.append({**actual, **{k: item[k] for k in ('reason', 'direction', 'evidenceType', 'visuallyRanked') if k in item}})
        card = {'id': uuid4().hex, 'taskId': task_id, 'intro': intro, 'items': safe_items, 'errors': errors or [],
                'excludedIds': context.get('referenceWorkflow', {}).get('exclude', []), 'status': 'pending'}
        with self.store._connect() as db:
            db.execute('INSERT OR IGNORE INTO reference_selections(id,project_id,task_id,data_json,created_at) VALUES (?,?,?,?,?)', (card['id'], project_id, task_id, json.dumps(card, ensure_ascii=False), utc_now()))
            card = loads(db.execute('SELECT data_json FROM reference_selections WHERE task_id=?', (task_id,)).fetchone()[0])
        return card

    def use_attachments(self, registry, project_id, task_id, attachments):
        """Recognize supplied images without searching or presenting a card."""
        context = registry._task_input(project_id, task_id)
        state = context.get('referenceWorkflow', {})
        if state.get('status') == 'required' and not state.get('selectionId') and any(str(a.get('mime', '')).startswith('image/') and a.get('assetId') for a in attachments):
            state = context['referenceWorkflow'] = {'status': 'provided'}
            with self.store._connect() as db:
                db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context, ensure_ascii=False), task_id))
        return state

    def preflight(self, registry, project_id, task_id, attachments=()):
        if attachments:
            self.use_attachments(registry, project_id, task_id, attachments)
        context = registry._task_input(project_id, task_id)
        state = context.get('referenceWorkflow', {})
        if state.get('status') != 'required':
            return None
        with self.store._connect() as db:
            saved = db.execute('SELECT data_json FROM reference_selections WHERE task_id=?', (task_id,)).fetchone()
        if saved and loads(saved[0]).get('items'):
            return AgentResult(status='succeeded', structured_data={'answer': '选择参考后继续设计，也可以明确跳过。', 'referenceSelection': loads(saved[0])})
        if saved:
            self.present(project_id, task_id, [])
            return None
        result = reference_search(registry, project_id=project_id, task_id=task_id, query=state.get('query') or context.get('userMessage', ''), source='auto', exclude=state.get('exclude', []))
        card = self.present(project_id, task_id, result['items'], errors=result.get('errors'))
        if card is None:
            return None
        return AgentResult(status='succeeded', structured_data={'answer': '先确定你倾向的视觉方向，选择参考后我会继续设计。' if card['items'] else '暂时没有找到可用参考。你可以上传图片、换个描述继续找，或跳过参考开始设计。', 'referenceSelection': card})


def reference_search(registry, *, project_id, task_id, query, source='auto', industry='', design_type='', exclude=None, **_):
    if source not in {'local', 'web', 'auto'}:
        raise ReferenceError('参考来源必须是 local、web 或 auto')
    library = getattr(registry, 'reference_library', None) or ReferenceLibraryStore(registry.store)
    context = registry._task_input(project_id, task_id)
    excluded = list(dict.fromkeys([*(exclude or []), *context.get('referenceWorkflow', {}).get('exclude', [])]))
    from .reference_efficiency import empty_reference_fallback, optional_simple_reference
    # Simple original concepts need no paid web discovery. Consult the local
    # library once; explicit research/reference requests keep the full path.
    if source == 'auto' and optional_simple_reference(context):
        source = 'local'
    fallback = empty_reference_fallback(context)
    if fallback:
        with registry.store._connect() as db:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context, ensure_ascii=False), task_id))
        return fallback
    signature = [str(query).strip(), source, industry, design_type, sorted(excluded)]
    for cached in context.get('referenceSearchCache', []):
        if cached['signature'] == signature:
            return {**cached['result'], 'cached': True}
    items = library.search(query, industry, design_type, excluded, limit=24)['items'] if source != 'web' else []
    analyzer = getattr(registry, 'reference_analyzer', None)
    errors = []
    if analyzer and source != 'web':
        try:
            extra = analyzer.semantic_candidates(query, excluded)
            items += [i for i in extra if i['id'] not in {r['id'] for r in items} and (not industry or industry in i.get('industries', [])) and (not design_type or design_type in i.get('designTypes', []))]
        except Exception:
            pass
    def cancelled():
        with registry.store._connect() as db:
            row = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
        return not row or row[0] in {'cancelled', 'failed'}
    ranked_locally = bool(analyzer and items and source != 'web')
    if ranked_locally:
        items = analyzer.rank(query, items, context.get('textProvider'), cancelled)
    directions = {i.get('direction') for i in items if i.get('direction')}
    needs_variety = any(i.get('visuallyRanked') for i in items) and len(directions) < 3
    if source != 'local' and (source == 'web' or len(items) < 6 or needs_variety) and context.get('allowExternalNetwork'):
        from .reference_network import import_page
        try:
            result = registry.web_search(project_id=project_id, task_id=task_id, query=f'{query} 设计案例 产品摄影 材质工艺 visual references case study site:behance.net OR site:pinterest.com OR site:design-milk.com', limit=8)
            for page in result.get('sources', [])[:8]:
                if len(items) >= 12 or cancelled():
                    break
                try:
                    imported = import_page(library, page['url'], saved=False, metadata={'title': page.get('title', '视觉参考')}, limit=2, cancelled=cancelled)
                    items += [item for item in imported['items'] if item['id'] not in excluded and item['id'] not in {r['id'] for r in items}]
                    if imported['items']:
                        ranked_locally = False
                    errors.extend(imported['errors'])
                except Exception:
                    errors.append({'url': page['url'], 'message': '作品页无法读取图片，可上传图片或更换来源'})
        except Exception:
            errors.append({'message': '本轮联网参考不可用，已保留本地结果；可上传图片或跳过参考'})
    elif source == 'web' and not context.get('allowExternalNetwork'):
        errors.append({'message': '本轮未开启联网，仅能使用本地参考'})
    if cancelled():
        raise ReferenceError('参考搜索已取消')
    if analyzer and not ranked_locally:
        items = analyzer.rank(query, items, context.get('textProvider'), cancelled)
    else:
        items = items[:6]
    def evidence_type(item):
        body = ' '.join(str(item.get(key, '')) for key in ('title', 'tags', 'description', 'notes', 'designTypes')).lower()
        if re.search(r'材质|工艺|纹理|纸张|金属|陶瓷|木|织物|material|process|texture', body): return 'material_process'
        if re.search(r'摄影|实拍|产品|场景|photo|photography|product', body): return 'product_photography'
        return 'design_case'
    # Candidate membership is persisted so the model cannot invent a reference.
    for item in items:
        item['evidenceType'] = evidence_type(item)
    with registry.store._connect() as db:
        current = loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (task_id,)).fetchone()[0])
        current['referenceCandidates'] = list(dict.fromkeys([*current.get('referenceCandidates', []), *(i['id'] for i in items)]))
        result = {'tool': 'reference_search', 'items': items, 'errors': errors[:8]}
        current['referenceSearchCache'] = [*current.get('referenceSearchCache', []), {'signature': signature, 'result': result}][-8:]
        fallback = empty_reference_fallback(current)
        db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(current, ensure_ascii=False), task_id))
    return fallback or result
