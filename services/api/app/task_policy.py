"""Request intent and delivery requirements independent of model-tier selection."""
import copy
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ArtifactRequirement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['image','video','audio','html','text','cad']
    count: int = Field(default=1, ge=1, le=50)
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    format: Literal['png','jpeg','webp','gif','svg','mp4','webm','mp3','wav','html','txt','step','stl','glb'] | None = None
    transparent: bool = False


def delivery_contract(brief, constraints=None):
    constraints = constraints or {}
    if is_skill_management(brief, constraints):
        return []
    exclusions = delivery_exclusions(brief, constraints)
    explicit = {item.kind: item.model_dump(exclude_none=True) for raw in constraints.get('deliveryContract', []) for item in [ArtifactRequirement.model_validate(raw)] if item.kind not in exclusions['kinds']}
    for item in explicit.values():
        if item.get('format') == 'svg' or item.get('format') in exclusions['formats']:
            item.pop('format', None)
    text = delivery_inference_text(brief)
    for kind in delivery_requirements(brief, constraints):
        item = explicit.setdefault(kind, {'kind': kind, 'count': 1, 'transparent': False})
        # A quantity belongs to the nearest output noun. In “两张图和文字卡”,
        # the two describes images only; it must not also create two text cards.
        boundary = r'(?:[1-9]\d?|[一二两三四五六七八九十])\s*[张个份段幅套]|' + '|'.join(NOUNS.values())
        numbers = re.finditer(r'([1-9]\d?|[一二两三四五六七八九十])\s*[张个份段幅套]\s*(?:(?!(?:' + boundary + r'))[^，,。；;\n]){0,12}?(?:' + NOUNS[kind] + ')', text)
        for number in numbers:
            token = number[1]
            count = int(token) if token.isdigit() else {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}[token]
            item['count'] = max(item['count'], min(50, count))
        if kind == 'image':
            size = image_pixel_size(text)
            if size:
                item.update(width=size[0], height=size[1])
            fmt = re.search(r'\b(png|jpe?g|webp|gif)\b', text)
            if fmt: item['format'] = 'jpeg' if fmt[1] == 'jpg' else fmt[1]
            if re.search(r'透明(?:背景|底)?|transparent', text) and not re.search(r'不(?:需要|要)?透明|非透明|不透明',text): item['transparent'] = True
    return list(explicit.values())


def image_pixel_size(text):
    # Paper/print dimensions are physical specifications, not raster pixels.
    # Converting them also needs DPI, bleed and the actual unfolded layout.
    physical = r'mm|cm|毫米|厘米|英寸|inch(?:es)?|in\b|寸'
    sizes = re.finditer(r'(\d{2,5})(?:\.\d+)?\s*(' + physical + r'|px|像素)?\s*[x×*]\s*(\d{2,5})(?:\.\d+)?\s*(' + physical + r'|px|像素)?', text)
    for size in sizes:
        if any(unit and re.fullmatch(physical, unit) for unit in (size[2], size[4])):
            continue
        if '.' in size.group():
            continue
        width, height = int(size[1]), int(size[3])
        if max(width, height) <= 16384:
            return width, height
    return None

KINDS = {"image", "video", "audio", "html", "text", "cad"}
NOUNS = {
    "cad": r"(?<![a-z0-9])cad(?![a-z0-9])|(?<![a-z0-9])step(?![a-z0-9])|参数化模型|精确尺寸模型|结构件|实体建模",
    "image": r"图片|图像|照片|海报|插画|效果图|三视图|平面图|刀版|展开图|标志|logo|(?<=[张幅])图|(?:\bimage\b|\bphoto\b|\bposter\b)",
    "video": r"视频|短片|动画|\bvideo\b",
    "audio": r"音频|语音|配音|朗读|\baudio\b|\bspeech\b",
    "html": r"网页|网站|交互原型|html|landing.?page|\bwebsite\b",
    "text": r"文本节点|文字节点|文字说明卡|文字卡|说明文本|文案交付|代码文件|\btext node\b",
}


