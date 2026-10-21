import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.credentials import CredentialError, LocalCredentialStore
from app.windows_credentials import Credential, WindowsCredentials


def test_windows_credential_blob_roundtrip_and_free(monkeypatch):
    saved = {}
    allocations = []
    def write(pointer, flags):
        value = ctypes.cast(pointer, ctypes.POINTER(Credential)).contents
        saved[value.TargetName] = ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize)
        assert value.Type == 1 and value.Persist == 2 and flags == 0
        return 1
    def read(target, kind, flags, out):
        if target not in saved: return 0
        blob = (ctypes.c_ubyte * len(saved[target])).from_buffer_copy(saved[target])
        value = Credential(CredentialBlobSize=len(blob), CredentialBlob=blob)
        allocations.extend([blob, value])
        ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(Credential)))[0] = ctypes.pointer(value)
        return 1
    def delete(target, kind, flags):
        return int(saved.pop(target, None) is not None)
    api = SimpleNamespace(CredWriteW=Mock(side_effect=write), CredReadW=Mock(side_effect=read), CredDeleteW=Mock(side_effect=delete), CredFree=Mock())
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: api, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 1168, raising=False)
    monkeypatch.setattr('app.credentials.platform.system', lambda: 'Windows')
    store = LocalCredentialStore('fixture-only')
    store.set('relay', 'sk-测试-fixture')
    assert store.get('relay') == 'sk-测试-fixture'
    api.CredFree.assert_called_once()
    assert list(saved) == ['fixture-only/relay']
    store.delete('relay')
    assert store.get('relay') is None
    store.delete('relay')
    with pytest.raises(CredentialError, match='长度上限'):
        store.set('relay', 'x'*1281)


def test_windows_storage_errors_do_not_silently_drop_credentials(monkeypatch):
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 5, raising=False)
    with pytest.raises(CredentialError, match='错误 5'):
        WindowsCredentials.check(False, missing_ok=True)
