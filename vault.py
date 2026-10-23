"""Windows-user-bound credential vault using DPAPI.

The vault stores opaque token bytes encrypted for the current Windows user.
It does not create, request, transmit, refresh, or print provider credentials.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import threading
from pathlib import Path


class VaultError(RuntimeError):
    pass


_VAULT_LOCK = threading.RLock()


if os.name == "nt":
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    _crypt_protect = ctypes.windll.crypt32.CryptProtectData
    _crypt_unprotect = ctypes.windll.crypt32.CryptUnprotectData
    _local_free = ctypes.windll.kernel32.LocalFree

    def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array[ctypes.c_ubyte]]:
        buffer = (ctypes.c_ubyte * len(data))(*data)
        return DATA_BLOB(len(data), buffer), buffer

    def _protect(data: bytes) -> bytes:
        source, _ = _blob(data)
        target = DATA_BLOB()
        if not _crypt_protect(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
            raise VaultError("DPAPI encryption failed")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            _local_free(target.pbData)

    def _unprotect(data: bytes) -> bytes:
        source, _ = _blob(data)
        target = DATA_BLOB()
        if not _crypt_unprotect(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
            raise VaultError("DPAPI decryption failed")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            _local_free(target.pbData)
else:
    def _protect(data: bytes) -> bytes:
        raise VaultError("DPAPI vault requires Windows")

    def _unprotect(data: bytes) -> bytes:
        raise VaultError("DPAPI vault requires Windows")


class UserVault:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VaultError("vault is unreadable; refusing to repair or overwrite") from exc
        if not isinstance(value, dict):
            raise VaultError("vault format is invalid")
        return value

    def set(self, key: str, value: str) -> None:
        if not key or not isinstance(value, str):
            raise ValueError("key and string value are required")
        with _VAULT_LOCK:
            data = self._read()
            data[key] = _protect(value.encode("utf-8")).hex()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                with temporary.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(json.dumps(data, sort_keys=True))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            except OSError as exc:
                raise VaultError("vault write failed; refusing uncertain persistence") from exc

    def get(self, key: str) -> str | None:
        with _VAULT_LOCK:
            data = self._read()
        encoded = data.get(key)
        if encoded is None:
            return None
        try:
            return _unprotect(bytes.fromhex(encoded)).decode("utf-8")
        except (ValueError, UnicodeDecodeError, VaultError) as exc:
            raise VaultError("vault entry cannot be decrypted; refusing fallback") from exc

    def delete(self, key: str) -> None:
        with _VAULT_LOCK:
            data = self._read()
            if key not in data:
                return
            del data[key]
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                with temporary.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(json.dumps(data, sort_keys=True))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            except OSError as exc:
                raise VaultError("vault write failed; refusing uncertain persistence") from exc