def delivery_request_spans(brief):
    """Separate prohibited outputs from positive requests, including lists.

    Keep the raw user message intact. A comma may continue a negative list;
    a new creation verb or contrast starts another positive request.
    """
    # An absence statement followed by an explicit prohibition is not a
    # positive output request: "没有制作 Logo，不需要生成图片". Absence alone
    # still allows requests such as "没有 Logo，请生成一个".
    absent_then_prohibited = r'(?:没有|尚未|未)(?:生成|制作|创建)(?=[^，,。；;\n]*[,，]\s*(?:不需要|不要|不用|无需)(?:再)?(?:生成|制作|创建))'
    negative = r'(?:' + absent_then_prohibited + r'|不要|不用|不需要|无需|不必|禁止|禁用|取消|避免|不(?:再|得|能|允许)?(?:生成|制作|创建|输出|交付|导出|提供|包含|附带|调用|使用|做|加)|别(?:生成|做)|\b(?:do\s+not|don[’\x27]t|without|no(?!t\b))\b)'
    action = r'(?:再|另(?:外)?|只|仅|请|同时|并)?\s*(?:生成|制作|创建|输出|交付|导出|设计|做|画|保留|需要|要|generate\b|create\b|make\b|provide\b|deliver\b|keep\b)'
    boundary = r'([。；;\n！？!?]|(?<!\d)\.(?!\d)|但是|但(?!是)|而是|改为|改用|改成|\bbut\b|\binstead\b|[,，]\s*(?=' + action + '))'
    positive, excluded = [], []
    for clause in re.split(boundary, str(brief).lower()):
        if not clause:
            continue
        match = re.search(negative, clause)
        if not match:
            positive.append(clause)
            continue
        prefix = clause[:match.start()]
        # "SVG、HTML 均禁用" is the same exclusion as "禁用 SVG、HTML".
        target = '|'.join(NOUNS.values()) + r'|\b(?:svg|png|jpe?g|webp|gif|zip)\b'
        remaining = re.sub(target, '', prefix)
        if prefix and not re.sub(r'[\s、,/或和及与均都全部]+', '', remaining):
            prefix = ''
        positive.append(prefix)
        excluded.append(clause[len(prefix):])
    return ''.join(positive), '；'.join(excluded)


def delivery_exclusions(brief, constraints=None):
    constraints = constraints or {}
    if constraints.get('clarificationContinuation') or constraints.get('continuation'):
        # A bare "continue" keeps the user's original exclusions. An unrelated
        # new task must not inherit them just because it shares a project goal.
        brief = str(constraints.get('designState', {}).get('goal') or '') + '\n' + str(brief)
    positive, negative = delivery_request_spans(brief)
    positive = html_reference_inputs(positive)
    kinds = {kind for kind, pattern in NOUNS.items() if re.search(pattern, negative) and not re.search(pattern, positive)}
    formats = {('jpeg' if fmt == 'jpg' else fmt) for fmt in re.findall(r'\b(png|jpe?g|webp|gif|svg|html|mp4|webm|mp3|wav|txt|step|stl|glb)\b', negative)}
    return {'kinds': kinds, 'formats': formats}


def normalize_delivery_context(context):
    """Drop legacy inferred obligations that contradict explicit exclusions.

    Only derived contracts/plans change; user messages, evidence, task history
    and real assets remain untouched. Reapplying this is idempotent.
    """
    data = copy.deepcopy(context)
    excluded = delivery_exclusions(data.get('userMessage', ''), data)
    for key in ('deliveryContract', 'requestedContract'):
        if key not in data:
            continue
        data[key] = [item for item in data[key] if item['kind'] not in excluded['kinds']]
        for item in data[key]:
            if item.get('format') == 'svg' or item.get('format') in excluded['formats']:
                item.pop('format', None)
    if 'requiredArtifacts' in data:
        data['requiredArtifacts'] = [kind for kind in data['requiredArtifacts'] or [] if kind not in excluded['kinds']]
    for key in ('designPlan', 'planBaseline'):
        plan = data.get(key)
        if not plan:
            continue
        removed = {item['id'] for item in plan.get('deliverables', []) if item['kind'] in excluded['kinds']}
        if removed:
            plan['deliverables'] = [item for item in plan['deliverables'] if item['id'] not in removed]
            if 'currentItemIds' in plan: plan['currentItemIds'] = [id for id in plan['currentItemIds'] if id not in removed]
            plan['visualSeries'] = [s for s in plan.get('visualSeries', []) if not removed.intersection(s['memberIds'])]
            for item in plan['deliverables']:
                item['dependsOn'] = [dep for dep in item.get('dependsOn', []) if dep not in removed]
            if key == 'designPlan' and 'deliveryProgress' in data:
                data['deliveryProgress'] = [item for item in data['deliveryProgress'] if item['id'] not in removed]
            if key == 'designPlan' and data.get('designBatch'):
                batch = data['designBatch']
                batch['itemIds'] = [id for id in batch['itemIds'] if id not in removed]
                batch['currentProgress'] = [item for item in batch.get('currentProgress', []) if item['id'] not in removed]
    return data


