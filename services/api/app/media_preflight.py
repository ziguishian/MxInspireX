"""Local media capability checks before any Agent/model request."""
import re

from .design_runtime import DesignRuntimeError
from .task_policy import delivery_inference_text, delivery_requirements, is_simple_conversation


def audio_configuration(registry, config, canvas=None):
    canvas = canvas or {}
    key = config.get('key') or 'openai-compatible'
    from .evolink import EVOLINK_BASE_URL
    base = EVOLINK_BASE_URL if key == 'evolink' else config.get('baseUrl') or ('https://openrouter.ai/api/v1' if key == 'openrouter' else 'https://api.openai.com/v1')
    model = (canvas.get('model') if canvas.get('kind') == 'audio' else None) or config.get('model')
    # A blank selection may use the single integrated speech route only when
    # that exact model was observed in this account's local catalog.
    if not model and key == 'evolink' and registry.catalog.record(key, base, 'qwen-audio-3.1-tts-flash'):
        model = 'qwen-audio-3.1-tts-flash'
    record = registry.catalog.record(key, base, model or '') if registry.catalog else {}
    if not model or not record or 'audio' not in record.get('kinds', []):
        raise ValueError('请先选择支持语音生成的音频模型；本次尚未调用 Agent 或媒体服务')
    if not registry.credentials.get(key):
        raise ValueError('请先配置语音服务的 API Key；本次尚未调用 Agent 或媒体服务')
    return {'key':key, 'baseUrl':base, 'model':model}


def preflight_media(registry, brief, context):
    if not registry.catalog or is_simple_conversation(brief, context): return context
    canvas = context.get('canvasParams') or {}
    kinds = set(delivery_requirements(brief, context)) | {canvas.get('kind')}
    positive = delivery_inference_text(brief)
    if re.search(r'(?:生成|制作|创建|交付|导出|做).{0,35}(?:3d\s*(?:模型|model)|三维模型|\bglb\b)', positive, re.I) and 'cad' not in kinds:
        kinds.add('3d')
    media = dict(context.get('mediaProvider') or {})
    try:
        if '3d' in kinds:
            config = media.get('threeD') or {}
            from .model_config import EndpointModel
            EndpointModel.safe_endpoint(config.get('endpoint') or '')
            key = registry.detect_3d_provider(config.get('endpoint'), config.get('key'))
            if not config.get('endpoint') or key not in {'meshy','tripo','rodin','hunyuan3d'} or not registry.credentials.get(key):
                raise ValueError('请先设置已支持的 Meshy、Tripo、Rodin 或 Hunyuan3D 服务地址及 Key；本次尚未调用 Agent 或媒体服务')
        if 'audio' in kinds:
            media['audio'] = audio_configuration(registry, media.get('audio') or {}, canvas)
    except ValueError as error:
        raise DesignRuntimeError(str(error), kind='configuration', submitted=False, billing_certainty='not_submitted') from error
    return {**context, 'mediaProvider':media}
