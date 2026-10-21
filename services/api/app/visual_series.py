"""Apply consistency requirements independently of execution dependencies."""
import hashlib
import json
from fractions import Fraction
from .image_parameters import ImageParameterError, TIERS, pixel_dimensions, ratio_value
from .image_quality import _explicit_aspect_ratio, _explicit_dimensions
from .image_production import append_visual_constraints


def bind_visual_series(context, binding, args, nodes, assets, project_id):
    plan = context.get('designPlan') or {}
    ids = set(binding.get('itemIds', []))
    groups = [s for s in plan.get('visualSeries', []) if ids.intersection(s['memberIds'])]
    if not groups: return args
    if len(groups) != 1 or len(ids) != 1:
        raise ValueError('同一套系每次生成一个独立交付项；执行顺序按该项的输入依赖决定')
    series = groups[0]
    args = dict(args)
    options = dict(args.get('params') or {})
    layout_ratio = Fraction(*pixel_dimensions(series['size']))
    ratio = f'{layout_ratio.numerator}:{layout_ratio.denominator}'
    explicit = options.get('size')
    if options.get('width') is not None or options.get('height') is not None:
        dimensions = pixel_dimensions(f"{options.get('width')}x{options.get('height')}")
        if explicit and str(explicit).lower()!='auto' and pixel_dimensions(explicit)!=dimensions:
            raise ImageParameterError('套系生成的 size 与 width/height 冲突，请保留一组尺寸参数。')
        explicit = f'{dimensions[0]}x{dimensions[1]}'
    explicit_pixels = explicit and str(explicit).upper() not in TIERS and str(explicit).lower()!='auto'
    supplied_ratio = options.get('aspect_ratio') or options.get('aspectRatio')
    # A ready series already chose its aspect ratio. A later, model-authored
    # ratio is redundant, not a new user decision. Resolve that harmless drift
    # before preflight/dispatch, without changing explicit pixel dimensions or
    # a user's size/aspect request (including the original goal on continuation).
    user_texts = [context.get('userMessage', ''), (context.get('designState') or {}).get('goal', '')]
    user_dimensions = any(_explicit_aspect_ratio(text) or _explicit_dimensions(text)[0] for text in user_texts)
    canvas = context.get('canvasParams') or {}
    canvas_dimensions = any(canvas.get(key) or (canvas.get('params') or {}).get(key) for key in ('size','width','height','aspectRatio','aspect_ratio'))
    normalize_ratio = bool(plan.get('ready') and context.get('userMessage') and not user_dimensions
                           and not canvas_dimensions and context.get('taskSurface') != 'canvas_node')
    if ((explicit_pixels and Fraction(*pixel_dimensions(explicit))!=layout_ratio) or
        (not explicit_pixels and supplied_ratio and supplied_ratio!='auto' and ratio_value(supplied_ratio)!=layout_ratio)):
        if explicit_pixels or not normalize_ratio:
            raise ImageParameterError(f"套系 {series['id']} 约定版式 {series['size']}（{ratio}），本次尺寸改变了比例。请使用 aspect_ratio={ratio}；若需改版先更新设计计划。")
    for key in ('aspectRatio','aspect_ratio','aspect','size','width','height'):
        options.pop(key,None)
    # A plan's layout size is not a provider-native resolution. Preserve its
    # aspect ratio; let the selected adapter choose legal output dimensions.
    options['aspectRatio'] = ratio
    if explicit and str(explicit).lower()!='auto' and (not explicit_pixels or pixel_dimensions(explicit)!=pixel_dimensions(series['size'])):
        options['size'] = explicit
    args['params'] = options
    snapshot = dict(args.get('_reference_snapshot') or {})
    layout_inputs = [ref for ref in snapshot.get('inputBindings',[]) if ref.get('role')=='layout' and ref.get('assetIds')]
    args['prompt'] = append_visual_constraints(args.get('prompt', ''), *series['lockedLayout'])
    snapshot['visualSeries'] = {'id':series['id'],'layoutSize':series['size'],'aspectRatio':ratio,**({'masterAssetId':layout_inputs[0]['assetIds'][0]} if layout_inputs else {})}
    snapshot.pop('id',None)
    snapshot['id'] = hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    args['_reference_snapshot'] = snapshot
    return args
