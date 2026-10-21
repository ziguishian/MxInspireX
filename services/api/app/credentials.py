from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass


class CredentialError(RuntimeError):
    pass


def mask_secret(secret: str | None) -> str | None:
    """Return a non-reversible display hint for a stored credential.

    The hint is intentionally short and contains only the final four
    characters. It is useful in settings UI while never returning the
    credential itself to the renderer or a persisted task.
    """
    value = str(secret or "").strip()
    if not value:
        return None
    if len(value) <= 4:
        return "••••"
    return f"••••••••{value[-4:]}"


@dataclass
class LocalCredentialStore:
    """Small OS-keychain boundary used by Provider adapters.

    macOS uses the ``security`` CLI, Windows uses Credential Manager, and development environments can opt
    into an environment variable. The project database never stores secrets.
    """

    service_name: str = "ai-creative-studio"

    def get(self, provider_key: str) -> str | None:
        env_name = f"AICS_PROVIDER_KEY_{provider_key.upper().replace('-', '_')}"
        if os.environ.get(env_name):
            return os.environ[env_name]
        if platform.system() == 'Windows':
            from .windows_credentials import WindowsCredentials
            return WindowsCredentials(self.service_name).get(provider_key)
        if platform.system() != "Darwin":
            return None
        result = subprocess.run(["security", "find-generic-password", "-a", provider_key, "-s", self.service_name, "-w"], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    def set(self, provider_key: str, secret: str) -> None:
        if not secret:
            raise CredentialError("凭据不能为空")
        if platform.system() == 'Windows':
            from .windows_credentials import WindowsCredentials
            WindowsCredentials(self.service_name).set(provider_key, secret)
            return
        if platform.system() != "Darwin":
            raise CredentialError("当前平台未实现系统凭据写入，请通过桌面安全存储适配器接入")
        subprocess.run(["security", "add-generic-password", "-U", "-a", provider_key, "-s", self.service_name, "-w", secret], capture_output=True, text=True, check=True)

    def delete(self, provider_key: str) -> None:
        if platform.system() == 'Windows':
            from .windows_credentials import WindowsCredentials
            WindowsCredentials(self.service_name).delete(provider_key)
            return
        if platform.system() != "Darwin":
            return
        subprocess.run(["security", "delete-generic-password", "-a", provider_key, "-s", self.service_name], capture_output=True, text=True, check=False)
