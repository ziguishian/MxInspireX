from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from app.design_tools import DesignToolError
from app.svg_text import outline_svg_text
from app.svg_print import preflight_svg
from test_design_execution import env

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="154mm" height="216mm" viewBox="0 0 154 216"><rect width="154" height="216" fill="#F5F1E8"/><text x="25" y="40" font-family="Noto Sans SC" font-size="6" fill="#174D38">青屿 QINGYU</text></svg>'
SPEC = {'trim_width_mm':148,'trim_height_mm':210,'bleed_mm':3,'safe_margin_mm':5}


def test_historical_print_helpers_preserve_chinese_outlines_and_spec():
    # Retain validation of historical files; Agent authoring is disabled.
    root = ET.fromstring(SVG)
    outlines = outline_svg_text(root)
    report = preflight_svg(root, SPEC)
    assert outlines['glyphs'] == 8
    assert report['trimBox'] == [3,3,148,210]
    assert report['safeBox'] == [8,8,138,200]
    assert report['pressApproved'] is False
    tags = [e.tag.split('}')[-1] for e in root.iter()]
    assert tags.count('path') == 8 and 'text' not in tags and 'image' not in tags


@pytest.mark.parametrize('svg,spec,error',[
    (SVG,SPEC,'尚未转曲'),
    (SVG.replace('154mm','154px'),SPEC,'mm 单位'),
    (SVG.replace('154mm','148mm'),SPEC,'四边出血'),
    (SVG.replace('0 0 154 216','0 0 308 432'),SPEC,'viewBox'),
    (SVG,{**SPEC,'bleed_mm':float('nan')},'finite'),
    (SVG,{**SPEC,'safe_margin_mm':80},'安全边距'),
    (SVG.replace('<text','<image').replace('</text>','</image>'),SPEC,'静态矢量'),
])
def test_invalid_print_never_creates_asset(env,svg,spec,error):
    _, project, _, registry, enqueue, call=env
    with pytest.raises(DesignToolError,match='全局禁用'):
        call(enqueue('打印检查'),'canvas_create_svg',svg=svg,print_spec=spec)
    assert registry.asset_store.list_assets(project) == []


@pytest.mark.parametrize('change,error',[
    ('font-family="Another Font"','仅支持'),
    ('font-weight="bold"','常规字重'),
    ('style="font-size:6px"','CSS'),
    ('rotate="20"','复杂排版'),
    ('x="2 4"','单个'),
])
def test_outline_rejects_silent_font_and_layout_changes(change,error):
    text=SVG.replace('font-family="Noto Sans SC"',change)
    if change.startswith('x='):
        text=text.replace('x="25" ', '')
    with pytest.raises(ValueError,match=error):
        outline_svg_text(ET.fromstring(text))


def test_anchor_and_tracking_have_correct_relative_position():
    def path(anchor):
        root=ET.fromstring(f'<svg><text x="50" y="40" font-size="6" text-anchor="{anchor}" letter-spacing="2">AA</text></svg>')
        outline_svg_text(root)
        return root.find('g/path').get('d')
    import re
    xs=[float(re.match(r'M([\d.-]+)',path(anchor))[1]) for anchor in ('start','middle','end')]
    assert xs[0] > xs[1] > xs[2]
    assert xs[0]-xs[1] == pytest.approx(xs[1]-xs[2],abs=0.0001)
