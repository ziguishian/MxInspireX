"""Bind explicit same-product requests to real image inputs, not style groups."""
import re

SAME_PRODUCT = re.compile(r'同款|同一款|同一(?:个)?(?:产品|商品)|(?:产品|主体)(?:的)?(?:造型|外观|结构|身份).{0,8}(?:一致|相同|不变)|\bsame\s+(?:physical\s+)?product\b', re.I)
DIFFERENT_PRODUCTS = re.compile(r'不同款|不同(?:的)?产品|多款产品|另一款|不(?:要求|需要|必|用).{0,6}(?:同款|一致)|\bdifferent\s+products?\b', re.I)
IDENTITY_PRESERVE = '除用户明确要求改变的部分外，产品本身的轮廓、比例、结构、开孔、部件、材质、颜色和标识保持一致；场景、光照与拍摄视角按本项要求变化，不重新设计产品'


def same_product_request(text):
    return bool(SAME_PRODUCT.search(str(text)) and not DIFFERENT_PRODUCTS.search(str(text)))


def bind_product_plan(plan, context):
    """Repair the unambiguous two-image case before scheduling, without an LLM.

    Complex multi-product plans must declare their own identity inputs; shared
    brands, palettes, templates and list order alone never imply an identity.
    """
    if context.get('planAccepted') or not same_product_request(context.get('userMessage', '')):
        return plan
    images = [item for item in plan['deliverables'] if item['kind'] == 'image']
    if len(images) < 2:
        return plan
    product_source = re.search(r'产品(?:摄影|主图|图)|商品(?:摄影|图)|白底图|棚拍|\bproduct\s+(?:photo|image|shot)\b',
                               images[0]['title'] + ' ' + images[0]['acceptance'], re.I)
    for item in images[1:]:
        refs = item.get('inputs', [])
        if any(ref['role'] == 'identity' for ref in refs):
            continue
        # Respect explicitly selected existing/future identity sources even if
        # an older model called the role "reference".
        identified = [ref for ref in refs if same_product_request(ref.get('purpose', ''))]
        if len(identified) == 1:
            identified[0]['role'] = 'identity'
        elif not refs and product_source and not images[0].get('dependsOn') and not any(ref['source'] == 'deliverable' for ref in images[0].get('inputs', [])) and (
            len(images) == 2 or re.search(r'场景|生活方式|产品摄影|实拍', item['title'] + item['acceptance'])):
            item['inputs'] = [{'source':'deliverable','id':images[0]['id'],'role':'identity',
                               'purpose':'以第一张成图作为同款产品身份参考，保留产品造型与材质，仅改变场景、光照和视角'}]
        elif SAME_PRODUCT.search(' '.join([item['title'], item['acceptance']])) or len(images) == 2:
            raise ValueError('同款产品必须明确 inputs 的 role=identity 及对应产品图来源；已有产品图使用 asset，尚需生成的首图使用 deliverable。不要把场景图作为无参考的独立生成。')
    return plan


def bind_identity_analysis(analysis, snapshot, intents):
    """Enforce pixel identity without inventing a visual analysis or another call."""
    from copy import deepcopy
    from .image_reference_design import ReferenceDesignError
    identities = {identity for ref in snapshot.get('inputBindings', []) if ref.get('role') == 'identity' for identity in ref.get('assetIds', [])}
    if not identities:
        return analysis
    if not isinstance(analysis, dict) or not isinstance(analysis.get('images'), list):
        raise ReferenceDesignError('请读取已保存的产品原图并填写 reference_analysis；同款场景必须传入原图，不能凭文字猜测产品造型。', asset_ids=list(identities))
    normalized = deepcopy(analysis)
    expected = {item['assetId']:item for item in intents}
    for entry in normalized['images']:
        if not isinstance(entry, dict) or entry.get('asset_id') not in identities:
            continue
        intent = expected.get(entry['asset_id'], {})
        if intent.get('confidence') == 'high' and intent.get('expectedMode') == 'inspiration':
            raise ReferenceDesignError('用户仅要求风格借鉴，与计划的同款身份约束冲突；请修正计划输入用途。', asset_ids=[entry['asset_id']])
        entry['mode'] = 'edit' if intent.get('expectedMode') == 'edit' else 'identity'
        preserve = str(entry.get('preserve') or '').strip()
        entry['preserve'] = preserve if IDENTITY_PRESERVE in preserve else '；'.join(filter(None, [preserve, IDENTITY_PRESERVE]))
    return normalized
