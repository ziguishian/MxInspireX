"""Windows Credential Manager; secrets never enter project files or argv."""
import ctypes


class FileTime(ctypes.Structure):
    _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]


class Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', ctypes.c_uint32), ('Type', ctypes.c_uint32),
        ('TargetName', ctypes.c_wchar_p), ('Comment', ctypes.c_wchar_p),
        ('LastWritten', FileTime), ('CredentialBlobSize', ctypes.c_uint32),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', ctypes.c_uint32), ('AttributeCount', ctypes.c_uint32),
        ('Attributes', ctypes.c_void_p), ('TargetAlias', ctypes.c_wchar_p),
        ('UserName', ctypes.c_wchar_p),
    ]


class WindowsCredentials:
    def __init__(self, service_name):
        self.service_name = service_name
        self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), ctypes.c_uint32]
        self.api.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        for name in ('CredReadW', 'CredWriteW', 'CredDeleteW'):
            getattr(self.api, name).restype = ctypes.c_int
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def target(self, provider_key):
        return f'{self.service_name}/{provider_key}'

    @staticmethod
    def check(success, *, missing_ok=False):
        if success: return True
        code = ctypes.get_last_error()
        if missing_ok and code == 1168: return False  # ERROR_NOT_FOUND
        from .credentials import CredentialError
        raise CredentialError(f'Windows 系统凭据操作失败（错误 {code}）')

    def get(self, provider_key):
        pointer = ctypes.POINTER(Credential)()
        if not self.check(self.api.CredReadW(self.target(provider_key), 1, 0, ctypes.byref(pointer)), missing_ok=True):
            return None
        try:
            value = pointer.contents
            return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode('utf-16-le') or None
        finally:
            self.api.CredFree(pointer)

    def set(self, provider_key, secret):
        from .credentials import CredentialError
        encoded = secret.encode('utf-16-le')
        if len(encoded) > 2560:
            raise CredentialError('API Key 超过 Windows 系统凭据长度上限')
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        value = Credential(Type=1, TargetName=self.target(provider_key),
                           CredentialBlobSize=len(encoded), CredentialBlob=blob,
                           Persist=2, UserName=provider_key)
        self.check(self.api.CredWriteW(ctypes.byref(value), 0))

    def delete(self, provider_key):
        self.check(self.api.CredDeleteW(self.target(provider_key), 1, 0), missing_ok=True)
