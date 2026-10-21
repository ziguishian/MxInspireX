"""Create real vector QA artifacts through the existing SVG tool; no model calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'services/api'))
from app.storage import ProjectStore
from app.main import new_project
from app.assets import AssetStore
from app.design_tools import DesignToolRegistry

OUTPUT = ROOT/'docs/examples/builtin-skills'
OUTPUT.mkdir(parents=True, exist_ok=True)
GREEN, IVORY, GOLD, SAGE = '#174D38', '#F5F1E8', '#D0AA58', '#96AC93'


def svg(width, height, content, mm=False):
    unit = 'mm' if mm else ''
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}{unit}" height="{height}{unit}" viewBox="0 0 {width} {height}">{content}</svg>'


def label(x, y, size, text, color=GREEN, anchor='start', spacing=0):
    return f'<text x="{x}" y="{y}" font-family="Noto Sans SC" font-size="{size}" text-anchor="{anchor}" letter-spacing="{spacing}" fill="{color}">{text}</text>'


front = f'<rect width="154" height="216" fill="{IVORY}"/>'
front += label(25, 35, 4.7, 'QINGYU', spacing=1.1) + label(25, 42, 2.4, 'FIELD NOTES', spacing=.7)
front += f'<circle cx="117" cy="40" r="16" fill="{GOLD}"/>'
front += f'<path d="M0 162 C42 162 62 155 88 147 C115 139 135 143 154 150 V216 H0Z" fill="{GREEN}"/>'
front += ''.join(f'<path d="M0 {y} C45 {y-18} 61 {y+3} 88 {y-13} C117 {y-30} 135 {y-28} 154 {y-18}" fill="none" stroke="{SAGE}" stroke-width="0.7"/>' for y in [191,199])
back = f'<rect width="154" height="216" fill="{GREEN}"/><circle cx="77" cy="87" r="13" fill="{GOLD}"/>'
back += label(77, 120, 5, '青屿 · 自然手记', IVORY, 'middle') + label(77, 129, 2.3, 'QINGYU FIELD NOTES', IVORY, 'middle', .55)
back += f'<path d="M0 180 Q40 160 77 180 T154 180 M0 190 Q40 170 77 190 T154 190" stroke="{SAGE}" stroke-width="0.7" fill="none"/>'
inside = '<rect width="148" height="210" fill="#FFFFFF"/>' + label(20,18,2.5,'日期 / DATE')
inside += '<path d="'+' '.join(f'M20 {y} H136' for y in range(28,197,8))+'" stroke="#A8B5AA" stroke-width="0.15" fill="none"/>'
proof = f'<rect width="174" height="246" fill="#FFFFFF"/><g transform="translate(10 10)">{front}</g>'
proof += '<rect x="13" y="13" width="148" height="210" fill="none" stroke="#D04A46" stroke-width=".3" stroke-dasharray="2 1"/>'
proof += '<rect x="18" y="18" width="138" height="200" fill="none" stroke="#276CC2" stroke-width=".2" stroke-dasharray="2 1"/>'
proof += label(10,235,2.7,'技术稿：成品 148×210 mm / 出血 3 mm / 安全边距示例 5 mm')
proof += label(10,241,2.7,'线圈打孔区须由印厂确认；此页不可作为净印刷图。')

# Explicitly fictional local topology: E--V--B; V--L. No invented extra paths.
map_art = f'<rect width="800" height="1100" rx="16" fill="{IVORY}"/><rect width="800" height="205" rx="16" fill="{GREEN}"/>'
map_art += label(58,87,40,'青屿湿地',IVORY) + label(58,145,21,'导览示意图 / VISITOR GUIDE',IVORY)
map_art += '<path d="M230 820 V350 M230 580 H550" fill="none" stroke="#96AC93" stroke-width="28" stroke-linecap="round"/>'
points=[('E',230,820,'入口','ENTRANCE'),('V',230,580,'游客中心','VISITOR CENTRE'),('B',230,350,'观鸟台','BIRD HIDE'),('L',550,580,'湖畔','LAKESIDE')]
for code,x,y,cn,en in points:
    map_art += f'<circle cx="{x}" cy="{y}" r="24" fill="{GOLD if code=="E" else GREEN}" stroke="{IVORY}" stroke-width="7"/>'
    map_art += label(x,y+8,20,code,IVORY,'middle')
    tx,ly,anchor = {'E':(285,820,'start'),'V':(185,560,'end'),'B':(285,350,'start'),'L':(550,650,'middle')}[code]
    map_art += label(tx,ly,25,cn,anchor=anchor)+label(tx,ly+28,12,en,anchor=anchor,spacing=.4)
map_art += label(230,935,18,'您在此 · 入口',anchor='middle')
map_art += label(58,1010,18,'虚构样例 · 示意图 · 非等比例')+label(58,1050,14,'路线仅验证 E—V—B 与 V—L 的信息关系，不用于真实导航。')
map_art += '<path d="M700 325 V260 M687 277 L700 260 713 277" stroke="#174D38" stroke-width="4" fill="none"/>'+label(700,245,14,'北',anchor='middle')
direction=f'<rect width="800" height="1000" rx="20" fill="{GREEN}"/>'+label(65,100,42,'青屿 · 方向指引',IVORY)+label(65,153,20,'游客中心 V · 面向示意图北侧',IVORY)
for y,cn,en,arrow in [(320,'观鸟台','BIRD HIDE','M660 355 V275 M640 295 L660 275 680 295'),(535,'湖畔','LAKESIDE','M620 520 H700 M680 500 L700 520 680 540'),(750,'入口','ENTRANCE','M660 715 V795 M640 775 L660 795 680 775')]:
    direction+=label(70,y,36,cn,IVORY)+label(70,y+40,16,en,IVORY,spacing=1)
    direction+=f'<path d="{arrow}" stroke="{GOLD}" stroke-width="9" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    direction+=f'<path d="M65 {y+88} H735" stroke="{SAGE}" stroke-width="1"/>'
direction+=label(65,935,18,'虚构设计样例 · 距离与安装尺寸待实测',IVORY)

spec={'trim_width_mm':148,'trim_height_mm':210,'bleed_mm':3,'safe_margin_mm':5}
files={'notebook-front.svg':(svg(154,216,front,True),spec), 'notebook-back.svg':(svg(154,216,back,True),spec),
       'notebook-inside.svg':(svg(148,210,inside,True),{**spec,'bleed_mm':0}),
       'notebook-proof.svg':(svg(174,246,proof,True),None),
       'wayfinding-map.svg':(svg(800,1100,map_art),None), 'wayfinding-direction.svg':(svg(800,1000,direction),None)}
report={}
with TemporaryDirectory(prefix='aics-print-sample-') as directory:
    store=ProjectStore(directory)
    project=store.create_project(new_project(name='内置技能虚构 QA',slug='builtin-qa',brief='虚构青屿设计验证',budget_minor=None,currency='CNY',root_path=str(Path(directory)/'qa')))
    assets=AssetStore(store); tools=DesignToolRegistry(store,asset_store=assets)
    for filename,(content,print_spec) in files.items():
        result=tools.canvas_create_svg(project_id=project['id'],task_id=None,svg=content,title=filename,outline_text=True,print_spec=print_spec)
        saved=assets.get_asset(project_id=project['id'],asset_id=result['assetId'])
        (OUTPUT/filename).write_bytes(Path(saved['absolutePath']).read_bytes())
        report[filename]={'bytes':(OUTPUT/filename).stat().st_size,'textOutlines':result['textOutlines'],'printPreflight':result.get('printPreflight')}
(OUTPUT/'vector-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({name:item['bytes'] for name,item in report.items()},indent=2))
