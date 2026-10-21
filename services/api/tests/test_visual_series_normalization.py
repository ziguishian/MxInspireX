import copy
import pytest

from app.image_parameters import ImageParameterError
from app.visual_series import bind_visual_series


def context():
    return {'userMessage':'做一套礼盒概念设计', 'designPlan':{'ready':True,'visualSeries':[
        {'id':'suite','memberIds':['a','b'],'size':'1024x1024','lockedLayout':['统一背景与色彩'],'variableFields':['单品材质与造型']}]}}


def bind(value, params):
    return bind_visual_series(value,{'itemIds':['a']},{'prompt':'保持材质细节','params':params},[],None,'project')


def test_ready_series_locally_resolves_agent_ratio_without_changing_resolution_or_prompt():
    source=context();saved=copy.deepcopy(source)
    result=bind(source,{'aspect_ratio':'4:3','resolution':'1K'})
    assert result['params']=={'aspectRatio':'1:1','resolution':'1K'}
    assert result['prompt'].startswith('保持材质细节')
    assert '统一背景与色彩' in result['prompt']
    assert source==saved


@pytest.mark.parametrize('extra',[
    {'userMessage':'图片统一4:3'},
    {'userMessage':'宽高比四比三'},
    {'userMessage':'图片尺寸1600x1200'},
    {'designState':{'goal':'图片尺寸1600x1200'}},
    {'taskSurface':'canvas_node'},
    {'canvasParams':{'size':'1600x1200'}},
    {'canvasParams':{'params':{'aspect_ratio':'4:3'}}},
    {'userMessage':''},
])
def test_user_dimensions_canvas_and_unknown_origin_are_never_silently_overridden(extra):
    with pytest.raises(ImageParameterError,match='约定版式'):
        bind({**context(),**extra},{'aspect_ratio':'4:3'})


def test_explicit_pixels_and_invalid_ratios_still_fail_before_dispatch():
    for params in [{'size':'1600x1200'}, {'aspect_ratio':'broken'}, {'size':'1024x1024','width':1600,'height':1200}]:
        with pytest.raises(ImageParameterError):bind(context(),params)
