"""Structural verification on any host; does not claim Windows runtime QA."""
import ast
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path


def machine(file):
    with file.open('rb') as stream:
        return machine_bytes(stream.read(), file)


def machine_bytes(data, label):
    assert data[:2] == b'MZ', label
    offset = struct.unpack_from('<I', data, 60)[0]
    pe = data[offset:offset + 6]
    assert pe[:4] == b'PE\0\0', label
    return struct.unpack_from('<H', pe, 4)[0]


output = Path(sys.argv[1]).resolve()
app = output/'windows-x64/LangjuAgent'
api = app/'resources/app/services/api'
python = api/'python'
metadata = json.loads((app/'BUILD-METADATA.json').read_text())
profile = metadata.get('packageProfile', 'full')
assert metadata['arch'] == 'x64'
assert machine(app/'LangjuAgent.exe') == 0x8664
assert machine(python/'python.exe') == 0x8664
assert (app/'resources/app/dist/renderer/index.html').is_file()
assert (app/'resources/app/dist/desktop/preload.js').is_file()
desktop_modules = app/'resources/app/node_modules'
desktop_runtime_packages = (
    'extract-zip', 'debug', 'ms', 'get-stream', 'pump', 'end-of-stream',
    'once', 'wrappy', 'yauzl', 'fd-slicer', 'pend', 'buffer-crc32',
)
for package in desktop_runtime_packages:
    matches = list(desktop_modules.rglob(f'{package}/package.json'))
    assert matches, f'missing desktop runtime dependency: {package}'
assert (api/'app/openai_agent_worker.mjs').stat().st_size > 1_000_000
assert '..' in (python/'python313._pth').read_text().splitlines()
site = python/'Lib/site-packages'
core_packages = ('fastapi', 'uvicorn', 'pydantic_core', 'PIL', 'lxml', 'tzdata', 'reportlab', 'docx', 'pptx', 'multipart', 'httpx', 'httpcore', 'certifi', 'h11')
for package in core_packages:
    assert (site/package).is_dir(), package
optional_packages = ('imageio_ffmpeg', 'cadquery', 'OCP', 'vtkmodules')
if profile == 'full':
    assert (app/'CAD-SMOKE.cmd').is_file()
    assert (app/'resources/cad-smoke.py').is_file()
    assert (app/'resources/CAD-LICENSES/OCCT-7.9.3/LICENSE_LGPL_21.txt').stat().st_size > 20000
    assert (app/'resources/CAD-LICENSES/OCCT-7.9.3/OCCT_LGPL_EXCEPTION.txt').stat().st_size > 100
    for package in optional_packages:
        assert (site/package).is_dir(), package
    assert any('win' in file.name for file in site.glob('imageio_ffmpeg/binaries/*.exe'))
else:
    for package in optional_packages:
        assert not (site/package).exists(), f'{package} must be installed on demand in lite builds'
    manifest = json.loads((app/'resources/app/runtime-components.json').read_text())
    assert manifest['profile'] == 'lite' and manifest['platform'] == 'win32' and manifest['arch'] == 'x64'
    assert {item['id'] for item in manifest['components']} == {'cad', 'media'}
    component_root = output/'components/win32-x64'
    for component in manifest['components']:
        archive = component_root/component['archiveName']
        assert archive.stat().st_size == component['bytes']
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == component['sha256']
        with zipfile.ZipFile(archive) as package_archive:
            assert package_archive.testzip() is None
            names = package_archive.namelist()
            assert not any(name.startswith('/') or '..' in Path(name).parts for name in names)
            assert any(name.startswith(f"{component['id']}/") for name in names)
            if component['id'] == 'cad':
                assert any(name.endswith('/cadquery/__init__.py') for name in names)
                assert any('/OCP/OCP.' in name and name.endswith('.pyd') for name in names)
                assert any('/vtkmodules/vtkCommonCore.' in name and name.endswith('.pyd') for name in names)
                assert any('CAD-LICENSES/OCCT-' in name and name.endswith('/LICENSE_LGPL_21.txt') for name in names)
            else:
                ffmpeg_name = next(name for name in names if name.endswith('/ffmpeg.exe'))
                assert machine_bytes(package_archive.read(ffmpeg_name), ffmpeg_name) == 0x8664
assert (site/'certifi/cacert.pem').stat().st_size > 100_000
assert not list(site.rglob('*.so')), 'No macOS/Linux native dependencies may be shipped'
natives = list(app.rglob('*.pyd')) + list(python.rglob('*.dll'))
for file in natives: assert machine(file) == 0x8664, file
for file in (api/'app').rglob('*.py'):
    ast.parse(file.read_text(encoding='utf-8'))
assert not list(app.rglob('catalog.sqlite'))
assert not list(app.rglob('.venv'))
with zipfile.ZipFile(next(output.glob('*windows*x64*portable.zip'))) as archive:
    assert archive.testzip() is None
    assert 'LangjuAgent/LangjuAgent.exe' in archive.namelist()
    assert not any(name.startswith('/') or '..' in Path(name).parts for name in archive.namelist())
setup = next(output.glob('*windows*x64*setup.exe'))
assert machine(setup) in (0x14c, 0x8664)
assert setup.stat().st_size > 50_000_000
print(json.dumps({'passed': True, 'profile': profile, 'nativeWindowsModules': len(natives), 'electron': metadata['electronVersion'], 'python': metadata['pythonVersion'], 'checks': ['PE architecture', 'embedded interpreter paths', 'desktop runtime dependencies', 'native wheels and optional components', 'timezone data', 'standalone SDK bundle', 'renderer and preload', 'ZIP CRC', 'installer PE', 'no workspace database'], 'windowsRuntimeTested': False}))