def delivery_inference_text(brief):
    """Frame references are inputs; explicit requests to create frames remain outputs."""
    text = html_reference_inputs(delivery_request_spans(brief)[0])
    if not re.search(NOUNS['video'], text) or not re.search(r'首尾帧|首帧|尾帧|first.{0,15}frame|last.{0,15}frame', text):
        return text
    image = re.compile(r'(?:[1-9]\d?|[一二两三四五六七八九十])?\s*[张幅]?\s*(?:' + NOUNS['image'] + ')')
    def mask_clause(clause):
        def mask(match):
            before = clause[:match.start()]
            # “生成两张图做首尾帧” explicitly asks for new images. In contrast,
            # “这两张图做首尾帧，做视频” names existing reference material.
            create = re.search(r'生成|制作|创建|绘制|画|输出|设计|补充|做|generate|create|draw|make', before)
            reference = re.search(r'这|那|已有|现有|上述|上传|提供|参考|使用|采用|根据|用|以|把|将|these|those|provided|uploaded|use', before)
            assigned = re.search(r'(?:做|作为|用作|用于|设为).{0,8}(?:首尾帧|首帧|尾帧)', clause[match.end():])
            return '参考素材' if not create and (reference or assigned) else match.group()
        return image.sub(mask, clause)
    return ''.join(mask_clause(clause) for clause in re.split(r'([，,。；;\n])', text))


def html_reference_inputs(text):
    """Existing product images embedded in HTML are inputs, not extra outputs."""
    if not re.search(NOUNS['html'], text):
        return text
    def mask_clause(clause):
        def mask(match):
            before, after = clause[:match.start()], clause[match.end():]
            create = re.search(r'(?:生成|绘制|制作|创建|输出|设计|新增|补充|generate|create|draw).{0,20}$', before)
            reference = re.search(r'已有|现有|上传|提供|参考|附件|直接使用|沿用|复用|作为商品|provided|uploaded|existing', before)
            described = re.match(r'(?:中|里|上)(?:的|所)|所示|可见|显示的', after)
            return '参考素材' if not create and (reference or described) else match.group()
        return re.sub(NOUNS['image'], mask, clause)
    return ''.join(mask_clause(clause) for clause in re.split(r'([，,。；;\n])', text))


def is_schedule_management(brief, constraints=None):
    constraints = constraints or {}
    if constraints.get('scheduledTask'):
        return False
    text = str(brief).lower()
    timing = re.search(r'定时|提醒|每(?:天|日|周|月|隔)|schedule|remind', text)
    immediate = re.search(r'(?:现在|立即|马上|先)(?:就)?(?:帮我|给我)?(?:生成|制作|创建|画|做|输出)|(?:generate|create|make).{0,30}\bnow\b', text)
    return bool(timing and not immediate)


def is_skill_management(brief, constraints=None):
    """Only author/manage skills; quoted workflow instructions are not outputs."""
    constraints = constraints or {}
    if constraints.get('canvasParams') or constraints.get('deliveryReviewOnly'):
        return False
    if constraints.get('skillAuthoringIntent') in {'create', 'manage'}:
        return True
    text = re.sub(r'#skill:[a-zA-Z0-9_-]+', '', str(brief)).strip().lower()
    subject = r'(?<![a-z])skills?(?![a-z])|技能'
    if not re.search(subject, text):
        return False
    # A second, immediate execution request makes this a normal mixed task.
    head = re.split(r'[:：\n]', text, maxsplit=1)[0]
    if re.search(r'(?:使用|用|按照|根据|with|using).{0,35}(?:' + subject + r').{0,20}(?:生成|创建|制作|设计|输出|画|做|generate|create|design|make)', head):
        return False
    clauses = re.split(r'[，,。；;]|然后|接着', head)
    if any(re.match(r'\s*(?:并且?|再|同时)?(?:帮我|给我)?(?:生成|画|做|制作|设计|输出|generate|make|draw)', clause)
           and not re.search(subject, clause) for clause in clauses[1:]):
        return False
    action = r'创建|新建|编写|保存|沉淀|更新|修改|编辑|删除|移除|列出|查询|查看|搜索|加载|装载|卸载|启用|停用|禁用|create|save|update|edit|delete|list|load|unload|enable|disable'
    return bool(re.search(r'(?:' + action + r').{0,100}(?:' + subject + r')|(?:' + subject + r').{0,40}(?:' + action + r')', head))


