import base64
import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.image_quality import decide_image_policy, image_tier, apply_image_quality, apply_policy_dimensions
from app.main import app
from app.model_router import MediaModelRouter
from app.providers.http import OpenAICompatibleImageProvider, ProviderError
from test_image_transparency import image_bytes


@pytest.mark.parametrize('message,level',[('测试一下','standard'),('先看看效果','standard'),('快速试试','standard'),('不要草稿','standard'),('这次用草稿质量','draft'),('降低画质','draft'),('先用低质量，最后改用最高质量','final')])
def test_task_quality_comes_from_user_not_text_speed(message,level):
    assert image_tier('standard',user_message=message)==level


@pytest.mark.parametrize('message,quality,resolution,tier',[
    ('给我做一张海报','low','1K','draft'),
    ('先做概念草图看看','low','1K','draft'),
    ('基于这张图做高保真修改','high','2K','final'),
    ('用于商场大屏正式交付','high','4K','final'),
    ('给我超高画质版本','xhigh','4K','final'),
    ('我要最好的效果，质量拉满','max','4K','final'),
    ('最高质量，但只要2K','max','2K','final'),
    ('普通质量，3840x2160','medium',None,'standard'),
])
def test_image_policy_selects_quality_and_resolution(message,quality,resolution,tier):
    decision=decide_image_policy(None,user_message=message,prompt='模型扩写不得改变用户档位')
    assert decision['quality']==quality and decision['resolution']==resolution and decision['tier']==tier
    if '3840' in message:
        assert decision['size']=='3840x2160'


def test_user_resolution_overrides_agent_dimensions_and_normal_default_is_2k():
    decision=decide_image_policy('standard',user_message='请用4K输出',params={'size':'1536x864','aspectRatio':'16:9'})
    options=apply_policy_dimensions({'size':'1536x864','aspectRatio':'16:9'},decision)
    assert options=={'aspectRatio':'16:9','resolution':'4K'}
    assert decision['userOverride'] is True
    normal=decide_image_policy('standard',user_message='设计一张海报',params={'aspectRatio':'3:4'})
    assert apply_policy_dimensions({'aspectRatio':'3:4'},normal)=={'aspectRatio':'3:4','resolution':'2K'}


def test_direct_max_control_also_selects_4k_without_affecting_exact_size():
    maximum=decide_image_policy('max',prompt='海报')
    assert maximum['quality']=='max' and maximum['resolution']=='4K'
    exact=decide_image_policy('max',prompt='海报',params={'size':'2048x2048'})
    assert exact['quality']=='max' and exact['resolution'] is None


def test_descriptive_best_words_do_not_accidentally_buy_max_quality():
    decision=decide_image_policy('standard',user_message='参考这张高清图片，你觉得构图怎么做最好',
                                 prompt='masterpiece, best quality, ultra detailed')
    assert decision['quality']=='medium' and decision['resolution']=='2K'


def test_references_and_agent_selected_tier_do_not_upgrade_without_user_signal():
    creative = decide_image_policy('final', user_message='参考这张图改成夜景', prompt='精修、细节丰富',
                                   has_references=True, trust_requested=False)
    assert (creative['tier'], creative['quality'], creative['resolution']) == ('draft', 'low', '1K')
    final = decide_image_policy(None, user_message='生成最终效果图')
    assert (final['tier'], final['quality'], final['resolution']) == ('final', 'high', '2K')
    large = decide_image_policy(None, user_message='用于大屏正式交付，4K')
    assert (large['tier'], large['quality'], large['resolution']) == ('final', 'high', '4K')


def test_task_tool_dimensions_are_distinct_from_user_and_ui_dimensions():
    agent = decide_image_policy(
        None, user_message='做成三比一的背景', params={'size': '3840x1200'}, trust_dimensions=False,
    )
    assert (agent['tier'], agent['quality'], agent['resolution']) == ('draft', 'low', '1K')
    assert agent['resolutionSource'] == 'default'
    assert agent['discardToolDimensions'] is True
    assert agent['inferredAspectRatio'] == '3:1'
    assert agent['aspectRatioSource'] == 'user'
    user = decide_image_policy(
        None, user_message='尺寸必须是3840x1200', params={'size': '3840x1200'}, trust_dimensions=False,
    )
    assert user['resolutionSource'] == 'user' and user['size'] == '3840x1200'
    interface = decide_image_policy(None, prompt='直接生成', params={'size': '3840x1200'})
    assert interface['resolutionSource'] == 'parameter'


