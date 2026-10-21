from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.evolink import EVOLINK_BASE_URL, normalize_evolink_model
from app.media_preflight import preflight_media
from app.design_runtime import DesignRuntimeError
from app.providers.registry import ProviderRegistry
from app.model_catalog import ModelCatalog
from app.storage import ProjectStore

def registry(tmp_path, models=(), key=True):
    catalog = ModelCatalog(ProjectStore(str(tmp_path)))
    catalog.save('evolink', EVOLINK_BASE_URL, {'models':list(models), 'modelCatalog':[normalize_evolink_model({'id':x}) for x in models]})
    return SimpleNamespace(catalog=catalog, credentials=SimpleNamespace(get=lambda _: 'test' if key else None), detect_3d_provider=ProviderRegistry.detect_3d_provider)

def test_audio_catalog_and_blank_selection_use_only_observed_supported_model(tmp_path):
    r=registry(tmp_path,['qwen-audio-3.1-tts-flash','suno-v5'])
    assert r.catalog.get('evolink',EVOLINK_BASE_URL)['audioModels'] == ['qwen-audio-3.1-tts-flash']
    result=preflight_media(r,'生成一段语音朗读：欢迎来到小岛。', {'mediaProvider':{'audio':{'key':'evolink'}}})
    assert result['mediaProvider']['audio']['model']=='qwen-audio-3.1-tts-flash'

@pytest.mark.parametrize('brief,context',[
    ('生成一段语音',{'mediaProvider':{'audio':{'key':'evolink'}}}),
    ('创建一个香炉的 3D 模型，交付 glb',{}),
    ('生成模型',{'canvasParams':{'kind':'3d'}}),
])
def test_unconfigured_media_stops_before_agent(tmp_path,brief,context):
    with pytest.raises(DesignRuntimeError) as error: preflight_media(registry(tmp_path),brief,context)
    assert error.value.submitted is False and error.value.billing_certainty == 'not_submitted'

def test_explicit_audio_model_not_overridden(tmp_path):
    with pytest.raises(DesignRuntimeError):
        preflight_media(registry(tmp_path,['qwen-audio-3.1-tts-flash']), '生成语音', {'mediaProvider':{'audio':{'key':'evolink','model':'missing'}}})

@pytest.mark.parametrize('brief',['生成一张 3D 风格海报，不要三维模型','你支持音频吗？','制作一段视频，不要音频','创建参数化 CAD 结构件'])
def test_visual_style_questions_and_negative_audio_not_blocked(tmp_path,brief):
    preflight_media(registry(tmp_path),brief,{})
