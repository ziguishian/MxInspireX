import copy
import pytest
from unittest.mock import patch
from app.design_planning import planning_profile
from app.task_policy import delivery_contract
from test_design_execution import env

BRIEF='生成两张图片和一张文字卡。第一张产品摄影，第二张窗边生活照，文字卡写品牌介绍，跳过参考。'
PLAN={'goal':'交付两图和文字卡','preserve':[], 'deliverables':[
    {'id':'photo','title':'产品摄影','kind':'image','acceptance':'产品摄影'},
    {'id':'scene','title':'窗边摄影','kind':'image','acceptance':'窗边生活照'},
    {'id':'copy','title':'文字卡','kind':'text','acceptance':'品牌介绍'}],
    'coverage':[],'deferred':[],'openQuestions':[],'research':'使用用户要求，不做研究'}

def test_mixed_counts_do_not_cross_the_next_quantity():
    assert {x['kind']:x['count'] for x in delivery_contract(BRIEF)}=={'image':2,'text':1}
    assert planning_profile(BRIEF)=='deliverables'
    assert planning_profile('生成一张海报，跳过参考') is None


@pytest.mark.parametrize('negative',['不调用图像或额外文本生成模型','不做图片','不加海报','不使用图像生成工具'])
def test_explicit_text_task_does_not_gain_negated_visual_outputs(negative):
    brief='只创建一个Markdown文本节点，写品牌定位和应用清单。只要文字，'+negative+'，不做研究。'
    assert {x['kind']:x['count'] for x in delivery_contract(brief)}=={'text':1}
    assert planning_profile(brief) is None


@pytest.mark.parametrize('brief', [
    '为图片中的陶土香薰炉制作一页商品详情HTML，直接使用这张附件作为商品图片，不调用图像模型。图片可见外观可描述。只交付一个HTML节点。',
    '使用上传的照片制作一个HTML网页，不生成图片。',
    '为照片所示产品创建一个网站，复用已有图片。',
])
def test_html_product_reference_is_not_an_image_delivery(brief):
    assert {x['kind']:x['count'] for x in delivery_contract(brief)} == {'html':1}
    assert planning_profile(brief) is None


def test_html_and_explicit_new_image_remain_mixed():
    brief = '为图片中的产品制作一个HTML网页，直接使用附件作为商品图片，另外生成两张海报。'
    assert {x['kind']:x['count'] for x in delivery_contract(brief)} == {'html':1,'image':2}

@pytest.mark.parametrize(('brief','expected'),[
    ('生成两张图和文字卡', {'image':2,'text':1}),
    ('生成两张独立的1:1图片和一张文字卡。只交付这两张图和文字卡，跳过参考搜索与研究，不需要确认方案，不做审查。', {'image':2,'text':1}),
    ('生成两张图和两张文字卡', {'image':2,'text':2}),
    ('生成三张文字卡和两张图片', {'image':2,'text':3}),
    ('生成2张产品摄影图片和1张文字说明卡', {'image':2,'text':1}),
])
def test_quantity_binds_only_to_its_nearest_output(brief,expected):
    assert {x['kind']:x['count'] for x in delivery_contract(brief)}==expected

def test_mixed_outputs_have_stable_typed_bindings_and_no_self_regeneration(env):
    store,project,_,tools,enqueue,call=env
    task=enqueue(BRIEF)
    assert call(task,'generate_image',prompt='提前生成',provider='local-placeholder')['status']=='planning_required'
    wrong=copy.deepcopy(PLAN);wrong['deliverables'][2]['kind']='image'
    result=call(task,'design_plan',plan=wrong)
    assert result['status']!='ready'
    assert call(task,'design_plan',plan=PLAN)['status']=='ready'
    first=call(task,'generate_image',prompt='产品摄影',provider='local-placeholder',deliverable_ids=['photo'])
    with patch('app.providers.local.LocalImageProvider.generate',side_effect=AssertionError('same deliverable must not charge again')):
        repeated=call(task,'generate_image',prompt='模型自行润色的摄影提示词',provider='local-placeholder',deliverable_ids=['photo'])
        assert repeated['assetId']==first['assetId'] and repeated['reused']
        assert call(task,'generate_image',prompt='不能画文字卡',provider='local-placeholder',deliverable_ids=['copy'])['status']=='delivery_assignment_required'
    call(task,'generate_image',prompt='窗边生活照',provider='local-placeholder',deliverable_ids=['scene'])
    call(task,'canvas_create_text',text='暖屿，陪你慢下来。',deliverable_ids=['copy'])
    assert len(tools.asset_store.list_assets(project))==2
    assert [n['data']['kind'] for n in tools.canvas_store.load(project)['nodes']].count('text')==1
