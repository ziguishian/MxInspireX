import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from app.design_planning import planning_profile
from app.product_identity import IDENTITY_PRESERVE
from test_design_execution import env
from test_mixed_delivery_scope import PLAN

BRIEF='生成两张图片和一张文字卡。第一张产品摄影，第二张是同款香薰炉的窗边生活方式场景图，保留产品造型。跳过参考搜索。'


def analysis(asset, mode='identity'):
    return {'images':[{'asset_id':asset,'mode':mode,'visual_prompt':'矮圆陶土炉，拱形开口和顶部圆碟',
            'use':'将同一产品放到窗边木桌','preserve':'矮圆炉身、拱形开口、顶部圆碟与陶土材质'}],
            'synthesis':'原产品造型不变，仅用窗边自然光与木桌场景'}


def test_real_sources_are_bound_before_provider_and_both_outputs_are_idempotent(env):
    store,project,_,tools,enqueue,call=env
    task=enqueue(BRIEF)
    saved=call(task,'design_plan',plan=copy.deepcopy(PLAN))['plan']
    assert saved['deliverables'][1]['inputs'][0]=={'source':'deliverable','id':'photo','role':'identity',
        'purpose':'以第一张成图作为同款产品身份参考，保留产品造型与材质，仅改变场景、光照和视角'}
    assert saved['deliverables'][1]['dependsOn']==['photo']
    assert not saved['deliverables'][2]['dependsOn']
    calls=[]
    from app.providers.local import LocalImageProvider
    original=LocalImageProvider.generate
    def generate(self,**kwargs):
        calls.append(kwargs)
        return original(self,**kwargs)
    with patch.object(LocalImageProvider,'generate',generate):
        assert call(task,'generate_image',prompt='场景',deliverable_ids=['scene'])['status']=='dependency_required'
        assert not calls
        first=call(task,'generate_image',prompt='陶土炉产品摄影',deliverable_ids=['photo'])
        assert len(calls)==1
        # Missing analysis must not silently become text-to-image, even when
        # the caller omits source_asset_ids and the memory protocol is absent.
        rejected=call(task,'generate_image',prompt='窗边场景',deliverable_ids=['scene'])
        assert rejected['status']=='reference_analysis_required' and len(calls)==1
        inspected=call(task,'asset_inspect',asset_id=first['assetId'])
        assert inspected['image'].startswith('data:image/')
        second=call(task,'generate_image',prompt='窗边木桌上的陶土炉',deliverable_ids=['scene'],reference_analysis=analysis(first['assetId'],'inspiration'))
        assert second['status']=='succeeded',second
        path=tools.asset_store.get_asset(project_id=project,asset_id=first['assetId'])['absolutePath']
        assert calls[1]['source_asset_paths']==[path] and Path(path).is_file()
        assert IDENTITY_PRESERVE in calls[1]['prompt']
        snapshot=second['asset']['metadata']['referenceSnapshot']
        assert snapshot['providerInputAssetIds']==[first['assetId']]
        assert snapshot['inputBindings'][0]['role']=='identity'
        # Explicit scene/background changes remain edits under the shared
        # intent resolver; both modes send the actual source pixels.
        assert snapshot['analysis']['images'][0]['mode'] in {'identity','edit'}
        assert call(task,'generate_image',prompt='自行润色产品摄影',deliverable_ids=['photo'])['assetId']==first['assetId']
        assert call(task,'generate_image',prompt='自行润色窗边场景',deliverable_ids=['scene'])['assetId']==second['assetId']
        assert len(calls)==2
    assert len(tools.asset_store.list_assets(project))==2


def test_existing_product_input_is_reused_without_new_master(env):
    _,project,_,tools,enqueue,call=env
    base=enqueue('生成一张产品图')
    asset=call(base,'generate_image',prompt='陶土炉')['assetId']
    task=enqueue(BRIEF,referencedAssets=[{'id':asset,'projectId':project}])
    value=copy.deepcopy(PLAN)
    for item in value['deliverables'][:2]:
        item['inputs']=[{'source':'asset','id':asset,'role':'identity','purpose':'沿用用户产品图'}]
    saved=call(task,'design_plan',plan=value)['plan']
    assert all(not item['dependsOn'] for item in saved['deliverables'])
    assert all(item['inputs'][0]['id']==asset for item in saved['deliverables'][:2])


@pytest.mark.parametrize('brief',[
    '生成两张独立的风格海报和文字卡',
    '生成两张同品牌不同款产品的图片和文字卡',
    '生成两张图片和文字卡，不要求同款产品造型一致',
])
def test_shared_style_or_different_products_do_not_gain_dependencies(env,brief):
    *_,enqueue,call=env
    saved=call(enqueue(brief),'design_plan',plan=copy.deepcopy(PLAN))['plan']
    assert all(not item['dependsOn'] for item in saved['deliverables'])


def test_only_images_still_plan_same_product_dependencies_without_extra_outputs():
    assert planning_profile('只生成两张同款产品的图片，第一张产品图，第二张场景图')=='deliverables'
    assert planning_profile('生成一张同款产品场景图') is None
    assert planning_profile('生成两张独立的风格海报') is None


def test_multiple_scenes_depend_on_product_not_on_each_other(env):
    *_,enqueue,call=env
    value=copy.deepcopy(PLAN)
    value['deliverables'][1]['title']='窗边生活方式摄影'
    value['deliverables'].insert(2,{'id':'night','title':'夜晚场景摄影','kind':'image','acceptance':'同款产品在卧室'})
    saved=call(enqueue('生成三张图片和一张文字卡：产品摄影、窗边生活方式、夜晚场景，均为同款香薰炉。'),'design_plan',plan=value)['plan']
    assert [item['dependsOn'] for item in saved['deliverables']]==[[],['photo'],['photo'],[]]


def test_a_logo_must_not_be_guessed_as_the_product_identity(env):
    *_,enqueue,call=env
    value=copy.deepcopy(PLAN)
    value['deliverables'][0].update(title='品牌 Logo',acceptance='标志图形')
    result=call(enqueue(BRIEF),'design_plan',plan=value)
    assert result['status']!='ready'


def test_identity_mode_is_canonical_without_fabricating_analysis():
    from app.product_identity import bind_identity_analysis
    from app.image_reference_design import ReferenceDesignError
    snapshot={'inputBindings':[{'role':'identity','assetIds':['product']}]}
    original=analysis('product','inspiration')
    normalized=bind_identity_analysis(original,snapshot,[])
    assert normalized['images'][0]['mode']=='identity'
    assert original['images'][0]['mode']=='inspiration'
    assert IDENTITY_PRESERVE in normalized['images'][0]['preserve']
    with pytest.raises(ReferenceDesignError):
        bind_identity_analysis(None,snapshot,[])
    with pytest.raises(ReferenceDesignError):
        bind_identity_analysis(original,snapshot,[{'assetId':'product','confidence':'high','expectedMode':'inspiration'}])


def test_accepted_plans_are_not_silently_rewritten():
    from app.product_identity import bind_product_plan
    value=copy.deepcopy(PLAN)
    assert bind_product_plan(value,{'planAccepted':True,'userMessage':BRIEF})==PLAN