@pytest.mark.parametrize('model,api,quality,fidelity',[('gpt-image-1','images','high','high'),('gpt-image-2','images','high',None),('dall-e-3','images','hd',None),('dall-e-2','images',None,None),('unknown','gemini',None,None)])
def test_supported_quality_mapping_is_honest(model,api,quality,fidelity):
    options,report=apply_image_quality({'size':'1024x1024','quality':'low','input_fidelity':'low'},model=model,provider_api=api,tier='final',has_references=True)
    assert options.get('quality')==quality and options.get('input_fidelity')==fidelity
    if api=='gemini':
        assert options['aspectRatio']=='1:1' and options['resolution']=='1K'
    else:
        assert options['size']=='1024x1024'
    assert report['status']==('applied' if quality else 'unsupported')


def test_image_model_default_draft_and_manual_preserved():
    catalog=SimpleNamespace(settings=lambda:SimpleNamespace(media={'image':{'draft':'low-model','standard':'medium-model','final':'high-model'}}),resolve_id=lambda _p,_b,m:m)
    router=MediaModelRouter(catalog)
    assert router.route('image',provider='p',base_url='b')=='low-model'
    assert router.route('image',provider='p',base_url='b',model='manual')=='manual'
    assert router.route('image',provider='p',base_url='b',quality='draft')=='low-model'


def test_direct_generation_regeneration_and_wire_quality(tmp_path,monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT',str(tmp_path))
    content=image_bytes(mode='RGB')
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'data':[{'b64_json':base64.b64encode(content).decode()}]}).encode()
    provider=OpenAICompatibleImageProvider(provider_key='fixture',base_url='https://fixture.invalid/v1',model='gpt-image-1',credentials=SimpleNamespace(get=lambda _: 'test-secret'))
    with TestClient(app) as client, patch('app.providers.http.urllib.request.urlopen',return_value=Response()) as network:
        project=client.post('/api/projects',json={'name':'quality'}).json()['id']
        with patch.object(app.state.providers,'image',return_value=provider):
            result=client.post(f'/api/projects/{project}/generations/image',json={'prompt':'先看效果','model':'gpt-image-1','params':{'size':'1024x1536','source_asset_paths':['/never/read']}})
            assert result.status_code==201,result.text
            sent=json.loads(network.call_args.args[0].data)
            assert sent['quality']=='low' and sent['size']=='1024x1536'
            assert result.json()['asset']['metadata']['imageQuality']['quality']=='low'
            draft=client.post(f'/api/projects/{project}/generations/image',json={'prompt':'草稿','model':'gpt-image-1','quality':'draft'})
            assert draft.status_code==201,draft.text
            assert json.loads(network.call_args.args[0].data)['quality']=='low'
            identifier=draft.json()['generationId']
            regen=client.post(f'/api/projects/{project}/generations/{identifier}/regenerate',json={})
            assert regen.status_code==201,regen.text
            multipart=network.call_args.args[0].data
            assert b'name="quality"\r\n\r\nlow' in multipart
            assert b'name="input_fidelity"\r\n\r\nhigh' in multipart
            assert regen.json()['asset']['metadata']['referenceSnapshot']['references'][0]['assetId']==draft.json()['asset']['id']
            assert network.call_count==3


def test_quality_rejection_is_configuration_error_without_retry():
    provider=OpenAICompatibleImageProvider(provider_key='fixture',base_url='https://fixture.invalid/v1',model='gpt-image-1',credentials=SimpleNamespace(get=lambda _: 'test-secret'))
    rejection=urllib.error.HTTPError('https://fixture.invalid',400,'bad quality',{},io.BytesIO(b'{"error":"quality high rejected test-secret"}'))
    with patch('app.providers.http.urllib.request.urlopen',side_effect=rejection) as network:
        with pytest.raises(ProviderError,match='质量参数被供应商拒绝') as error:
            provider.generate(prompt='image',quality='high')
        assert error.value.status_code==400 and network.call_count==1
        assert 'test-secret' not in str(error.value)


@pytest.mark.parametrize('message,expected',[('这是之前的草稿，帮我完善','standard'),('参考附件 draft-logo.png','standard'),('把草稿做成最终效果','final')])
def test_mentioning_an_existing_draft_does_not_lower_new_output_quality(message,expected):
    assert image_tier('standard',user_message=message)==expected


def test_missing_final_slot_uses_the_builtin_final_route():
    catalog=SimpleNamespace(settings=lambda:SimpleNamespace(media={'image':{'standard':'medium-model'}}),resolve_id=lambda _p,_b,m:m)
    assert MediaModelRouter(catalog).route('image',provider='p',base_url='b',quality='final') == 'medium-model'
