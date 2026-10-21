"""Shared image candidate planning, parameter adaptation and safe dispatch."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Callable

from .image_quality import apply_image_quality, apply_policy_dimensions
from .image_parameters import is_custom_gpt_image, nearest_native_gpt_size, pixel_dimensions, valid_native_gpt_dimensions
from .model_config import DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL
from .model_router import MediaModelRouter
from .providers.image_request import image_request_scope


@dataclass
class ImageCandidate:
    provider: str
    model: str
    adapter: Any
    options: dict[str, Any]
    quality: dict[str, Any]
    adjustments: list[str]


def _seedream(model: str) -> str | None:
    leaf = str(model or '').lower().replace('_', '-').split('/')[-1]
    if 'seedream-5-0-lite' in leaf:
        return 'lite'
    if 'seedream-5-0-pro' in leaf:
        return 'pro'
    if re.search(r'seedream-4[.-]5', leaf):
        return '4.5'
    return None


def _dedupe(values):
    return list(dict.fromkeys(value for value in values if value))


def _literal_plan(settings, *, requested_model, tier, params, has_references):
    if requested_model:
        return {'mode': 'manual', 'tier': tier, 'primaryModel': requested_model,
                'candidateModels': [requested_model], 'allCandidateModels': [requested_model], 'unavailableModels': []}
    level = tier if tier in {'draft', 'standard', 'final'} else 'draft'
    slots = settings.media['image']
    configured = slots.get(level) or slots.get('standard') or ''
    builtins = ([DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL]
                if level == 'draft' else [DEFAULT_IMAGE_MODEL, DEFAULT_DRAFT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL])
    resolution = str(params.get('resolution') or params.get('image_size') or '').upper()
    explicit = params.get('_resolutionSource') in {'user', 'parameter'}
    if level == 'draft':
        family = (['bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-pro']
                  if resolution == '1K' and explicit else
                  ['bytedance-seed/seedream-5-0-lite', 'bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-pro'])
    elif resolution == '4K':
        family = ['bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-lite']
    else:
        family = ['bytedance-seed/seedream-5-0-pro', 'bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-lite']
    candidates = [item for item in _dedupe([configured, *builtins, *family])
                  if MediaModelRouter.automatic_image_model_allowed(item)]
    return {'mode': 'auto', 'tier': level, 'primaryModel': candidates[0],
            'candidateModels': candidates, 'allCandidateModels': candidates, 'unavailableModels': []}


def plan_image_route(registry, *, provider, base_url, requested_model, decision, params, has_references):
    """Plan against the current catalog; explicit models remain single-shot."""
    routing_params = dict(params)
    routing_params['_resolutionSource'] = decision.get('resolutionSource')
    catalog = getattr(registry, 'catalog', None)
    if catalog and provider in {'openrouter', 'openai-compatible', 'evolink'}:
        # Task payloads may carry the user-entered gateway root while model
        # discovery is stored under the adapter's canonical `/v1` endpoint.
        # Text routing already resolves through an adapter before consulting
        # the catalog; do the same for media preflight so a harmless trailing
        # slash or omitted `/v1` cannot make every image model look absent.
        probe_model = requested_model or catalog.settings().media['image'].get(decision['tier']) or DEFAULT_DRAFT_IMAGE_MODEL
        adapter = registry.image(provider, base_url=base_url or None, model=probe_model)
        catalog_base_url = str(getattr(adapter, 'base_url', None) or base_url).rstrip('/')
        plan = MediaModelRouter(catalog).image_plan(
            provider=provider, base_url=catalog_base_url, model=requested_model or None,
            quality=decision['tier'], params=routing_params, has_references=has_references,
        )
    else:
        settings = catalog.settings() if catalog else type('Settings', (), {'media': {'image': {
            'draft': DEFAULT_DRAFT_IMAGE_MODEL, 'standard': DEFAULT_IMAGE_MODEL, 'final': DEFAULT_IMAGE_MODEL,
        }}})()
        plan = _literal_plan(settings, requested_model=requested_model, tier=decision['tier'],
                             params=routing_params, has_references=has_references)
    return plan


def _supports_seedream(candidate: str, options: dict[str, Any], decision: dict[str, Any], adapter, reference_count: int) -> bool:
    family = _seedream(candidate)
    if not family:
        return True
    resolution = str(decision.get('resolution') or options.get('resolution') or '').upper()
    explicit_size = str(decision.get('size') or options.get('size') or '').lower().replace('×', 'x')
    pixels = re.fullmatch(r'([1-9]\d*)x([1-9]\d*)', explicit_size)
    if not resolution and pixels:
        edge = max(int(pixels.group(1)), int(pixels.group(2)))
        resolution = '1K' if edge <= 1024 else '2K' if edge <= 2048 else '4K'
    supported = {'lite': {'2K', '4K'}, 'pro': {'1K', '2K'}, '4.5': {'1K', '2K', '4K'}}[family]
    if resolution and resolution not in supported:
        return False
    if reference_count > 14 or options.get('mask_asset_path'):
        return False
    parameters = getattr(adapter, 'supported_parameters', None)
    if options.get('background') == 'transparent':
        # Seedream catalog records do not currently promise alpha output.
        return False
    ratio = options.get('aspect_ratio') or options.get('aspectRatio')
    definition = parameters.get('aspect_ratio') if isinstance(parameters, dict) else None
    allowed = (definition.get('values') or definition.get('enum') or []) if isinstance(definition, dict) else []
    if ratio not in (None, '', 'auto') and allowed and ratio not in allowed:
        return False
    return True


def build_image_route(
    registry,
    *,
    provider: str,
    base_url: str,
    requested_model: str | None,
    decision: dict[str, Any],
    params: dict[str, Any],
    has_references: bool,
    reference_count: int = 0,
):
    """Create a fresh adapter and wire parameters for every route candidate."""
    base = apply_policy_dimensions(params, decision)
    plan = plan_image_route(
        registry, provider=provider, base_url=base_url, requested_model=requested_model,
        decision=decision, params=base, has_references=has_references,
    )
    candidates: list[ImageCandidate] = []
    incompatible: list[dict[str, str]] = []
    for model in plan['candidateModels']:
        candidate_decision = deepcopy(decision)
        candidate_params = dict(base)
        adjustments: list[str] = []
        family = _seedream(model)
        if family == 'lite' and str(candidate_decision.get('resolution') or '').upper() == '1K':
            if candidate_decision.get('resolutionSource') in {'user', 'parameter'}:
                incompatible.append({'model': model, 'reason': 'Lite 不支持用户明确指定的 1K'})
                continue
            candidate_decision['resolution'] = '2K'
            candidate_params['resolution'] = '2K'
            adjustments.append('Seedream Lite 最低分辨率提升为 2K')
        if re.search(r'(?:^|/)gpt-image-2(?:-\d{4}-\d{2}-\d{2})?$', model, re.I) and candidate_decision.get('quality') in {'xhigh', 'max'}:
            candidate_decision['quality'] = 'high'
            adjustments.append('GPT Image 2 使用其最高兼容质量 high')
        adapter = registry.image(provider, base_url=base_url or None, model=model)
        # Exact user/UI dimensions remain strict. Pixels invented by the Agent
        # may be normalized locally before preflight so a tiny arithmetic error
        # (for example 3840x1200 = 3.2:1) cannot consume more model turns or
        # reach a paid Provider request.
        explicit_size = str(candidate_params.get('size') or '').strip()
        if (
            candidate_decision.get('resolutionSource') == 'tool'
            and getattr(adapter, 'api', 'images') in {'images', 'evolink'}
            and is_custom_gpt_image(model)
            and explicit_size and explicit_size.lower() != 'auto'
            and candidate_params.get('width') is None and candidate_params.get('height') is None
        ):
            dimensions = pixel_dimensions(explicit_size)
            if not valid_native_gpt_dimensions(*dimensions):
                repaired_size = nearest_native_gpt_size(explicit_size)
                candidate_params['size'] = repaired_size
                adjustments.append(f'Agent 推导尺寸 {explicit_size.replace("×", "x")} 自动修正为 {repaired_size}（满足原生 GPT Image 限制）')
        if not _supports_seedream(model, candidate_params, candidate_decision, adapter, reference_count):
            incompatible.append({'model': model, 'reason': '尺寸、比例、透明背景、蒙版或参考图要求不兼容'})
            continue
        try:
            options, report = apply_image_quality(
                candidate_params, model=model, provider_api=getattr(adapter, 'api', 'images'),
                tier=candidate_decision['tier'], provider_quality=candidate_decision['quality'],
                policy=candidate_decision, has_references=has_references, provider_key=provider,
                supported_parameters=getattr(adapter, 'supported_parameters', None),
            )
        except ValueError as error:
            if plan['mode'] == 'manual':
                raise
            incompatible.append({'model': model, 'reason': str(error)[:240]})
            continue
        if adjustments:
            report['routeAdjustments'] = adjustments
        candidates.append(ImageCandidate(provider, model, adapter, options, report, adjustments))
    if not candidates:
        detail = '；'.join(f"{item['model']}: {item['reason']}" for item in incompatible[:4])
        raise ValueError('没有模型能保持本次图像尺寸、比例、透明背景、蒙版和参考图要求' + (f'：{detail}' if detail else ''))
    plan['incompatibleModels'] = incompatible
    plan['candidateModels'] = [candidate.model for candidate in candidates]
    return plan, candidates


_SAFE_UNAVAILABLE = re.compile(
    r'(?:model[^\n]{0,80}(?:not found|does not exist|unavailable|not available|unknown)|'
    r'no (?:available )?(?:image )?endpoints?|model_not_found|'
    r'模型[^\n]{0,40}(?:不存在|不可用|未找到)|无可用[^\n]{0,20}(?:图像)?端点)',
    re.I,
)
_UNSAFE_REJECTION = re.compile(
    r'authentication|unauthorized|forbidden|api[ _-]?key|insufficient (?:balance|credit)|\bbalance\b|\bcredits?\b|'
    r'budget|content (?:policy|moderation)|safety|quality|resolution|aspect|mask|reference|'
    r'鉴权|认证|密钥|余额|积分|预算|审核|安全策略|质量|尺寸|分辨率|比例|蒙版|参考图',
    re.I,
)


def _has_usage(adapter, error=None) -> bool:
    if getattr(error, 'usage', None):
        return True
    response = getattr(adapter, 'last_response', {})
    usage = response.get('usage') if isinstance(response, dict) else None
    return bool(usage)


def safe_to_fallback(error: Exception, adapter) -> bool:
    """True only when the failed attempt is known not to have produced work."""
    if _has_usage(adapter, error):
        return False
    status = getattr(error, 'status_code', None)
    if status == 429:
        return True
    message = str(error)
    return status in {400, 404, 422} and not _UNSAFE_REJECTION.search(message) and bool(_SAFE_UNAVAILABLE.search(message))


def sanitized_reason(error: Exception) -> str:
    text = re.sub(r'(?i)(?:sk-|bearer\s+)[A-Za-z0-9._-]{8,}', '[REDACTED]', str(error))
    return text[:240]


def dispatch_image_route(
    plan: dict[str, Any],
    candidates: list[ImageCandidate],
    *,
    prompt: str,
    negative_prompt: str | None,
    on_submitted: Callable[[ImageCandidate], None] | None = None,
    on_status: Callable[[dict[str, Any]], None] | None = None,
    validate_content: Callable[[bytes, ImageCandidate], Any] | None = None,
):
    """Dispatch one candidate at a time and retry only proven safe rejects."""
    route_models = _dedupe([*plan.get('allCandidateModels', []), *(item.model for item in candidates)])
    statuses = [{'model': model, 'status': 'planned'} for model in route_models]
    index = {item['model']: item for item in statuses}

    def record(candidate, status, reason=None):
        index.setdefault(candidate.model, {'model': candidate.model})['status'] = status
        if reason:
            index[candidate.model]['reason'] = reason
        if on_status:
            on_status({'model': candidate.model, 'status': status, **({'reason': reason} if reason else {})})

    for model in plan.get('unavailableModels', []):
        item = type('UnavailableCandidate', (), {'model': model})()
        record(item, 'planned')
        record(item, 'safe_rejected', '本地模型目录中不可用')
    for item in plan.get('incompatibleModels', []):
        skipped = type('IncompatibleCandidate', (), {'model': item['model']})()
        record(skipped, 'planned')
        record(skipped, 'safe_rejected', item['reason'])
    for candidate in candidates:
        record(candidate, 'planned')
    last_error = None
    for position, candidate in enumerate(candidates):
        submitted = False

        def started():
            nonlocal submitted
            if submitted:
                return
            submitted = True
            record(candidate, 'submitted')
            if on_submitted:
                on_submitted(candidate)

        try:
            with image_request_scope(started):
                if not getattr(candidate.adapter, 'reports_image_request_start', False):
                    started()
                content = candidate.adapter.generate(
                    prompt=prompt, negative_prompt=negative_prompt, model=candidate.model, **candidate.options,
                )
            validation = validate_content(bytes(content), candidate) if validate_content else None
            record(candidate, 'succeeded')
            summary = {
                'mode': plan['mode'], 'tier': plan['tier'], 'primaryModel': plan['primaryModel'],
                'finalModel': candidate.model, 'fallbackUsed': candidate.model != plan['primaryModel'],
                'candidates': statuses, 'parameterAdjustments': candidate.adjustments,
            }
            return content, candidate, summary, validation
        except Exception as error:
            last_error = error
            if plan['mode'] == 'auto' and safe_to_fallback(error, candidate.adapter):
                record(candidate, 'safe_rejected', sanitized_reason(error))
                if position + 1 < len(candidates):
                    continue
                raise
            record(candidate, 'unknown' if submitted else 'safe_rejected', sanitized_reason(error))
            raise
    raise last_error or RuntimeError('没有可用的图像候选模型')
