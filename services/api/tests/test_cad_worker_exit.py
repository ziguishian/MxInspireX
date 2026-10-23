import io
import json
import sys
from types import SimpleNamespace

import pytest

from app import cad_worker


@pytest.mark.parametrize('payload,code', [(b'{"health":true}', 0), (b'not-json', 1)])
def test_windows_worker_persists_result_before_exit(tmp_path, monkeypatch, payload, code):
    class Shape:
        def box(self, *args): return self
        def val(self): return self
        def isValid(self): return True
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, 'cadquery', SimpleNamespace(Workplane=Shape, __version__='fixture'))
    monkeypatch.setitem(sys.modules, 'vtk', SimpleNamespace())
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(payload)))
    monkeypatch.setattr(sys, 'platform', 'win32')
    def exit_worker(status):
        result = json.loads((tmp_path / 'result.json').read_text(encoding='utf-8'))
        assert result['ok'] is (status == 0)
        if status == 0: assert result['valid'] is True
        else: assert result['error']
        raise SystemExit(status)
    monkeypatch.setattr(cad_worker.os, '_exit', exit_worker)
    with pytest.raises(SystemExit) as stopped:
        cad_worker.main()
    assert stopped.value.code == code
