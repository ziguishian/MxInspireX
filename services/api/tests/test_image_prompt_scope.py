"""The image endpoint gets pixels and visual intent, not Agent reasoning."""
from copy import deepcopy

from app.image_production import append_visual_constraints, prepare_production_image_request
from app.image_reference_design import compile_design_spec, prepare_reference_design
from test_design_quality import direction, image_spec


def test_complete_visual_prompt_is_not_expanded_into_a_plan_or_analysis():
    prompt = '3:2 横向茶礼盒，粗纹本色纸、凹压山线、局部烫银。左上方柔光；保留品名主位置与盒体比例。标题“任务：慢下来”，副标题“仅供参考”。'
    spec = image_spec()
    context = {'designPlan': {'visualDirection': direction(), 'deliverables': [
        {'id': 'box', 'title': '茶礼盒主视觉', 'kind': 'image', 'imageSpec': spec}]}}
    args = compile_design_spec(context, {'itemIds': ['box']}, {'prompt': prompt})
    analysis = {'images': [{'asset_id': 'palette', 'mode': 'inspiration',
        'visual_prompt': '青色竹叶和旧包装上的大标题', 'use': '提取纸材的凹压效果', 'avoid': '旧包装标题'}],
        'synthesis': '选择此方向的理由：符合目标受众，执行后保存并检查产物。'}
    visual, snapshot, pixels = prepare_reference_design(args['prompt'], ['palette'], analysis, {}, required=True)
    sent, negative = prepare_production_image_request(visual, args['negative_prompt'], allow_disclaimer=True)
    assert sent == prompt  # Exact on-image wording survives, including workflow-like words.
    assert pixels == [] and snapshot['analysis']['synthesis'] == analysis['synthesis']
    assert args['_design_spec']['imageSpec'] == spec and '塑料反光' in negative


def test_edit_keeps_pixel_order_and_uses_one_task_marker_without_analysis():
    analysis = {'images': [
        {'asset_id': 'palette', 'mode': 'inspiration', 'visual_prompt': '海边日落', 'use': '只取暖色'},
        {'asset_id': 'original', 'mode': 'edit', 'visual_prompt': '不应重绘整张原图的长篇观察',
         'use': '更改杯身颜色', 'preserve': 'Logo、背景与构图'},
        {'asset_id': 'logo', 'mode': 'identity', 'visual_prompt': '黑色标识', 'use': '保持标识', 'preserve': '标识形状'},
    ], 'synthesis': '内部推理：检查参考绑定后按计划执行，保存新节点。'}
    original = deepcopy(analysis)
    prompt = '图像编辑任务：仅将杯身改为暖橙色，Logo、背景与构图不变。'
    sent, snapshot, pixels = prepare_reference_design(prompt, ['palette', 'original', 'logo'], analysis, {}, required=True, masked_edit=False)
    assert sent.startswith(prompt) and sent.count('图像编辑任务') == 1
    assert pixels == ['original', 'logo']
    assert '输入图 1（待编辑原图）' in sent and '输入图 2（外观参考）' in sent
    assert '内部推理' not in sent and '海边日落' not in sent and '长篇观察' not in sent
    assert snapshot['analysis']['synthesis'] == analysis['synthesis'] and analysis == original


def test_visual_constraints_are_idempotent_and_do_not_truncate_copy():
    prompt = '黑白海报，正文“' + '这是用户指定的完整文案。' * 60 + '”'
    once = append_visual_constraints(prompt, '底部文字基线 y=90%', '底部文字基线 y=90%')
    assert once.count('底部文字基线 y=90%') == 1 and prompt in once
    first = prepare_production_image_request(once, '模糊')
    assert prepare_production_image_request(*first) == first
