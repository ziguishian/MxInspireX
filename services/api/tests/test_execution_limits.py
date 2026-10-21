import pytest

from app.model_config import ModelSettings
from app.task_policy import delivery_contract


def test_saved_tier_deadlines_are_discarded_without_changing_models():
    original = ModelSettings().model_dump(mode='json')
    legacy = ModelSettings().model_dump(mode='json')
    for tier in legacy['tiers'].values(): tier['timeout'] = 300
    loaded = ModelSettings.model_validate(legacy)
    assert loaded.model_dump(mode='json') == original
    assert all(tier.timeout is None for tier in loaded.tiers.values())


@pytest.mark.parametrize('dimensions', ['148×210mm', '148 × 210 mm', '148mm×210mm', '148×210毫米', '148×210厘米', '148×210cm'])
def test_print_dimensions_are_not_pixel_requirements(dimensions):
    contract = delivery_contract(f'生成笔记本平面印刷图，A5（{dimensions}），精装封面展开图')
    image = next(item for item in contract if item['kind'] == 'image')
    assert 'width' not in image and 'height' not in image


@pytest.mark.parametrize('dimensions', ['1024×1536', '1024×1536px', '1024px×1536px', '1024×1536像素'])
def test_pixel_output_dimensions_still_apply(dimensions):
    image = delivery_contract(f'生成一张图片，{dimensions}')[0]
    assert (image['width'], image['height']) == (1024, 1536)


def test_physical_print_size_and_separate_raster_size():
    image = delivery_contract('生成 A5（148×210mm）的封面图片，输出 1748×2480 像素')[0]
    assert (image['width'], image['height']) == (1748, 2480)
