"""A design scope checklist and public deliverable plan, not model reasoning."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .design_brief import VisualDirection


# Planning aids, not mandatory purchases or claims about an industry standard.
AREAS = {
    'deliverables': [],
    'brand': [
        ('positioning', '品牌定位', '目标、受众、差异点、品牌信息；沿用已确认内容'),
        ('identity', '核心视觉识别', '标志及适用变体、标准色、字体层级、辅助图形'),
        ('applications', '实际应用', '按业务选择有用的触点，如包装、导视、社媒；不默认全部制作'),
        ('guidelines', '使用规范与交付', '版式与使用边界、输出规格；概念图不冒充可编辑矢量源文件'),
    ],
    'comprehensive': [
        ('objectives', '项目目标与条件', '商业/体验目标、使用者、场地或产品条件、约束和已有资料'),
        ('concept', '整体概念', '主线、主题、视觉语言；明确各部分如何形成同一方案'),
        ('system', '专业设计系统', '按项目领域分解：空间动线/分区/重点展区，或品牌/产品/服务等'),
        ('visuals', '关键设计表达', '明确需要的平面、效果图、示意或交互原型；每份图有不同用途'),
        ('delivery', '落地与交付边界', '规格、实施依赖、待确认事项；概念方案不冒充施工/CAD或工程验证'),
    ],
}

# Exact, unambiguous labels accepted from model gateways. Unknown checklist
# entries still require a correction; do not guess scope or remove review.
AREA_ALIASES = {
    'objectives': ['目标与项目条件', '目标与条件'],
    'concept': ['整体概念与色彩'],
    'system': ['设计系统'],
    'visuals': ['关键视觉'],
    'delivery': ['生产落地与交付边界', '落地交付'],
}


_LAYOUT_TERM = re.compile(r'排版|版式|布局|构图|位置关系|结构关系|\b(?:layout|composition|template)\b', re.I)
_LAYOUT_ACTION = re.compile(r'沿用|保持|保留|复用|套用|参照|参考|按照|照着|不变|一致|相同|同一|锁定|\b(?:keep|preserve|reuse|follow|match|same)\b', re.I)
_NEGATED_LAYOUT = re.compile(
    r'(?:不(?:要|用|需|必|沿用|保持|保留|复用|照搬|复制)|仅(?:作|做)?风格参考).{0,12}'
    r'(?:排版|版式|布局|构图|位置关系|结构关系)|'
    r'\b(?:not|never|don.t|without)\b.{0,20}\b(?:layout|composition|template)\b',
    re.I,
)


def explicit_layout_request(text):
    """Only user language can promote a current input image to a layout lock."""
    for clause in re.split(r'[，。；;\n]|\bbut\b', str(text or ''), flags=re.I):
        if _LAYOUT_TERM.search(clause) and _LAYOUT_ACTION.search(clause) and not _NEGATED_LAYOUT.search(clause):
            return True
    return False


def normalize_current_input_roles(plan, context):
    """Keep ordinary composer image inputs as references, not layout mandates.

    An accepted plan, a declared series master, or explicit user wording keeps
    the stronger layout role. This preserves real template workflows while
    preventing an Agent-authored plan from turning an attached style/reference
    image into a pixel-preserving layout requirement by itself.
    """
    if context.get('planAccepted') or (context.get('designBatch') or {}).get('intent') in {'next_batch', 'resume', 'revise'}:
        return plan
    if explicit_layout_request(context.get('userMessage')):
        return plan
    current_assets = {
        ref.get('assetId') or ref.get('id')
        for ref in context.get('referencedAssets') or []
        if isinstance(ref, dict) and (ref.get('assetId') or ref.get('id'))
    }
    series_masters = {series.get('masterAssetId') for series in plan.get('visualSeries', []) if series.get('masterAssetId')}
    for item in plan.get('deliverables', []):
        for ref in item.get('inputs', []):
            if (ref.get('source') == 'asset' and ref.get('role') == 'layout'
                    and ref.get('id') in current_assets and ref.get('id') not in series_masters):
                ref['role'] = 'reference'
    return plan


def planning_profile(brief, constraints=None):
    """Conservative entry guard; the Agent can also elect to plan other tasks."""
    constraints = constraints or {}
    if constraints.get('deliveryReviewOnly') or constraints.get('deliveryRepairOnly') or constraints.get('scheduledTask'):
        return None
    text = str(brief).strip().lower()
    from .task_policy import is_schedule_management, is_skill_management
    if is_skill_management(text, constraints): return None
    if is_schedule_management(text, constraints): return None
    if re.match(r'^(?:请)?(?:解释|介绍|什么是|如何|怎么|为什么)', text) or re.search(r'包含什么|包括什么|有什么区别', text):
        return None
    from .product_identity import same_product_request
    from .task_policy import delivery_contract
    if same_product_request(text) and any(item['kind'] == 'image' and item['count'] > 1 for item in delivery_contract(brief, constraints)):
        return 'deliverables'
    # A focused edit in a larger project must not restart its entire design.
    if re.search(r'(?:只|仅|仅仅)(?:需|要|用)?[^，。\n]{0,12}(?:改|调|换|生成|做|画|设计)', text):
        return None
    if re.search(r'(?:修改|调整|替换|改成|改为|去掉|移除).{0,25}(?:背景|颜色|配色|文字|字体|尺寸|标志|logo)', text):
        return None
    if re.search(r'品牌(?:全案|视觉|形象|识别|设计)|品牌的?(?:整套|全套)|(?:整套|全套).{0,8}(?:品牌|vi)|\b(?:brand(?:ing| identity| design)|visual identity)\b', text):
        return 'brand'
    if re.search(r'全案|(?:完整|整套|系统|整体|一整套).{0,12}(?:设计|方案)|(?:设计|方案).{0,8}全套|(?:做|设计|制作)一套.{0,15}(?:礼盒|包装)', text):
        return 'comprehensive'
    if len(delivery_contract(brief,constraints)) > 1:
        return 'deliverables'
    return None


def planning_guide(profile):
    if profile not in AREAS: return None
    if profile == 'deliverables':
        return {'version':1,'profile':profile,'required':True,'areas':[],
                'rule':'直接用一次 design_plan 登记用户要求的各项类型、数量和稳定 ID；coverage 可为空，不额外整理需求或研究，不等待用户确认。文字卡用 text 与 canvas_create_text。计划 ready 后只制作未完成项，禁止改名重做或自行润色重生成；完成即交付。'}
    return {'version': 1, 'profile': profile, 'required': True,
            'areas': [{'id': key, 'title': title, 'consider': detail, 'aliases': AREA_ALIASES.get(key, [])} for key, title, detail in AREAS[profile]],
            'rule': '这是检查范围的参考框架，不是强制交付清单。按用户要求逐项选择本轮覆盖、暂缓或不适用并说明；不擅自扩单。先 design_plan 明确目标、保留项、交付物和验收条件，再生成。缺关键决策才逐题澄清；通用范围无需联网，缺行业/竞品/案例依据才按需搜索。'}


class DeliverableInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    source: Literal['asset', 'deliverable']
    id: str = Field(min_length=1, max_length=100)
    role: Literal['reference', 'identity', 'layout', 'content'] = 'reference'
    purpose: str = Field(min_length=1, max_length=350)

    @model_validator(mode='after')
    def canonical_identity(self):
        if self.source == 'asset':
            from .asset_identity import asset_id
            self.id = asset_id(self.id)
            if not self.id:
                raise ValueError('素材引用缺少资产 ID')
        return self


class Deliverable(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=100)
    kind: Literal['image', 'html', 'text', 'video', 'audio', '3d', 'cad']
    acceptance: str = Field(min_length=1, max_length=350)
    representation: Literal['auto', 'concept', 'raster', 'vector', 'model', 'document'] = 'auto'
    blockingFields: list[str] = Field(default_factory=list, max_length=8)
    dependsOn: list[str] = Field(default_factory=list, max_length=49)
    inputs: list[DeliverableInput] = Field(default_factory=list, max_length=20)
    imageSpec: 'ImageSpec | None' = None


class ImageSpec(BaseModel):
    """Concrete image-making decisions, not another free-form style prompt."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    subjectStructure: str = Field(min_length=1, max_length=700)
    formProportion: str = Field(min_length=1, max_length=700)
    materialConstruction: str = Field(min_length=1, max_length=700)
    compositionFraming: str = Field(min_length=1, max_length=700)
    lightSurface: str = Field(min_length=1, max_length=700)
    preserve: list[str] = Field(default_factory=list, max_length=8)
    avoid: list[str] = Field(default_factory=list, min_length=1, max_length=8)
    variationAxis: str | None = Field(default=None, min_length=1, max_length=350)


