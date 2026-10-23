"""Trusted CAD process entry point; stdin is JSON, outputs stay in its cwd."""
from __future__ import annotations

import json
import math
import os
import struct
import sys
from types import ModuleType
from pathlib import Path

from .cad_program import Interpreter, resolve_parameters


def glb_millimeters_to_meters(path):
    """CadQuery 2.8 rotates Z-up but preserves numeric millimetre coordinates.

    Add a scene root scale, retaining assembly hierarchy, colours and mesh data.
    The downloaded GLB then obeys glTF's metre convention in every viewer.
    """
    data = path.read_bytes()
    if data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2:
        raise ValueError('GLB 导出格式无效')
    length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A: raise ValueError('GLB 缺少模型清单')
    model = json.loads(data[20:20+length])
    nodes = model.setdefault('nodes', [])
    for scene in model.get('scenes', []):
        index = len(nodes)
        nodes.append({'name':'Millimeters to meters','scale':[.001,.001,.001],'children':scene.get('nodes', [])})
        scene['nodes'] = [index]
    encoded = json.dumps(model,separators=(',',':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    remaining = data[20+length:]
    path.write_bytes(struct.pack('<4sII',b'glTF',2,20+len(encoded)+len(remaining)) + struct.pack('<II',len(encoded),kind) + encoded + remaining)


def inspect_shape(shape):
    solids = shape.Solids()
    if not solids or len(solids) > 64 or not shape.isValid() or any(not s.isValid() or s.Volume() <= 0 for s in solids):
        raise ValueError('结果必须包含 1–64 个有效且体积为正的实体')
    box = shape.BoundingBox()
    dimensions = {'x': box.xlen, 'y': box.ylen, 'z': box.zlen}
    if any(not math.isfinite(v) or not 1e-6 < v <= 100000 for v in dimensions.values()):
        raise ValueError('模型尺寸无效或超过 100 米限制')
    return {'valid': True, 'solidCount': len(solids), 'volumeMm3': sum(s.Volume() for s in solids), 'dimensionsMm': dimensions, 'unit': 'mm'}


def thumbnail(shape, destination):
    """A deterministic raster of actual tessellated geometry (no placeholder)."""
    from PIL import Image, ImageDraw
    vertices, triangles = shape.tessellate(0.2, 0.2)
    if len(triangles) > 200000: raise ValueError('模型网格超过 20 万三角形限制')
    points = [(v.x - v.y, (v.x + v.y) * .45 - v.z, v.x + v.y + v.z) for v in vertices]
    lo_x, hi_x = min(p[0] for p in points), max(p[0] for p in points)
    lo_y, hi_y = min(p[1] for p in points), max(p[1] for p in points)
    scale = min(540 / max(hi_x-lo_x, 1e-6), 400 / max(hi_y-lo_y, 1e-6))
    screen = [((x-(lo_x+hi_x)/2)*scale+320, (y-(lo_y+hi_y)/2)*scale+240) for x,y,_ in points]
    image = Image.new('RGB', (640,480), '#f0f2f5')
    draw = ImageDraw.Draw(image)
    for a,b,c in sorted(triangles, key=lambda t: sum(points[i][2] for i in t)):
        v1, v2 = vertices[b]-vertices[a], vertices[c]-vertices[a]
        normal = v1.cross(v2)
        light = abs(normal.z) / max(normal.Length, 1e-12)
        shade = int(120 + 85*light)
        draw.polygon([screen[a],screen[b],screen[c]], fill=(int(shade*.78),int(shade*.91),shade))
    image.save(destination)


def build(payload, directory):
    import cadquery as cq
    directory = Path(directory)
    values = resolve_parameters(payload.get('parameter_definitions') or [], payload.get('parameters') or {})
    model = Interpreter(values, cq).run(payload['source'])
    if isinstance(model, cq.Workplane):
        shapes = [v for v in model.vals() if isinstance(v, cq.Shape)]
        model = cq.Compound.makeCompound(shapes)
    if isinstance(model, cq.Shape):
        shape, assembly = model, cq.Assembly(model, name='model')
    elif isinstance(model, cq.Assembly):
        assembly, shape = model, model.toCompound()
    else: raise ValueError('result 必须是 Workplane、Shape 或 Assembly')
    checks = inspect_shape(shape)
    for axis, expected in payload.get('expected_dimensions', {}).items():
        if axis not in {'x', 'y', 'z'} or not math.isfinite(expected) or expected <= 0: raise ValueError('期望尺寸必须是 x/y/z 的正数，单位 mm')
        if not math.isclose(checks['dimensionsMm'][axis], expected, rel_tol=1e-5, abs_tol=.01):
            raise ValueError(f'{axis} 尺寸不符：实际 {checks["dimensionsMm"][axis]:.4f}，要求 {expected} mm')
    # Native geometry exports are owned by the host, never by generated code.
    cq.exporters.export(shape, str(directory/'model.step'))
    cq.exporters.export(shape, str(directory/'model.stl'), tolerance=.1, angularTolerance=.1)
    assembly.export(str(directory/'model.glb'))
    glb_millimeters_to_meters(directory/'model.glb')
    restored = inspect_shape(cq.importers.importStep(str(directory/'model.step')).val())
    if restored['solidCount'] != checks['solidCount'] or not math.isclose(restored['volumeMm3'], checks['volumeMm3'], rel_tol=1e-5, abs_tol=1e-4):
        raise ValueError('STEP 回读实体或体积不一致')
    if any(not math.isclose(restored['dimensionsMm'][k],v,rel_tol=1e-5,abs_tol=1e-4) for k,v in checks['dimensionsMm'].items()):
        raise ValueError('STEP 回读尺寸不一致')
    checks['stepRoundTrip'] = True
    checks['expectedDimensions'] = payload.get('expected_dimensions', {})
    thumbnail(shape, directory/'thumbnail.png')
    files = {'step':'model.step', 'stl':'model.stl', 'glb':'model.glb', 'thumbnail':'thumbnail.png', 'source':'model.py', 'parameters':'parameters.json'}
    (directory/'model.py').write_text('import cadquery as cq\nimport math\nparams = '+repr(values)+'\n'+payload['source'], encoding='utf-8')
    (directory/'parameters.json').write_text(json.dumps({'definitions':payload.get('parameter_definitions') or [],'values':values},ensure_ascii=False,indent=2),encoding='utf-8')
    for filename in files.values():
        size = (directory/filename).stat().st_size
        if not 0 < size < 100*1024*1024: raise ValueError('导出文件为空或超过 100 MB')
    return {'checks':checks, 'parameters':values, 'files':files, 'engine':{'cadquery':cq.__version__}, 'previewUnit':'m'}


def main():
    exit_code = 0
    try:
        payload = json.loads(sys.stdin.buffer.read(200000))
        # OCP imports the legacy all-in-one ``vtk`` namespace even though this
        # worker only uses CadQuery's explicit ``vtkmodules`` dependencies.
        # Avoid loading every optional VTK plug-in for each isolated build.
        sys.modules.setdefault("vtk", ModuleType("vtk"))
        import cadquery as cq
        # Loading native libraries on the first launch has a separate deadline.
        # Generated code cannot create this marker or extend the build deadline.
        Path('ready.json').write_text('{}',encoding='utf-8')
        if payload.get('health'):
            result = {'available':True, 'version':cq.__version__, 'valid':cq.Workplane().box(1,2,3).val().isValid()}
        else: result = build(payload, Path.cwd())
        Path('result.json').write_text(json.dumps({'ok':True, **result},ensure_ascii=False),encoding='utf-8')
    except Exception as error:
        Path('result.json').write_text(json.dumps({'ok':False,'error':str(error)[:3000]},ensure_ascii=False),encoding='utf-8')
        exit_code = 1
    if sys.platform == 'win32':
        # OCP/VTK's native shutdown can corrupt the Windows heap after even a
        # health probe. This disposable worker has already closed every output
        # and written the validated success/error result; let the OS reclaim
        # native state instead of running unsafe interpreter finalizers.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    if exit_code:
        sys.exit(exit_code)


if __name__ == '__main__': main()
