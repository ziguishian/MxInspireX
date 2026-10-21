"""Validate visual reasoning and route image references without prompt bloat.

The Agent supplies the final visual description; this module never invents
one or calls a second model. Provenance keeps all selected references,
while identity/layout/edit inputs are sent as pixels to the image provider.
"""
import hashlib
import json
import re
from .image_production import append_visual_constraints, image_edit_prompt


class ReferenceDesignError(ValueError):
    code = 'reference_analysis_required'

    def __init__(self, message, *, asset_ids=(), issues=()):
        super().__init__(message)
        self.field = 'reference_analysis'
        self.asset_ids = list(asset_ids)
        self.issues = list(issues)


class DesignSpecError(ValueError):
    """Raised before a provider request when a plan is not image-actionable."""
    code = 'design_spec_required'
    field = 'imageSpec'

    def __init__(self, message):
        super().__init__(message)
        self.asset_ids = []


LAYOUT_GUIDANCE = '沿用草图的主体位置、相对大小、空间层次和留白；画面不含草稿笔触和辅助线。'

_GENERIC_ONLY = re.compile(r'^(?:高级感|精致感|艺术感|有质感|时尚感|好看|大气|氛围感|premium|elegant|beautiful)[、，,\s。！!]*$', re.I)


def _image_deliverable(context, binding, args):
    plan = context.get('designPlan') or {}
    ids = (binding or {}).get('itemIds') or args.get('deliverable_ids') or []
    if len(ids) != 1:
        return None
    return next((item for item in plan.get('deliverables', []) if item.get('id') == ids[0] and item.get('kind') == 'image'), None)


def compile_design_spec(context, binding, args):
    """Validate and retain the plan without repeating it in the image prompt.

    The Agent writes the final visual description. Only explicit preservation
    and negative constraints are carried over; reasoning stays in metadata.
    """
    args = dict(args)
    plan = context.get('designPlan') or {}
    direction = plan.get('visualDirection') or ((context.get('designState') or {}).get('brief') or {}).get('visualDirection')
    item = _image_deliverable(context, binding, args)
    spec = (item or {}).get('imageSpec')
    if not direction and not spec:
        return args
    if not direction:
        raise DesignSpecError('图片交付已填写 imageSpec，但缺少 visualDirection。请先在 design_state.brief 或 design_plan 中记录受众、主题、核心创意与视觉依据。')
    if item and not spec:
        raise DesignSpecError(f"图片交付“{item.get('title', item.get('id'))}”缺少 imageSpec。请写清主体结构、比例、材质工艺、构图、光线与避免项后再生成。")
    # Direct, focused edits may reuse a compact visualDirection without forcing
    # a new design plan. Their explicit edit prompt remains the scoped spec.
    if not spec:
        return args
    concrete = [spec.get(key, '').strip() for key in ('subjectStructure', 'formProportion', 'materialConstruction', 'compositionFraming', 'lightSurface')]
    if any(not value or _GENERIC_ONLY.fullmatch(value) for value in concrete) or sum(len(value) for value in concrete) < 40:
        raise DesignSpecError('imageSpec 不能只写“高级感、精致感”等空泛形容词；请具体说明形态结构、比例、材质制作、构图视角与光线表面。')
    avoid = [str(value).strip() for value in spec.get('avoid') or [] if str(value).strip()]
    if not avoid:
        raise DesignSpecError('imageSpec.avoid 至少写一项本图要避免的具体问题，例如不合理拼接、塑料感表面、重复纹样或伪文字。')
    args['prompt'] = append_visual_constraints(args.get('prompt', ''),
        *(f'保留：{value}' for value in spec.get('preserve') or [] if value not in str(args.get('prompt', ''))))
    args['negative_prompt'] = append_visual_constraints(args.get('negative_prompt', ''), *(direction.get('avoid') or []), *avoid)
    args['_design_spec'] = {'direction': direction, 'itemId': item.get('id') if item else None, 'imageSpec': spec}
    return args


def drawing_reference_ids(assets, project_id, source_ids):
    return [identity for identity in source_ids if assets and
            ((assets.get_asset(project_id=project_id, asset_id=identity) or {}).get('metadata') or {}).get('source') == 'canvas-drawing']


