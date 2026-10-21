"""Outline simple Chinese/Latin SVG labels with a bundled OFL font, offline."""
import math
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

FONT_PATH = Path(__file__).with_name('print_fonts') / 'NotoSansSC-Regular.otf'
FONT_NAME = 'Noto Sans SC'


def number(value, label):
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', str(value)):
        raise ValueError('文字转曲：' + label + ' 需为单个 SVG 坐标数值，不带单位')
    result = float(value)
    if not math.isfinite(result) or abs(result) > 100000:
        raise ValueError('文字转曲：坐标或字号超出范围')
    return result


def outline_svg_text(root):
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen

    labels, inherited_keys = [], {'font-family', 'font-size', 'font-weight', 'font-style', 'text-anchor', 'letter-spacing'}
    def visit(element, inherited):
        tag = element.tag.split('}')[-1].lower()
        if tag in {'style', 'tspan', 'textpath'} or element.get('style'):
            raise ValueError('文字转曲：请使用无 CSS 的独立 text 元素；暂不支持 tspan/textPath')
        if any(key in element.attrib for key in ('textLength', 'lengthAdjust', 'rotate', 'dx', 'dy', 'writing-mode', 'direction', 'dominant-baseline', 'alignment-baseline', 'font-feature-settings', 'word-spacing')):
            raise ValueError('文字转曲：复杂排版请先展平成使用 x/y 基线定位的独立文字行')
        attrs = {**inherited, **{k:v for k,v in element.attrib.items() if k in inherited_keys}}
        if tag == 'text':
            if len(element):
                raise ValueError('文字转曲：text 必须为单行纯文本')
            labels.append((element, attrs))
        for child in element:
            visit(child, attrs)
    visit(root, {})
    if sum(len(element.text or '') for element, _ in labels) > 1200:
        raise ValueError('文字转曲：一次最多 1200 字，请拆分页面')
    if not labels:
        return {'font': FONT_NAME, 'labels': 0, 'glyphs': 0}
    if not FONT_PATH.is_file():
        raise ValueError('文字转曲：应用内置字体缺失，请修复安装')
    glyph_count = 0
    with TTFont(FONT_PATH) as font:
        glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
        units = font['head'].unitsPerEm
        for element, attrs in labels:
            if attrs.get('font-family', FONT_NAME).strip('\"\x27') not in {FONT_NAME, 'NotoSansSC'}:
                raise ValueError('文字转曲：仅支持内置 Noto Sans SC；请先明确采用该字体或提供已转曲字标')
            if attrs.get('font-weight', '400') not in {'normal', '400'} or attrs.get('font-style', 'normal') != 'normal':
                raise ValueError('文字转曲：内置字体为常规字重，不支持模拟粗体或斜体')
            text = ' '.join((element.text or '').split())
            if any(ord(c) not in cmap or unicodedata.combining(c) or unicodedata.bidirectional(c) in {'R', 'AL', 'AN'} for c in text):
                raise ValueError('文字转曲：字体不含某些字符或文本需要复杂塑形，请换字/使用专业排版提供的路径')
            size = number(attrs.get('font-size', ''), 'font-size')
            if size <= 0:
                raise ValueError('文字转曲：字号必须大于 0')
            x, y = number(element.get('x', '0'), 'x'), number(element.get('y', '0'), 'y')
            spacing = number(attrs.get('letter-spacing', '0'), 'letter-spacing')
            scale = size / units
            widths = [glyphs[cmap[ord(c)]].width * scale for c in text]
            total = sum(widths) + max(0, len(widths)-1) * spacing
            anchor = attrs.get('text-anchor', 'start')
            if anchor not in {'start', 'middle', 'end'}:
                raise ValueError('文字转曲：text-anchor 只支持 start/middle/end')
            x -= total * {'start': 0, 'middle': .5, 'end': 1}[anchor]
            namespace = element.tag.rsplit('}', 1)[0] + '}' if '}' in element.tag else ''
            element.tag = namespace + 'g'
            element.text = None
            for key in inherited_keys | {'x', 'y'}:
                element.attrib.pop(key, None)
            element.set('data-outlined-font', FONT_NAME)
            title = ET.SubElement(element, namespace + 'title')
            title.text = text
            for character, width in zip(text, widths):
                pen = SVGPathPen(glyphs, ntos=lambda n: format(n, '.5f').rstrip('0').rstrip('.') or '0')
                glyphs[cmap[ord(character)]].draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
                commands = pen.getCommands()
                if commands:
                    ET.SubElement(element, namespace + 'path', {'d': commands})
                    glyph_count += 1
                x += width + spacing
    return {'font': FONT_NAME, 'labels': len(labels), 'glyphs': glyph_count}
