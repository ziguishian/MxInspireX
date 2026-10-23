"""Run against dev Python, a frozen Mac sidecar, or Windows embedded Python.

Usage: python scripts/smoke-cad.py [--frozen /path/to/aics-api]
       embedded-python scripts/smoke-cad.py --api-dir /path/to/services/api
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--frozen')
parser.add_argument('--api-dir',default=str(Path(__file__).resolve().parents[1]/'services/api'))
args = parser.parse_args()
programs = {
    'plate': 'result = cq.Workplane("XY").box(80,50,8).faces(">Z").workplane().pushPoints([[-30,-15],[30,-15],[-30,15],[30,15]]).hole(5)',
    'shell': 'result = cq.Workplane("XY").box(80,50,30).edges("|Z").fillet(3).faces(">Z").shell(-2)',
    'vessel': 'result = cq.Workplane("XZ").moveTo(10,0).lineTo(15,0).lineTo(15,40).lineTo(10,40).close().revolve(360)',
}
results = {}
for name, source in programs.items():
    with tempfile.TemporaryDirectory(prefix='cad-package-smoke-') as directory:
        command = [str(Path(args.frozen).resolve()),'--cad-worker'] if args.frozen else [sys.executable,'-m','app.cad_worker']
        env = {k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','TMPDIR'}}
        env['PYTHONPATH'] = str(Path(args.api_dir).resolve())
        env['HOME'] = directory
        env['USERPROFILE'] = directory
        env['PYTHONUTF8'] = '1'
        env.update(PYTHONNOUSERSITE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        process = subprocess.run(command,input=json.dumps({'source':source}),cwd=directory,env=env,capture_output=True,text=True,timeout=420)
        output = Path(directory)/'result.json'
        result = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {'ok':False,'error':process.stderr[-2000:]}
        assert process.returncode==0 and result.get('ok') and result['checks']['stepRoundTrip'], {'returncode':process.returncode,'stderr':process.stderr[-2000:],'result':result}
        assert all((Path(directory)/filename).stat().st_size for filename in result['files'].values())
        results[name] = result['checks']
        print(f'{name}: native build and exports passed',flush=True)
print(json.dumps({'platform':sys.platform,'python':sys.version.split()[0],'passed':True,'models':results},ensure_ascii=False,indent=2))