def is_skill_creation(brief, constraints=None):
    if not is_skill_management(brief, constraints):
        return False
    if (constraints or {}).get('skillAuthoringIntent') == 'create':
        return True
    # Inspect the user's command, not the workflow body following a colon.
    head = re.split(r'[:：\n]', str(brief).strip().lower(), maxsplit=1)[0]
    if re.search(r'不要|无需|不用|不必|do not|don.t', head):
        return False
    return bool(re.search(r'(?:创建|新建|编写|沉淀|create|author|build).{0,60}(?:skills?\b|技能)|(?:skills?\b|技能).{0,30}(?:创建|新建|编写)', head))


def delivery_requirements(brief, constraints=None):
    constraints = constraints or {}
    if is_skill_management(brief, constraints):
        return []
    required = set(constraints.get("requiredArtifacts") or []) & KINDS
    excluded = delivery_exclusions(brief, constraints)['kinds']
    canvas = constraints.get("canvasParams") or {}
    if canvas.get("kind") in KINDS:
        required.add(canvas["kind"])
    if constraints.get('clarificationContinuation'):
        return sorted(required - excluded)
    if constraints.get('planAccepted'):
        batch = constraints.get('designBatch')
        required.update(d['kind'] for d in constraints.get('designPlan', {}).get('deliverables', []) if d['kind'] in KINDS and (not batch or d['id'] in batch['itemIds']))
    if is_schedule_management(brief, constraints):
        return sorted(required - excluded)
    text = delivery_inference_text(brief)
    transcription = bool(re.search(r'转写|转录|语音转文字|transcrib|transcription', text))
    if transcription: required.add('text')
    question = re.match(r"^(?:请)?(?:解释|介绍|如何|怎么|怎样|为什么|what|how|why)", text.strip())
    if not question and re.search(r"生成|制作|创建|画|做|写|开发|搭建|输出|修改|调整|改成|设计|generate|create|build|make|draw|design", text):
        for kind, pattern in NOUNS.items():
            if transcription and kind in {'audio','video'}: continue
            if re.search(pattern, text):
                required.add(kind)
    return sorted(required - excluded)


EXECUTION_POLICY_VERSION = 2


def independent_research(brief):
    """Route explicit research deliverables, never keywords in quoted evidence."""
    text = re.sub(r'```[\s\S]*?```|`[^`]*`|“[^”]*”|「[^」]*」|"[^"\n]*"', '', str(brief).lower())
    text = re.sub(r'(?m)^\s*>.*$', '', text)
    positive = delivery_request_spans(text)[0]
    topic = r'(?:调研|研究|竞品|research|competitor|competitive)'
    for clause in re.split(r'[。；;\n！？!?]', positive):
        if re.search(r'之前|此前|曾经|已经|已做|上次|历史|previously|already|last time', clause):
            continue
        report = re.search(r'(?:输出|交付|撰写|编写|生成|做|需要|给我|write|produce|deliver|create).{0,35}' + topic + r'.{0,20}(?:报告|分析文档|report)', clause)
        phase = re.search(r'(?:独立|单独|专门|separately).{0,25}(?:调研|研究|分析竞品|research)|(?:先|first).{0,15}(?:调研|研究|research).{0,50}(?:再|然后|之后|then)', clause)
        if report or phase:
            return True
    return False


