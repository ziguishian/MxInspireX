"""Bound optional reference discovery without relaxing explicit input requirements."""
import re


def optional_simple_reference(context):
    if int(context.get('executionPolicyVersion') or 0) < 2:
        return False
    state = context.get('referenceWorkflow') or {}
    # Use the original server-recorded request, never an Agent's search query.
    brief = str(state.get('query') or context.get('userMessage') or '')
    brief = re.sub(r'```[\s\S]*?```|`[^`]*`|“[^”]*”|「[^」]*」|"[^"\n]*"|(?m:^\s*>.*$)', '', brief)
    from .task_policy import delivery_request_spans
    brief = re.sub(r'不做(?:研究|调研)', '', brief)
    brief = delivery_request_spans(brief)[0]
    if re.search(r'参考|借鉴|对标|竞品|临摹|模仿|沿用|调研|研究|趋势|联网|搜索|查找|案例|根据.{0,12}(?:图|资料)|reference|inspired|research|search|latest|trend|match.{0,10}style', brief, re.I):
        return False
    if state.get('selectionId') or state.get('assetIds'):
        return False
    if any(context.get(key) for key in ('referencedAssets', 'referencedNodes', 'referencedFiles', 'referencedSkills', 'attachments', 'reviewRevision')):
        return False
    params = context.get('canvasParams') or {}
    if params.get('source_asset_id') or params.get('source_asset_ids') or params.get('canvasNodeId'):
        return False
    plan = context.get('designPlan') or {}
    batch = context.get('designBatch') or {}
    if plan:
        if not plan.get('ready') or plan.get('openQuestions') or plan.get('visualSeries') or batch.get('status') == 'needs_plan':
            return False
        items = [item for item in plan.get('deliverables', []) if not batch or item['id'] in batch.get('itemIds', [])]
        return bool(0 < len(items) <= 2 and sum(item['kind'] in {'image', 'html'} for item in items) == 1
                    and all(item['kind'] in {'image', 'html', 'text'} and not item.get('inputs') and not item.get('blockingFields') and not item.get('dependsOn') for item in items))
    target = context.get('singleDeliveryTarget') or {}
    return target.get('count') == 1 and target.get('kind') in {'image', 'html'} and not context.get('designPlanning')


def empty_reference_fallback(context):
    searches = context.get('referenceSearchCache') or []
    if not searches or context.get('referenceCandidates') or any(entry['result'].get('items') for entry in searches) or not optional_simple_reference(context):
        return None
    state = context['referenceWorkflow'] = {**context.get('referenceWorkflow', {}), 'status': 'unavailable',
        'reason': 'optional_search_empty', 'notice': '未找到可用参考；按已确认需求继续原创设计，不代表已有参考或用户主动跳过。'}
    return {'tool': 'reference_search', 'items': [], 'errors': searches[-1]['result'].get('errors', []),
            'referenceWorkflow': state, 'status': 'ready', 'instruction': '可选参考检索已完成，不再重复搜索或展示空选择卡。保留原需求与视觉约束，按就绪计划制作并保存到画布。'}