def prepare_reference_design(prompt, source_ids, analysis, snapshot, *, required=False, masked_edit=False, layout_source_ids=()):
    source_ids = list(dict.fromkeys(source_ids))
    layout_source_ids = set(layout_source_ids).intersection(source_ids)
    if analysis is None:
        if required and source_ids:
            raise ReferenceDesignError('请先实际看图，反推可见的视觉描述，再结合本项需求填写 reference_analysis：逐图说明 visual_prompt、mode、use、avoid、preserve，并写 synthesis。风格借鉴用 inspiration；需保持对象身份用 identity；明确改原图用 edit。反推描述不是原作者的真实提示词。缺少分析的资产：' + '、'.join(source_ids), asset_ids=source_ids)
        if layout_source_ids and not masked_edit:
            prompt = append_visual_constraints(prompt, LAYOUT_GUIDANCE)
        if masked_edit:
            prompt = append_visual_constraints(image_edit_prompt(prompt), '仅修改遮罩区域，其余内容保持不变。')
        return prompt, snapshot, source_ids
    if not isinstance(analysis, dict) or not isinstance(analysis.get('images'), list):
        raise ReferenceDesignError('reference_analysis 需要 images 数组和本项 synthesis 融合方案。')

    issues = []
    def issue(field, message, identity=None):
        issues.append({'field': 'reference_analysis.' + field, 'message': message,
                       'assetIds': [identity] if identity else []})

    def text(value, label, *, optional=False):
        if value is None and optional:
            return ''
        if not isinstance(value, str) or (not value.strip() and not optional) or len(value) > 4000:
            issue(label, f'{label} 需要具体文字，最多 4000 字符。')
            return ''
        return value.strip()

    synthesis = text(analysis.get('synthesis'), 'synthesis')
    images = {}
    for index, entry in enumerate(analysis['images']):
        prefix = f'images.{index}.'
        if not isinstance(entry, dict):
            issue(prefix.rstrip('.'), '逐图分析必须是对象。')
            continue
        identity = entry.get('asset_id')
        if not isinstance(identity, str) or identity not in source_ids or identity in images:
            issue(prefix + 'asset_id', '逐图分析的 asset_id 必须与实际选用参考一一对应，不能遗漏、重复或引用其他图片。')
            continue
        mode = entry.get('mode')
        if mode not in {'inspiration', 'identity', 'edit', 'layout'}:
            issue(prefix + 'mode', '参考用途 mode 只能为 inspiration、identity、layout 或 edit。', identity)
            continue
        if identity in layout_source_ids and mode != 'edit' and not (masked_edit and identity == source_ids[0]):
            mode = 'layout'
        images[identity] = {
            'asset_id': identity, 'mode': mode,
            'visual_prompt': text(entry.get('visual_prompt'), prefix + 'visual_prompt'),
            'use': text(entry.get('use'), prefix + 'use'),
            'avoid': text(entry.get('avoid'), prefix + 'avoid', optional=True),
            'preserve': text(entry.get('preserve') or ('主体位置、相对大小、空间层次和留白' if mode == 'layout' else None), prefix + 'preserve', optional=mode == 'inspiration'),
        }
    if set(images) != set(source_ids):
        for identity in source_ids:
            if identity not in images: issue('images', '逐图分析未覆盖实际参考：' + identity, identity)
    if masked_edit and (not source_ids or images.get(source_ids[0], {}).get('mode') != 'edit'):
        issue('images.0.mode', '遮罩重绘的原图必须使用 mode=edit 并填写 preserve；不能把待修改原图当作风格借鉴或新场景身份参考。')
    layout_ids = {identity for binding in snapshot.get('inputBindings', []) if binding.get('role') == 'layout' for identity in binding.get('assetIds', [])}
    if any(images[identity]['mode'] == 'inspiration' for identity in layout_ids if identity in images):
        issue('images', '计划中明确复用的排版依据需要 identity/layout/edit 及 preserve；仅借鉴风格时先调整计划输入用途。')
    if issues:
        raise ReferenceDesignError('请一次修正以下参考分析问题，尚未提交生成：' + '；'.join(item['message'] for item in issues),
            asset_ids=list(dict.fromkeys(identity for item in issues for identity in item['assetIds'])), issues=issues)

    provider_ids = [identity for identity in source_ids if images[identity]['mode'] != 'inspiration']
    sections = []
    is_edit = any(images[identity]['mode'] == 'edit' for identity in provider_ids)
    for index, identity in enumerate(provider_ids, 1):
        item = images[identity]
        role = {'identity': '外观参考', 'layout': '构图参考', 'edit': '待编辑原图'}[item['mode']]
        sections.append(f"输入图 {index}（{role}）：保留{item['preserve']}。")
        if item['mode'] == 'layout' and identity in layout_source_ids:
            sections.append(LAYOUT_GUIDANCE)
    if is_edit:
        prompt = image_edit_prompt(prompt)
        sections.append('仅修改遮罩区域，其余内容保持不变。' if masked_edit else '未指定修改的内容保持不变。')
    prepared = {**snapshot, 'analysis': {'images': [images[i] for i in source_ids], 'synthesis': synthesis},
                'providerInputAssetIds': provider_ids}
    prepared.pop('id', None)
    prepared['id'] = hashlib.sha256(json.dumps(prepared, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return append_visual_constraints(prompt, *sections), prepared, provider_ids