def single_delivery_target(brief, constraints):
    """A conservative completion hint; the worker must still verify real receipts."""
    if any(constraints.get(key) for key in ('designPlanning', 'designPlan', 'continuation', 'referencedSkills', 'deliveryRepairOnly', 'deliveryReviewOnly')):
        return None
    contract = constraints.get('deliveryContract') or []
    if len(contract) != 1 or contract[0].get('count', 1) != 1:
        return None
    kind = contract[0]['kind']
    if kind not in {'image', 'text', 'html'}:
        return None
    text = delivery_request_spans(re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"', '', str(brief)))[0]
    # Saving the same artifact and a requested review are not extra deliverables.
    text = re.sub(r'(?:并|然后|接着|随后)?\s*(?:放到|放在|保存到|添加到)(?:项目)?画布', '', text)
    text = re.sub(r'(?:生成后|完成后|然后|并)?\s*(?:做|进行|保留)?\s*(?:一次|1\s*次)?\s*质量审查', '', text)
    # A single concept image is still an image, not a separate proposal document.
    if kind == 'image':
        text = re.sub(r'方案图', '图', text)
    # Conjunctions join visual constraints too. Reject additional actions and
    # uncertain multiplicity, not "并保留产品外观" or "另外背景用暖色".
    extra = r'导出|打包|报告|方案|分析|对比|分别|系列|套|export|report|compare'
    follow_up = r'(?:然后|接着|同时|另外|并|还要|以及|随后|[,，]|\bthen\b|\balso\b|\band\b)\s*(?:再|另外)?\s*(?:写|介绍|解释|说明|总结|输出|交付|生成|制作|创建|做|画|设计|write\b|explain\b|generate\b|create\b|make\b)'
    if re.search(extra, text, re.I) or re.search(follow_up, text, re.I):
        return None
    canvas = constraints.get('canvasParams') or {}
    if canvas.get('kind') != kind and not re.search(r'(?:一|1)\s*(?:张|幅|个|份)|\b(?:one|single|an?)\b', text, re.I):
        return None
    return {'kind': kind, 'count': 1, 'nodeId': canvas.get('canvasNodeId')}


def execution_flow(brief, constraints=None):
    constraints = constraints or {}
    text = str(brief).lower().strip()
    if constraints.get("deliveryReviewOnly"):
        return "delivery"
    if is_skill_management(brief, constraints):
        return 'direct'
    if constraints.get("agentCollaboration") is False:
        return "direct"
    if is_schedule_management(brief, constraints):
        return "direct"
    research = independent_research(brief) if constraints.get('executionPolicyVersion', 0) >= 2 else re.search(r"调研|研究|竞品|趋势|最新|联网|research|competitive|latest", text)
    if research and not constraints.get('continuation'):
        return "research_design"
    from .design_planning import planning_profile
    if constraints.get('designPlanning') or constraints.get('designPlan') or planning_profile(brief, constraints):
        return "design"
    if delivery_requirements(brief, constraints):
        return "design"
    return "direct"


def is_greeting(brief):
    return bool(re.fullmatch(r"(?:你好|您好|嗨|哈喽|hello|hi|早上好|下午好|晚上好|晚安|谢谢(?:你|您)?|感谢|在吗|你是谁)[！!。，,.？?\s]*", str(brief).strip(), re.I))


def is_simple_conversation(brief, constraints=None):
    constraints = constraints or {}
    if is_skill_management(brief, constraints):
        return False
    # A short message accompanying a selected node or attachment may be an
    # instruction about that content, so retain the normal tool-capable flow.
    if any(constraints.get(key) for key in (
        "referencedAssets", "referencedNodes", "referencedFiles", "referencedSkills", "attachments",
        "canvasParams", "requiredArtifacts", "deliveryReviewOnly", "continuation",
    )):
        return False
    text = str(brief).strip()
    if is_greeting(text): return True
    if len(text) > 1600 or re.search(r'https?://|www\.|最新|实时|联网|调研|研究|查找|查询|画布|节点|文件|附件|上次|之前|刚才|历史|医疗|药物|用药|疾病|法律|投资|股票', text, re.I):
        return False
    if re.fullmatch(r'(?:请)?(?:介绍(?:一下|下)?(?:你自己|自己|你)|自我介绍(?:一下|下)?|你(?:能|可以|会)做什么|你有什么功能|你(?:能|可以)帮我做什么|你好呀|明白了|好的谢谢)[！!。，,.？?\s]*', text):
        return True
    # Inline source text is sufficient: no retrieval or tool turn is needed.
    if re.match(r'^(?:请|帮我)?(?:把)?(?:这段|以下|下面的?)?(?:文字|文本|句子|内容)?(?:润色|改写|翻译|精简|总结)|^(?:请|帮我)?(?:润色|改写|翻译|精简|总结)(?:这段|以下|下面)', text) and re.search(r'[:：\n].{3,}', text, re.S):
        return not re.search(r'生成.*(?:图片|视频|音频|网页)|保存|导出|上传|创建', text)
    if len(text) <= 120 and not delivery_requirements(text, constraints):
        return bool(re.match(r'^(?:请)?(?:简单解释|解释一下|简要介绍|什么是)', text) or re.search(r'(?:是什么意思|有什么区别|有什么不同)[？?。\s]*$', text))
    return False