class Coverage(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    area: str = Field(min_length=1, max_length=50)
    status: Literal['included', 'deferred', 'not_applicable']
    detail: str = Field(min_length=1, max_length=250)


class VisualSeries(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=50)
    masterId: str | None = Field(default=None, min_length=1, max_length=50)
    masterAssetId: str | None = Field(default=None, min_length=1, max_length=100)
    memberIds: list[str] = Field(min_length=2, max_length=50)
    size: str = Field(pattern=r'^[1-9]\d{0,4}x[1-9]\d{0,4}$')
    lockedLayout: list[str] = Field(min_length=1, max_length=10)
    variableFields: list[str] = Field(min_length=1, max_length=10)


class DesignPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    goal: str = Field(min_length=1, max_length=300)
    preserve: list[str] = Field(default_factory=list, max_length=10)
    visualDirection: VisualDirection | None = None
    deliverables: list[Deliverable] = Field(min_length=1, max_length=50)
    currentItemIds: list[str] = Field(default_factory=list, max_length=50)
    visualSeries: list[VisualSeries] = Field(default_factory=list, max_length=12)
    coverage: list[Coverage] = Field(default_factory=list, max_length=8)
    deferred: list[str] = Field(default_factory=list, max_length=10)
    openQuestions: list[str] = Field(default_factory=list, max_length=3)
    research: str = Field(min_length=1, max_length=350)


def reused_plan_receipt(context):
    return {'tool': 'design_plan', 'status': 'plan_reused', 'code': 'no_plan_change', 'fieldPath': 'plan',
            'plan': context['designPlan'], 'batch': context.get('designBatch'), 'progress': context.get('deliveryProgress', []),
            'instruction': '当前计划已经 ready，已保留原清单、视觉要求、验收条件和进度，未重复改写。直接执行未完成项；无需再次保存或确认计划。只有新证据、用户补充或真实制作/依赖问题需要修改时，提供具体 change_reason。'}


def save_design_plan(store, project_id, task_id, plan, *, reuse_ready=False, expected_revision=None, expected_scope_id=None):
    import copy
    from .design_batches import observe, register, set_progress
    # Keep completed items server-side even if the model submits only the next
    # batch. A concurrent plan change must be read again before overwriting it.
    with store._connect() as db:
        initial_row = db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
    if not initial_row: raise ValueError('设计计划需要关联当前项目的真实任务')
    from .task_policy import normalize_delivery_context
    initial = normalize_delivery_context(json.loads(initial_row[0]))
    prior_plan = initial.get('designPlan') or initial.get('planBaseline') or {}
    if reuse_ready and (initial.get('designPlan') or {}).get('ready') and (initial.get('designBatch') or {}).get('status') != 'needs_plan':
        return reused_plan_receipt(initial)
    current_version = initial.get('designPlan') or {}
    if expected_revision is not None and (expected_revision != int(current_version.get('revision', 0))
            or expected_scope_id is not None and expected_scope_id != current_version.get('scopeId')):
        return {'tool': 'design_plan', 'status': 'plan_conflict', 'submitted': False,
                'plan': initial.get('designPlan'), 'batch': initial.get('designBatch'),
                'progress': initial.get('deliveryProgress', []),
                'instruction': '计划版本已更新，旧修改未保存。按返回的有效计划继续；确有新需求时基于此版本重新修改。'}
    proposal = copy.deepcopy(plan)
    aliases = {alias: key for key, title, _ in AREAS.get((initial.get('designPlanning') or {}).get('profile'), [])
               for alias in [key, title, *AREA_ALIASES.get(key, [])]}
    for item in proposal.get('coverage', []):
        if isinstance(item, dict):
            label = re.sub(r'^[一二三四五六七八九十百\d]+项', '', str(item.get('area') or ''))
            item['area'] = aliases.get(label, item.get('area'))
    batch = initial.get('designBatch') or {}
    if batch:
        supplied = {d.get('id') for d in proposal.get('deliverables', [])}
        proposal['deliverables'] = [d for d in prior_plan.get('deliverables', []) if d['id'] not in supplied and
                                    (batch['intent'] in {'next_batch', 'revise'} or d['id'] not in batch['itemIds'])] + proposal.get('deliverables', [])
        supplied_series = {s.get('id') for s in proposal.get('visualSeries', [])}
        proposal['visualSeries'] = [s for s in prior_plan.get('visualSeries', []) if s['id'] not in supplied_series and
                                   (batch['intent'] in {'next_batch', 'revise'} or not set(s['memberIds']).intersection(batch['itemIds']))] + proposal.get('visualSeries', [])
    # The brief is the canonical compact design judgement.  Copy it into a
    # public plan when the Agent deliberately omitted a duplicate payload.
    if not proposal.get('visualDirection'):
        direction = ((initial.get('designState') or {}).get('brief') or {}).get('visualDirection')
        if direction:
            proposal['visualDirection'] = copy.deepcopy(direction)
    # The memory tool exposes both a stable semantic key and the backing asset
    # id. Models sometimes copy the key into plan inputs. Resolve only aliases
    # that are explicitly selected for this task before persisting the plan.
    from .asset_identity import selected_asset_id
    for item in proposal.get('deliverables', []):
        for ref in item.get('inputs', []):
            if ref.get('source') == 'asset':
                ref['id'] = selected_asset_id(ref.get('id'), initial)
    plan = normalize_current_input_roles(proposal, initial)
    value = DesignPlan.model_validate(plan).model_dump()
    from .product_identity import bind_product_plan
    value = bind_product_plan(value, initial)
    if (initial.get('designPlanning') or {}).get('profile') == 'deliverables' and not initial.get('planAccepted'):
        from collections import Counter
        from .task_policy import delivery_contract
        expected_counts = {item['kind']:item['count'] for item in delivery_contract(initial.get('userMessage',''),initial)}
        actual_counts = dict(Counter(item['kind'] for item in value['deliverables']))
        if actual_counts != expected_counts:
            raise ValueError('交付清单须保留用户要求的类型和数量：'+json.dumps(expected_counts,ensure_ascii=False)+'。文字卡是 text，不用图像工具制作，不增加产物。')
    for key in ('preserve', 'deferred', 'openQuestions'):
        if any(not text.strip() or len(text) > 350 for text in value[key]):
            raise ValueError(f'{key} 每项应为 1–350 字的具体说明')
    if len({item['id'] for item in value['deliverables']}) != len(value['deliverables']):
        raise ValueError('交付物 ID 不能重复')
    # A visual direction is useful only when every planned image translates it
    # into observable form/material/composition decisions.  Old saved plans
    # without the new field stay readable and executable.
    if value.get('visualDirection'):
        missing_specs = [item['title'] for item in value['deliverables'] if item['kind'] == 'image' and not item.get('imageSpec')]
        if missing_specs:
            raise ValueError('设计方向已包含视觉判断；每个图片交付项还需填写 imageSpec（主体结构、比例、材质工艺、构图、光线和避免项）：' + '、'.join(missing_specs))
    items = {item['id']: item for item in value['deliverables']}
    members, groups = set(), set()
    for series in value['visualSeries']:
        ids = series['memberIds']
        if series['id'] in groups or len(set(ids)) != len(ids) or members.intersection(ids):
            raise ValueError('套系 ID 和套系成员不能重复或交叉')
        if series['masterId'] and series['masterAssetId']:
            raise ValueError('套系对照请选择已有图片或本轮成员之一，不能同时指定两个基准')
        if series['masterId'] and series['masterId'] not in ids or any(id not in items or items[id]['kind'] != 'image' for id in ids):
            raise ValueError('套系成员和本轮对照项必须引用本计划中的图片交付项')
        for key in ('lockedLayout', 'variableFields'):
            if any(not text.strip() or len(text) > 350 for text in series[key]):
                raise ValueError(f'套系 {key} 每项应为 1–350 字')
        groups.add(series['id']); members.update(ids)
    # Shared style alone never creates edges. Identity inputs are actual image
    # consumption, so scenes wait for their chosen product image.
    for item in items.values():
        if sum(ref['role'] == 'layout' for ref in item['inputs']) > 1:
            raise ValueError('每项选择一个排版输入；其他图片按参考或内容用途声明')
        sources = [ref['id'] for ref in item['inputs'] if ref['source'] == 'deliverable']
        item['dependsOn'] = list(dict.fromkeys([*item['dependsOn'], *sources]))
    dependencies = {item['id']: set(item['dependsOn']) for item in value['deliverables']}
    for item, required in dependencies.items():
        if item in required or not required.issubset(dependencies):
            raise ValueError('dependsOn 必须引用本计划中其他交付项的 ID')
    remaining = dict(dependencies)
    while remaining:
        ready = {item for item, required in remaining.items() if not required.intersection(remaining)}
        if not ready: raise ValueError('交付项的 dependsOn 不能形成循环依赖')
        remaining = {item: required for item, required in remaining.items() if item not in ready}
    # Resolve the old scope before entering the write transaction; no provider
    # or browser calls are involved in this local asset inspection.
    evidence_context = {**initial, 'designPlan': {**value, 'scopeId': prior_plan.get('scopeId') or task_id}}
    observed = observe(store, project_id, task_id, evidence_context)
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT input_json FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if not row: raise ValueError('设计计划需要关联当前项目的真实任务')
        from .task_policy import delivery_exclusions, normalize_delivery_context
        data = normalize_delivery_context(json.loads(row[0]))
        if (data.get('designPlan') or {}) != (initial.get('designPlan') or {}):
            return {'tool': 'design_plan', 'status': 'plan_conflict', 'submitted': False,
                    'plan': data.get('designPlan'), 'batch': data.get('designBatch'),
                    'progress': data.get('deliveryProgress', []),
                    'instruction': '计划版本已更新，旧修改未保存。按返回的有效计划继续。'}
        excluded = delivery_exclusions(data.get('userMessage', ''), data)['kinds']
        if any(item['kind'] in excluded for item in value['deliverables']):
            raise ValueError('用户明确排除的产物不能加入交付清单，也不能列为阻塞项。请移到不适用范围说明，仅保留用户需要的交付项。')
        from .svg_policy import task_policy, ERROR as SVG_ERROR
        if not task_policy(store, data, db)['allowed'] and any(d['kind'] == 'image' and d['representation'] == 'vector' and not d['blockingFields'] for d in value['deliverables']) and not value['openQuestions']:
            raise ValueError('不能承诺当前工具不可交付的矢量图。先完成效果图；用户要求的矢量项应标明阻塞条件。' + SVG_ERROR)
        from .design_state import unanswered_questions
        unanswered, _ = unanswered_questions(data.get('designState', {}), [{'question': question} for question in value['openQuestions']])
        value['openQuestions'] = [question['question'] for question in unanswered]
        profile = (data.get('designPlanning') or {}).get('profile')
        expected = {key for key, *_ in AREAS.get(profile, [])}
        if expected and {item['area'] for item in value['coverage']} != expected:
            raise ValueError('只修正 coverage[].area，必须使用以下英文 ID（不能填中文标题或交付项名称），各列一次并标明 included/deferred/not_applicable；保留其他设计内容：' + '、'.join(sorted(expected)))
        previous = data.get('designPlan') or {}
        baseline = data.get('planBaseline') or {}
        if data.get('planAccepted') or (data.get('designBatch') or {}).get('intent') in {'next_batch', 'resume'}:
            accepted_series = [VisualSeries.model_validate(s).model_dump() for s in previous.get('visualSeries', baseline.get('visualSeries', []))]
            proposed_series = {s['id']: s for s in value['visualSeries']}
            if any(proposed_series.get(s['id']) != s for s in accepted_series):
                raise ValueError('继续执行时不能移除或修改已接受的套系对照与版式约束')
            accepted_items = previous.get('deliverables', baseline.get('deliverables', []))
            required_ids = {d['id'] for d in accepted_items}
            if not required_ids.issubset({d['id'] for d in value['deliverables']}):
                raise ValueError('不能删去已接受计划中的交付项。保留缺项并说明依赖，用户明确调整范围后再修改。')
            proposed = {d['id']: d for d in value['deliverables']}
            if any(any(proposed[d['id']].get(key, 'auto') != d.get(key, 'auto') for key in ('kind', 'acceptance', 'representation')) for d in accepted_items):
                raise ValueError('继续执行时不可降低或替换已接受交付项的类型、形式和验收条件。请按原清单完成，用户修改要求后再调整。')
        requested = data.get('requestedContract', data.get('deliveryContract', []))
        if not value['openQuestions']:
            for requirement in requested:
                if not any(d['kind'] == requirement['kind'] for d in value['deliverables']):
                    raise ValueError(f"用户要求的 {requirement['kind']} 交付不可暂缓或改成其他类型。请纳入计划，缺少条件则记录 blockingFields。")
                if sum(d['kind'] == requirement['kind'] for d in value['deliverables']) < requirement.get('count', 1):
                    raise ValueError(f"用户明确要求 {requirement['count']} 份 {requirement['kind']}，请分别列出交付项，不能合并为一份后视为全部完成。")
        value.update(version=2, scopeId=previous.get('scopeId') or (baseline.get('scopeId') or data.get('planBaselineTaskId') if data.get('planAccepted') else task_id), revision=int(previous.get('revision', 0)) + 1, ready=not value['openQuestions'])
        data['designBatch'] = register(data, value)
        # Writes are local and atomic. Replaying an identical plan changes no state.
        if {k:v for k,v in previous.items() if k!='revision'} == {k:v for k,v in value.items() if k!='revision'}:
            value = previous
        data['designPlan'] = value
        set_progress(data, observed)
        db.execute('UPDATE tasks SET input_json=? WHERE id=? AND project_id=?', (json.dumps(data, ensure_ascii=False), task_id, project_id))
    lines = ['本轮设计计划（当前批次）：' + value['goal'], *[f"• {item['title']}：{item['acceptance']}" for item in value['deliverables'] if item['id'] in value['currentItemIds']]]
    for item in value['deliverables']:
        if item['id'] in value['currentItemIds'] and item['inputs']:
            lines.append(item['title'] + ' 使用：' + '；'.join(('已有素材' if ref['source']=='asset' else '交付项 ' + items[ref['id']]['title']) + '（' + ref['purpose'] + '）' for ref in item['inputs']))
    if value['preserve']: lines.append('保留：' + '；'.join(value['preserve']))
    if value['deferred']: lines.append('本轮暂不做：' + '；'.join(value['deferred']))
    if value['openQuestions']: lines.append('待补充：' + '；'.join(value['openQuestions']))
    return {'tool': 'design_plan', 'plan': value, 'batch': data['designBatch'], 'progress': data['deliveryProgress'], 'summary': '\n'.join(lines),
            'status': 'ready' if value['ready'] else 'needs_clarification',
            'instruction': ('计划已就绪，直接按本批清单执行未完成项；独立项使用 generate_batch。不要重复保存或读取计划。按参考分析和质量要求生成，成功保存后直接交付。' if value['ready'] else '计划已保存；立即向用户展示 openQuestions 并结束本轮。不要重复提交 design_plan，也不要在用户回答前调用生成工具。')}
